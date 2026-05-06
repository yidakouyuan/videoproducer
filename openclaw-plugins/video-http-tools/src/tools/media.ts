import { Type, getConfig, httpJson, toolTextResult } from "../shared";

const SourceRefSchema = Type.Object({
  platform: Type.Optional(Type.String({ description: "平台名称，固定为 douyin" })),
  aweme_id: Type.String({ description: "抖音视频 ID" }),
  share_url: Type.String({ description: "抖音分享链接" })
});

const ResolvedVideoRefSchema = Type.Object({
  platform: Type.String(),
  aweme_id: Type.String(),
  share_url: Type.String(),
  video_url: Type.String(),
  downloadable: Type.Boolean()
});

export default function registerMediaTools(api: any) {
  api.registerTool({
    name: "media_resolve_video",
    description: "Resolve a Douyin video reference into a downloadable media object. Returns platform, aweme_id, share_url, video_url, downloadable.",
    parameters: Type.Object({
      source_ref: SourceRefSchema
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const result = await httpJson(cfg, "/media/resolve_video", "POST", params);
      return toolTextResult(result);
    }
  });

  api.registerTool({
    name: "media_fetch_video",
    description: "Download and cache a resolved video. Pass the full resolved_video_ref object returned by media_resolve_video. Returns media_id and local_video_path.",
    parameters: Type.Object({
      resolved_video_ref: ResolvedVideoRefSchema
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      // media_fetch_video downloads a video file from Douyin — the slowest
      // operation in this plugin family. The plugin-wide default (60s) often
      // isn't enough on slow networks or for larger videos; previous runs saw
      // batches of fetches all aborted at exactly 30s/60s. Override per-call
      // to 120s. Other tools in this plugin keep the default.
      const fetchCfg = { ...cfg, timeoutMs: 120_000 };
      const result = await httpJson(fetchCfg, "/media/fetch_video", "POST", params);
      return toolTextResult(result);
    }
  });

  api.registerTool({
    name: "media_delete",
    description: "Delete a cached media object by media_id",
    parameters: Type.Object({
      media_id: Type.String()
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const result = await httpJson(cfg, `/media/${encodeURIComponent(params.media_id)}`, "DELETE");
      return toolTextResult(result);
    }
  });

  api.registerTool({
    name: "media_cleanup",
    description: "Batch cleanup cached media. Use dry_run=true to preview before deleting.",
    parameters: Type.Object({
      older_than_days: Type.Optional(Type.Integer({ minimum: 1, description: "清理 N 天前的媒体" })),
      only_unreferenced: Type.Optional(Type.Boolean({ description: "只清理未被引用的媒体，默认 true" })),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000, description: "单次最多处理数量，默认 100" })),
      dry_run: Type.Optional(Type.Boolean({ description: "true 时只预览不删除，默认 true" }))
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const result = await httpJson(cfg, "/media/cleanup", "POST", params);
      return toolTextResult(result);
    }
  });
}
