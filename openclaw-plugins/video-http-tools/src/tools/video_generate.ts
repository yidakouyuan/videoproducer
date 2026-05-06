import { Type, getConfig, httpJson, toolTextResult } from "../shared";

export default function registerVideoGenerateTools(api: any) {
  api.registerTool({
    name: "video_generate_models",
    description: "List all available video generation models for the current provider. Call this before video_generate_start if you need to select a specific model. Returns provider name and model list with supported modes (t2v/i2v), max duration, and which is the default.",
    parameters: Type.Object({}),
    async execute(_id: string, _params: any) {
      const cfg = getConfig(api);
      const result = await httpJson(cfg, "/video/generate/models", "GET");
      return toolTextResult(result);
    }
  });

  api.registerTool({
    name: "video_generate_start",
    description: "Start a video generation job. Supports text-to-video and image-to-video.",
    parameters: Type.Object({
      prompt: Type.String(),
      duration: Type.Optional(Type.Integer({ minimum: 1, maximum: 60, description: "视频时长（秒），默认 6" })),
      first_frame_path: Type.Optional(Type.String({ description: "首帧图片：本地文件路径或公网 URL，不传则为纯文生视频（t2v）" })),
      model: Type.Optional(Type.String({ description: "模型名，覆盖服务端默认值（如 MiniMax-Hailuo-02、seedance-1-5-pro-251215）" }))
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const result = await httpJson(cfg, "/video/generate/start", "POST", params);
      return toolTextResult(result);
    }
  });

  api.registerTool({
    name: "video_generate_result",
    description: "Get video generation result by job_id. Poll until status is done or failed. Pass wait_sec=30 to enable server-side long-polling — the server will wait up to 30s for a state change before responding, reducing the number of calls needed. Use this for multi-shot parallel polling (one call per pending job per round). For single-shot blocking wait, prefer video_generate_wait_for_done.",
    parameters: Type.Object({
      job_id: Type.String(),
      wait_sec: Type.Optional(Type.Integer({
        minimum: 0,
        maximum: 120,
        description: "Server-side long-poll wait seconds (0 = return immediately). Recommended: 30. Reduces polling calls and keeps agent context lean."
      }))
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const waitSec = params.wait_sec ?? 0;
      // Client timeout = server long-poll wait + 15s buffer to avoid racing the response
      const timeoutMs = waitSec * 1000 + 15000;
      const result = await httpJson(
        cfg,
        `/video/generate/result/${encodeURIComponent(params.job_id)}?wait_sec=${waitSec}`,
        "GET",
        undefined,
        timeoutMs
      );
      return toolTextResult(result);
    }
  });

  api.registerTool({
    name: "video_generate_delete",
    description: "Delete a video generation job by job_id after use.",
    parameters: Type.Object({
      job_id: Type.String()
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const result = await httpJson(
        cfg,
        `/video/generate/${encodeURIComponent(params.job_id)}`,
        "DELETE"
      );
      return toolTextResult(result);
    }
  });

  // Server-side wait. Use this INSTEAD of repeatedly calling video_generate_result
  // yourself — it polls within the plugin process so the agent doesn't burn LLM
  // turns busy-polling. Returns the same shape as video_generate_result, with
  // an extra `waited_sec` field. Returns a timeout payload (status:"timeout") if
  // the job has not reached a terminal state within `max_wait_sec`.
  //
  // PREFERRED for single-shot generation. For multi-shot parallel flows, use
  // video_generate_result(wait_sec=30) instead so multiple jobs can be polled
  // concurrently (this tool blocks on a single job_id).
  api.registerTool({
    name: "video_generate_wait_for_done",
    description:
      "Wait for a video generation job to reach a terminal state (done/failed/partial/cancelled). " +
      "Polls server-side so the calling agent does not need to busy-poll. " +
      "Use this for single-shot generation INSTEAD of repeatedly calling video_generate_result yourself. " +
      "For multi-shot parallel flows where multiple jobs need concurrent polling, use video_generate_result with wait_sec=30 instead. " +
      "Returns the final result payload plus a waited_sec field, or a timeout payload " +
      "(status:\"timeout\") if max_wait_sec is exceeded.",
    parameters: Type.Object({
      job_id: Type.String(),
      max_wait_sec: Type.Optional(
        Type.Integer({
          minimum: 1,
          maximum: 3600,
          default: 900,
          description: "Maximum total wait in seconds (default 900 = 15 min)."
        })
      ),
      poll_interval_sec: Type.Optional(
        Type.Integer({
          minimum: 1,
          maximum: 60,
          default: 5,
          description: "Seconds between polls (default 5)."
        })
      )
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const maxWaitSec: number = params.max_wait_sec ?? 900;
      const intervalSec: number = params.poll_interval_sec ?? 5;
      const TERMINAL = new Set(["done", "failed", "partial", "cancelled"]);

      const startedMs = Date.now();
      let lastObserved: any = null;
      let consecutiveErrors = 0;

      while ((Date.now() - startedMs) / 1000 < maxWaitSec) {
        let result: any = null;
        try {
          result = await httpJson(
            cfg,
            `/video/generate/result/${encodeURIComponent(params.job_id)}`,
            "GET"
          );
          consecutiveErrors = 0;
        } catch (err) {
          consecutiveErrors += 1;
          // Tolerate up to 3 consecutive transient failures; surface after that.
          if (consecutiveErrors >= 3) {
            const waitedSec = Math.round((Date.now() - startedMs) / 1000);
            return toolTextResult({
              ok: false,
              status: "error",
              error: `Polling failed 3 times consecutively: ${(err as Error)?.message ?? String(err)}`,
              job_id: params.job_id,
              waited_sec: waitedSec,
              last_observed: lastObserved
            });
          }
          await new Promise((r) => setTimeout(r, intervalSec * 1000));
          continue;
        }

        lastObserved = result;
        // Backend response shape (observed): { ok, data: { status, ... } }.
        // Fall back to a top-level status field for robustness.
        const status =
          (result && result.data && result.data.status) ??
          (result && result.status) ??
          null;

        if (status && TERMINAL.has(status)) {
          const waitedSec = Math.round((Date.now() - startedMs) / 1000);
          return toolTextResult({ ...(result as object), waited_sec: waitedSec });
        }

        await new Promise((r) => setTimeout(r, intervalSec * 1000));
      }

      const waitedSec = Math.round((Date.now() - startedMs) / 1000);
      return toolTextResult({
        ok: false,
        status: "timeout",
        message: `Job did not reach a terminal state within ${maxWaitSec}s`,
        job_id: params.job_id,
        waited_sec: waitedSec,
        last_observed: lastObserved
      });
    }
  });

  api.registerTool({
    name: "video_stitch",
    description: "Concatenate multiple local MP4 files into a single video in the given order. Use this after all per-shot video generation jobs are done to produce the final stitched video. Requires ffmpeg on the server. If reencode=false fails (codec mismatch), retry with reencode=true.",
    parameters: Type.Object({
      video_paths: Type.Array(Type.String(), {
        minItems: 2,
        description: "Ordered list of local MP4 paths (from video_generate_result local_video_path). Must be server-side paths."
      }),
      output_name: Type.Optional(Type.String({
        description: "Output filename without extension. Auto-generated if omitted."
      })),
      reencode: Type.Optional(Type.Boolean({
        description: "false (default) = stream copy, very fast, requires identical codec params. true = re-encode to 1920x1080 H.264, slower but handles mixed formats."
      }))
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      // ffmpeg server-side timeout is 600s; add 60s buffer for connection overhead
      const result = await httpJson(cfg, "/video/stitch", "POST", params, 660000);
      return toolTextResult(result);
    }
  });
}
