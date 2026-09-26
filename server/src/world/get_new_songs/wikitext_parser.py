"""Internal source-node parsing; no HTML fetching or remote template expansion."""
import re
from copy import deepcopy
from typing import Dict, List

import mwparserfromhell as mw
from mwparserfromhell.nodes import Comment, ExternalLink, Heading, Tag, Template, Text, Wikilink

from .template_rules import (
    descriptor,
    field_key,
    is_excluded_field,
    is_presentation_key,
    role_priority,
    structure,
    template_name,
)
from .text_conversion import TextConversion, spaced_from

# Tags whose contents never carry business text; structural walks skip them whole.
NON_CONTENT_TAGS = {"ref", "references", "includeonly", "script", "style", "nowiki"}


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


def sectioned_code(value):
    """Parse wikitext into nodes, reparsing when headings hide inside plain text.

    Template values and section tags may carry line-initial equals signs that
    mwparserfromhell keeps as Text; the structural walk would miss the section
    switch they imply.
    """
    code = _code(value)
    if any(isinstance(n, Text) and re.search(r"(?m)^=", str(n)) for n in code.nodes):
        return mw.parse(str(code))
    return code


def _text(code, lyrics=False, gaps=None):
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
            parts.append(_text(node.text if node.text is not None else title.removeprefix(":"), lyrics, gaps))
        elif isinstance(node, ExternalLink):
            parts.append(_text(node.title or "", lyrics, gaps))
        elif isinstance(node, Tag):
            parts.append(_tag_text(node, lyrics, gaps))
        elif isinstance(node, Template):
            parts.append(_template_text(node, lyrics, gaps))
        elif not isinstance(node, (Comment, Heading)):
            parts.append(str(_code(node).strip_code() or ""))
    return "".join(parts)


def _tag_text(node, lyrics, gaps):
    """Text a tag renders: hidden markup vanishes, ruby resolves to base or
    annotation, block tags close their line."""
    tag = str(node.tag).strip().lower()
    if tag in {"ref", "references", "gallery", "noinclude", "style", "script"}:
        return ""
    if tag == "rp" or "template-ruby-hidden" in _classes(node):
        return ""
    if tag == "ruby":
        return _ruby_text(_ruby_base(node), _ruby_annotations(node), lyrics, gaps)
    if tag == "br":
        return "\n"
    tail = "\n" if tag in {"p", "div", "poem", "li"} or (lyrics and tag == "span") else ""
    return _text(node.contents or "", lyrics, gaps) + tail


def _ruby_base(node):
    """The base text source of a ruby tag: explicit rb children when present, else
    the contents stripped of rt/rp annotations.

    HTML allows implicit ruby bases: keep their normal inline markup, removing
    annotations before testing for empty text.
    """
    children = list(node.contents.filter_tags(recursive=False))
    bases = [t for t in children if str(t.tag).lower() == "rb"]
    if bases:
        return mw.wikicode.Wikicode(bases)
    surface = deepcopy(node.contents)
    for annotation in list(surface.filter_tags()):
        if str(annotation.tag).lower() in {"rt", "rp"}:
            surface.remove(annotation, recursive=True)
    return surface


def _ruby_annotations(node):
    return mw.wikicode.Wikicode([t for t in node.contents.filter_tags(recursive=False)
                                 if str(t.tag).lower() == "rt"])


def _ruby_text(base_source, fallback_source, lyrics, gaps):
    """Emit the ruby base when it stands alone, else the annotation fallback.

    Only the branch that produced the visible text contributes missing content.
    """
    base_gaps = set() if gaps is not None else None
    base = _text(base_source, lyrics, base_gaps)
    if base.strip():
        if gaps is not None:
            gaps.update(base_gaps)
        return base
    return _text(fallback_source, lyrics, gaps)


def _inline_text(node, lyrics, gaps):
    rule = descriptor(_name(node))
    if any(str(_value(node, key)).strip().casefold() in
           {value.strip().casefold() for value in values}
           for key, values in rule.get("skip_if", {}).items()):
        return ""
    return _text(_preferred_value(node, rule["text_params"]), lyrics, gaps)


def _ruby_template_text(node, lyrics, gaps):
    return _ruby_text(_value(node, "1"), _value(node, "2"), lyrics, gaps)


def _numbered_values(node, lyrics, gaps):
    """Rendered values of the numbered parameters, in parameter order."""
    return [_text(p.value, lyrics, gaps).strip() for p in node.params if str(p.name).strip().isdigit()]


def _utawari_text(node, lyrics, gaps):
    # "##" marks a repeated line; "###"/"#2" style marks stay escaped as "#".
    values = _numbered_values(node, lyrics, gaps)
    return "\n".join(re.sub(r"##|#\d+", lambda m: "#" if m[0] == "##" else "", v) for v in values)


def _multiline_text(node, lyrics, gaps):
    return "\n".join(_numbered_values(node, lyrics, gaps))


def _body_slots_text(node, lyrics, gaps):
    return "\n".join(_text(value, lyrics, gaps) for _, _, value in _contents(node))


def _break_text(node, lyrics, gaps):
    return "\n"


def _lyrics_template_text(node, lyrics, gaps):
    return _lyric_pair(mw.wikicode.Wikicode([node]), gaps)[0]


_TEXT_KINDS = {
    "inline": _inline_text,
    "ruby": _ruby_template_text,
    "utawari": _utawari_text,
    "multiline": _multiline_text,
    "tabs": _body_slots_text,
    "break": _break_text,
    "lyrics": _lyrics_template_text,
}


def _template_text(node, lyrics, gaps):
    """Text one template call renders, decided by its configured kind.

    A playback counter (name ending in ``count``) stays silent unless a rendering
    kind claims the call first; structural containers never render here; a
    template without a rendering kind only reports its unread content.
    """
    name = _name(node)
    kind = descriptor(name).get("kind")
    counter = name.endswith("count")
    if counter and kind not in {"inline", "ruby", "utawari", "tabs", "break", "wrapper"}:
        return ""
    if kind == "wrapper":
        # Wrapper slots render only while tracking missing content of ordinary
        # prose; otherwise the call is judged like any unconfigured template.
        if gaps is not None and not lyrics:
            return _body_slots_text(node, lyrics, gaps)
    elif kind in _TEXT_KINDS:
        return _TEXT_KINDS[kind](node, lyrics, gaps)
    if kind in {"songbox", "staff"} or counter:
        return ""
    if gaps is not None and _unread_content(node):
        gaps.add(str(node))
    return ""


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


# Keep HEAD's display-text filters and their order, not title namespaces.
_NON_SONG_TITLES = {
    "原创曲", "非原创曲", "传说曲", "殿堂曲", "部分", "25万以上", "25万以下",
    "模板文档", "查看", "编辑", "历史", "刷新", "简体", "繁體", "大陆简体",
    "香港繁體", "臺灣正體", "不转换", "跳转到导航", "跳转到搜索", "洛天依",
    "bilibili", "ACE Studio", "X studio", "VOCALOID中文殿堂曲", "ACE殿堂曲", "文档", "嵌入",
}
_NON_SONG_TITLE_PARTS = ("Template:", "模板:", "分类:", "Category:", "帮助", "首页",
                         "随机页面", "最近更改", "殿堂曲", "传说曲")
_NON_SONG_TARGETS = ("Template:", "Category:", "分类:")


def _song_entry(raw, target):
    """(display title, link target) of one candidate song link, or None when the
    pair is navigation noise: banners, site chrome, namespaces, anchors."""
    title = _joined_text(raw)
    href = str(target).strip()
    if not title or title in _NON_SONG_TITLES or title.isdigit() \
            or any(word in title for word in _NON_SONG_TITLE_PARTS):
        return None
    if not href or href.startswith("#") or "action=" in href \
            or any(word in href for word in _NON_SONG_TARGETS):
        return None
    title = title.rstrip("*").strip()
    if not title:
        return None
    if href.startswith(("https://", "http://")):
        return title, title
    return title, href.split("#", 1)[0].replace("_", " ").strip()


def _link_candidates(code):
    """Yield (raw display, href) for every link-shaped node, in source order."""
    for node in code.nodes:
        if isinstance(node, Wikilink):
            target = str(node.title).strip()
            if not target.casefold().startswith(("file:", "image:", "文件:", "category:", "分类:")):
                display = node.text if node.text is not None else node.title
                if node.text is None and ("_" in target or target.startswith(":")):
                    display = target.replace("_", " ")
                yield display, target
        elif isinstance(node, ExternalLink):
            yield node.title or "", node.url
        elif isinstance(node, Template):
            if _name(node) == "lj":
                yield _value(node, "2", _value(node, "1")), _value(node, "1")
            else:
                for _, _, value in _contents(node):
                    yield from _link_candidates(value)
        elif isinstance(node, Tag) and str(node.tag).lower() not in {"includeonly", "ref"} and node.contents:
            yield from _link_candidates(node.contents)


def parse_song_candidates(source: str):
    titles, seen = [], set()
    for raw, target in _link_candidates(mw.parse(source)):
        entry = _song_entry(raw, target)
        if entry and entry[0] not in seen:
            seen.add(entry[0])
            titles.append(entry)
    return titles


def _heading_level(node):
    if isinstance(node, Heading):
        return node.level
    if isinstance(node, Tag) and re.fullmatch(r"h[1-6]", str(node.tag).lower()):
        return int(str(node.tag)[1])
    return None


def heading_section(heading):
    """Which business section a heading names: 简介 or 歌词, else none."""
    heading = structure(heading)
    if "简介" in heading or "VOCALOID原创作者" in heading:
        return "简介"
    return "歌词" if "歌词" in heading else ""


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


def _sentence_text(text):
    """The intro keeps whole sentences; sentences carrying a count mark vanish."""
    return "".join(sentence for sentence in re.findall(r"[^。！？\n]+[。！？]?|\n", text)
                   if "\ufff0" not in sentence).strip()


class _IntroParagraphs:
    """Intro paragraph assembly with the anchor-continuation rule: an anchor never
    starts a paragraph, and a plain block right after an anchor continues it."""

    def __init__(self):
        self._parts = []
        self._last_was_a = False

    def add(self, name, text):
        if not text:
            return
        text = _sentence_text(text)
        if self._parts and (self._last_was_a or name == "a"):
            self._parts[-1] += text
        else:
            self._parts.append(text)
        self._last_was_a = name == "a"

    def joined(self):
        return "\n".join(line.strip() for part in self._parts for line in part.splitlines() if line.strip())


def _intro_text(code, gaps=None):
    code = _mark_counts(code)
    paragraphs = _IntroParagraphs()
    inline = []

    def flush():
        if inline:
            paragraphs.add("p", _joined_text(mw.wikicode.Wikicode(inline), gaps))
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
                        paragraphs.add("li", _joined_text(li.contents, gaps))
            else:
                paragraphs.add(tag, _joined_text(node.contents, gaps))
        elif tag == "li" and node.wiki_markup:
            # Source list markers precede their text, unlike rendered li tags.
            flush()
        else:
            inline.append(node)
    flush()
    return paragraphs.joined()


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


def _is_hidden_row(row):
    return row.has("style") and "display:none" in str(row.get("style").value)


def _read_pair_row(data, cols):
    key = _cell_text(cols[0].contents)
    if key:
        data[field_key(key)] = _cell_text(cols[1].contents, br=",")


def _read_single_col_row(data, cell, preserved_title):
    """Pair rows of a single-column box: a role line names the field, the next line
    carries its value. Returns the role awaiting its value."""
    if "infobox-image-container" in _classes(cell):
        return preserved_title
    text = _cell_text(cell.contents)
    if not text:
        return preserved_title
    if preserved_title is None:
        return next((kw for kw in role_priority() if kw in structure(text)), None)
    # Styled single-column boxes can place decorative prose beside
    # a dedicated linked value span. Read that value container.
    linked_spans = [span for span in cell.contents.filter_tags()
                    if str(span.tag).lower() == "span" and span.contents.filter_wikilinks()]
    data[preserved_title] = _cell_text(linked_spans[-1].contents) if linked_spans else text
    return None


def _table_data(table, single_col):
    data, preserved_title = {}, None
    for row in table.contents.filter_tags():
        if str(row.tag).lower() != "tr" or _is_hidden_row(row):
            continue
        cols = [t for t in row.contents.filter_tags() if str(t.tag).lower() in {"th", "td"}]
        if len(cols) == 2:
            _read_pair_row(data, cols)
        elif len(cols) == 1 and single_col:
            preserved_title = _read_single_col_row(data, cols[0], preserved_title)
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


def _param_skipped(key, normkey, folded, staff, rule):
    """Presentation keys never carry business text; non-staff excludes and staff
    list entries are documented non-fields."""
    if is_presentation_key(normkey):
        return True
    if not staff and is_excluded_field(normkey):
        return True
    return staff and (folded.startswith(rule["list_prefix"])
                      or folded in rule["exclude_params"] or key.isdigit())


def _infobox_text(value, normkey):
    """其他资料/再生 keep their clauses beside count marks; other fields join lines."""
    if normkey in {"其他资料", "再生"}:
        return _information_text(value)
    return ",".join(line.strip() for line in _text(value).splitlines() if line.strip())


def _fields(template, missing):
    staff = _kind(template) == "staff"
    rule = descriptor(_name(template))
    data = {}
    for param in template.params:
        key = str(param.name).strip()
        normkey = structure(key)
        folded = normkey.casefold()
        if _param_skipped(key, normkey, folded, staff, rule):
            continue
        role, value = key, param.value
        if staff and folded.startswith(rule["group_prefix"]):
            role, value = _text(value), _value(template, rule["list_prefix"] + key[len(rule["group_prefix"]):])
        text = _infobox_text(value, normkey)
        for label in _text(role).splitlines():
            label = field_key(label)
            if not label or is_presentation_key(label):
                continue
            if text:
                data[label] = text
            elif not any(_name(t).endswith("count") for t in _code(value).filter_templates()):
                missing.add(label)
    return data


class _Frame:
    """Routing context and buffers of one node stream.

    Sections switch inside a frame; recursion into template parameters or
    containers opens a new one, so buffered content never crosses frames.
    """

    def __init__(self, section, level, direct, nested):
        self.section = section
        self.level = level
        self.direct = direct
        self.nested = nested
        self.intro = []
        self.lyric_nodes = []
        self.nested_summaries = []
        self.table_done = False


class _DetailExtraction:
    """One page's traversal collecting infobox, first summary and first lyrics.

    Headings name the sections (简介/歌词) and route every node into one of the
    collectors. The first songbox owns the infobox together with adjacent staff
    templates and the main table; lyrics come from the first candidate in source
    order. Gaps record why a field stayed empty so the caller can request
    supplements.
    """

    def __init__(self):
        self.infobox = {}
        self.summaries = []
        self.lyric_candidates = []
        self.missing = set()
        self.gaps = {"summary": set(), "lyrics": set()}
        self.boxes = 0
        self.has_heading = False
        self.has_lyrics = False

    def walk(self, value, section="", level=0, direct=False, nested=False):
        frame = _Frame(section, level, direct, nested)
        for node in sectioned_code(value).nodes:
            if _heading_level(node):
                self._on_heading(node, frame)
            elif isinstance(node, Template):
                self._on_template(node, frame)
            elif isinstance(node, Tag):
                self._on_tag(node, frame)
            else:
                self._collect_by_section(node, frame)
        self._flush(frame)

    def result(self, title, conversion):
        """Convert the collected state into the result dict and missing-field report."""
        summary = self.summaries[:1] or ([""] if self.has_heading else [])
        lyrics = next(iter(self.lyric_candidates), "")
        self.missing.difference_update(self.infobox)
        needed = {
            "infobox": sorted(self.missing),
            "summary": bool(self.gaps["summary"]) or bool(self.boxes) and not any(summary),
            "lyrics": bool(self.gaps["lyrics"]) or bool(self.boxes or self.has_lyrics) and not lyrics,
        }
        return {
            "name": title,
            "type": "Song" if self.has_lyrics else "Person",
            "infobox": {key: conversion.finish(value) for key, value in self.infobox.items()},
            "summary": [conversion.finish(value) for value in summary],
            "lyrics": conversion.finish(lyrics),
            "spaced_lyrics": conversion.finish(spaced_from(lyrics)),
        }, needed

    def _collect_by_section(self, node, frame):
        if frame.section == "简介":
            frame.intro.append(node)
        elif frame.section == "歌词":
            frame.lyric_nodes.append(node)

    def _on_heading(self, node, frame):
        level = _heading_level(node)
        self.has_heading = True
        target = heading_section(_clean(node.title if isinstance(node, Heading) else node.contents))
        if frame.section == "简介" and level > frame.level and target != "歌词":
            frame.intro.append(node)
            return
        self._flush(frame)
        frame.section, frame.level = target, level
        self.has_lyrics |= frame.section == "歌词"
        frame.table_done = False

    def _on_template(self, node, frame):
        kind = _kind(node)
        if kind == "songbox":
            self._collect_songbox(node, frame)
        elif kind == "staff":
            # 首框到第二框之间的 staff 属于该信息框（可隔着简介标题）；首框之前的不算。
            if self.boxes == 1:
                self.infobox.update(_fields(node, self.missing))
        elif kind == "lyrics":
            self._collect_lyrics_template(node, frame)
        elif descriptor(_name(node)).get("kind") == "inline":
            self._collect_by_section(node, frame)
        elif frame.direct and _text(node, lyrics=True):
            frame.lyric_nodes.append(node)
        else:
            self._on_other_template(node, frame, kind)

    def _collect_songbox(self, node, frame):
        # 参数值里出现的同名模板不是新的歌曲框，只是该参数的取值。
        if not frame.nested:
            self.boxes += 1
            if self.boxes == 1:
                self.infobox.update(_fields(node, self.missing))
        slots = {id(content): slot for slot, _, content in _contents(node)}
        for param in node.params:
            self._flush(frame)
            slot = slots.get(id(param.value), "")
            self.has_lyrics |= slot == "歌词"
            self.walk(param.value, slot, direct=slot == "歌词", nested=True)

    def _collect_lyrics_template(self, node, frame):
        if frame.section != "歌词":
            return
        self._flush(frame)
        self.has_lyrics = True
        original, _ = _lyric_pair(node, self.gaps["lyrics"])
        if original:
            self.lyric_candidates.append(original)

    def _on_other_template(self, node, frame, kind):
        if frame.section != "简介":
            self._flush(frame)
        if frame.section == "歌词" and not descriptor(_name(node)):
            self._mark_catalog_gap(node, frame)
        start = len(self.summaries)
        slots = ({id(content) for _, _, content in _contents(node)}
                 if kind in {"tabs", "wrapper"} else set())
        for param in node.params:
            # Only documented content slots inherit surrounding prose. All other
            # values are independent structural search roots.
            if id(param.value) in slots:
                self.walk(param.value, frame.section, frame.level, frame.direct)
            else:
                self.walk(param.value, "歌词" if frame.section == "歌词" else "")
        if frame.section == "简介":
            if len(self.summaries) > start:
                frame.intro.append(Tag("p", contents=self.summaries[start]))
                del self.summaries[start:]
            else:
                frame.intro.append(node)

    def _mark_catalog_gap(self, node, frame):
        # A 歌词 section also contains catalogs/navigation. Only direct body slots
        # or explicit lyric parameters establish prose.
        has_lyric_param = any(structure(p.name).strip().casefold() in {"original", "歌词"}
                              and str(p.value).strip() for p in node.params)
        if (frame.direct and _unread_content(node)) or has_lyric_param:
            self.gaps["lyrics"].add(str(node))

    def _on_tag(self, node, frame):
        tag = str(node.tag).lower()
        if tag in NON_CONTENT_TAGS:
            return
        if frame.section == "歌词" and (tag == "poem" or "poem" in _classes(node)):
            self._collect_poem(node, frame)
            return
        table = node if tag == "table" else _first_table(node.contents) if tag == "div" else None
        if table is not None:
            self._read_infobox_table(node, tag, table, frame)
            return
        if tag in {"div", "section"} and node.contents and "poem" not in _classes(node):
            if self._walk_container(node, tag, frame):
                return
        self._collect_by_section(node, frame)

    def _collect_poem(self, node, frame):
        self._flush(frame)
        self.has_lyrics = True
        original = _lyric_text(node.contents, self.gaps["lyrics"])
        if original:
            self.lyric_candidates.append(original)

    def _read_infobox_table(self, node, tag, table, frame):
        classes = _classes(table)
        main_table = classes == ["moe-infobox", "infobox"] or "infotemplate" in classes
        adjacent_section = (frame.section == "简介" and tag == "div") or (
            frame.section == "歌词" and not frame.table_done)
        if self.boxes <= 1 and (main_table or adjacent_section):
            if "navbox" not in classes:
                self.infobox.update(_table_data(table, single_col=frame.section != "歌词" or main_table))
            if frame.section == "歌词" and (tag == "table" or "navbox" not in classes):
                frame.table_done = True

    def _walk_container(self, node, tag, frame):
        """Walk a container's contents; return False when the enclosing intro keeps
        collecting the container itself."""
        content = mw.parse(str(node.contents)) if tag == "section" else node.contents
        # Inline prose templates do not start a new introduction. Only headings or
        # structural content need a separate walk.
        if (frame.section != "简介" or any(_heading_level(n) for n in content.nodes)
                or any(_kind(t) in {"songbox", "staff", "tabs"} for t in content.filter_templates())):
            self._flush(frame)
            self.walk(content, frame.section, frame.level, frame.direct)
            return True
        # Keep discovering structures, but publish nested intros after the
        # enclosing intro has finished, including its tail.
        start = len(self.summaries)
        self.walk(content)
        frame.nested_summaries.extend(self.summaries[start:])
        del self.summaries[start:]
        return False

    def _flush(self, frame):
        if frame.intro:
            text = _intro_text(mw.wikicode.Wikicode(frame.intro), self.gaps["summary"])
            if text:
                self.summaries.append(text)
            frame.intro.clear()
        self.summaries.extend(frame.nested_summaries)
        frame.nested_summaries.clear()
        if frame.lyric_nodes:
            content = mw.wikicode.Wikicode(frame.lyric_nodes)
            original, _ = _lyric_pair(content, self.gaps["lyrics"])
            if not original and frame.direct:
                original = _lyric_text(content, self.gaps["lyrics"])
            if original:
                self.lyric_candidates.append(original)
            frame.lyric_nodes.clear()


def parse_details(source: str, title: str, *, with_missing=False) -> Dict:
    """Read fields, first introduction and first lyrics independently."""
    extraction = _DetailExtraction()
    conversion = TextConversion(source)
    extraction.walk(mw.parse(conversion.protect(source)))
    result, needed = extraction.result(title, conversion)
    return (result, needed) if with_missing else result
