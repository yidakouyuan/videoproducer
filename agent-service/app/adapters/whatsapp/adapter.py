"""
WhatsApp adapter.

The production WhatsApp entry remains OpenClaw's native channel. This adapter
keeps the same normalization surface for platforms that expose HTTP webhooks.
"""
from __future__ import annotations

import logging
from typing import Any

from app.adapters.base import NormalizedMessage, utc_now_iso

logger = logging.getLogger(__name__)


class WhatsAppAdapter:
    platform = "whatsapp"

    def parseIncoming(self, event: Any) -> NormalizedMessage:
        value = (
            (event.get("entry") or [{}])[0]
            .get("changes", [{}])[0]
            .get("value", {})
        )
        message = (value.get("messages") or [{}])[0]
        contact = (value.get("contacts") or [{}])[0]
        text = (message.get("text") or {}).get("body") or ""

        return NormalizedMessage(
            platform="whatsapp",
            message_id=str(message.get("id") or ""),
            chat_id=str(message.get("from") or contact.get("wa_id") or ""),
            user_id=str(message.get("from") or contact.get("wa_id") or ""),
            text=text,
            raw_event=event,
            created_at=utc_now_iso(),
            message_type=str(message.get("type") or ("text" if text else "unknown")),
        )

    async def sendText(self, chat_id: str, text: str) -> None:
        logger.info("whatsapp sendText delegated to OpenClaw native channel: chat_id=%s", chat_id)

    async def sendFile(self, chat_id: str, file, caption: str | None = None) -> None:
        logger.info("whatsapp sendFile delegated to OpenClaw native channel: chat_id=%s file=%s", chat_id, file)
