from __future__ import annotations

import asyncio
import os
import tempfile
import unittest

from app.adapters.base import NormalizedMessage
from app.services.feishu_observer_service import (
    clear_observing_registry_for_tests,
    is_observing,
    recover_feishu_observers,
    schedule_feishu_observation,
)
from app.services.workflow_service import OpenClawWorkflowClient


class WorkflowStatusTests(unittest.TestCase):
    def test_run_status_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client = OpenClawWorkflowClient(runs_root=tmpdir, start_mode="dry_run")
            status = client.init_run_status("run_001", _message())

            self.assertEqual(status["status"], "pending")
            self.assertEqual(status["channel"], "feishu")
            self.assertEqual(status["reply_target"], "oc_123")
            self.assertTrue(client.run_status_path("run_001").exists())

    def test_run_status_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client = OpenClawWorkflowClient(runs_root=tmpdir, start_mode="dry_run")
            client.init_run_status("run_002", _message())

            status = client.update_run_status("run_002", "generated", output_video="/tmp/video.mp4")

            self.assertEqual(status["status"], "generated")
            self.assertEqual(status["output_video"], "/tmp/video.mp4")
            self.assertIsNone(status["error"])

    def test_video_result_success_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client = OpenClawWorkflowClient(runs_root=tmpdir, start_mode="dry_run")
            client.init_run_status("run_003", _message())
            client.update_run_status("run_003", "running")
            client._write_json_atomic(
                client.video_result_path("run_003"),
                {"status": "done", "local_video_path": "/tmp/generated.mp4"},
            )

            result = asyncio.run(client.observe_video_result("run_003", timeout_sec=1, interval_sec=1))

            self.assertEqual(result.status, "generated")
            self.assertEqual(result.output_video, "/tmp/generated.mp4")
            self.assertEqual(client.read_run_status("run_003")["status"], "generated")

    def test_failed_status_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client = OpenClawWorkflowClient(runs_root=tmpdir, start_mode="dry_run")
            client.init_run_status("run_004", _message())
            client.update_run_status("run_004", "failed", error="provider quota exceeded")

            result = asyncio.run(client.observe_video_result("run_004", timeout_sec=1, interval_sec=1))

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.error, "provider quota exceeded")

    def test_timeout_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client = OpenClawWorkflowClient(runs_root=tmpdir, start_mode="dry_run")
            client.init_run_status("run_005", _message())
            client.update_run_status("run_005", "running")

            result = asyncio.run(client.observe_video_result("run_005", timeout_sec=0, interval_sec=1))

            self.assertEqual(result.status, "failed")
            self.assertIn("timeout", result.error or "")
            status = client.read_run_status("run_005")
            self.assertEqual(status["status"], "failed")
            self.assertIn("timeout", status["error"])


class FeishuRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        clear_observing_registry_for_tests()
        os.environ["FEISHU_APP_ID"] = ""
        os.environ["FEISHU_APP_SECRET"] = ""
        os.environ["FEISHU_RESULT_WATCH_TIMEOUT_SEC"] = "0"
        os.environ["FEISHU_RESULT_WATCH_INTERVAL_SEC"] = "1"

    async def asyncTearDown(self) -> None:
        clear_observing_registry_for_tests()

    async def test_startup_recovery_recovers_running_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["OPENCLAW_RUNS_ROOT"] = tmpdir
            client = OpenClawWorkflowClient(runs_root=tmpdir, start_mode="dry_run")
            client.init_run_status("run_running", _message())
            client.update_run_status("run_running", "running")

            recovered = await recover_feishu_observers()

            self.assertEqual(recovered, ["run_running"])
            clear_observing_registry_for_tests()

    async def test_startup_recovery_recovers_generated_unreplied_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["OPENCLAW_RUNS_ROOT"] = tmpdir
            client = OpenClawWorkflowClient(runs_root=tmpdir, start_mode="dry_run")
            client.init_run_status("run_generated", _message())
            client.update_run_status("run_generated", "generated", output_video="/tmp/generated.mp4")
            client.write_video_result("run_generated", "/tmp/generated.mp4")

            recovered = await recover_feishu_observers()

            self.assertEqual(recovered, ["run_generated"])
            clear_observing_registry_for_tests()

    async def test_startup_recovery_skips_replied_and_failed_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["OPENCLAW_RUNS_ROOT"] = tmpdir
            client = OpenClawWorkflowClient(runs_root=tmpdir, start_mode="dry_run")
            client.init_run_status("run_replied", _message())
            client.update_run_status("run_replied", "replied")
            client.init_run_status("run_failed", _message())
            client.update_run_status("run_failed", "failed", error="boom")

            recovered = await recover_feishu_observers()

            self.assertEqual(recovered, [])

    async def test_observing_registry_prevents_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["OPENCLAW_RUNS_ROOT"] = tmpdir
            os.environ["FEISHU_RESULT_WATCH_TIMEOUT_SEC"] = "30"
            client = OpenClawWorkflowClient(runs_root=tmpdir, start_mode="dry_run")
            client.init_run_status("run_dup", _message())
            client.update_run_status("run_dup", "running")

            first = schedule_feishu_observation("run_dup", "oc_123")
            second = schedule_feishu_observation("run_dup", "oc_123")

            self.assertTrue(first)
            self.assertFalse(second)
            self.assertTrue(is_observing("run_dup"))
            clear_observing_registry_for_tests()


def _message() -> NormalizedMessage:
    return NormalizedMessage(
        platform="feishu",
        message_id="om_123",
        chat_id="oc_123",
        user_id="ou_123",
        text="帮我做一个露营美食 30 秒短视频",
        raw_event={},
        created_at="2026-05-06T00:00:00Z",
    )


if __name__ == "__main__":
    unittest.main()
