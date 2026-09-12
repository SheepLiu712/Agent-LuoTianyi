"""Shared oracle: the site's own rendered lyric surface, used to check extractions.

Both frozen-capture replay and recorded-material comparison read the served HTML as
the ground truth. Keeping one implementation stops the two callers from drifting.
"""
from bs4 import BeautifulSoup


def surface_lines(html, *, section_id="歌词"):
    """Visible lyric lines of served HTML, following the rb/rt surface contract.

    Displayed ``rb`` wins; a blank ``rb`` keeps ``rt`` because that is actual singing.
    With a section id the heading's first poem is used, otherwise the ``.Lyrics-original``
    containers are the fallback. Callers compare whitespace-insensitively.
    """
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find(id=section_id) if section_id else None
    poem = heading.find_next(class_="poem") if heading else None
    if poem is None and section_id is None:
        poem = soup.select_one(".poem")
    if poem is None:
        return [node.get_text().strip() for node in soup.select(".Lyrics-original")
                if node.get_text().strip()]
    for node in poem.select(".mw-editsection, .reference, .template-ruby-hidden, rp"):
        node.decompose()
    for ruby in poem.select("ruby"):
        base, reading = ruby.find("rb"), ruby.find("rt")
        if base is not None and base.get_text().strip():
            if reading is not None:
                reading.decompose()
        elif reading is not None:
            ruby.replace_with(reading.get_text())
    for br in poem.select("br"):
        br.replace_with("\n")
    return [line.strip() for line in poem.get_text().splitlines() if line.strip()]
