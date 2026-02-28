import sys
import os
import unittest

# Ensure valid import paths
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.music.song_database import init_song_db, get_song_session, Song
from src.music.knowledge_service import (
    get_song_introduction, 
    get_song_lyrics, 
    get_songs_by_uploader, 
    get_random_songs_by_singer,
    get_song_info
)

class TestKnowledgeService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 初始化数据库连接 (假设数据库已存在并包含数据，基于之前的操作)
        # 这里直接使用 production DB 的路径，因为我们只是读取测试
        # 如果需要完全隔离的测试环境，应该创建一个临时DB并populate数据
        # 但既然用户指定用《千年食谱颂》《光与影的对白》测试，暗示用现有数据
        project_root = os.getcwd()
        db_folder = os.path.join(project_root, "res", "knowledge")
        db_file = "knowledge_db.db"
        config = {
            "db_folder": db_folder,
            "db_file": db_file
        }
        init_song_db(config)
        cls.db = get_song_session()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_get_song_introduction(self):
        print("\n=== Test Get Song Introduction ===")
        # 测试《纯蓝》
        intro = get_song_introduction(self.db, "纯蓝")
        print(f"Song: 纯蓝\nIntro Preview: {intro[:50] if intro else 'None'}...")
        self.assertIsNotNone(intro)
        self.assertIn("H.K.君", intro) # 假设summary里提到了作者

        # 测试《光与影的对白》
        intro2 = get_song_introduction(self.db, "光与影的对白")
        print(f"Song: 光与影的对白\nIntro Preview: {intro2[:50] if intro2 else 'None'}...")
        self.assertIsNotNone(intro2)

    def test_get_song_lyrics(self):
        print("\n=== Test Get Song Lyrics ===")
        lyrics = get_song_lyrics(self.db, "纯蓝")
        print(f"Song: 纯蓝\nLyrics Preview: {lyrics[:600] if lyrics else 'None'}...")
        self.assertIsNotNone(lyrics)
        
        lyrics2 = get_song_lyrics(self.db, "光与影的对白")
        print(f"Song: 光与影的对白\nLyrics Preview: {lyrics2[:500] if lyrics2 else 'None'}...")
        self.assertIsNotNone(lyrics2)

    def test_get_songs_by_uploader(self):
        print("\n=== Test Get Songs By Uploader ===")
        # 查找《纯蓝》的UP主
        info = get_song_info(self.db, "纯蓝")
        uploader = info.get("uploader")
        print(f"Uploader of 纯蓝: {uploader}")
        
        if uploader:
            songs = get_songs_by_uploader(self.db, uploader)
            print(f"Songs by {uploader}: {songs[:5]}")
            self.assertIn("纯蓝", songs)

    def test_get_random_songs_by_singer(self):
        print("\n=== Test Get Random Songs By Singer ===")
        singer = "洛天依"
        n = 5
        songs = get_random_songs_by_singer(self.db, singer, n)
        print(f"Random {n} songs by {singer}: {songs}")
        self.assertTrue(len(songs) <= n)
        self.assertTrue(len(songs) > 0)

if __name__ == "__main__":
    unittest.main()
