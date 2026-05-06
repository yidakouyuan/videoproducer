"""
Feishu/Lark bot adapter.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

from app.adapters.base import NormalizedMessage, utc_now_iso

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_SEND_MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"


class FeishuAdapter:
    platform = "feishu"

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
        verification_token: str | None = None,
    ) -> None:
        self.app_id = app_id if app_id is not None else os.environ.get("FEISHU_APP_ID", "")
        self.app_secret = app_secret if app_secret is not None else os.environ.get("FEISHU_APP_SECRET", "")
        self.verification_token = (
            verification_token
            if verification_token is not None
            else os.environ.get("FEISHU_VERIFICATION_TOKEN", "")
        )
        self._tenant_access_token: str | None = None
        self._token_expire_at = 0.0

    def verify_token(self, event: dict[str, Any]) -> bool:
        expected = self.verification_token.strip()
        if not expected:
            return True
        actual = str(event.get("token") or event.get("header", {}).get("token") or "")
        return actual == expected

    def parseIncoming(self, event: Any) -> NormalizedMessage:
        payload = event.get("event") or {}
        message = payload.get("message") or {}
        sender = payload.get("sender") or {}
        sender_id = sender.get("sender_id") or {}
        header = event.get("header") or {}

        message_type = str(message.get("message_type") or "unknown")
        text = ""
        if message_type == "text":
            text = self._parse_text_content(message.get("content"))

        return NormalizedMessage(
            platform="feishu",
            message_id=str(message.get("message_id") or header.get("event_id") or ""),
            chat_id=str(message.get("chat_id") or ""),
            user_id=str(
                sender_id.get("user_id")
                or sender_id.get("open_id")
                or sender_id.get("union_id")
                or ""
            ),
            text=text,
            raw_event=event,
            created_at=self._parse_created_at(header.get("create_time")),
            message_type=message_type,
        )

    async def sendText(self, chat_id: str, text: str) -> None:
        if not self.app_id or not self.app_secret:
            logger.warning("skip feishu sendText because FEISHU_APP_ID/FEISHU_APP_SECRET is not configured")
            return

        token = await self._get_tenant_access_token()
        payload = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                _SEND_MESSAGE_URL,
                params={"receive_id_type": "chat_id"},
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") != 0:
                raise RuntimeError(f"Feishu send message failed: {data}")
        logger.info("reply feishu success: chat_id=%s", chat_id)

    async def sendFile(self, chat_id: str, file: str | Path, caption: str | None = None) -> None:
        message = caption or "视频已生成"
        message = f"{message}\n{file}"
        await self.sendText(chat_id, message)

    async def sendCard(self, chat_id: str, card: dict[str, Any]) -> None:
        """
        Placeholder for Feishu interactive cards.

        The current entry layer keeps a text fallback so status commands remain
        usable before card rendering is wired to Feishu's card API.
        """
        text = str(card.get("text") or card.get("summary") or card)
        await self.sendText(chat_id, text)

    async def _get_tenant_access_token(self) -> str:
        now = time.time()
        if self._tenant_access_token and now < self._token_expire_at - 60:
            return self._tenant_access_token

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                _TOKEN_URL,
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") != 0 or not data.get("tenant_access_token"):
                raise RuntimeError(f"Feishu tenant token failed: {data}")

        self._tenant_access_token = data["tenant_access_token"]
        self._token_expire_at = now + int(data.get("expire", 7200))
        return self._tenant_access_token

    @staticmethod
    def _parse_text_content(content: Any) -> str:
        if isinstance(content, dict):
            return str(content.get("text") or "").strip()
        if not content:
            return ""
        try:
            parsed = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            return str(content).strip()
        if isinstance(parsed, dict):
            return str(parsed.get("text") or "").strip()
        return str(parsed).strip()

    @staticmethod
    def _parse_created_at(create_time: Any) -> str:
        if create_time is None:
            return utc_now_iso()
        try:
            ts = int(create_time)
            if ts > 10_000_000_000:
                ts = ts // 1000
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
        except (TypeError, ValueError):
            return utc_now_iso()
