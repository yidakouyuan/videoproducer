"""
Thin client for handing normalized IM messages to the existing OpenClaw pipeline.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.adapters.base import NormalizedMessage

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStartResult:
    run_id: str
    status: str


@dataclass
class VideoObservationResult:
    status: str
    output_video: str | None = None
    error: str | None = None


class OpenClawWorkflowClient:
    def __init__(
        self,
        command: str | None = None,
        runs_root: str | None = None,
        start_mode: str | None = None,
        workdir: str | None = None,
    ) -> None:
        self.command = command if command is not None else os.environ.get(
            "OPENCLAW_ORCHESTRATOR_COMMAND",
            "openclaw agents spawn orchestrator",
        )
        self.runs_root = Path(
            runs_root if runs_root is not None else os.environ.get("OPENCLAW_RUNS_ROOT", "~/.openclaw/runs")
        ).expanduser()
        self.start_mode = start_mode if start_mode is not None else os.environ.get("OPENCLAW_START_MODE", "cli")
        configured_workdir = workdir if workdir is not None else os.environ.get("OPENCLAW_WORKDIR")
        self.workdir = Path(configured_workdir).expanduser() if configured_workdir else None

    async def start(self, message: NormalizedMessage) -> WorkflowStartResult:
        run_id = self._new_run_id()
        self._write_entry_context(run_id, message)
        self.init_run_status(run_id, message)
        logger.info("created run_id=%s channel=%s reply_target=%s", run_id, message.platform, message.chat_id)

        prompt = self._build_prompt(run_id, message)
        if self.start_mode.strip().lower() in {"dry_run", "dry-run", "noop"}:
            logger.info("openclaw dry-run start: run_id=%s", run_id)
            self.update_run_status(run_id, "running")
            return WorkflowStartResult(run_id=run_id, status="running")

        args = self._build_command_args(prompt)
        logger.info("starting openclaw orchestrator: args=%s cwd=%s run_id=%s", args[:-1], self.workdir, run_id)
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workdir) if self.workdir else None,
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                raise RuntimeError(
                    "OpenClaw orchestrator start failed: "
                    f"returncode={process.returncode}, stderr={stderr.decode(errors='ignore')}"
                )
            if stdout:
                logger.info("openclaw start stdout: %s", stdout.decode(errors="ignore").strip())
            self.update_run_status(run_id, "running")
            return WorkflowStartResult(run_id=run_id, status="running")
        except Exception as exc:
            self.write_error(run_id, str(exc))
            self.update_run_status(run_id, "failed", error=str(exc))
            raise

    def video_result_path(self, run_id: str) -> Path:
        return self.runs_root / run_id / "video_result.json"

    def video_partial_path(self, run_id: str) -> Path:
        return self.runs_root / run_id / "video_result.json.partial"

    def run_dir(self, run_id: str) -> Path:
        return self.runs_root / run_id

    def entry_message_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "entry_message.json"

    def run_status_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "run_status.json"

    def error_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "error.json"

    def init_run_status(self, run_id: str, message: NormalizedMessage) -> dict[str, Any]:
        now = _now_iso()
        status = {
            "run_id": run_id,
            "status": "pending",
            "channel": message.platform,
            "reply_target": message.chat_id,
            "created_at": now,
            "updated_at": now,
            "source_message_id": message.message_id,
            "user_id": message.user_id,
            "error": None,
            "output_video": None,
        }
        self._write_json_atomic(self.run_status_path(run_id), status)
        logger.info("run_status initialized: run_id=%s status=pending", run_id)
        return status

    def read_run_status(self, run_id: str) -> dict[str, Any]:
        path = self.run_status_path(run_id)
        if not path.exists():
            raise FileNotFoundError(f"run_status.json not found for run_id={run_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def update_run_status(
        self,
        run_id: str,
        status: str,
        error: str | None = None,
        output_video: str | None = None,
    ) -> dict[str, Any]:
        try:
            current = self.read_run_status(run_id)
        except FileNotFoundError:
            current = {
                "run_id": run_id,
                "status": "pending",
                "channel": None,
                "reply_target": None,
                "created_at": _now_iso(),
                "error": None,
                "output_video": None,
            }

        current["status"] = status
        current["updated_at"] = _now_iso()
        if error is not None:
            current["error"] = error
        if output_video is not None:
            current["output_video"] = output_video
        self._write_json_atomic(self.run_status_path(run_id), current)
        logger.info("run_status updated: run_id=%s status=%s", run_id, status)
        return current

    def write_error(self, run_id: str, error: str) -> None:
        payload = {"run_id": run_id, "error": error, "created_at": _now_iso()}
        self._write_json_atomic(self.error_path(run_id), payload)

    def write_video_result(self, run_id: str, output_video: str, status: str = "done") -> dict[str, Any]:
        payload = {"status": status, "local_video_path": output_video}
        self._write_json_atomic(self.video_result_path(run_id), payload)
        return payload

    def run_file_state(self, run_id: str) -> dict[str, bool]:
        return {
            "entry_message_exists": self.entry_message_path(run_id).exists(),
            "video_result_exists": self.video_result_path(run_id).exists(),
            "error_exists": self.error_path(run_id).exists(),
        }

    def list_run_statuses(self, limit: int = 20) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if not self.runs_root.exists():
            return items

        for status_path in self.runs_root.glob("*/run_status.json"):
            try:
                status = self._read_json_file(status_path)
            except Exception:
                logger.warning("skip unreadable run_status: %s", status_path, exc_info=True)
                continue
            status.setdefault("run_id", status_path.parent.name)
            items.append(status)

        items.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
        return items[: max(limit, 0)]

    async def observe_video_result(
        self,
        run_id: str,
        timeout_sec: int,
        interval_sec: int,
    ) -> VideoObservationResult:
        deadline = datetime.now(timezone.utc).timestamp() + max(timeout_sec, 0)
        interval = max(interval_sec, 1)
        logger.info("start observing video result: run_id=%s timeout_sec=%s", run_id, timeout_sec)

        terminal = self._inspect_terminal_files(run_id)
        if terminal is not None:
            return terminal

        while datetime.now(timezone.utc).timestamp() < deadline:
            terminal = self._inspect_terminal_files(run_id)
            if terminal is not None:
                return terminal
            await asyncio.sleep(interval)

        error = f"video_result.json wait timeout after {timeout_sec}s"
        logger.warning("video result observe timeout: run_id=%s", run_id)
        self.write_error(run_id, error)
        self.update_run_status(run_id, "failed", error=error)
        return VideoObservationResult(status="failed", error=error)

    def _inspect_terminal_files(self, run_id: str) -> VideoObservationResult | None:
        try:
            status = self.read_run_status(run_id)
            if status.get("status") == "failed":
                return VideoObservationResult(status="failed", error=status.get("error") or "run failed")
            if status.get("status") == "generated" and status.get("output_video"):
                return VideoObservationResult(status="generated", output_video=str(status["output_video"]))
        except FileNotFoundError:
            logger.warning("run_status missing while observing: run_id=%s", run_id)

        error_path = self.error_path(run_id)
        if error_path.exists():
            error = self._read_error_file(error_path)
            self.update_run_status(run_id, "failed", error=error)
            return VideoObservationResult(status="failed", error=error)

        result_path = self.video_result_path(run_id)
        if result_path.exists():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception as exc:
                error = f"failed to parse video_result.json: {exc}"
                logger.exception("failed to parse video_result.json: run_id=%s", run_id)
                self.write_error(run_id, error)
                self.update_run_status(run_id, "failed", error=error)
                return VideoObservationResult(status="failed", error=error)

            if result.get("status") == "done":
                output = _extract_output_video(result)
                self.update_run_status(run_id, "generated", output_video=output)
                return VideoObservationResult(status="generated", output_video=output)

            error = str(result.get("error") or result.get("error_message") or "video generation failed")
            self.write_error(run_id, error)
            self.update_run_status(run_id, "failed", error=error)
            return VideoObservationResult(status="failed", error=error)

        partial_path = self.video_partial_path(run_id)
        if partial_path.exists():
            try:
                partial = json.loads(partial_path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("failed to inspect partial video result: run_id=%s", run_id, exc_info=True)
                return None
            if partial.get("status") == "failed":
                error = str(partial.get("error") or partial.get("error_message") or "video generation failed")
                self.write_error(run_id, error)
                self.update_run_status(run_id, "failed", error=error)
                return VideoObservationResult(status="failed", error=error)

        return None

    def _new_run_id(self) -> str:
        base = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = base
        suffix = 1
        while (self.runs_root / candidate).exists():
            suffix += 1
            candidate = f"{base}_{suffix}"
        return candidate

    def _write_entry_context(self, run_id: str, message: NormalizedMessage) -> None:
        run_dir = self.runs_root / run_id
        raw_dir = run_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "run_id": run_id,
            "channel": message.platform,
            "reply_target": message.chat_id,
            "message_id": message.message_id,
            "user_id": message.user_id,
            "text": message.text,
            "created_at": message.created_at,
        }
        self._write_json_atomic(self.entry_message_path(run_id), entry)

    def _build_prompt(self, run_id: str, message: NormalizedMessage) -> str:
        return (
            "外部 IM 入口收到一个新的短视频生产任务。\n"
            "请使用下面指定的 run_id，不要重新生成 run_id；请按现有 VideoClaw 多 Agent 流水线执行。\n\n"
            f"run_id: {run_id}\n"
            f"channel: {message.platform}\n"
            f"reply_target: {message.chat_id}\n"
            f"source_message_id: {message.message_id}\n"
            f"user_id: {message.user_id}\n"
            f"用户原始请求: {message.text}\n\n"
            "请在 brief.json 中保留 channel、reply_target、source_message_id。"
            "如果当前 OpenClaw message 工具不能直接投递该 channel，也请照常完成并写入 video_result.json，"
            "外部 Message Adapter 会负责把成片结果回传到对应 IM 会话。"
        )

    def _build_command_args(self, prompt: str) -> list[str]:
        parts = shlex.split(self.command)
        if any("{prompt}" in part for part in parts):
            return [part.replace("{prompt}", prompt) for part in parts]
        return [*parts, prompt]

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    @staticmethod
    def _read_json_file(path: Path) -> dict[str, Any]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"expected JSON object in {path}")
        return data

    @staticmethod
    def _read_error_file(path: Path) -> str:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return path.read_text(encoding="utf-8", errors="ignore").strip() or "run failed"
        if isinstance(data, dict):
            return str(data.get("error") or data.get("message") or data)
        return str(data)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_output_video(result: dict[str, Any]) -> str | None:
    value = (
        result.get("public_url")
        or result.get("object_url")
        or result.get("video_url")
        or result.get("local_video_path")
    )
    return str(value) if value else None
