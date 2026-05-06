"""
Message adapters normalize IM platform events before they enter OpenClaw.
"""
from app.adapters.base import MessageAdapter, NormalizedMessage, ReplyPayload

__all__ = ["MessageAdapter", "NormalizedMessage", "ReplyPayload"]
