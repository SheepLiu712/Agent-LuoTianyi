"""按未朗读正文长度和标点增量解析回复，情绪标签跨模型分片保留。"""

from ._response_parser import StructuredResponseParser
from ._text_cleaning import build_sound_content


class StreamingReplyParser:
    punctuation = frozenset("，。！？；：、,.!?;:…～~")

    def __init__(self, parser: StructuredResponseParser, sing_plan=None):
        self._parser = parser
        self._sing_plan = sing_plan
        self._tone = "中性"
        self._sentence_tone = self._tone
        self._text = ""
        self._tag = None
        self._song = None
        self._parentheses = 0
        self._started = False

    def feed(self, delta: str):
        drafts = []
        for char in delta:
            drafts.extend(self._character(char))
        return tuple(drafts)

    def _character(self, char):
        if self._song is not None:
            if char in "\r\n":
                return self._flush_song()
            self._song += char
            return ()
        if self._tag is not None:
            return self._tag_character(char)
        if char == "[" and not self._parentheses:
            self._tag = ""
            return ()
        if not self._started or char == "`":
            return ()
        if not self._text.strip():
            self._sentence_tone = self._tone
        self._text += char
        self._parentheses += int(char in "（(")
        if char in "）)":
            self._parentheses = max(0, self._parentheses - 1)
        if not self._parentheses and char in self.punctuation:
            sound = build_sound_content(self._text)
            if sum(c.isalnum() for c in sound) > 7:
                return self._flush_text()
        return ()

    def _tag_character(self, char):
        if char != "]":
            self._tag += char
            return ()
        tag, self._tag = self._tag.strip(), None
        if not tag:
            raise ValueError("回复情绪标识符不能为空")
        self._started = True
        if tag.lower() == "sing":
            drafts = self._flush_text()
            self._song = ""
            return drafts
        drafts = self._flush_text()
        self._tone = tag
        return drafts

    def _flush_text(self):
        text, self._text = self._text.strip(), ""
        if not any(c.isalnum() for c in build_sound_content(text)):
            return ()
        draft = self._parser._parse_tone_line(self._sentence_tone, text)
        return (draft,) if draft is not None else ()

    def _flush_song(self):
        text, self._song = self._song, None
        draft = self._parser._parse_sing_line(text, self._sing_plan)
        return (draft,) if draft is not None else ()

    def finish(self):
        if self._tag is not None:
            raise ValueError("回复以未闭合的情绪标识符结束")
        if self._parentheses:
            raise ValueError("回复以未闭合的动作描述结束")
        if not self._started:
            raise ValueError("回复缺少情绪或演唱标识符")
        return self._flush_song() if self._song is not None else self._flush_text()
