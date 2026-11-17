"""Offline adapter of the historical HTML extractor; no transport, cache or LLM.

Reference: 910af449680091e339e0e6fd517d08c1f5222923 (also 79ae2c0),
server/src/world/get_new_songs/vcpedia_fetcher.py, blob
3208aae7a2f2dc74f9c77f2c8b7bcee680b596a5. Behaviour, including old bugs,
is intentionally preserved. The frozen reference is exercised by equivalence tests.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup


def _role(text):
    return next((key for key in ("演唱", "作词", "作曲", "编曲", "作编曲", "PV", "UP主", "曲绘")
                 if key in text.strip()), None)


def _single_column(col, preserved, result):
    if "infobox-image-container" in col.get("class", []):
        return preserved
    text = col.get_text(strip=True)
    if not text:
        return preserved
    if preserved is None:
        return _role(text)
    result[preserved] = text
    return None


def infobox(table, single_col=False):
    result, preserved = {}, None
    for row in table.find_all("tr"):
        if "display:none" in row.get("style", ""):
            continue
        cols = row.find_all(["th", "td"])
        if len(cols) == 2:
            for br in cols[1].find_all("br"):
                br.replace_with(",")
            result[cols[0].get_text(strip=True)] = cols[1].get_text(strip=True)
        elif len(cols) == 1 and single_col:
            preserved = _single_column(cols[0], preserved, result)
    return result


def _headers(soup):
    intros, lyric = [], None
    for heading in soup.find_all("h2"):
        text = heading.get_text()
        if "简介" in text or "VOCALOID原创作者" in text:
            intros.append(heading)
        elif "歌词" in text:
            lyric = heading
    # Preserve the old Tag-versus-list fallback, including its child iteration.
    return intros or soup.find("h2"), lyric


def _summary_text(name, text, parts, last_anchor):
    if not text:
        return last_anchor
    text = re.sub(r"截至[^。！？\n]*?收藏", "", text).strip()
    if parts and (last_anchor or name == "a"):
        parts[-1] += text
    else:
        parts.append(text)
    return name == "a"


def _summary_sibling(sibling, parts, last_anchor, data):
    if sibling.name in ["p", None, "a"]:
        return _summary_text(sibling.name, sibling.get_text(strip=True), parts, last_anchor)
    if sibling.name in ["ul", "ol"]:
        for li in sibling.find_all("li"):
            last_anchor = _summary_text("li", li.get_text(strip=True), parts, last_anchor)
    elif sibling.name == "div":
        table = sibling.find("table")
        if table:
            data.update(infobox(table, single_col=True))
    return last_anchor


def _summaries(headers, data):
    result = []
    if headers:
        for header in headers:
            parts, last_anchor = [], False
            for sibling in header.next_siblings:
                if sibling.name in ["h2", "h3"]:
                    break
                last_anchor = _summary_sibling(sibling, parts, last_anchor, data)
            result.append("\n".join(parts))
    return result


def _lyric_table(header):
    for sibling in header.next_siblings:
        if sibling.name == "table":
            return None if sibling.get("class", []) == ["navbox"] else sibling
        if sibling.name == "div":
            table = sibling.find("table")
            if table and table.get("class", []) != ["navbox"]:
                return table
    return None


def _poem(header):
    for sibling in header.next_siblings:
        if sibling.name == "div" and "poem" in sibling.get("class", []):
            return sibling
        if sibling.name == "div" and sibling.get("class", []) in [["Tabs"], ["tabLabelTop"]]:
            return sibling.find("div", class_="poem")
    return None


def _lyrics(poem):
    p = poem.find("p") if poem else None
    if not p:
        return ""
    spans = p.find_all("span")
    text = "".join(span.get_text() + " " for span in spans if span is not None) if spans else p.get_text()
    text = text.replace("\u3000", " ")
    text = re.sub(r"\[.*?\]|\(.*?\)|（.*?）|【.*?】", "", text, flags=re.S)
    return re.sub(r"\s+", " ", text).strip()


def parse_html(html, title):
    """Return the same six complete fields as historical _parse_page."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="moe-infobox infobox")
    data = infobox(table, single_col=True) if table else {}
    intro_headers, lyric_header = _headers(soup)
    summary = _summaries(intro_headers, data)
    lyrics = ""
    if lyric_header:
        table = _lyric_table(lyric_header)
        lyrics = _lyrics(_poem(lyric_header))
        if table:
            data.update(infobox(table))
    return {"name": title, "type": "Song" if lyric_header else "Person", "infobox": data,
            "summary": summary, "lyrics": lyrics.strip(), "spaced_lyrics": lyrics}
