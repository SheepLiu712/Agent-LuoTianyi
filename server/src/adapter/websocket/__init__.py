"""Shared WebSocket adapter network contracts; implementations live in chat and call_v1."""

from .connection import AdapterConnection, AdapterConnectionError, OutboundDelivery

__all__ = ["AdapterConnection", "AdapterConnectionError", "OutboundDelivery"]
