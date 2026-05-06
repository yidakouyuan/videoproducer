"""
Shared message adapter contracts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional, Protocol, runtime_checkable

Platform = Literal["telegram", "whatsapp", "feishu", "wecom", "dingtalk"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class NormalizedMessage:
    platform: Platform
    message_id: str
    chat_id: str
    user_id: str
    text: str
    raw_event: Any
    created_at: str
    message_type: str = "text"


@dataclass
class ReplyPayload:
    chat_id: str
    text: Optional[str] = None
    file: Optional[str | Path] = None
    caption: Optional[str] = None


@runtime_checkable
class MessageAdapter(Protocol):
    platform: Platform

    def parseIncoming(self, event: Any) -> NormalizedMessage:
        """Convert a platform webhook/update into a NormalizedMessage."""

    async def sendText(self, chat_id: str, text: str) -> None:
        """Send a plain text reply to the platform conversation."""

    async def sendFile(self, chat_id: str, file: str | Path, caption: str | None = None) -> None:
        """Send a file reply when the platform implementation supports it."""
