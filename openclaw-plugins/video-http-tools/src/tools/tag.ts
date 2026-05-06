import { Type, getConfig, httpJson, toolTextResult } from "../shared";

export default function registerTagTools(api: any) {
  api.registerTool({
    name: "tag_get_script_pack",
    description: "Get a script pack for a tag query",
    parameters: Type.Object({
      tag: Type.String({ description: "目标标签，如 '清迈旅行'" }),
      top_k_communities: Type.Optional(Type.Integer({ minimum: 1, maximum: 20, description: "返回社区报告数量上限，默认 3" })),
      top_k_cooccur: Type.Optional(Type.Integer({ minimum: 1, maximum: 100, description: "共现标签数量上限，默认 20" })),
      lang: Type.Optional(Type.String({ description: "语言代码，默认 zh" })),
      version: Type.Optional(Type.String({ description: "GraphRAG 版本，默认 latest" }))
    }),
    async execute(_id: string, params: any) {
      const cfg = getConfig(api);
      const result = await httpJson(cfg, "/tag/script_pack", "POST", params);
      return toolTextResult(result);
    }
  });
}
