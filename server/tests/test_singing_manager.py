import os
import sys

# Setup paths
current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.plugins.music.singing_manager import SingingManager

singing_manager = SingingManager(config={})

def test_singing_manager():
    # Test get_music_data
    _, ret = singing_manager.can_i_sing_song("夜曲")
    assert len(ret) == 0, "Expected no segments for '夜曲' since it's not in the library."
    _, ret = singing_manager.can_i_sing_song("MAO！")
    assert len(ret) > 0, "Expected to find segments for 'MAO！' since it's in the library."
    _, ret = singing_manager.can_i_sing_song("流光")
    assert len(ret) > 0, "Expected to find segments for 'MAO！' since it's in the library."
    sn, ret = singing_manager.can_i_sing_song("66ccff")
    assert len(ret) > 0, "Expected to find segments for 'MAO！' since it's in the library."
    lyrics, song_bytes = singing_manager.get_song_segment(sn, ret[0], require_audio=True)
    for lyric in lyrics:
        assert lyric, "Expected non-empty lyric."
    _, ret = singing_manager.can_i_sing_song("歪歪")
    assert len(ret) > 0, "Expected to find segments for 'MAO！' since it's in the library."

if __name__ == "__main__":     
    test_singing_manager()
    print("All tests passed!")