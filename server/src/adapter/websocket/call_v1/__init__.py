"""Stable call adapter facade; protocol sessions and codecs remain internal."""

from ._transport import CallTransportError, parse_call_transport_enabled
from .adapter import CallCapabilityStatus, CallWebSocketAdapter

__all__ = ["CallCapabilityStatus", "CallWebSocketAdapter", "CallTransportError", "parse_call_transport_enabled"]
