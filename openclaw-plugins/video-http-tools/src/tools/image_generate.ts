import { Type, getConfig, httpJson, toolTextResult } from "../shared";

export default function registerImageGenerateTools(api: any) {
  api.registerTool({
    name: "image_generate_models",
    description: "List all available image generation models for the current provider. Call this before image_generate_start if you need to select a specific model. Returns provider name and model list with supported modes (t2i/i2i) and which is the default.",
    parameters: Type.Object({}),
    async execute(_id: string, _params: any) {
      const cfg = getConfig(api);
      const result = await httpJson(cfg, "/image/generate/models", "GET");
      return toolTextResult(result);
    }
  });

  api.registerTool({
    name: "image_generate_start",
    description: "Start an image generation job. Supports text-to-image (t2i) and style-reference image generation (i2i). Use this to generate a style anchor image for a video, or to generate per-shot reference images that will be used as first frames for video generation.",
    parameters: Type.Object({
      prompt: Type.String({ description: "Image generation text description" }),
      style_reference_path: Type.Optional(Type.String({
        description: "Style reference image: local file path or public URL. When provided, the generated image will maintain visual style consistency with the reference. Use the style anchor image here for per-shot generation."
      })),
      model: Type.Optional(Type.String({
        description: "Model name, overrides server default (e.g., kolors, kolors-image-to-image). Use image_generate_models to list options."
      }))
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const result = await httpJson(cfg, "/image/generate/start", "POST", params);
      return toolTextResult(result);
    }
  });

  api.registerTool({
    name: "image_generate_result",
    description: "Get image generation result by job_id. Poll until status is done or failed. Pass wait_sec=30 to enable server-side long-polling — the server will wait up to 30s for a state change before responding, reducing the number of calls needed. On success, local_image_path contains the downloaded image path to use as first_frame_path in video_generate_start.",
    parameters: Type.Object({
      job_id: Type.String(),
      wait_sec: Type.Optional(Type.Integer({
        minimum: 0,
        maximum: 120,
        description: "Server-side long-poll wait seconds (0 = return immediately). Recommended: 30."
      }))
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const waitSec = params.wait_sec ?? 0;
      // Client timeout = server long-poll wait + 15s buffer to avoid racing the response
      const timeoutMs = waitSec * 1000 + 15000;
      const result = await httpJson(
        cfg,
        `/image/generate/result/${encodeURIComponent(params.job_id)}?wait_sec=${waitSec}`,
        "GET",
        undefined,
        timeoutMs
      );
      return toolTextResult(result);
    }
  });

  api.registerTool({
    name: "image_generate_delete",
    description: "Delete an image generation job by job_id after use.",
    parameters: Type.Object({
      job_id: Type.String()
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const result = await httpJson(
        cfg,
        `/image/generate/${encodeURIComponent(params.job_id)}`,
        "DELETE"
      );
      return toolTextResult(result);
    }
  });

  // Server-side wait. Use this INSTEAD of repeatedly calling image_generate_result
  // yourself — it polls within the plugin process so the agent doesn't burn LLM
  // turns busy-polling. Returns the same shape as image_generate_result, with
  // an extra `waited_sec` field. Returns a timeout payload (status:"timeout") if
  // the job has not reached a terminal state within `max_wait_sec`.
  //
  // PREFERRED for both anchor and per-shot image generation. For storyboard runs
  // that submit many images in parallel, you can also use image_generate_result
  // with wait_sec=30 if you need concurrent polling, but most flows are simpler
  // with wait_for_done.
  api.registerTool({
    name: "image_generate_wait_for_done",
    description:
      "Wait for an image generation job to reach a terminal state (done/failed/partial/cancelled). " +
      "Polls server-side so the calling agent does not need to busy-poll. " +
      "Use this INSTEAD of repeatedly calling image_generate_result yourself for the typical " +
      "submit-then-wait flow (anchor image, per-shot reference images). " +
      "Returns the final result payload plus a waited_sec field, or a timeout payload " +
      "(status:\"timeout\") if max_wait_sec is exceeded.",
    parameters: Type.Object({
      job_id: Type.String(),
      max_wait_sec: Type.Optional(
        Type.Integer({
          minimum: 1,
          maximum: 1800,
          default: 300,
          description: "Maximum total wait in seconds (default 300 = 5 min). Image generation is typically 5–60s, so 300s is generous."
        })
      ),
      poll_interval_sec: Type.Optional(
        Type.Integer({
          minimum: 1,
          maximum: 30,
          default: 3,
          description: "Seconds between polls (default 3). Image generation is faster than video, so smaller intervals are fine."
        })
      )
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const maxWaitSec: number = params.max_wait_sec ?? 300;
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
            `/image/generate/result/${encodeURIComponent(params.job_id)}`,
            "GET"
          );
          consecutiveErrors = 0;
        } catch (err) {
          consecutiveErrors += 1;
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
