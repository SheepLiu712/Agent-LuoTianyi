import os
import sys

# Setup paths
current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.agent.jargon_retriver import SongEntityLinker

def test_jargon_retriver():
    linker = SongEntityLinker()
    
    # 测试用例1：包含歌名和触发动词
    input1 = "我怎会不知你挚爱纯蓝，唱给我听听吧！"
    songnames, lyrics = linker.extract_and_verify(input1)
    print("Test Case 1 - Song Names:", songnames)
    print("Test Case 1 - Lyrics:", lyrics)
    

if __name__ == "__main__":
    test_jargon_retriver()