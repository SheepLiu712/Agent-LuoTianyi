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

    has_text = False
    normalized_blocks: list[dict[str, Any]] = []
    for candidate in blocks:
        if not isinstance(candidate, Mapping) or set(candidate) - _BLOCK_KEYS:
            return None

        font_size = candidate.get("font_size", DEFAULT_BLOCK_FONT_SIZE)
        if type(font_size) is not int or not MIN_BLOCK_FONT_SIZE <= font_size <= MAX_BLOCK_FONT_SIZE:
            return None

        align = candidate.get("align", ALIGN_JUSTIFY)
        if align not in {ALIGN_CENTER, ALIGN_JUSTIFY}:
            return None

        runs = candidate.get("runs")
        if not isinstance(runs, list) or not runs:
            return None

        normalized_runs: list[dict[str, Any]] = []
        for run_candidate in runs:
            if not isinstance(run_candidate, Mapping) or set(run_candidate) - _RUN_KEYS:
                return None
            text = run_candidate.get("text")
            bold = run_candidate.get("bold", False)
            if not isinstance(text, str) or not isinstance(bold, bool):
                return None
            has_text = has_text or bool(text.strip())
            normalized_runs.append({"text": text, "bold": bold})

        normalized_blocks.append({"font_size": font_size, "align": align, "runs": normalized_runs})

    if not has_text:
        return None

    return {
        "version": version,
        "title": title,
        "format": AGREEMENT_FORMAT,
        "blocks": normalized_blocks,
    }
