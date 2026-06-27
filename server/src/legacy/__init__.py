"""Compatibility adapters for the pre-runtime chat pipeline."""

from src.legacy.chat_input_adapter import stimulus_to_chat_input_event, ws_message_to_stimulus

__all__ = ["stimulus_to_chat_input_event", "ws_message_to_stimulus"]
