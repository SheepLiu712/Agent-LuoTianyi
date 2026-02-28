import re
import dataclasses

@dataclasses.dataclass
class OneSentenceChat:
    expression: str
    tone: str
    content: str
    sound_content: str = ""

content = "你好！这是一个测试文本（挥手），用于测试文本拆分功能。希望它能正常工作......（小声）你在说什么？！他不会~，真的吗？"

resp = OneSentenceChat(
    content=content,
    expression="happy",
    tone="normal"
)
split_responses = []



# 使用捕获组 () 保留分隔符
parts = re.split(r'((?:\.{3}|[。，！？~,]))', resp.content)

    
# Merging logic: 
# 如果一个part仅由标点符号组成，则分给前一个，否则作为一个新句子
sentences_with_punct = []
punct_pattern = re.compile(r'^(?:\.{3}|[。，！？~,])+$')

for s in parts:
    if not s: continue
    if punct_pattern.match(s) and sentences_with_punct:
        sentences_with_punct[-1] += s
    else:
        sentences_with_punct.append(s)

# 只要一句话超过了5个字，就拆分。否则分给下一句一起拆分
sentence_buffer: str = ""

def clean_sound_content(text: str) -> str:
    # Remove content within parentheses (Chinese and English)
    return re.sub(r'（.*?）|\(.*?\)', '', text)

for i, sentence in enumerate(sentences_with_punct):
    # check if sentence starts with parenthesis (action/mood)
    match = re.match(r'^(\（.*?\）|\(.*?\))', sentence)
    paren_content = None
    if match:
        paren_content = match.group(1)
        sentence = sentence[len(paren_content):] # remove from current sentence

    if paren_content:
        # assign to previous sentence
        if sentence_buffer.strip():
            # append to current buffer
            sentence_buffer += paren_content
        elif split_responses:
            # append to last existing response content
            # No need to update sound_content as it strips parentheses anyway
            split_responses[-1].content += paren_content
        else:
            # no previous sentence, keep it at start
            sentence = paren_content + sentence
    
    sentence_buffer += sentence
    
    # Standard flush condition
    if len(sentence_buffer) >= 6 or i == len(sentences_with_punct) - 1:
        if sentence_buffer.strip():
            final_content = sentence_buffer.strip()
            split_responses.append(
                OneSentenceChat(
                    content=final_content,
                    expression=resp.expression,
                    tone=resp.tone,
                    sound_content=clean_sound_content(final_content)
                )
            )
            sentence_buffer = ""
print(split_responses)