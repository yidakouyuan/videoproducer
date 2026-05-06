import { Type, getConfig, httpJson, toolTextResult } from "../shared";

const WriteItemSchema = Type.Object({
  platform: Type.Optional(Type.String({ description: "平台，如 douyin，默认 douyin" })),
  title: Type.String({ description: "视频标题" }),
  publish_time: Type.String({ description: "发布时间，ISO 8601，如 2026-03-10T12:00:00Z" }),
  duration_sec: Type.Optional(Type.Number({ description: "视频时长（秒）" })),
  play_count: Type.Optional(Type.Integer({ description: "播放量" })),
  like_count: Type.Optional(Type.Integer({ description: "点赞量" })),
  comment_count: Type.Optional(Type.Integer({ description: "评论量" })),
  share_count: Type.Optional(Type.Integer({ description: "分享量" })),
  collect_count: Type.Optional(Type.Integer({ description: "收藏量" })),
  danmaku_count: Type.Optional(Type.Integer({ description: "弹幕量" })),
  completion_rate: Type.Optional(Type.Number({ description: "完播率，0.0~1.0" })),
  two_sec_exit_rate: Type.Optional(Type.Number({ description: "2s 跳出率，0.0~1.0" })),
  follower_gain: Type.Optional(Type.Integer({ description: "吸粉量" })),
  follower_loss: Type.Optional(Type.Integer({ description: "脱粉量" })),
  fan_play_ratio: Type.Optional(Type.Number({ description: "粉丝播放占比，0.0~1.0" }))
});

export default function registerStatsTools(api: any) {
  api.registerTool({
    name: "stats_write",
    description: "Write one or more video metric snapshots to the database. Each call adds a new snapshot without overwriting history.",
    parameters: Type.Object({
      items: Type.Array(WriteItemSchema, { description: "快照列表，单条也需用数组包装" })
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const result = await httpJson(cfg, "/stats/write", "POST", params);
      return toolTextResult(result);
    }
  });

  api.registerTool({
    name: "stats_query",
    description: "Query video metric snapshots with filters and pagination. Returns total_count for pagination. Use latest_only=true to get only the most recent snapshot per video.",
    parameters: Type.Object({
      platform: Type.Optional(Type.String({ description: "按平台过滤" })),
      title: Type.Optional(Type.String({ description: "标题模糊匹配" })),
      publish_since: Type.Optional(Type.String({ description: "发布时间起点，ISO 8601" })),
      publish_until: Type.Optional(Type.String({ description: "发布时间终点，ISO 8601" })),
      snapshot_since: Type.Optional(Type.String({ description: "快照时间起点，ISO 8601" })),
      snapshot_until: Type.Optional(Type.String({ description: "快照时间终点，ISO 8601" })),
      latest_only: Type.Optional(Type.Boolean({ description: "true 时每个视频只返回最新快照" })),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 500, description: "每页条数，默认 50" })),
      offset: Type.Optional(Type.Integer({ minimum: 0, description: "跳过条数，默认 0" }))
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const query = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) {
        if (v !== undefined && v !== null) query.set(k, String(v));
      }
      const path = `/stats/query${query.toString() ? "?" + query.toString() : ""}`;
      const result = await httpJson(cfg, path, "GET");
      return toolTextResult(result);
    }
  });
}
