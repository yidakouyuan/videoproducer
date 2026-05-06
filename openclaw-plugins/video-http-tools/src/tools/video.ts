import { Type, getConfig, httpJson, toolTextResult } from "../shared";

export default function registerVideoTools(api: any) {
  api.registerTool({
    name: "video_analyze_start",
    description: "Start a video analysis job",
    parameters: Type.Object({
      media_id: Type.String({ description: "已缓存视频的 media_id" }),
      input_url: Type.Optional(Type.String({ description: "可选：直接传入视频 URL（跳过 media_id 查询）" })),
      analysis_profile: Type.Optional(Type.String({ description: "分析配置，如 travel / food / fashion，默认 travel" })),
      lang: Type.Optional(Type.String({ description: "语言代码，默认 zh" })),
      output_schema_version: Type.Optional(Type.String({ description: "输出 schema 版本，默认 v1" }))
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const result = await httpJson(cfg, "/video/analyze/start", "POST", params);
      return toolTextResult(result);
    }
  });

  api.registerTool({
    name: "video_analyze_result",
    description: "Get video analysis result by job_id",
    parameters: Type.Object({
      job_id: Type.String()
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const result = await httpJson(
        cfg,
        `/video/analyze/result/${encodeURIComponent(params.job_id)}`,
        "GET"
      );
      return toolTextResult(result);
    }
  });

  api.registerTool({
    name: "video_analyze_delete",
    description: "Delete a video analysis job by job_id",
    parameters: Type.Object({
      job_id: Type.String()
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const result = await httpJson(
        cfg,
        `/video/analyze/${encodeURIComponent(params.job_id)}`,
        "DELETE"
      );
      return toolTextResult(result);
    }
  });

  // Server-side wait. Use this INSTEAD of repeatedly calling video_analyze_result
  // yourself — it polls within the plugin process so the agent doesn't burn LLM
  // turns busy-polling. Returns the same shape as video_analyze_result, with
  // an extra `waited_sec` field. Returns a timeout payload (status:"timeout") if
  // the job has not reached a terminal state within `max_wait_sec`.
  api.registerTool({
    name: "video_analyze_wait_for_done",
    description:
      "Wait for a video analysis job to reach a terminal state (done/failed/partial/cancelled). " +
      "Polls server-side so the calling agent does not need to busy-poll. " +
      "Use this instead of repeatedly calling video_analyze_result yourself. " +
      "Returns the final result payload plus a waited_sec field, or a timeout payload " +
      "(status:\"timeout\") if max_wait_sec is exceeded — in that case the job is still " +
      "running in the backend and you may call this tool again with the same job_id to " +
      "continue waiting.",
    parameters: Type.Object({
      job_id: Type.String(),
      max_wait_sec: Type.Optional(
        Type.Integer({
          minimum: 1,
          maximum: 3600,
          default: 600,
          description: "Maximum total wait in seconds (default 600 = 10 min)."
        })
      ),
      poll_interval_sec: Type.Optional(
        Type.Integer({
          minimum: 1,
          maximum: 60,
          default: 3,
          description: "Seconds between polls (default 3)."
        })
      )
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const maxWaitSec: number = params.max_wait_sec ?? 600;
      const intervalSec: number = params.poll_interval_sec ?? 3;
      const TERMINAL = new Set(["done", "failed", "partial", "cancelled"]);

      const startedMs = Date.now();
      let lastObserved: any = null;
      let consecutiveErrors = 0;

      while ((Date.now() - startedMs) / 1000 < maxWaitSec) {
        let result: any = null;
        try {
          result = await httpJson(
            cfg,
            `/video/analyze/result/${encodeURIComponent(params.job_id)}`,
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
}
