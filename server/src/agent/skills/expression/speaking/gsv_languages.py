"""Normalize Chinese language labels before gsv's supported-language filter."""


def configure_chinese_language_labels(segmenter) -> None:
    """Keep Mandarin speech usable when langid labels Chinese text yue/wuu.

    gsv supports zh, en, ja and ko, but its classifier also returns Chinese
    varieties which its filter silently drops. Normalize before that filter;
    do not change Japanese/Korean detection or admit other unsupported text.
    """
    for name in ("_lang_classify", "_lang_classify_full"):
        classify = getattr(segmenter, name)

        def normalized(text, _classify=classify):
            language = _classify(text)
            return "zh" if language in {"yue", "wuu"} else language

        setattr(segmenter, name, staticmethod(normalized))
