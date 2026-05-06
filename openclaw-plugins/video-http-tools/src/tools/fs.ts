import * as fs from "fs/promises";
import * as path from "path";
import { Type, toolTextResult } from "../shared";

// Read-only directory listing. Lives in this plugin (alongside the
// video/media tools) because the whole pipeline's "shared infrastructure"
// happens to be hosted here and the system's core is video. Discovery
// agents (research-supervisor, web-search, douyin-search) need this to
// inspect the run directory without abusing `read` (which throws EISDIR
// on directories) or being granted full `exec` (over-broad).
export default function registerFsTools(api: any) {
  api.registerTool({
    name: "list_dir",
    description:
      "List the entries in a directory. Read-only — does not modify anything. " +
      "Use this when you need to discover what files exist before reading them. " +
      "DO NOT call `read` on a directory path; that fails with EISDIR. " +
      "Returns each entry's name, whether it's a file or directory, size in bytes, " +
      "and modification time.",
    parameters: Type.Object({
      path: Type.String({
        description: "Absolute path to the directory to list (e.g., /home/administrator/.openclaw/runs/20260424_202300/raw)."
      }),
      include_hidden: Type.Optional(
        Type.Boolean({
          default: false,
          description: "If true, include entries whose name starts with a dot."
        })
      )
    }),
    async execute(_id: string, params: any) {
      const target: string = params.path;
      const includeHidden: boolean = params.include_hidden === true;

      try {
        const dirents = await fs.readdir(target, { withFileTypes: true });
        const filtered = includeHidden
          ? dirents
          : dirents.filter((d) => !d.name.startsWith("."));

        const entries = await Promise.all(
          filtered.map(async (d) => {
            const full = path.join(target, d.name);
            let size: number | null = null;
            let mtime: string | null = null;
            try {
              const st = await fs.stat(full);
              size = st.size;
              mtime = st.mtime.toISOString();
            } catch {
              // ignore per-entry stat errors (e.g., broken symlink)
            }
            return {
              name: d.name,
              is_dir: d.isDirectory(),
              is_file: d.isFile(),
              size_bytes: size,
              modified_at: mtime
            };
          })
        );

        // Sort: directories first, then files; alphabetical within each group.
        entries.sort((a, b) => {
          if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
          return a.name.localeCompare(b.name);
        });

        return toolTextResult({
          ok: true,
          path: target,
          entry_count: entries.length,
          entries
        });
      } catch (err: any) {
        return toolTextResult({
          ok: false,
          status: "error",
          error: `${err?.code ?? "ERROR"}: ${err?.message ?? String(err)}`,
          path: target
        });
      }
    }
  });
}
