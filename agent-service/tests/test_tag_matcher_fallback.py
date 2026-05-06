from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_GROUNDING_PATH = _ROOT / "workspace-tag-matcher" / "tools" / "local_grounding.py"
_SPEC = importlib.util.spec_from_file_location("local_grounding", _LOCAL_GROUNDING_PATH)
local_grounding = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(local_grounding)

from app.providers.local_script_pack_provider import LocalScriptPackProvider  # noqa: E402


class TagMatcherFallbackTests(unittest.TestCase):
    def test_http_tool_available_uses_http_result(self) -> None:
        def http_tool(tag: str) -> dict:
            return {
                "data": {
                    "canonical_topic": "HTTP露营美食",
                    "search_seeds": {
                        "douyin_queries": ["http douyin"],
                        "web_queries": ["http web"],
                    },
                }
            }

        result = local_grounding.ground_topic("帮我做一个露营美食 30 秒短视频", http_tool=http_tool)

        self.assertTrue(result["ok"])
        self.assertEqual(result["grounding_results"][0]["source"], "tag_get_script_pack")
        self.assertEqual(result["best_matches"], ["HTTP露营美食"])

    def test_http_tool_unavailable_uses_local_script_pack(self) -> None:
        def broken_http_tool(tag: str) -> dict:
            raise RuntimeError("HTTP backend not running")

        result = local_grounding.ground_topic("帮我做一个露营美食 30 秒短视频", http_tool=broken_http_tool)

        self.assertTrue(result["ok"])
        grounding = result["grounding_results"][0]
        self.assertEqual(grounding["source"], "local_script_pack")
        self.assertEqual(grounding["canonical_topic"], "露营美食")
        self.assertIn("露营美食", grounding["search_seeds"]["douyin_queries"])
        self.assertIn("tag_get_script_pack unavailable", result["notes_for_orchestrator"][0])

    def test_missing_local_file_generates_minimal_fallback(self) -> None:
        missing_path = Path(tempfile.gettempdir()) / "not_existing_script_packs.json"

        result = local_grounding.ground_topic("帮我做一个小众手作 30 秒短视频", script_pack_path=missing_path)

        self.assertTrue(result["ok"])
        grounding = result["grounding_results"][0]
        self.assertEqual(grounding["source"], "minimal_fallback")
        self.assertIn("minimal fallback", grounding["evidence_packs"][0]["evidence_notes"][0])

    def test_camping_food_query_grounds_to_outdoor_food_tag(self) -> None:
        result = local_grounding.ground_topic("帮我做一个露营美食 30 秒短视频")

        self.assertTrue(result["ok"])
        self.assertEqual(result["recommendation"], "露营美食")
        self.assertIn("露营美食", result["best_matches"][0])

    def test_unregistered_tool_does_not_block_pipeline(self) -> None:
        result = local_grounding.ground_topic("帮我做一个城市探店 30 秒短视频", http_tool=None)

        self.assertTrue(result["ok"])
        self.assertNotIn("error", result)
        self.assertTrue(result["best_matches"])

    def test_empty_input_returns_understandable_error(self) -> None:
        result = local_grounding.ground_topic("   ")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "empty_input")

    def test_agent_service_local_provider_serves_camping_pack(self) -> None:
        import asyncio

        provider = LocalScriptPackProvider()
        pack = asyncio.run(provider.get_script_pack("露营美食", 3, 20, "zh", "latest"))

        self.assertEqual(pack.canonical_topic, "露营美食")
        self.assertIn("露营美食", pack.search_seeds["douyin_queries"])


if __name__ == "__main__":
    unittest.main()
