"""Internal source-node parsing; no HTML fetching or remote template expansion."""
import re
from copy import deepcopy
from typing import Dict, List

import mwparserfromhell as mw
from mwparserfromhell.nodes import Comment, ExternalLink, Heading, Tag, Template, Text, Wikilink

from .text_conversion import TextConversion, spaced_from

from .template_rules import (
    descriptor,
    field_key,
    is_excluded_field,
    is_presentation_key,
    role_priority,
    structure,
    template_name,
)


def _name(template):
    return template_name(template.name)


def _value(template, key, default=""):
    for param in reversed(template.params):
        if structure(param.name).strip() == key:
            return param.value
    return default


def _code(value):
    if isinstance(value, mw.wikicode.Wikicode):
        return value
    if isinstance(value, mw.nodes.Node):
        return mw.wikicode.Wikicode([value])
    return mw.parse(value)


def _text(code, lyrics=False, gaps=None):
    def text(value, lyrics=lyrics):
        return _text(value, lyrics, gaps)

    parts = []
    for node in _code(code).nodes:
        if isinstance(node, Text):
            # MediaWiki resets apostrophe styles at line boundaries. Its source
            # parser can leave closing runs as Text in cross-line template values.
            parts.append(re.sub(r"'{2,5}", "", str(node)))
        elif isinstance(node, Wikilink):
            title = str(node.title).strip()
            # File embeds/category declarations are not visible text links;
            # a leading colon explicitly turns either into an ordinary link.
            if title.casefold().startswith(("file:", "image:", "文件:", "图像:", "category:", "分类:")):
                continue
            parts.append(text(node.text if node.text is not None else title.removeprefix(":"), lyrics))
        elif isinstance(node, ExternalLink):
            parts.append(text(node.title or "", lyrics))
        elif isinstance(node, Tag):
            tag = str(node.tag).strip().lower()
            if tag in {"ref", "references", "gallery", "noinclude", "style", "script"}:
                continue
            if tag == "rp" or "template-ruby-hidden" in _classes(node):
                continue
            if tag == "ruby":
                children = list(node.contents.filter_tags(recursive=False))
                bases = [t for t in children if str(t.tag).lower() == "rb"]
                base_gaps = set() if gaps is not None else None
                if bases:
                    base = "".join(_text(t.contents, lyrics, base_gaps) for t in bases)
                else:
                    # HTML allows implicit ruby bases: keep their normal inline
                    # markup, removing annotations before testing for empty text.
                    surface = deepcopy(node.contents)
                    for annotation in list(surface.filter_tags()):
                        if str(annotation.tag).lower() in {"rt", "rp"}:
                            surface.remove(annotation, recursive=True)
                    base = _text(surface, lyrics, base_gaps)
                if base.strip():
                    if gaps is not None:
                        gaps.update(base_gaps)
                    parts.append(base)
                else:
                    parts.append("".join(text(t.contents, lyrics) for t in children if str(t.tag).lower() == "rt"))
            elif tag == "br":
                parts.append("\n")
            else:
                parts.append(text(node.contents or "", lyrics))
                if tag in {"p", "div", "poem", "li"} or (lyrics and tag == "span"):
                    parts.append("\n")
        elif isinstance(node, Template):
            name = _name(node)
            rule = descriptor(name)
            kind = rule.get("kind")
            if kind == "inline":
                if any(str(_value(node, key)).strip().casefold() in
                       {value.strip().casefold() for value in values}
                       for key, values in rule.get("skip_if", {}).items()):
                    continue
                parts.append(text(_preferred_value(node, rule["text_params"]), lyrics))
            elif kind == "ruby":
                # Only the selected surface/fallback contributes missing content.
                base_gaps = set() if gaps is not None else None
                base = _text(_value(node, "1"), lyrics, base_gaps)
                if base.strip():
                    if gaps is not None:
                        gaps.update(base_gaps)
                    parts.append(base)
                else:
                    parts.append(text(_value(node, "2"), lyrics))
            elif kind == "utawari":
                values = [text(p.value, lyrics).strip() for p in node.params if str(p.name).strip().isdigit()]
                parts.append("\n".join(re.sub(r"##|#\d+", lambda m: "#" if m[0] == "##" else "", v) for v in values))
            elif kind == "tabs" or (kind == "wrapper" and gaps is not None and not lyrics):
                parts.append("\n".join(text(value, lyrics) for _, _, value in _contents(node)))
            elif kind == "break":
                parts.append("\n")
            elif kind in {"songbox", "staff"} or name.endswith("count"):
                continue
            elif kind == "lyrics":
                parts.append(_lyric_pair(mw.wikicode.Wikicode([node]), gaps)[0])
            elif kind == "multiline":
                values = [p.value for p in node.params if str(p.name).strip().isdigit()]
                parts.append("\n".join(text(v, lyrics).strip() for v in values))
            elif gaps is not None and _unread_content(node):
                gaps.add(str(node))
        elif not isinstance(node, (Comment, Heading)):
            parts.append(str(_code(node).strip_code() or ""))
    return "".join(parts)


def _unread_content(template):
    # A name or administrative identifier alone is not missing prose evidence.
    return any(str(p.value).strip() for p in template.params
               if structure(p.name).strip().casefold() in
               {"original", "歌词", "简介", "body", "text", "content", "内容"}
               or str(p.name).strip().isdigit())


def _clean(code):
    return " ".join(_text(code).split())


def parse_song_titles(source: str) -> List[str]:
    return [display for display, _ in parse_song_candidates(source)]


def parse_song_candidates(source: str):
    titles = []
    seen = set()

    # Keep HEAD's display-text filters and their order, not title namespaces.
    bad_exact = {
        "原创曲", "非原创曲", "传说曲", "殿堂曲", "部分", "25万以上", "25万以下",
        "模板文档", "查看", "编辑", "历史", "刷新", "简体", "繁體", "大陆简体",
        "香港繁體", "臺灣正體", "不转换", "跳转到导航", "跳转到搜索", "洛天依",
        "bilibili", "ACE Studio", "X studio", "VOCALOID中文殿堂曲", "ACE殿堂曲", "文档", "嵌入",
    }
    bad_contains = ("Template:", "模板:", "分类:", "Category:", "帮助", "首页",
                    "随机页面", "最近更改", "殿堂曲", "传说曲")

    def add(raw, target):
        title = _joined_text(raw)
        href = str(target).strip()
        if (not title or title in bad_exact or title.isdigit()
                or any(word in title for word in bad_contains)
                or not href or href.startswith("#") or "action=" in href
                or any(word in href for word in ("Template:", "Category:", "分类:"))):
            return
        title = title.rstrip("*").strip()
        if title and title not in seen:
            seen.add(title)
            target = title if href.startswith(("https://", "http://")) else href.split("#", 1)[0].replace("_", " ").strip()
            titles.append((title, target))

    def walk(code):
        for node in code.nodes:
            if isinstance(node, Wikilink):
                target = str(node.title).strip()
                if not target.casefold().startswith(("file:", "image:", "文件:", "category:", "分类:")):
                    display = node.text if node.text is not None else node.title
                    if node.text is None and ("_" in target or target.startswith(":")):
                        display = target.replace("_", " ")
                    add(display, target)
            elif isinstance(node, ExternalLink):
                add(node.title or "", node.url)
            elif isinstance(node, Template):
                if _name(node) == "lj":
                    add(_value(node, "2", _value(node, "1")), _value(node, "1"))
                else:
                    for _, _, value in _contents(node):
                        walk(value)
            elif isinstance(node, Tag) and str(node.tag).lower() not in {"includeonly", "ref"}:
                if node.contents:
                    walk(node.contents)
    walk(mw.parse(source))
    return titles


def _heading_level(node):
    if isinstance(node, Heading):
        return node.level
    if isinstance(node, Tag) and re.fullmatch(r"h[1-6]", str(node.tag).lower()):
        return int(str(node.tag)[1])
    return None


def _joined_text(code, gaps=None):
    """Rendered get_text(strip=True), only for display names and intros."""
    parts = []
    for node in _code(code).nodes:
        if isinstance(node, Tag):
            if str(node.tag).lower() not in {"br", "ref", "references", "includeonly"}:
                parts.append(_joined_text(node.contents, gaps))
        elif isinstance(node, Wikilink):
            target = str(node.title).strip()
            if not target.casefold().startswith(("file:", "image:", "文件:", "图像:", "category:", "分类:")):
                parts.append(_joined_text(node.text if node.text is not None else target.removeprefix(":"), gaps))
        elif isinstance(node, ExternalLink):
            parts.append(_joined_text(node.title or "", gaps))
        else:
            parts.append(_text(node, gaps=gaps).strip())
    return "".join(parts)


def _mark_counts(code):
    code = deepcopy(_code(code))
    for template in list(code.ifilter_templates()):
        if _name(template).endswith("count"):
            code.replace(template, "\ufff0", recursive=True)
    return code


def _information_text(code):
    # Preserve adjacent posting/reissue clauses, unlike the intro's whole
    # statistical sentence policy. Never expand templates globally.
    text = _text(_mark_counts(code))
    lines = []
    for line in text.splitlines():
        clauses = re.split(r"[，,；;]", line)
        kept = [clause.strip() for clause in clauses if "\ufff0" not in clause and clause.strip()]
        if kept:
            lines.append("，".join(kept))
    return ",".join(lines)


def _intro_text(code, gaps=None):
    code = _mark_counts(code)
    parts, inline = [], []
    last_was_a = False

    def add(name, text):
        nonlocal last_was_a
        if not text:
            return
        text = "".join(sentence for sentence in re.findall(r"[^。！？\n]+[。！？]?|\n", text)
                       if "\ufff0" not in sentence).strip()
        if parts and (last_was_a or name == "a"):
            parts[-1] += text
        else:
            parts.append(text)
        last_was_a = name == "a"

    def flush():
        if inline:
            add("p", _joined_text(mw.wikicode.Wikicode(inline), gaps))
            inline.clear()

    for node in _code(code).nodes:
        if _heading_level(node):
            flush()
            continue
        tag = str(node.tag).lower() if isinstance(node, Tag) else None
        if tag in {"p", "a", "ul", "ol"}:
            flush()
            if tag in {"ul", "ol"}:
                for li in node.contents.filter_tags():
                    if str(li.tag).lower() == "li":
                        add("li", _joined_text(li.contents, gaps))
            else:
                add(tag, _joined_text(node.contents, gaps))
        elif tag == "li" and node.wiki_markup:
            # Source list markers precede their text, unlike rendered li tags.
            flush()
        else:
            inline.append(node)
    flush()
    return "\n".join(line.strip() for part in parts for line in part.splitlines() if line.strip())


def _lyric_text(code, gaps=None):
    return "\n".join(line.rstrip() for line in _text(code, lyrics=True, gaps=gaps).splitlines()).strip()


def _classes(tag):
    try:
        return str(tag.get("class").value).split()
    except ValueError:
        return []


def _cell_text(code, br=""):
    """HEAD table cells join individually stripped text nodes, not words."""
    parts = []
    for node in code.nodes:
        if isinstance(node, Tag):
            parts.append(br if str(node.tag).lower() == "br" else _cell_text(node.contents, br))
        else:
            parts.append(_text(node).strip())
    return "".join(parts)


def _table_data(table, single_col):
    data, preserved_title = {}, None
    for row in table.contents.filter_tags():
        if str(row.tag).lower() != "tr":
            continue
        if row.has("style") and "display:none" in str(row.get("style").value):
            continue
        cols = [t for t in row.contents.filter_tags() if str(t.tag).lower() in {"th", "td"}]
        if len(cols) == 2:
            key = _cell_text(cols[0].contents)
            if key:
                data[field_key(key)] = _cell_text(cols[1].contents, br=",")
        elif len(cols) == 1 and single_col:
            if "infobox-image-container" in _classes(cols[0]):
                continue
            text = _cell_text(cols[0].contents)
            if not text:
                continue
            if preserved_title is None:
                preserved_title = next((kw for kw in role_priority() if kw in structure(text)), None)
            else:
                # Styled single-column boxes can place decorative prose beside
                # a dedicated linked value span. Read that value container.
                linked_spans = [span for span in cols[0].contents.filter_tags()
                                if str(span.tag).lower() == "span" and span.contents.filter_wikilinks()]
                data[preserved_title] = _cell_text(linked_spans[-1].contents) if linked_spans else text
                preserved_title = None
    return data


def _first_table(code):
    return next((t for t in code.ifilter_tags() if str(t.tag).lower() == "table"), None)


def _preferred_value(template, keys):
    value = ""
    for key in reversed(keys):
        value = _value(template, key, value)
    return value


def _lyric_pair(code, gaps=None):
    """Read documented content parameters, never translated/control values as original."""
    for node in _code(code).nodes:
        if isinstance(node, Template) and _kind(node) == "lyrics":
            rule = descriptor(_name(node))
            def column(prefix, record_gaps=None):
                values = [(int(str(p.name).strip()[len(prefix):]), p.value) for p in node.params
                          if re.fullmatch(re.escape(prefix) + r"\d+", str(p.name).strip(), re.I)]
                return "\n\n".join(_lyric_text(v, record_gaps) for _, v in sorted(values))
            original = column(rule["original_prefix"], gaps)
            translated = column(rule["translated_prefix"])
            if original or translated:
                return original, translated
            original = _preferred_value(node, rule["original_params"])
            return _lyric_text(original, gaps), _lyric_text(_preferred_value(node, rule["translated_params"]))
        if isinstance(node, Tag):
            if str(node.tag).lower() == "poem" or "poem" in _classes(node):
                return _lyric_text(node.contents, gaps), ""
            if node.contents and str(node.tag).lower() not in {"ref", "script", "style"}:
                pair = _lyric_pair(node.contents, gaps)
                if any(pair):
                    return pair
    return "", ""


def _kind(template):
    kind = descriptor(_name(template)).get("kind", "")
    return kind if kind in {"staff", "songbox", "tabs", "wrapper", "embed", "lyrics"} else ""


def is_embed(template):
    """Whether the template is the documented external-content embed.

    Answered from the rules directly, so callers never depend on the parser's
    internal kind shortlist.
    """
    return descriptor(_name(template)).get("kind") == "embed"


def _contents(template):
    """Yield (business slot, label, source nodes), without HTML simulation."""
    kind = _kind(template)
    rule = descriptor(_name(template))
    for param in template.params:
        key = structure(param.name).strip().casefold()
        if kind == "songbox" and key in rule["body_params"]:
            yield key, "", param.value
        elif kind == "tabs" and any(re.fullmatch(re.escape(prefix) + r"\d+", key) for prefix in rule["body_prefixes"]):
            number = re.search(r"\d+$", key)[0]
            label = _clean(_preferred_value(template, [prefix + number for prefix in rule["label_prefixes"]]))
            yield "tab", label or "tab" + number, param.value
        elif kind == "wrapper" and key in rule["body_params"]:
            yield "body", "", param.value
        elif not kind and (key.isdigit() or key.startswith(("list", "内容")) or key in {"body", "text"}):
            yield "list", "", param.value


def _fields(template, missing):
    staff = _kind(template) == "staff"
    rule = descriptor(_name(template))
    data = {}
    for param in template.params:
        key = str(param.name).strip()
        normkey = structure(key)
        folded = normkey.casefold()
        if (is_presentation_key(normkey) or (not staff and is_excluded_field(normkey))
                or (staff and (folded.startswith(rule["list_prefix"]) or folded in rule["exclude_params"] or key.isdigit()))):
            continue
        role, value = key, param.value
        if staff and folded.startswith(rule["group_prefix"]):
            role, value = _text(value), _value(template, rule["list_prefix"] + key[len(rule["group_prefix"]):])
        text = (_information_text(value) if normkey in {"其他资料", "再生"}
                else ",".join(line.strip() for line in _text(value).splitlines() if line.strip()))
        for label in _text(role).splitlines():
            label = field_key(label)
            if not label or is_presentation_key(label):
                continue
            if text:
                data[label] = text
            elif not any(_name(t).endswith("count") for t in _code(value).filter_templates()):
                missing.add(label)
    return data


def parse_details(source: str, title: str, *, with_missing=False) -> Dict:
    """Read fields, first introduction and first lyrics independently."""
    infobox, summaries, lyric_candidates, missing = {}, [], [], set()
    gaps = {"summary": set(), "lyrics": set()}
    boxes = 0
    has_heading = False
    has_lyrics = False

    def walk(value, section="", level=0, direct=False):
        nonlocal boxes, has_heading, has_lyrics
        code = _code(value)
        if any(isinstance(n, Text) and re.search(r"(?m)^=", str(n)) for n in code.nodes):
            code = mw.parse(str(code))
        intro, lyric_nodes = [], []
        nested_summaries = []
        table_done = False

        def flush():
            if intro:
                text = _intro_text(mw.wikicode.Wikicode(intro), gaps["summary"])
                if text:
                    summaries.append(text)
                intro.clear()
            summaries.extend(nested_summaries)
            nested_summaries.clear()
            if lyric_nodes:
                content = mw.wikicode.Wikicode(lyric_nodes)
                original, _ = _lyric_pair(content, gaps["lyrics"])
                if not original and direct:
                    original = _lyric_text(content, gaps["lyrics"])
                if original:
                    lyric_candidates.append(original)
                lyric_nodes.clear()

        for node in code.nodes:
            heading_level = _heading_level(node)
            if heading_level:
                has_heading = True
                heading = structure(_clean(node.title if isinstance(node, Heading) else node.contents))
                target = "简介" if "简介" in heading or "VOCALOID原创作者" in heading else "歌词" if "歌词" in heading else ""
                if section == "简介" and heading_level > level and target != "歌词":
                    intro.append(node)
                    continue
                flush()
                section, level = target, heading_level
                has_lyrics |= section == "歌词"
                table_done = False
                continue
            if isinstance(node, Template):
                kind = _kind(node)
                if kind == "songbox":
                    boxes += 1
                    if boxes == 1:
                        infobox.update(_fields(node, missing))
                    slots = {id(content): slot for slot, _, content in _contents(node)}
                    for param in node.params:
                        flush()
                        slot = slots.get(id(param.value), "")
                        has_lyrics |= slot == "歌词"
                        walk(param.value, slot, direct=slot == "歌词")
                    continue
                if kind == "staff":
                    if boxes <= 1:
                        infobox.update(_fields(node, missing))
                    continue
                if kind == "lyrics":
                    if section != "歌词":
                        continue
                    flush()
                    has_lyrics = True
                    original, _ = _lyric_pair(node, gaps["lyrics"])
                    if original:
                        lyric_candidates.append(original)
                    continue
                if descriptor(_name(node)).get("kind") == "inline":
                    # Inline descriptors own their visible slots; other parameters
                    # must not become independent structural candidates.
                    if section == "简介":
                        intro.append(node)
                    elif section == "歌词":
                        lyric_nodes.append(node)
                    continue
                if direct and _text(node, lyrics=True):
                    lyric_nodes.append(node)
                    continue
                if section != "简介":
                    flush()
                if section == "歌词" and not descriptor(_name(node)):
                    # A section also contains catalogs/navigation. Only direct
                    # body slots or explicit lyric parameters establish prose.
                    if (direct and _unread_content(node)) or any(
                            structure(p.name).strip().casefold() in {"original", "歌词"}
                            and str(p.value).strip() for p in node.params):
                        gaps["lyrics"].add(str(node))
                start = len(summaries)
                slots = {id(content) for _, _, content in _contents(node)} if kind in {"tabs", "wrapper"} else set()
                for param in node.params:
                    # Only documented content slots inherit surrounding prose.
                    # All other values are independent structural search roots.
                    if id(param.value) in slots:
                        walk(param.value, section, level, direct)
                    else:
                        walk(param.value, "歌词" if section == "歌词" else "")
                if section == "简介":
                    if len(summaries) > start:
                        intro.append(Tag("p", contents=summaries[start]))
                        del summaries[start:]
                    else:
                        intro.append(node)
                continue
            if isinstance(node, Tag):
                tag = str(node.tag).lower()
                if tag in {"ref", "references", "includeonly", "script", "style", "nowiki"}:
                    continue
                if section == "歌词" and (tag == "poem" or "poem" in _classes(node)):
                    flush()
                    has_lyrics = True
                    original = _lyric_text(node.contents, gaps["lyrics"])
                    if original:
                        lyric_candidates.append(original)
                    continue
                table = node if tag == "table" else _first_table(node.contents) if tag == "div" else None
                if table is not None:
                    classes = _classes(table)
                    main_table = classes == ["moe-infobox", "infobox"] or "infotemplate" in classes
                    if boxes <= 1 and (main_table or (section == "简介" and tag == "div") or (section == "歌词" and not table_done)):
                        if "navbox" not in classes:
                            infobox.update(_table_data(table, single_col=section != "歌词" or main_table))
                        if section == "歌词" and (tag == "table" or "navbox" not in classes):
                            table_done = True
                    continue
                if tag in {"div", "section"} and node.contents and "poem" not in _classes(node):
                    content = mw.parse(str(node.contents)) if tag == "section" else node.contents
                    # Inline prose templates do not start a new introduction.
                    # Only headings or structural content need a separate walk.
                    if (section != "简介" or any(_heading_level(n) for n in content.nodes)
                            or any(_kind(t) in {"songbox", "staff", "tabs"}
                                   for t in content.filter_templates())):
                        flush()
                        walk(content, section, level, direct)
                        continue
                    # Keep discovering structures, but publish nested intros
                    # after the enclosing intro has finished, including its tail.
                    start = len(summaries)
                    walk(content)
                    nested_summaries.extend(summaries[start:])
                    del summaries[start:]
            if section == "简介":
                intro.append(node)
            elif section == "歌词":
                lyric_nodes.append(node)
        flush()

    conversion = TextConversion(source)
    walk(mw.parse(conversion.protect(source)))
    summary = summaries[:1] or ([""] if has_heading else [])
    lyrics = next(iter(lyric_candidates), "")
    missing.difference_update(infobox)
    needed = {"infobox": sorted(missing), "summary": bool(gaps["summary"]) or bool(boxes) and not any(summary),
              "lyrics": bool(gaps["lyrics"]) or bool(boxes or has_lyrics) and not lyrics}
    result = {"name": title, "type": "Song" if has_lyrics else "Person",
              "infobox": infobox, "summary": summary, "lyrics": lyrics,
              "spaced_lyrics": spaced_from(lyrics)}
    result["infobox"] = {key: conversion.finish(value) for key, value in infobox.items()}
    result["summary"] = [conversion.finish(value) for value in summary]
    for key in ("lyrics", "spaced_lyrics"):
        result[key] = conversion.finish(result[key])
    return (result, needed) if with_missing else result
