"""Collect missing-field materials and merge business values; never call a model."""
import re
import mwparserfromhell as mw
from mwparserfromhell.nodes import Heading, Tag, Template, Text
from bs4 import BeautifulSoup

from src.utils.logger import get_logger

from .template_rules import descriptor, field_key, structure, template_name
from .wikitext_parser import is_embed
from .wiki_api import render_fragment
from .text_conversion import convert_text, spaced_from


_MARKUP = re.compile(r"\[\[|'''|\{\{")
_COUNT_MARK = "\ufff0"
_SENTENCE = re.compile(r"[^。！？\n]+[。！？]?|\n")
_CLAUSE = re.compile(r"[，,；;]")


def _mark_counts(code):
    """Replace every ``count`` template in place; report whether anything was replaced."""
    marked = False
    for template in list(code.filter_templates()):
        if template_name(template.name).endswith("count"):
            code.replace(template, _COUNT_MARK, recursive=True)
            marked = True
    return marked


def _kept_line(line):
    """Keep the prose sentences — or, without sentence punctuation, the clauses — free of counts."""
    if re.search(r"[。！？]", line):
        return "".join(part for part in _SENTENCE.findall(line) if _COUNT_MARK not in part).strip()
    kept = [clause.strip() for clause in _CLAUSE.split(line)
            if clause.strip() and _COUNT_MARK not in clause]
    return "，".join(kept)


def _kept_lines(text):
    """Filter one block line by line; a line that only carried counts disappears."""
    kept = []
    for line in text.splitlines():
        if _COUNT_MARK not in line:
            kept.append(line)
            continue
        trimmed = _kept_line(line)
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
            kept = _kept_lines(value)
            if kept:
                param.value = kept
            else:
                template.remove(param.name)
    return _kept_lines(str(code))[:24000]


def merge_missing(data, result, needed):
    """Merge the model's answer as final text.

    The material handed to the model has already been through the one glyph conversion, so
    answers arrive converted as well and must not be converted a second time here — that
    would undo the glyphs the conversion left as-is for LC and nowiki. Leftover wiki markup
    means the model wrote markup rather than business text; it is reported, not silently
    rewritten.
    """
    box = result.get("infobox")
    if isinstance(box, dict):
        box = {field_key(k): v for k, v in box.items() if isinstance(k, str)}
        for key in needed["infobox"][:]:
            if isinstance(box.get(key), str) and box[key].strip():
                data["infobox"][key] = box[key]
                needed["infobox"].remove(key)
    for key in ("summary", "lyrics"):
        value = result.get(key)
        valid = (isinstance(value, list) and all(isinstance(x, str) for x in value)
                 and any(value)) if key == "summary" else isinstance(value, str) and bool(value.strip())
        if needed[key] and valid:
            items = [value] if isinstance(value, str) else list(value)
            if any(_MARKUP.search(item) for item in items if isinstance(item, str)):
                get_logger(__name__).warning(
                    "Supplement answer for %s carries wiki markup although the material is "
                    "normalized; the model rewrote instead of copying", key)
            if any(convert_text(item) != item for item in items if isinstance(item, str)):
                get_logger(__name__).warning(
                    "Supplement answer for %s still holds unconverted glyphs; the material is "
                    "already zh-cn, so the model changed the text", key)
            data[key] = value
            needed[key] = False
            if key == "lyrics":
                data["spaced_lyrics"] = spaced_from(value)


def _target_fragments(source, needed):
    selected = []
    def target(title):
        title = structure(title)
        return "summary" if "简介" in title or "VOCALOID原创作者" in title else "lyrics" if "歌词" in title else ""

    def walk(code, context=""):
        if any(isinstance(n, Text) and re.search(r"(?m)^=", str(n)) for n in code.nodes):
            code = mw.parse(str(code))
        for node in code.nodes:
            if isinstance(node, Heading):
                context = target(node.title)
            elif isinstance(node, Tag):
                tag = str(node.tag).lower()
                if re.fullmatch(r"h[1-6]", tag):
                    context = target(node.contents)
                elif tag not in {"nowiki", "ref", "references", "script", "style", "includeonly"} and node.contents:
                    walk(mw.parse(str(node.contents)) if tag == "section" else node.contents, context)
            elif isinstance(node, Template):
                call = str(node)
                if is_embed(node):
                    if (context and needed[context] and node.params and len(call) <= 8000
                            and not any(call in parent for parent, _ in selected)):
                        selected.append((call, [context]))
                    continue
                rule = descriptor(template_name(node.name))
                kind = rule.get("kind")
                if kind in {"inline", "staff"}:
                    continue
                for param in node.params:
                    key = structure(param.name).strip().casefold()
                    inherited = ""
                    if kind == "songbox" and key in rule["body_params"]:
                        inherited = target(key)
                    elif kind == "wrapper" and key in rule["body_params"]:
                        inherited = context
                    elif kind == "tabs" and any(re.fullmatch(re.escape(p) + r"\d+", key) for p in rule["body_prefixes"]):
                        inherited = context
                    walk(param.value, inherited)
    walk(mw.parse(source))
    return selected[:2]


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
            if post is None:
                raise RuntimeError("Optional fragment POST transport is unavailable")
            html = render_fragment(base_url, title, call, post, 10)
            soup = BeautifulSoup(html[:100000], "html.parser")
            for node in soup.select("script, style, nav, .navbox, .reference, .mw-editsection"):
                node.decompose()
            for br in soup.find_all("br"):
                br.replace_with("\n")
            text = soup.get_text("\n", strip=True)[:remaining]
            if text:
                remaining -= len(text)
                merge_missing(data, {key: [text] if key == "summary" else text for key in targets}, needed)
        except Exception as exc:
            get_logger(__name__).warning(f"Optional VCPedia fragment failed: {exc}")
        if remaining <= 0:
            break
    return materials
