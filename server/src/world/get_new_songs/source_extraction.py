"""Collect missing-field materials and merge business values; never call a model."""

import json
import re

import mwparserfromhell as mw
from bs4 import BeautifulSoup
from mwparserfromhell.nodes import Heading, Tag, Template

from src.utils.logger import get_logger

from .template_rules import descriptor, field_key, structure, template_name
from .text_conversion import convert_text, spaced_from
from .wiki_api import render_fragment
from .wikitext_parser import (
    NON_CONTENT_TAGS,
    heading_section,
    is_embed,
    mark_counts,
    original_lyrics_source,
    parse_extraction,
    parse_lyric_candidate,
    rendered_lyrics_text,
    sectioned_code,
    select_lyrics,
)

_MARKUP = re.compile(r"\[\[|'''|\{\{")
_COUNT_MARK = "\ufff0"
_SENTENCE = re.compile(r"[^。！？\n]+[。！？]?|\n")
_CLAUSE = re.compile(r"[，,；;]")

_NEEDED_BY_SECTION = {"简介": "summary", "歌词": "lyrics"}


def _kept_line(line, *, parameter_line):
    """Drop unexpandable counts from one line.

    The policy follows the line's structure, not its punctuation: a template parameter value
    keeps its other clauses, while a prose line drops the whole statistics sentence. A prose
    line without sentence punctuation therefore loses everything it carries, instead of
    surviving as a leftover clause such as "达成殿堂".
    """
    if parameter_line:
        kept = [clause.strip() for clause in _CLAUSE.split(line) if clause.strip() and _COUNT_MARK not in clause]
        return "，".join(kept)
    return "".join(part for part in _SENTENCE.findall(line) if _COUNT_MARK not in part).strip()


def _kept_lines(text, *, parameter_line):
    """Filter one block line by line; a line that only carried counts disappears."""
    kept = []
    for line in text.splitlines():
        if _COUNT_MARK not in line:
            kept.append(line)
            continue
        trimmed = _kept_line(line, parameter_line=parameter_line)
        if trimmed:
            kept.append(trimmed)
    return "\n".join(kept)


def material_text(source):
    """Return the model material: one glyph conversion minus unexpandable count statistics.

    A dynamic count cannot be expanded offline, so text carrying one could only ever be
    reproduced with a hole. Prose drops the whole statistics sentence; parameter values keep
    their other clauses and disappear only when nothing but counts was there — the same two
    policies ``wikitext_parser`` applies to the intro and to 其他资料, with the same rule: a
    template whose name ends with ``count``.
    """
    text = convert_text(source)
    code = mw.parse(text)
    if not mark_counts(code):
        return text[:24000]
    for template in list(code.filter_templates()):
        for param in list(template.params):
            value = str(param.value)
            if _COUNT_MARK not in value:
                continue
            kept = _kept_lines(value, parameter_line=True)
            if kept:
                param.value = kept
            else:
                template.remove(param.name)
    return _kept_lines(str(code), parameter_line=False)[:24000]


def _reject_nonfinite_json(value):
    raise ValueError(f"Extraction response contains a non-finite JSON number: {value}")


def decode_extraction_response(response: str | dict) -> dict:
    """Require finite JSON object values and bound raw text or serialized dict replies."""
    from_text = isinstance(response, str)
    if from_text:
        if len(response) > 24000:
            raise ValueError("Extraction response exceeds 24000 characters")
        response = json.loads(response, parse_constant=_reject_nonfinite_json)
    if not isinstance(response, dict):
        raise ValueError("Extraction response must be a JSON object")
    try:
        # Also catches numeric overflow after decoding, and invalid nested dict values.
        encoded = json.dumps(response, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Extraction response must contain finite JSON-compatible values") from exc
    if not from_text and len(encoded) > 24000:
        raise ValueError("Extraction response exceeds 24000 characters")
    return response


def merge_missing(data, result, needed):
    """Merge the model's answer as final text.

    The material handed to the model has already been through the one glyph conversion, so
    answers arrive converted as well and must not be converted a second time here — that
    would undo the glyphs the conversion left as-is for LC and nowiki. Leftover wiki markup
    means the model wrote markup rather than business text; it is reported, not silently
    rewritten.
    """
    _merge_infobox(data, result, needed)
    _merge_prose(data, result, needed)


def _merge_infobox(data, result, needed):
    box = result.get("infobox")
    if not isinstance(box, dict):
        return
    box = {field_key(k): v for k, v in box.items() if isinstance(k, str)}
    for key in needed["infobox"][:]:
        if isinstance(box.get(key), str) and box[key].strip():
            data["infobox"][key] = box[key]
            needed["infobox"].remove(key)


def _merge_prose(data, result, needed):
    for key in ("summary", "lyrics"):
        value = result.get(key)
        if not needed[key] or not _usable_answer(value, list_form=key == "summary"):
            continue
        _warn_suspicious_answer(
            [item for item in ([value] if isinstance(value, str) else list(value)) if isinstance(item, str)], key
        )
        data[key] = value
        needed[key] = False
        if key == "lyrics":
            data["spaced_lyrics"] = spaced_from(value)


def _usable_answer(value, *, list_form):
    if list_form:
        return isinstance(value, list) and all(isinstance(x, str) for x in value) and any(value)
    return isinstance(value, str) and bool(value.strip())


def _warn_suspicious_answer(items, key):
    """The material is normalized business text; markup or unconverted glyphs mean
    the model rewrote instead of copying."""
    logger = get_logger(__name__)
    if any(_MARKUP.search(item) for item in items):
        logger.warning(
            "Supplement answer for %s carries wiki markup although the material is "
            "normalized; the model rewrote instead of copying",
            key,
        )
    if any(convert_text(item) != item for item in items):
        logger.warning(
            "Supplement answer for %s still holds unconverted glyphs; the material is "
            "already zh-cn, so the model changed the text",
            key,
        )


def _needed_section(heading):
    """Which needed field a heading can fill: summary, lyrics, or none."""
    return _NEEDED_BY_SECTION.get(heading_section(heading), "")


def _inherited_section(rule, key, context):
    """Section a template parameter is searched under: documented slots keep their
    own or the surrounding section, everything else starts fresh."""
    kind = rule.get("kind")
    if kind == "songbox" and key in rule["body_params"]:
        return _needed_section(key)
    if (kind == "wrapper" and key in rule["body_params"]) or (
        kind == "tabs" and any(re.fullmatch(re.escape(p) + r"\d+", key) for p in rule["body_prefixes"])
    ):
        return context
    return ""


def _embed_candidates(code, context=""):
    """Yield (embed template, section) for every embed call, in source order."""
    for node in sectioned_code(code).nodes:
        if isinstance(node, Heading):
            context = _needed_section(node.title)
        elif isinstance(node, Tag):
            tag = str(node.tag).lower()
            if re.fullmatch(r"h[1-6]", tag):
                context = _needed_section(node.contents)
            elif tag not in NON_CONTENT_TAGS and node.contents:
                subcode = mw.parse(str(node.contents)) if tag == "section" else node.contents
                yield from _embed_candidates(subcode, context)
        elif isinstance(node, Template):
            if is_embed(node):
                yield node, context
            else:
                rule = descriptor(template_name(node.name))
                if rule.get("kind") not in {"inline", "staff"}:
                    for param in node.params:
                        key = structure(param.name).strip().casefold()
                        yield from _embed_candidates(param.value, _inherited_section(rule, key, context))


def _target_fragments(source, needed):
    """Embed calls whose rendered fragment could fill a needed field, in source order."""
    selected = []
    for node, context in _embed_candidates(mw.parse(source)):
        call = str(node)
        if (
            context
            and needed[context]
            and node.params
            and len(call) <= 8000
            and not any(call in parent for parent, _ in selected)
        ):
            selected.append((call, [context]))
    return selected[:2]


def _rendered_fragment(base_url, title, call, post, limit, *, lyrics=False):
    """Render a bounded fragment; truncated/error/multi-version lyrics remain unresolved."""
    if post is None:
        raise RuntimeError("Optional fragment POST transport is unavailable")
    html = render_fragment(base_url, title, call, post, 10)
    if lyrics and len(html) > 100000:
        raise ValueError("Rendered lyrics exceed the HTML limit")
    soup = BeautifulSoup(html[:100000], "html.parser")
    if lyrics:
        _check_lyric_fragment(soup)
    for node in soup.select("script, style, nav, .navbox, .reference, .mw-editsection"):
        node.decompose()
    if lyrics:
        text = rendered_lyrics_text(str(soup))
        if len(text) > limit:
            raise ValueError("Rendered lyrics exceed the text limit")
        return text
    for br in soup.find_all("br"):
        br.replace_with("\n")
    return soup.get_text("\n", strip=True)[:limit]


def _check_lyric_fragment(soup):
    if soup.select(".error, .mw-error, .errorbox, a.new"):
        raise ValueError("Rendered lyric fragment is unresolved")
    versions = (".poem, poem", ".TabContentText, .tabbertab", ".Lyrics")
    if any(len(soup.select(selector)) > 1 for selector in versions):
        raise ValueError("Rendered fragment contains multiple lyric versions")
    if soup.select("table, .Lyrics-translated"):
        raise ValueError("Rendered lyric columns cannot be assigned to a single original version")


def _non_lyric_material(value, context=""):
    """Keep prose/credit source without exposing other versions through page materials."""
    code = sectioned_code(value)
    level = 0
    kept = []
    for node in code.nodes:
        heading = node if isinstance(node, Heading) else None
        if isinstance(node, Tag) and re.fullmatch(r"h[1-6]", str(node.tag).lower()):
            heading = Heading(node.contents, int(str(node.tag)[1]))
        if heading is not None:
            if heading.level <= level or _needed_section(heading.title):
                context = _needed_section(heading.title)
                level = heading.level
        if context == "lyrics":
            kept.extend(_credit_material(node))
        else:
            kept.append(_non_lyric_node(node, context))
    return "".join(kept)


def _credit_material(node):
    if isinstance(node, Template) and descriptor(template_name(node.name)).get("kind") in {"songbox", "staff"}:
        yield _non_lyric_node(node, "")
    elif isinstance(node, Template):
        for param in node.params:
            for child in sectioned_code(param.value).nodes:
                yield from _credit_material(child)
    elif isinstance(node, Tag) and str(node.tag).lower() not in NON_CONTENT_TAGS:
        for child in sectioned_code(node.contents or "").nodes:
            yield from _credit_material(child)


def _non_lyric_node(node, context):
    if isinstance(node, Tag) and node.contents:
        if str(node.tag).lower() == "poem" or (node.has("class") and "poem" in str(node.get("class").value).split()):
            return ""
        if str(node.tag).lower() in NON_CONTENT_TAGS - {"nowiki"}:
            return ""
        if str(node.tag).lower() != "nowiki":
            node.contents = _non_lyric_material(node.contents, context)
    elif isinstance(node, Template):
        rule = descriptor(template_name(node.name))
        if rule.get("kind") == "lyrics":
            return ""
        for param in node.params:
            key = structure(param.name).strip().casefold()
            inherited = _inherited_section(rule, key, context)
            if key in {"歌词", "original"}:
                param.value = "".join(
                    part for child in sectioned_code(param.value).nodes for part in _credit_material(child)
                )
            else:
                param.value = _non_lyric_material(param.value, inherited)
    return str(node)


def _render_candidate(candidate, base_url, title, post):
    code = mw.parse(original_lyrics_source(candidate.source))
    replacements = {}
    remaining = 12000
    for index, node in enumerate(list(code.filter_templates())):
        if remaining <= 0:
            break
        if not is_embed(node) or str(node) not in candidate.gaps or len(str(node)) > 8000:
            continue
        call = str(node)
        try:
            text = _rendered_fragment(base_url, title, call, post, remaining, lyrics=True)
            if not text.strip():
                continue
            token = "\ue100" + str(index) + "\ue101"
            while token in candidate.source or token in text:
                token += "\ue101"
            code.replace(node, token, recursive=True)
            replacements[token] = text
            candidate.rendered.append({"source": call, "text": text})
            remaining -= len(text)
        except Exception as exc:
            get_logger(__name__).warning(f"Optional VCPedia lyric fragment failed: {exc}")
    if replacements:
        rendered = parse_lyric_candidate(str(code))
        for token, text in replacements.items():
            rendered.text = rendered.text.replace(token, text)
        candidate.text = rendered.text
        candidate.spaced_lyrics = spaced_from(rendered.text)
        candidate.gaps = rendered.gaps


def _select_candidate(data, needed, candidates, base_url, title, post, merge_fragments):
    selected = select_lyrics(candidates)
    if selected is not None and selected.complete:
        return selected
    if merge_fragments:
        for candidate in candidates:
            _render_candidate(candidate, base_url, title, post)
        selected = select_lyrics(candidates)
    if selected is not None:
        data["lyrics"], data["spaced_lyrics"] = selected.text, selected.spaced_lyrics
        needed["lyrics"] = not selected.complete
    return selected


def _merge_prose_fragments(data, needed, source, base_url, title, post):
    remaining = 12000
    for call, targets in _target_fragments(source, {**needed, "lyrics": False}):
        try:
            text = _rendered_fragment(base_url, title, call, post, remaining)
            if text:
                remaining -= len(text)
                merge_missing(data, {key: [text] for key in targets}, needed)
        except Exception as exc:
            get_logger(__name__).warning(f"Optional VCPedia fragment failed: {exc}")
        if remaining <= 0:
            break


def collect_materials(data, needed, source, base_url, title, *, post=None, merge_fragments=True, candidates=None):
    """Finish all deterministic lyric candidates before preparing one candidate for the model.

    Candidate state stays outside business data. Other fields receive lyric-free source;
    only the selected version contributes lyric source, rule result, rendered text and gaps.
    """
    if not any(needed.values()):
        return {}
    selected = None
    rule_results = {}
    if needed["lyrics"]:
        if candidates is None:
            _, _, candidates = parse_extraction(source, title)
        rule_results = {id(candidate): candidate.text for candidate in candidates}
        selected = _select_candidate(data, needed, candidates, base_url, title, post, merge_fragments)
    prose = _non_lyric_material(source)
    if merge_fragments:
        _merge_prose_fragments(data, needed, prose, base_url, title, post)
    materials = {"text": material_text(prose)}
    if needed["lyrics"] and selected is not None and (selected.text.strip() or selected.gaps):
        materials["lyrics"] = {
            "source": material_text(original_lyrics_source(selected.source)),
            "rule_result": rule_results[id(selected)],
            "rendered": [{"source": material_text(item["source"]), "text": item["text"]} for item in selected.rendered],
            "gaps": [material_text(gap) for gap in sorted(selected.gaps)],
        }
    return materials
