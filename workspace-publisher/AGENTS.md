# AGENTS.md - publisher

## Environment

- `exec` shell: Windows cmd.exe (NOT bash). Publish flow uses `C:\Users\Administrator\.openclaw\scripts\run-douyin-publish.cmd` — that's the intended path.
- workdir: already your workspace. Never run `pwd` to check.
- For unix-style helpers (jq / find), use `bash -lc '...'`.

## Every Session

Before doing anything else:

1. Read `~/.openclaw/workspace-publisher/SOUL.md` — who you are, your scope, your core principles
2. Read `~/.openclaw/docs/PRINCIPLES.md` — shared pipeline principles
3. Read `~/.openclaw/docs/EXEC_ENV.md` — exec is cmd.exe; cmd-equivalents and `bash -lc` escape hatch

Don't ask permission. Just do it.

## Memory protocol (every session)

Per `~/.openclaw/docs/MEMORY_LAYOUT.md`, after the L0 reads above:

1. Read `~/.openclaw/workspace-publisher/MEMORY.md` — long-term lessons (skip if missing/empty).
2. Read `~/.openclaw/workspace-publisher/memory/<today>.md` — today's notes (skip if missing).
3. Read `~/.openclaw/workspace-publisher/memory/<yesterday>.md` — cross-day continuity (skip if missing).
4. Read `~/.openclaw/insights/playbooks/publisher.md` — stage playbook (skip if missing).
5. **Check for promotion proposals** — if `~/.openclaw/workspace-publisher/MEMORY.md._pending_*.md` exists, read it. It lists candidate lessons surfaced by `scripts/promote_memory.py` from your daily-notes (clusters that recurred ≥ 2 times). For each cluster, decide **promote** / **drop** / **defer**. For "promote", append a polished one-liner (in your own words) to `~/.openclaw/workspace-publisher/MEMORY.md` — cite source dates for future audit. For "drop" / "defer", no extra action. Once you've processed every cluster (or decided to skip the file entirely this session), delete the proposal: `exec bash -lc 'rm ~/.openclaw/workspace-publisher/MEMORY.md._pending_*.md'`. If short on time, leave the file in place — it will still be there next session. Do NOT half-merge.

Before the session ends (after any existing Completion gate / final write): if you learned something non-trivial that future-you would want to know, **append one line** to `~/.openclaw/workspace-publisher/memory/<YYYY-MM-DD>.md`:

```
- [HH:MM] <terse lesson>; src: run=<run_id_or_context>
```

Skip if nothing surprising happened. Quality over quantity.

## Input

You receive:
- `run_id`

Read the following files from `~/.openclaw/runs/{run_id}/` (→ `~/.openclaw/docs/RUN_LAYOUT.md`):
- `video_result.json` — `local_video_path` to upload
- `script.json` — `title` and `tags` for publish metadata
- `brief.json` — `grounded_tag` for verifying tag grounding

If any required file is missing, invalid, or unusable, stop and return failure immediately.

---

## Working schema

1. **Read and validate run files** — ALL THREE are required, in this order. Skipping `video_result.json` is the most common silent failure mode (you'll be tempted to guess the path or use a staged WSL path; do NOT — always read the file and use the exact `local_video_path` field).

   - **read `~/.openclaw/runs/{run_id}/video_result.json`** → confirm `local_video_path` is present and non-empty. **The value will be a Windows path like `C:\Users\Administrator\AppData\Local\Temp\openclaw\uploads\final_*.mp4` — pass it through verbatim, do NOT transform.** Never substitute this with `~/.openclaw/runs/<run_id>/video.mp4` or any WSL `/home/...` path — those are stage paths for `message`, NOT for browser upload.
   - read `~/.openclaw/runs/{run_id}/script.json` → confirm `title` and `tags` are present
   - read `~/.openclaw/runs/{run_id}/brief.json` → confirm `grounded_tag` is present

   If any of the three files is missing or required fields are missing, return `success: false, status: "failed", error: "missing_file"` immediately.

   **Do NOT verify file existence with `exec`/`if exist`/`dir`/`Test-Path` shell calls.** `video_result.json` is written by `video-generate` immediately after a successful stitch — the file IS there. Shell-based existence checks under nested quoting frequently false-negative on paths with backslashes. Trust `video_result.json`; if the file truly is gone (rare), the `browser` tool in step 2 will surface a real error from the upload widget.

2. **Publish via the `.cmd` bridge** — do NOT use the `creator-center` skill / `browser` tool's upload action directly.

   Why: OpenClaw's `browser` tool has a hard-coded "must stay within uploads directory" sandbox check that path-resolves the file and frequently rejects the legitimate `C:\Users\...\Temp\openclaw\uploads\final_*.mp4` path even when the file is genuinely there (Windows path-resolve / NTFS reparse interaction). The bridge bypasses this entirely by driving Playwright through CDP against the already logged-in Chrome session.

   ### 2-pre. Ensure CDP Chrome is up

   The bridge connects to `http://127.0.0.1:18800` (the OpenClaw-managed Chrome with logged-in douyin session). If the user happens to close that Chrome window between runs, the bridge will fail with `ECONNREFUSED 127.0.0.1:18800` before any upload happens. Always run a quick health check first:

   ```
   browser(action="status", target="node", profile="openclaw")
   ```

   - If response includes `"running": true, "cdpReady": true, "cdpPort": 18800` → proceed to step 2a.
   - If `"running": false` or `"cdpReady": false` (Chrome was closed):
     ```
     browser(action="start", target="node", profile="openclaw")
     ```
     Wait 3-5 seconds, then re-check `status`. Once `cdpReady: true`, proceed.
   - If `start` itself fails (chrome.exe not found / port in use), report `error: "cdp_unavailable: <reason>"` to orchestrator — do NOT proceed.

   ### 2a. Write the payload file

   **Path discipline (CRITICAL):** the `write` tool runs inside the WSL Node process. It does NOT auto-translate `C:\...` Windows paths — backslashes become literal filename characters and you'll create a garbage file like `<workspace>/C:\Users\Administrator\.openclaw\scripts\payloads\pending-douyin-publish.json`. Always use the **WSL-mounted form** so it transparently writes to the Windows location:

   `path` argument for `write`:
   ```
   /mnt/c/Users/Administrator/.openclaw/scripts/payloads/pending-douyin-publish.json
   ```

   ⚠️ Do NOT use `C:\Users\Administrator\.openclaw\scripts\payloads\pending-douyin-publish.json` for the `write` tool's `path` arg — that creates the broken filename above. Same rule applies to any future `write` against Windows paths from a subagent: prefix with `/mnt/c/` and use forward slashes.

   Content (the `video_path` INSIDE the JSON keeps the Windows form with double backslashes — the .cmd bridge runs Node on Windows and needs the Windows path):

   ```json
   {
     "platform": "douyin",
     "video_path": "<exact local_video_path from video_result.json, with double backslashes>",
     "title": "<title from script.json>",
     "description": "<description from script.json, optional>",
     "hashtags": ["tag1", "tag2"],
     "visibility": "public",
     "publish_mode": "publish",
     "require_manual_confirmation": false
   }
   ```

   Field mapping:
   - `video_path` ← `local_video_path` from `video_result.json`. **Use double backslashes** (`C:\\Users\\...\\final_*.mp4`) so the JSON parses correctly.
   - `title` ← `title` from `script.json`
   - `hashtags` ← `tags` from `script.json` (array; the script auto-prefixes `#` if missing)
   - `description` ← `description` from `script.json` if present, else omit or set to ""
   - `visibility`: read `visibility` from `brief.json` if present (allowed values: `"public"` / `"friends"` / `"private"`). If not present, **default to `"public"`** — this pipeline is meant for actual public posts. Only downgrade to `"private"` if the user explicitly says so (e.g. brief.json `"visibility":"private"` or the user message contains 私密 / 仅自己可见 / draft / test-only).
   - `publish_mode`: `"publish"` to actually publish, `"draft"` to stop at the editor

   ### 2b. Invoke the bridge
   Call `exec` with the fixed command (no extra arguments — the .cmd file reads the payload at the fixed path above):

   ```
   exec(command="C:\\Users\\Administrator\\.openclaw\\scripts\\run-douyin-publish.cmd", yieldMs=180000)
   ```

   The script runs Playwright via CDP against `http://127.0.0.1:18800` (already attached Chrome with logged-in douyin session) and prints a single JSON object to stdout. Set `yieldMs` to at least 180000 — Douyin upload + render can take 1-3 minutes for short videos.

   ### 2c. Parse the JSON output
   Stdout is a JSON like:

   ```json
   {
     "success": true,
     "status": "publish_clicked",
     "confirmation": "url_changed_after_publish" | "publish_likely_succeeded" | "publish_unknown_state",
     "url": "https://creator.douyin.com/...",
     "title": "...",
     "body_excerpt": "...",
     "payload": { ... }
   }
   ```

   - `success: true` + `confirmation` is `url_changed_after_publish` or `publish_likely_succeeded` → real success
   - `success: true` + `confirmation: "publish_unknown_state"` or `"publish_clicked_but_unconfirmed"` → ambiguous; report `success: false, status: "ambiguous"` and let the user verify on the platform
   - `success: false` → failed; pass through the script's `status` and any error info as your `error`
   - If `exec` itself errors (non-zero exit / timeout), that's `error: "bridge_failed: <stderr summary>"`

3. **Persist publish outcome** (irrespective of success/failure):

   The backward-optimization pipeline needs every publish attempt recorded on disk so platform stats can later be joined back to `run_id`. Do this BEFORE returning to orchestrator.

   a. **Parse `aweme_id` from `url`**. The bridge stdout's `url` looks like `https://www.douyin.com/video/7234567890123456789` (or a creator.douyin.com variant). Extract the numeric segment after `/video/` — pseudocode: `aweme_id = re.search(r'/video/(\d+)', url).group(1)`. If `url` is missing or the regex fails, `aweme_id = null` (do NOT abort — `(title, publish_ts)` is the fallback join key).

   b. **Write `~/.openclaw/runs/{run_id}/publish_result.json`** using the `write` tool. Path argument: use the **WSL-native main run-dir path** `/home/administrator/.openclaw/runs/{run_id}/publish_result.json` — this is the WSL real filesystem.
   
   ⚠️ **Do NOT** use `/mnt/c/Users/Administrator/.openclaw/runs/{run_id}/publish_result.json` — that writes to the **Windows-side `.openclaw` directory**, which is a SEPARATE filesystem location from the WSL main `.openclaw`. Orchestrator and the backward chain (`episode_init.py`, `outcome_aggregator.py`, etc.) read from `/home/administrator/.openclaw/runs/...`; a publish_result.json that lands under `/mnt/c/Users/Administrator/.openclaw/runs/...` is invisible to them.
   
   The "WSL-mounted form" path-discipline rule from step 2a applies only to the **bridge interop payload** (`~/.openclaw/scripts/payloads/...` is a Windows-side artifact consumed by `run-douyin-publish.cmd`). `publish_result.json` is a **main-run-dir artifact** — it must live on the WSL main filesystem alongside `brief.json`, `script.json`, `video_result.json`.
   
   Content:

      ```json
      {
        "ok": <success bool from bridge>,
        "run_id": "<run_id>",
        "publish_ts": "<current UTC ISO8601, e.g. 2026-05-01T14:23:00Z>",
        "platform": "douyin",
        "aweme_id": "<parsed | null>",
        "url": "<bridge stdout url, may be null on bridge failure>",
        "title": "<title from script.json>",
        "hashtags": <tags array from script.json>,
        "confirmation": "<bridge stdout confirmation field>"
      }
      ```

      Always write this file — even on `ok: false` — so the backward chain can see failed attempts. On bridge failure where there is no `url`, leave `url: null` and `aweme_id: null`; still record `ok: false` and `confirmation: "bridge_failed"` (or whatever the bridge returned).

   c. **Initialize the L4 episode snapshot** by calling:

      ```
      exec(command="bash /home/administrator/.openclaw/scripts/run-episode-init.sh {run_id}", yieldMs=20000)
      ```

      The wrapper script (`run-episode-init.sh`) always exits 0: episode_init failure MUST NOT block your return. It's best-effort. Errors land in stderr; the backward chain handles missing episodes gracefully on its own retries. **Do NOT** call episode_init via inline `bash -lc 'python3 ... || true'` — cmd.exe parses `||` as its own OR operator even inside quoted bash strings, which broke prior runs (2026-05-02). Always use the wrapper.

      You don't need to inspect this exec's stdout/stderr — just fire-and-forget. (If you're curious, it prints the path of the episode file it wrote.)

4. **Return result**
   - report whether publishing succeeded
   - if publishing failed, include the script's status + url + body_excerpt verbatim so the user can see what stage it stopped at

**Anti-patterns** (Don't do these):
- ❌ Calling `creator-center` skill or `browser(action="upload")` / `browser(action="file-upload")` directly — sandbox rejection is near-certain.
- ❌ Trying to copy/move the video to `/tmp/openclaw/uploads/` or anywhere else — the `.cmd` bridge accepts the original `C:\Users\...` path verbatim.
- ❌ Constructing your own Playwright/CDP call — use `run-douyin-publish.cmd`; it's the maintained entry.

---

## Output

Return:
- `success`
- `status`
- `error`

Suggested shape:

```json
{
  "success": true,
  "status": "published",
  "error": ""
}
```

If publishing fails:

```json
{
  "success": false,
  "status": "failed",
  "error": "reason"
}
```

---

## Completion gate (MUST)

Publishing is **irreversible**. Your deliverable is the structured return — orchestrator and the user act on it directly. Before any final reply, `sessions_yield`, or `NO_REPLY`:

1. **Honesty check on `success`**:
   - `success: true` MUST be returned **only if** the platform upload completed and you observed a successful response from `creator-center`. NEVER return `success: true` based on an inferred or assumed outcome.
   - If you did not actually call the publish action successfully, `success` must be `false` and `error` must name the exact failure (e.g., `auth_required`, `upload_failed`, `metadata_rejected`, `tool_unavailable`).

2. **Honesty check on failure (anti-hallucination)** — equally important:
   - You may report `success: false, error: "tool_unavailable"` / `"upload_failed"` / `"Invalid path"` / similar **only after** you actually invoked the `browser` tool and saw the rejection in its `toolResult`. If your trajectory contains zero `browser` toolCalls, you have not attempted publishing — you cannot fabricate a tool error.
   - If you read the run files and discover a structural blocker BEFORE calling `browser` (e.g. `local_video_path` missing from `video_result.json`, or the file does not exist), the correct error is `missing_file` or `path_not_found`, NOT `tool_unavailable`. Be specific.
   - Reading `creator-center/SKILL.md` and inferring "the path probably won't work" is not a substitute for actually calling the browser. Always make the real call first.

3. **Required fields**:
   - `success` is a real boolean (not omitted)
   - `status` is one of `published` / `failed`
   - When `success: false`, `error` is a non-empty, specific reason (not just `"failed"`)

4. **Never silently exit**:
   - DO NOT reply `NO_REPLY` after attempting a publish — orchestrator MUST receive a definitive success-or-failure result, because publish is irreversible and the user is waiting on the outcome.

**Cap**: do not retry publish on your own. Report the failure to orchestrator and let it (and the user) decide whether to retry. Re-publishing the same content can create duplicate posts.

---

## Safety

- Use only the provided `local_video_path`. Do not switch assets.
- Use `title` and `tags` exactly as written in `script.json`. Do not invent metadata.
- Final publish is irreversible. Do not publish without Orchestrator authorization.
