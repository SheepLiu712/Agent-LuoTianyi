"""Collect missing-field materials and merge business values; never call a model."""
import re

import mwparserfromhell as mw
from bs4 import BeautifulSoup
from mwparserfromhell.nodes import Heading, Tag, Template

from src.utils.logger import get_logger

from .template_rules import descriptor, field_key, structure, template_name
from .text_conversion import convert_text, spaced_from
from .wiki_api import render_fragment
from .wikitext_parser import NON_CONTENT_TAGS, heading_section, is_embed, sectioned_code

_MARKUP = re.compile(r"\[\[|'''|\{\{")
_COUNT_MARK = "\ufff0"
_SENTENCE = re.compile(r"[^。！？\n]+[。！？]?|\n")
_CLAUSE = re.compile(r"[，,；;]")

_NEEDED_BY_SECTION = {"简介": "summary", "歌词": "lyrics"}


def _mark_counts(code):
    """Replace every ``count`` template in place; report whether anything was replaced."""
    marked = False
    for template in list(code.filter_templates()):
        if template_name(template.name).endswith("count"):
            code.replace(template, _COUNT_MARK, recursive=True)
            marked = True
    return marked


def _kept_line(line, *, parameter_line):
    """Drop unexpandable counts from one line.

    The policy follows the line's structure, not its punctuation: a template parameter value
    keeps its other clauses, while a prose line drops the whole statistics sentence. A prose
    line without sentence punctuation therefore loses everything it carries, instead of
    surviving as a leftover clause such as "达成殿堂".
    """
    if parameter_line:
        kept = [clause.strip() for clause in _CLAUSE.split(line)
                if clause.strip() and _COUNT_MARK not in clause]
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
    if not _mark_counts(code):
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
        _warn_suspicious_answer([item for item in ([value] if isinstance(value, str) else list(value))
                                 if isinstance(item, str)], key)
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
        logger.warning("Supplement answer for %s carries wiki markup although the material is "
                       "normalized; the model rewrote instead of copying", key)
    if any(convert_text(item) != item for item in items):
        logger.warning("Supplement answer for %s still holds unconverted glyphs; the material is "
                       "already zh-cn, so the model changed the text", key)


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
            kind == "tabs" and any(re.fullmatch(re.escape(p) + r"\d+", key) for p in rule["body_prefixes"])):
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
        if (context and needed[context] and node.params and len(call) <= 8000
                and not any(call in parent for parent, _ in selected)):
            selected.append((call, [context]))
    return selected[:2]


def _rendered_fragment(base_url, title, call, post, limit):
    """Render one embed call through the site and return its cleaned text.

    Script/style/nav chrome goes, br becomes a newline, and the result is cut to
    the remaining budget.
    """
    if post is None:
        raise RuntimeError("Optional fragment POST transport is unavailable")
    html = render_fragment(base_url, title, call, post, 10)
    soup = BeautifulSoup(html[:100000], "html.parser")
    for node in soup.select("script, style, nav, .navbox, .reference, .mw-editsection"):
        node.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    return soup.get_text("\n", strip=True)[:limit]


def collect_materials(data, needed, source, base_url, title, get, *, post=None):
    """Render the needed fragments, merge them locally, and hand the model the material.

    A rendered fragment is a finished site value, so the program merges it itself and never
    forwards it as model material. The material the model receives is ``material_text``: the
    source after the one glyph conversion, without the statistics the program cannot expand.
    Protected LC/nowiki glyphs are already final there, so answers need no second conversion
    (see ``merge_missing``).
    """
    if not any(needed.values()):
        return {}
    materials = {"text": material_text(source)}
    remaining = 12000
    for call, targets in _target_fragments(source, needed):
        try:
            text = _rendered_fragment(base_url, title, call, post, remaining)
            if text:
                remaining -= len(text)
                merge_missing(data, {key: [text] if key == "summary" else text for key in targets}, needed)
        except Exception as exc:
            get_logger(__name__).warning(f"Optional VCPedia fragment failed: {exc}")
        if remaining <= 0:
            break
    return materials
