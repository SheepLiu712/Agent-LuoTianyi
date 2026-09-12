"""Internal source-node parsing; no HTML fetching or remote template expansion."""
import re
from copy import deepcopy
from typing import Dict, List, Union

import mwparserfromhell as mw
from mwparserfromhell.nodes import Comment, ExternalLink, Heading, Tag, Template, Text, Wikilink

_ALIASES = {
    "singer": "演唱", "singers": "演唱", "vocal": "演唱", "歌手": "演唱",
    "uploader": "UP主", "up主": "UP主", "lyricist": "作词", "lyrics": "作词",
    "composer": "作曲", "music": "作曲", "arranger": "编曲", "arrangement": "编曲",
    "illustrator": "曲绘", "illustration": "曲绘", "pv": "PV", "tuning": "调教",
}
_LYRIC_TEMPLATES = {"歌词", "lyrics", "lyricskai", "lyric"}
_LYRIC_PARAMS = {"lyrics", "歌词", "original", "translated", "translation", "text", "内容", "原文", "译文"}


def _name(template):
    return str(template.name).strip().replace("_", " ").removeprefix("Template:").removeprefix("模板:").casefold()


def _value(template, key, default=""):
    param = template.get(key, None)
    return param.value if param is not None else default


def _code(value):
    if isinstance(value, mw.wikicode.Wikicode):
        return value
    if isinstance(value, mw.nodes.Node):
        return mw.wikicode.Wikicode([value])
    return mw.parse(value)


def _text(code, lyrics=False):
    parts = []
    for node in _code(code).nodes:
        if isinstance(node, Text):
            parts.append(str(node))
        elif isinstance(node, Wikilink):
            title = str(node.title).strip()
            # File embeds/category declarations are not visible text links;
            # a leading colon explicitly turns either into an ordinary link.
            if title.casefold().startswith(("file:", "image:", "文件:", "图像:", "category:", "分类:")):
                continue
            parts.append(_text(node.text if node.text is not None else title.removeprefix(":"), lyrics))
        elif isinstance(node, ExternalLink):
            parts.append(_text(node.title or "", lyrics))
        elif isinstance(node, Tag):
            tag = str(node.tag).strip().lower()
            if tag in {"ref", "references", "gallery", "noinclude", "style", "script"}:
                continue
            if tag == "br":
                parts.append("\n")
            else:
                parts.append(_text(node.contents or "", lyrics))
                if tag in {"p", "div", "poem", "li"} or (lyrics and tag == "span"):
                    parts.append("\n")
        elif isinstance(node, Template):
            name = _name(node)
            if name == "lj":
                parts.append(_text(_value(node, "2", _value(node, "1")), lyrics))
            elif name in {"color", "colored", "颜色", "fontcolor"}:
                parts.append(_text(_value(node, "2"), lyrics))
            elif name in {"ruby", "注音"}:
                parts.append(_text(_value(node, "1"), lyrics))
            elif name in {"tabs", "tabs/core"}:
                values = [p.value for p in node.params
                          if str(p.name).strip().casefold().startswith(("text", "content", "内容"))]
                parts.append("\n".join(_text(value, lyrics) for value in values))
            elif name in {"br", "clear"}:
                parts.append("\n")
            elif name.startswith("bilibilicount") or "songbox" in name or name in {"创作者名单", "creator", "creators"}:
                continue
            else:
                values = [p.value for p in node.params if str(p.name).strip().isdigit()
                          or (name in _LYRIC_TEMPLATES and str(p.name).strip().lower() in _LYRIC_PARAMS)]
                parts.append(("\n" if lyrics else "").join(_text(v, lyrics) for v in values))
        elif not isinstance(node, (Comment, Heading)):
            parts.append(str(node.strip_code() or ""))
    return "".join(parts)


def _clean(code):
    return " ".join(_text(code).split())


def parse_song_titles(source: str) -> List[str]:
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
            titles.append(title)

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
                    for param in node.params:
                        key = str(param.name).strip().casefold()
                        if key.isdigit() or key.startswith(("list", "内容")) or key in {"body", "text"}:
                            walk(param.value)
            elif isinstance(node, Tag) and str(node.tag).lower() not in {"includeonly", "ref"}:
                if node.contents:
                    walk(node.contents)
    walk(mw.parse(source))
    return titles


def _heading_level(node):
    if isinstance(node, Heading):
        return node.level
    if isinstance(node, Tag) and str(node.tag).lower() in {"h2", "h3"}:
        return int(str(node.tag)[1])
    return None


def _headings(code):
    """Discover headings globally, but retain each heading's local siblings."""
    nodes = _code(code).nodes
    for index, node in enumerate(nodes):
        if _heading_level(node) == 2:
            title = node.title if isinstance(node, Heading) else node.contents
            siblings = mw.wikicode.Wikicode(nodes[index + 1:])
            yield _clean(title), list(_content_nodes(siblings))
        elif isinstance(node, Template) and _name(node) in {"tabs", "tabs/core"}:
            # Each tab's headings scan only that parameter's siblings, never
            # another tab or nodes following the template in its parent.
            for value in _tab_contents(node):
                yield from _headings(value)
        elif isinstance(node, Tag) and node.contents:
            yield from _headings(node.contents)


def _sections(headings):
    """Only rendered h2 selects an intro; h2/h3 ends its sibling scan."""
    for heading, siblings in headings:
        if "简介" in heading or "VOCALOID原创作者" in heading:
            end = next((i for i, node in enumerate(siblings)
                        if _heading_level(node) in {2, 3}), len(siblings))
            yield mw.wikicode.Wikicode(siblings[:end])


def _tab_contents(template):
    for param in template.params:
        if str(param.name).strip().casefold().startswith(("text", "content", "内容")):
            # Parameter parsing leaves wiki headings as Text. Reparse only
            # this expansion boundary, keeping each parameter independent.
            value = param.value
            if any(isinstance(n, Text) and re.search(r"(?m)^=", str(n))
                   for n in value.nodes):
                value = mw.parse(str(value))
            yield value


def _content_nodes(code):
    """Expose field content; heading discovery must retain parameter scopes."""
    for node in _code(code).nodes:
        if isinstance(node, Template) and _name(node) in {"tabs", "tabs/core"}:
            for value in _tab_contents(node):
                yield from _content_nodes(value)
                yield Text("\n")
        else:
            yield node


def _joined_text(code):
    """Rendered get_text(strip=True), only for display names and intros."""
    parts = []
    for node in _code(code).nodes:
        if isinstance(node, Tag):
            if str(node.tag).lower() not in {"br", "ref", "references", "includeonly"}:
                parts.append(_joined_text(node.contents))
        elif isinstance(node, Wikilink):
            target = str(node.title).strip()
            if not target.casefold().startswith(("file:", "image:", "文件:", "图像:", "category:", "分类:")):
                parts.append(_joined_text(node.text if node.text is not None else target.removeprefix(":")))
        elif isinstance(node, ExternalLink):
            parts.append(_joined_text(node.title or ""))
        else:
            parts.append(_text(node).strip())
    return "".join(parts)


def _intro_text(code):
    parts, inline = [], []
    last_was_a = False

    def add(name, text):
        nonlocal last_was_a
        if not text:
            return
        text = re.sub(r"截至[^。！？\n]*?收藏", "", text).strip()
        if parts and (last_was_a or name == "a"):
            parts[-1] += text
        else:
            parts.append(text)
        last_was_a = name == "a"

    def flush():
        if inline:
            add("p", _joined_text(mw.wikicode.Wikicode(inline)))
            inline.clear()

    for node in _content_nodes(code):
        tag = str(node.tag).lower() if isinstance(node, Tag) else None
        if tag in {"p", "a", "ul", "ol"}:
            flush()
            if tag in {"ul", "ol"}:
                for li in node.contents.filter_tags():
                    if str(li.tag).lower() == "li":
                        add("li", _joined_text(li.contents))
            else:
                add(tag, _joined_text(node.contents))
        elif tag == "li" and node.wiki_markup:
            # Source list markers precede their text, unlike rendered li tags.
            flush()
        else:
            inline.append(node)
    flush()
    return "\n".join(line.strip() for part in parts for line in part.splitlines() if line.strip())


def _lyric_text(code):
    # HEAD takes every span in the first p, ignoring non-span text when present.
    code = _code(code)
    paragraph = next((t for t in code.ifilter_tags() if str(t.tag).lower() == "p"), None)
    if paragraph is not None:
        code = paragraph.contents
    # Removing br must never mutate the page tree used by other fields.
    code = deepcopy(code)
    # HTML br has no get_text() separator, including inside spans.
    for tag in code.filter_tags():
        if str(tag.tag).lower() == "br":
            code.remove(tag)
    spans = [t for t in code.filter_tags() if str(t.tag).lower() == "span"]
    if spans:
        return " ".join(_text(t.contents) for t in spans)
    return _text(code)


def _classes(tag):
    try:
        return str(tag.get("class").value).split()
    except ValueError:
        return []


def _first_poem(nodes):
    for node in nodes:
        if isinstance(node, Tag):
            tag = str(node.tag).lower()
            is_poem = tag == "poem" or (tag == "div" and node.has("class")
                       and "poem" in str(node.get("class").value).strip('\"\'').split())
            if is_poem:
                return _lyric_text(node.contents)
            if tag == "div" and _classes(node) in (["Tabs"], ["tabLabelTop"]):
                poem = next((t for t in node.contents.ifilter_tags()
                             if str(t.tag).lower() == "div" and "poem" in _classes(t)), None)
                # An explicit tabs container stops the search even if empty.
                return _lyric_text(poem.contents) if poem is not None else ""
        elif isinstance(node, Template) and _name(node) in _LYRIC_TEMPLATES:
            values = [p.value for p in node.params if str(p.name).strip().isdigit()
                      or str(p.name).strip().lower() in _LYRIC_PARAMS]
            return _lyric_text("\n".join(str(v) for v in values))
    return ""


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
            data[_cell_text(cols[0].contents)] = _cell_text(cols[1].contents, br=",")
        elif len(cols) == 1 and single_col:
            if "infobox-image-container" in _classes(cols[0]):
                continue
            text = _cell_text(cols[0].contents)
            if not text:
                continue
            if preserved_title is None:
                preserved_title = next((kw for kw in ("演唱", "作词", "作曲", "编曲", "作编曲", "PV", "UP主", "曲绘") if kw in text), None)
            else:
                data[preserved_title] = text
                preserved_title = None
    return data


def _first_table(code):
    return next((t for t in code.ifilter_tags() if str(t.tag).lower() == "table"), None)


def parse_details(
    source: str, title: str
) -> Dict[str, Union[str, Dict[str, str], List[str]]]:
    code = mw.parse(source)
    infobox, summary = {}, []
    templates = [(t, _name(t)) for t in code.ifilter_templates()]
    songboxes = [t for t, name in templates if "songbox" in name]
    for template in songboxes:
        for param in template.params:
            key = str(param.name).strip()
            if key.casefold() in {"image", "图片", "width", "图片大小", "style", "class", "color", "colour", "background", "背景色", "border", "state", "title", "caption"}:
                continue
            value = ",".join(line.strip() for line in _text(param.value).splitlines() if line.strip())
            if value:
                infobox[_ALIASES.get(key.casefold(), key)] = value
    for template, name in templates:
        if name not in {"创作者名单", "creator", "creators", "制作人员", "staff"}:
            continue
        for param in template.params:
            key = str(param.name).strip()
            if key.startswith("group"):
                role = _clean(param.value)
                value = _clean(_value(template, "list" + key[5:]))
            elif key.startswith("list") or key in {"title", "state", "style"} or key.isdigit():
                continue
            else:
                role, value = _ALIASES.get(key.casefold(), key), _clean(param.value)
            if role and value:
                infobox[role] = value
    main_table = next((t for t in code.ifilter_tags() if str(t.tag).lower() == "table"
                       and _classes(t) == ["moe-infobox", "infobox"]), None)
    if main_table is not None:
        infobox.update(_table_data(main_table, single_col=True))
    headings = list(_headings(code))
    for section in _sections(headings):
        intro_nodes = []
        for node in section.nodes:
            if isinstance(node, Tag):
                tag = str(node.tag).lower()
                if tag == "div":
                    table = _first_table(node.contents)
                    if table is not None:
                        infobox.update(_table_data(table, single_col=True))
                    continue
                # Inline source nodes belong to a rendered paragraph. Explicit
                # blocks follow HEAD's p/a/ul/ol whitelist; tables only via div.
                if tag not in {"p", "a", "ul", "ol", "li", "span", "br", "b", "i", "strong", "em", "ref"}:
                    continue
            intro_nodes.append(node)
        summary.append(_intro_text(mw.wikicode.Wikicode(intro_nodes)))
    # HEAD iterates the first h2's children when no intro exists, yielding an
    # empty summary entry for a plain heading. Do not replace it with body text.
    if not summary and headings:
        summary = [""]
    lyric_headers = [siblings for heading, siblings in headings if "歌词" in heading
                     and "简介" not in heading and "VOCALOID原创作者" not in heading]
    lyric_nodes = lyric_headers[-1] if lyric_headers else []
    for node in lyric_nodes:
        if not isinstance(node, Tag):
            continue
        tag = str(node.tag).lower()
        table = None
        if tag == "table":
            table = node
        elif tag == "div":
            table = _first_table(node.contents)
        if table is not None:
            if _classes(table) == ["navbox"]:
                if tag == "table":
                    break
                continue
            infobox.update(_table_data(table, single_col=False))
            break
    lyrics = _first_poem(lyric_nodes)
    lyrics = re.sub(r"\[.*?\]|\(.*?\)|（.*?）|【.*?】", "", lyrics, flags=re.S)
    lyrics = " ".join(lyrics.split())
    return {"name": title, "type": "Song" if lyric_headers else "Person",
            "infobox": infobox, "summary": summary,
            "lyrics": lyrics, "spaced_lyrics": lyrics}
