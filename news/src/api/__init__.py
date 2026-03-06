"""SSE API service for real-time Telegram news streaming."""

from .app import create_app
from .broadcast import BroadcastHub

__all__ = ["create_app", "BroadcastHub"]
