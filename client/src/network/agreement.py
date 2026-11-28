from __future__ import annotations

from typing import Any, Mapping

AGREEMENT_FORMAT = "agreement.richtext.v1"
DEFAULT_BLOCK_FONT_SIZE = 16
MIN_BLOCK_FONT_SIZE = 12
MAX_BLOCK_FONT_SIZE = 32
ALIGN_CENTER = "center"
ALIGN_JUSTIFY = "justify"

_TOP_LEVEL_KEYS = frozenset({"version", "title", "format", "blocks"})
_BLOCK_KEYS = frozenset({"font_size", "align", "runs"})
_RUN_KEYS = frozenset({"text", "bold"})


def _normalize_run(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) - _RUN_KEYS:
        return None
    text = value.get("text")
    bold = value.get("bold", False)
    if not isinstance(text, str) or not isinstance(bold, bool):
        return None
    return {"text": text, "bold": bold}


def _normalize_block(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) - _BLOCK_KEYS:
        return None

    font_size = value.get("font_size", DEFAULT_BLOCK_FONT_SIZE)
    if type(font_size) is not int or not MIN_BLOCK_FONT_SIZE <= font_size <= MAX_BLOCK_FONT_SIZE:
        return None

    align = value.get("align", ALIGN_JUSTIFY)
    if align not in {ALIGN_CENTER, ALIGN_JUSTIFY}:
        return None

    runs = value.get("runs")
    if not isinstance(runs, list) or not runs:
        return None
    normalized_runs = [_normalize_run(run) for run in runs]
    if any(run is None for run in normalized_runs):
        return None

    return {"font_size": font_size, "align": align, "runs": normalized_runs}


def validate_agreement_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) - _TOP_LEVEL_KEYS:
        return None

    version = value.get("version")
    title = value.get("title")
    format_name = value.get("format")
    blocks = value.get("blocks")
    if not isinstance(version, str) or not version:
        return None
    if not isinstance(title, str) or not title.strip():
        return None
    if format_name != AGREEMENT_FORMAT:
        return None
    if not isinstance(blocks, list) or not blocks:
        return None

    normalized_blocks = [_normalize_block(block) for block in blocks]
    if any(block is None for block in normalized_blocks):
        return None
    if not any(
        run["text"].strip()
        for block in normalized_blocks
        if block is not None
        for run in block["runs"]
    ):
        return None

    return {
        "version": version,
        "title": title,
        "format": AGREEMENT_FORMAT,
        "blocks": normalized_blocks,
    }
