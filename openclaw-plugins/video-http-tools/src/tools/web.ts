import { Type, getConfig, httpJson, toolTextResult } from "../shared";

export default function registerWebTools(api: any) {
  api.registerTool({
    name: "web_search_query",
    description:
      "Lightweight web search via Serper (Google). Use FIRST for any public web query — only fall back to `browser` when JS rendering or login state is required. ALWAYS pass `query` as an array (even for a single query, use `[\"my query\"]`). Up to 5 complementary queries per call run in parallel. Returns structured hits + ready-to-cite markdown; partial failure (one bad query in a batch) does NOT fail the whole call — see `errors[i]` for per-query failures.",
    parameters: Type.Object({
      query: Type.Array(Type.String(), {
        minItems: 1,
        maxItems: 20,
        description: "Query 数组（即使只查一条也用单元素数组 [\"hello\"]）。最多 20 条，建议每次 1-5 条。"
      }),
      top_k: Type.Optional(
        Type.Integer({ minimum: 1, maximum: 20, description: "每条 query 返回的结果数上限，默认 10" })
      ),
      country: Type.Optional(Type.String({ description: "Serper gl，默认 cn" })),
      lang: Type.Optional(Type.String({ description: "Serper hl，默认 zh" }))
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const result = await httpJson(cfg, "/web/search", "POST", params, 30000);
      return toolTextResult(result);
    }
  });

  api.registerTool({
    name: "web_fetch_url",
    description:
      "Fetch webpages as clean markdown via Jina Reader. Use AFTER web_search_query when you need page body. ALWAYS pass `url` as an array (single URL: use `[\"https://...\"]`). Up to 10 URLs per call run in parallel. Returns raw markdown — YOU judge what's relevant; the server does NOT do LLM extraction. Per-URL failures are reported in `items[i].ok=false` with `error` field; one failure does NOT fail the whole batch.",
    parameters: Type.Object({
      url: Type.Array(Type.String(), {
        minItems: 1,
        maxItems: 10,
        description: "URL 数组（即使只抓一条也用单元素数组）。最多 10 条。"
      }),
      max_chars: Type.Optional(
        Type.Integer({ minimum: 2000, maximum: 80000, description: "单页 markdown 截断上限，默认 30000" })
      )
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const result = await httpJson(cfg, "/web/fetch", "POST", params, 60000);
      return toolTextResult(result);
    }
  });
}
