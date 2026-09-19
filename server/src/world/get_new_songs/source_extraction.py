"""Collect missing-field materials and merge business values; never call a model."""
import re
import mwparserfromhell as mw
from mwparserfromhell.nodes import Heading, Tag, Template, Text
from bs4 import BeautifulSoup

from src.utils.logger import get_logger

from .template_rules import descriptor, field_key, structure, template_name
from .wikitext_parser import is_embed
from .wiki_api import render_fragment
from .text_conversion import convert_text, converted_lyrics, spaced_from


def merge_missing(data, result, needed, *, rendered=False):
    box = result.get("infobox")
    if isinstance(box, dict):
        box = {field_key(k): v for k, v in box.items() if isinstance(k, str)}
        for key in needed["infobox"][:]:
            if isinstance(box.get(key), str) and box[key].strip():
                data["infobox"][key] = box[key] if rendered else convert_text(box[key])
                needed["infobox"].remove(key)
    for key in ("summary", "lyrics"):
        value = result.get(key)
        valid = (isinstance(value, list) and all(isinstance(x, str) for x in value)
                 and any(value)) if key == "summary" else isinstance(value, str) and bool(value.strip())
        if needed[key] and valid:
            data[key] = value
            needed[key] = False
            if key == "lyrics":
                if rendered:
                    data["spaced_lyrics"] = spaced_from(value)
                else:
                    data["lyrics"], data["spaced_lyrics"] = converted_lyrics(value)
            elif not rendered:
                data["summary"] = [convert_text(item) for item in value]


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
    """Render the needed fragments, merge them locally, and hand the model raw source only.

    A rendered fragment is a finished site value, so the program merges it itself
    (``rendered=True``) and never forwards it as model material: the model's job is
    reading source, not re-cleaning rendered text.
    """
    if not any(needed.values()):
        return {}
    materials = {"raw": source[:24000]}
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
                merge_missing(data, {key: [text] if key == "summary" else text for key in targets}, needed, rendered=True)
        except Exception as exc:
            get_logger(__name__).warning(f"Optional VCPedia fragment failed: {exc}")
        if remaining <= 0:
            break
    return materials
