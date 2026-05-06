import { Type } from "@sinclair/typebox";

export { Type };

export type PluginConfig = {
  baseUrl: string;
  timeoutMs?: number;
  apiKey?: string;
};

export function getConfig(api: any) {
  const root = api?.config ?? {};
  const cfg = root?.plugins?.entries?.["video-http-tools"]?.config ?? null;
  const env = (globalThis as any)?.process?.env ?? {};
  const baseUrl =
    cfg?.baseUrl ||
    env.AGENT_SERVICE_BASE_URL ||
    env.VIDEO_HTTP_TOOLS_BASE_URL ||
    "http://127.0.0.1:8000";

  return {
    baseUrl,
    timeoutMs: cfg?.timeoutMs ?? Number(env.AGENT_SERVICE_TIMEOUT_MS || 60000),
    apiKey: cfg?.apiKey || env.AGENT_SERVICE_API_KEY
  };
}

export async function httpJson(
  cfg: PluginConfig,
  path: string,
  method: "GET" | "POST" | "DELETE",
  body?: unknown,
  timeoutMs?: number   // per-call override; falls back to cfg.timeoutMs then 60000
) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs ?? cfg.timeoutMs ?? 60000);

  try {
    const res = await fetch(`${cfg.baseUrl}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(cfg.apiKey ? { Authorization: `Bearer ${cfg.apiKey}` } : {})
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal
    });

    const rawText = await res.text();
    let parsed: unknown = null;

    try {
      parsed = rawText ? JSON.parse(rawText) : null;
    } catch {
      parsed = rawText;
    }

    if (!res.ok) {
      throw new Error(`HTTP ${res.status} ${method} ${path}: ${JSON.stringify(parsed)}`);
    }

    return parsed;
  } finally {
    clearTimeout(timer);
  }
}

export function toolTextResult(payload: unknown) {
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify(payload, null, 2)
      }
    ]
  };
}
