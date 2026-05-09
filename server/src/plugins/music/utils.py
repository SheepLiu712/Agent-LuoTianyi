import re
def get_unified_song_name(song_name: str) -> str:
    '''
        去除所有的空格，标点符号（？！?1~，,、·），书名号
        去除括号（尖括号，小括号，中括号，中英文两种）内的内容
    '''
    if not song_name:
        return ""

    unified = str(song_name)

    # 去除中英文括号内的内容（支持多段，尽量兼容嵌套）
    bracket_patterns = [
        r"\([^()]*\)",
        r"（[^（）]*）",
        r"\[[^\[\]]*\]",
        r"【[^【】]*】",
        r"<[^<>]*>",
        r"〈[^〈〉]*〉",
        r"「[^「」]*」",
        r"『[^『』]*』",
    ]
    for pattern in bracket_patterns:
        while True:
            updated = re.sub(pattern, "", unified)
            if updated == unified:
                break
            unified = updated

    # 去除空白和常见干扰标点
    unified = re.sub(r"\s+", "", unified)
    unified = re.sub(r"[？！!?~，,、·《》]", "", unified)

    return unified.strip().lower()