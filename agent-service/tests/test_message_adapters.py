from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from fastapi import FastAPI

os.environ["FEISHU_BOT_ENABLED"] = "true"
os.environ["FEISHU_VERIFICATION_TOKEN"] = "test_token"
os.environ["FEISHU_APP_ID"] = ""
os.environ["FEISHU_APP_SECRET"] = ""
os.environ["OPENCLAW_START_MODE"] = "dry_run"
os.environ["FEISHU_RESULT_WATCH_TIMEOUT_SEC"] = "0"
os.environ["FEISHU_RESULT_WATCH_INTERVAL_SEC"] = "1"

from app.adapters.base import MessageAdapter  # noqa: E402
from app.adapters.feishu import FeishuAdapter  # noqa: E402
from app.adapters.telegram import TelegramAdapter  # noqa: E402
from app.adapters.whatsapp import WhatsAppAdapter  # noqa: E402
from app.infra.response import RequestContextMiddleware  # noqa: E402
from app.routes.feishu import router as feishu_router  # noqa: E402
from app.routes.runs import router as runs_router  # noqa: E402
from app.services.feishu_observer_service import clear_observing_registry_for_tests  # noqa: E402
from app.services.workflow_service import OpenClawWorkflowClient  # noqa: E402


def _test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.include_router(feishu_router)
    app.include_router(runs_router)
    return app


class MessageAdapterTests(unittest.TestCase):
    def test_feishu_challenge_event(self) -> None:
        client = TestClient(_test_app())
        response = client.post(
            "/webhooks/feishu/events",
            json={
                "type": "url_verification",
                "token": "test_token",
                "challenge": "challenge_value",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"challenge": "challenge_value"})

    def test_feishu_text_message_parse(self) -> None:
        adapter = FeishuAdapter(verification_token="test_token")
        event = _feishu_event("帮我做一个露营美食 30 秒短视频")

        message = adapter.parseIncoming(event)

        self.assertEqual(message.platform, "feishu")
        self.assertEqual(message.message_id, "om_123")
        self.assertEqual(message.chat_id, "oc_123")
        self.assertEqual(message.user_id, "ou_123")
        self.assertEqual(message.text, "帮我做一个露营美食 30 秒短视频")
        self.assertEqual(message.message_type, "text")

    def test_feishu_empty_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["OPENCLAW_RUNS_ROOT"] = tmpdir
            client = TestClient(_test_app())
            response = client.post("/webhooks/feishu/events", json=_feishu_event("   "))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data"]["status"], "ignored")
        self.assertEqual(body["data"]["reason"], "empty_message")

    def test_run_status_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["OPENCLAW_RUNS_ROOT"] = tmpdir
            client = TestClient(_test_app())
            response = client.post("/webhooks/feishu/events", json=_feishu_event("帮我做一个露营美食 30 秒短视频"))
            run_id = response.json()["data"]["run_id"]

            status_response = client.get(f"/runs/{run_id}/status")

        self.assertEqual(status_response.status_code, 200)
        data = status_response.json()["data"]
        self.assertEqual(data["run_id"], run_id)
        self.assertEqual(data["channel"], "feishu")
        self.assertEqual(data["reply_target"], "oc_123")
        self.assertIn("observing", data)
        self.assertTrue(data["run_dir"].endswith(run_id))
        self.assertTrue(data["entry_message_exists"])
        self.assertFalse(data["video_result_exists"])
        self.assertIn("error_exists", data)
        clear_observing_registry_for_tests()

    def test_runs_list_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["OPENCLAW_RUNS_ROOT"] = tmpdir
            workflow = OpenClawWorkflowClient(runs_root=tmpdir, start_mode="dry_run")
            workflow.init_run_status("run_a", _normalized_message("om_a", "oc_a"))
            workflow.update_run_status("run_a", "running")
            workflow.init_run_status("run_b", _normalized_message("om_b", "oc_b"))
            workflow.update_run_status("run_b", "generated", output_video="/tmp/b.mp4")

            client = TestClient(_test_app())
            response = client.get("/runs?limit=2")

        self.assertEqual(response.status_code, 200)
        runs = response.json()["data"]["runs"]
        self.assertEqual(len(runs), 2)
        self.assertEqual({item["run_id"] for item in runs}, {"run_a", "run_b"})

    def test_mock_complete_available_in_test_mode(self) -> None:
        clear_observing_registry_for_tests()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["OPENCLAW_RUNS_ROOT"] = tmpdir
            os.environ["TEST_MODE"] = "true"
            workflow = OpenClawWorkflowClient(runs_root=tmpdir, start_mode="dry_run")
            workflow.init_run_status("run_mock", _normalized_message("om_mock", "oc_mock"))
            workflow.update_run_status("run_mock", "running")

            client = TestClient(_test_app())
            response = client.post("/runs/run_mock/mock-complete?output_video=/tmp/mock.mp4")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["output_video"], "/tmp/mock.mp4")
        self.assertTrue(data["scheduled_observer"])
        clear_observing_registry_for_tests()

    def test_mock_complete_disabled_in_production_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["OPENCLAW_RUNS_ROOT"] = tmpdir
            os.environ["DEBUG"] = "false"
            os.environ["TEST_MODE"] = "false"
            os.environ["ENV"] = "production"
            workflow = OpenClawWorkflowClient(runs_root=tmpdir, start_mode="dry_run")
            workflow.init_run_status("run_prod", _normalized_message("om_prod", "oc_prod"))

            client = TestClient(_test_app())
            response = client.post("/runs/run_prod/mock-complete")

        self.assertEqual(response.status_code, 403)

    def test_feishu_status_command_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["OPENCLAW_RUNS_ROOT"] = tmpdir
            workflow = OpenClawWorkflowClient(runs_root=tmpdir, start_mode="dry_run")
            workflow.init_run_status("run_status", _normalized_message("om_status", "oc_123"))
            workflow.update_run_status("run_status", "generated", output_video="/tmp/status.mp4")
            workflow.write_video_result("run_status", "/tmp/status.mp4")

            client = TestClient(_test_app())
            with patch("app.adapters.feishu.adapter.FeishuAdapter.sendText", new=AsyncMock()) as send_text:
                response = client.post("/webhooks/feishu/events", json=_feishu_event("/status run_status"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "command_handled")
        sent = send_text.await_args.args[1]
        self.assertIn("任务状态", sent)
        self.assertIn("run_id: run_status", sent)
        self.assertIn("output_video: /tmp/status.mp4", sent)
        self.assertIn("video_result: yes", sent)

    def test_feishu_status_command_missing_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["OPENCLAW_RUNS_ROOT"] = tmpdir
            client = TestClient(_test_app())
            with patch("app.adapters.feishu.adapter.FeishuAdapter.sendText", new=AsyncMock()) as send_text:
                response = client.post("/webhooks/feishu/events", json=_feishu_event("/status"))

        self.assertEqual(response.status_code, 200)
        sent = send_text.await_args.args[1]
        self.assertIn("请带上 run_id", sent)

    def test_feishu_status_command_run_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["OPENCLAW_RUNS_ROOT"] = tmpdir
            client = TestClient(_test_app())
            with patch("app.adapters.feishu.adapter.FeishuAdapter.sendText", new=AsyncMock()) as send_text:
                response = client.post("/webhooks/feishu/events", json=_feishu_event("查询 missing_run"))

        self.assertEqual(response.status_code, 200)
        sent = send_text.await_args.args[1]
        self.assertIn("没有找到 run_id：missing_run", sent)

    def test_feishu_runs_command_returns_recent_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["OPENCLAW_RUNS_ROOT"] = tmpdir
            workflow = OpenClawWorkflowClient(runs_root=tmpdir, start_mode="dry_run")
            workflow.init_run_status("run_recent_a", _normalized_message("om_a", "oc_a"))
            workflow.update_run_status("run_recent_a", "running")
            workflow.init_run_status("run_recent_b", _normalized_message("om_b", "oc_b"))
            workflow.update_run_status("run_recent_b", "generated", output_video="/tmp/recent_b.mp4")

            client = TestClient(_test_app())
            with patch("app.adapters.feishu.adapter.FeishuAdapter.sendText", new=AsyncMock()) as send_text:
                response = client.post("/webhooks/feishu/events", json=_feishu_event("最近任务"))

        self.assertEqual(response.status_code, 200)
        sent = send_text.await_args.args[1]
        self.assertIn("最近任务", sent)
        self.assertIn("run_recent_a", sent)
        self.assertIn("run_recent_b", sent)
        self.assertIn("/tmp/recent_b.mp4", sent)

    def test_feishu_runs_command_no_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["OPENCLAW_RUNS_ROOT"] = tmpdir
            client = TestClient(_test_app())
            with patch("app.adapters.feishu.adapter.FeishuAdapter.sendText", new=AsyncMock()) as send_text:
                response = client.post("/webhooks/feishu/events", json=_feishu_event("/runs"))

        self.assertEqual(response.status_code, 200)
        sent = send_text.await_args.args[1]
        self.assertIn("暂时没有历史任务", sent)

    def test_normal_video_start_reply_includes_status_command(self) -> None:
        clear_observing_registry_for_tests()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["OPENCLAW_RUNS_ROOT"] = tmpdir
            os.environ["OPENCLAW_START_MODE"] = "dry_run"
            client = TestClient(_test_app())
            with patch("app.adapters.feishu.adapter.FeishuAdapter.sendText", new=AsyncMock()) as send_text:
                response = client.post("/webhooks/feishu/events", json=_feishu_event("帮我做一个露营美食 30 秒短视频"))
                run_id = response.json()["data"]["run_id"]

        self.assertEqual(response.status_code, 200)
        sent_messages = [call.args[1] for call in send_text.await_args_list]
        start_replies = [message for message in sent_messages if "任务主题：" in message]
        self.assertTrue(start_replies)
        self.assertIn(f"/status {run_id}", start_replies[0])
        self.assertIn("当前状态：running", start_replies[0])
        clear_observing_registry_for_tests()

    def test_feishu_send_card_text_fallback(self) -> None:
        adapter = FeishuAdapter(app_id="", app_secret="", verification_token="test_token")
        adapter.sendText = AsyncMock()

        import asyncio

        asyncio.run(adapter.sendCard("oc_123", {"text": "卡片 fallback 文本"}))

        adapter.sendText.assert_awaited_once_with("oc_123", "卡片 fallback 文本")

    def test_telegram_whatsapp_adapters_match_contract(self) -> None:
        telegram = TelegramAdapter()
        whatsapp = WhatsAppAdapter()

        self.assertIsInstance(telegram, MessageAdapter)
        self.assertIsInstance(whatsapp, MessageAdapter)

        tg_msg = telegram.parseIncoming(
            {
                "update_id": 1,
                "message": {
                    "message_id": 2,
                    "chat": {"id": 3},
                    "from": {"id": 4},
                    "text": "做一个户外美食视频",
                },
            }
        )
        self.assertEqual(tg_msg.platform, "telegram")
        self.assertEqual(tg_msg.text, "做一个户外美食视频")

        wa_msg = whatsapp.parseIncoming(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "id": "wamid.1",
                                            "from": "15550001111",
                                            "type": "text",
                                            "text": {"body": "做一个探店视频"},
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
        )
        self.assertEqual(wa_msg.platform, "whatsapp")
        self.assertEqual(wa_msg.text, "做一个探店视频")


def _feishu_event(text: str) -> dict:
    return {
        "schema": "2.0",
        "header": {
            "event_id": "ev_123",
            "event_type": "im.message.receive_v1",
            "create_time": "1714970000000",
            "token": "test_token",
        },
        "event": {
            "sender": {"sender_id": {"open_id": "ou_123"}},
            "message": {
                "message_id": "om_123",
                "chat_id": "oc_123",
                "message_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        },
    }


def _normalized_message(message_id: str, chat_id: str):
    from app.adapters.base import NormalizedMessage

    return NormalizedMessage(
        platform="feishu",
        message_id=message_id,
        chat_id=chat_id,
        user_id="ou_123",
        text="帮我做一个露营美食 30 秒短视频",
        raw_event={},
        created_at="2026-05-06T00:00:00Z",
    )


if __name__ == "__main__":
    unittest.main()
