"""Package-internal, per-extraction text protection; never attach state to business data."""
import re

from zhconv import convert


class TextConversion:
    """One protection scope per extraction.

    ``protect`` must run before any structural traversal of the source, and the
    same instance must ``finish`` every output field afterwards. Parsing first
    would hand the walk the raw nowiki tags, which it drops instead of keeping
    the inner text literally.
    """

    def __init__(self, source):
        self._prefix = "\ue000"
        while self._prefix in source:
            self._prefix += "\ue000"
        self._saved = {}

    def protect(self, text):
        def save(match):
            token = self._prefix + str(len(self._saved)) + "\ue001"
            self._saved[token] = match[1]
            return token
        # Hide nowiki before parsing: the structural walk drops nowiki tag nodes,
        # so only a plain token lets the inner text survive to finish() literally.
        return re.sub(r"<nowiki\s*>(.*?)</nowiki\s*>", save, text, flags=re.I | re.S)

    def finish(self, text):
        # Ordinary LC stays in place through node extraction so inline markup is
        # still parsed; protect its rendered surface only at the conversion boundary.
        saved_lc = {}
        def save_lc(match):
            token = self._prefix + "LC" + str(len(saved_lc)) + "\ue001"
            saved_lc[token] = match[1]
            return token
        text = re.sub(r"-\{([^{}|]*?)\}-", save_lc, text, flags=re.S)
        text = convert(text, "zh-cn")
        for token, original in saved_lc.items():
            text = text.replace(token, original)
        for token, original in self._saved.items():
            text = text.replace(token, original)
        return text


def spaced_from(text):
    """Derive the spaced lyric form the existing keyword consumer splits on."""
    return "\n".join(part.strip() for part in re.split(r"[\n，。！？；、,.!?;]+", text) if part.strip())


def convert_text(text):
    conversion = TextConversion(text)
    return conversion.finish(conversion.protect(text))


def converted_lyrics(text):
    conversion = TextConversion(text)
    protected = conversion.protect(text)
    return conversion.finish(protected), conversion.finish(spaced_from(protected))
