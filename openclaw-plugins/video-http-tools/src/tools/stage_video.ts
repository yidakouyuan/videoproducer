import * as fs from "fs/promises";
import * as path from "path";
import * as os from "os";
import { Type, toolTextResult } from "../shared";

// Convert C:\Users\Foo\bar.mp4 → /mnt/c/Users/Foo/bar.mp4.
// Pass-through for already-Linux paths.
function windowsPathToWsl(p: string): string {
  if (/^[a-zA-Z]:[\\/]/.test(p)) {
    const drive = p[0].toLowerCase();
    const rest = p.slice(2).replace(/\\/g, "/").replace(/^\//, "");
    return `/mnt/${drive}/${rest}`;
  }
  return p;
}

// Atomic "stage video for sending": converts Windows paths, verifies the
// source exists, and copies it into the run directory at a known location.
// This replaces the multi-step `video-path` skill that the orchestrator
// kept skipping or executing partially. Failures return ok:false with a
// concrete reason — the agent can NEVER end up with a non-existent
// staged_path that it then tries to send.
export default function registerStageVideoTool(api: any) {
  api.registerTool({
    name: "stage_video_for_send",
    description:
      "Prepare a locally generated video file for sending via the message tool. " +
      "Accepts a Windows path (C:\\...) or an already-WSL path; converts as needed; " +
      "verifies the source exists; copies it to ~/.openclaw/runs/{run_id}/video.mp4; " +
      "returns the staged path. Always call this BEFORE message.send for any local " +
      "video file. If the source can't be found or copied, returns ok:false with the " +
      "exact reason — never fabricates a path. Use the returned staged_path verbatim " +
      "as the message.send media path.",
    parameters: Type.Object({
      source_path: Type.String({
        description:
          "Source video path from video_result.json's local_video_path field. " +
          "Either a Windows path (C:\\Users\\...) or a Linux/WSL path (/home/... or /mnt/c/...)."
      }),
      run_id: Type.String({
        description:
          "The pipeline run_id (timestamp like 20260424_202300). The staged file " +
          "will be placed at ~/.openclaw/runs/{run_id}/video.mp4."
      })
    }),
    async execute(_id: string, params: any) {
      const sourceRaw: string = params.source_path;
      const runId: string = params.run_id;
      const wslSource = windowsPathToWsl(sourceRaw);
      const home = process.env.HOME ?? os.homedir() ?? "/home/administrator";
      const stagedPath = `${home}/.openclaw/runs/${runId}/video.mp4`;

      try {
        const sourceStat = await fs.stat(wslSource);
        if (!sourceStat.isFile()) {
          return toolTextResult({
            ok: false,
            status: "error",
            error: `Source path exists but is not a regular file: ${sourceRaw}`,
            source_attempted: sourceRaw,
            wsl_path_attempted: wslSource
          });
        }

        await fs.mkdir(path.dirname(stagedPath), { recursive: true });
        await fs.copyFile(wslSource, stagedPath);
        const stagedStat = await fs.stat(stagedPath);

        if (stagedStat.size !== sourceStat.size) {
          return toolTextResult({
            ok: false,
            status: "error",
            error: `Staged file size (${stagedStat.size}) does not match source (${sourceStat.size}); copy may have been truncated.`,
            source_attempted: sourceRaw,
            wsl_path_attempted: wslSource,
            staged_path_attempted: stagedPath
          });
        }

        return toolTextResult({
          ok: true,
          staged_path: stagedPath,
          source_size_bytes: sourceStat.size,
          staged_size_bytes: stagedStat.size,
          note: "Pass staged_path verbatim to message.send as the media path. Do NOT modify it."
        });
      } catch (err: any) {
        return toolTextResult({
          ok: false,
          status: "error",
          error: `${err?.code ?? "ERROR"}: ${err?.message ?? String(err)}`,
          source_attempted: sourceRaw,
          wsl_path_attempted: wslSource,
          staged_path_attempted: stagedPath
        });
      }
    }
  });
}
