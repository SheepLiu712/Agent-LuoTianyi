import sys
import os
import unittest

# Ensure valid import paths
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.plugins.music.song_database import init_song_db, get_song_session, Song
from src.plugins.music.knowledge_service import (
    get_song_introduction, 
    get_song_lyrics, 
    get_songs_by_uploader, 
    get_random_songs_by_singer,
    get_song_info
)

class TestKnowledgeService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 使用内存数据库，隔离测试数据
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.plugins.music.song_database import Base, Song

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        cls.db = session_factory()

        # 种子测试数据
        test_songs = [
            Song(
                name="纯蓝", safe_name="chun_lan",
                uploader="H.K.君", singers="洛天依",
                introduction="《纯蓝》是Vsinger（洛天依）演唱的歌曲，由H.K.君创作。",
                lyrics="也许某天 你终想起我 纯蓝的 回忆中 那片天空"
            ),
            Song(
                name="光与影的对白", safe_name="guang_yu_ying_de_dui_bai",
                uploader="OQQ", singers="洛天依",
                introduction="《光与影的对白》是洛天依演唱的歌曲。",
                lyrics="光与影的对白 诉说着我们的存在"
            ),
        ]
        for song in test_songs:
            cls.db.add(song)
        cls.db.commit()

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
