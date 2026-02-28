from sqlalchemy.orm import Session
from sqlalchemy import func
from .song_database import Song
from typing import List, Optional, Dict
import random
import re

def get_song_introduction(db: Session, song_name: str) -> Optional[str]:
    """
    根据歌名查询歌曲介绍 (Summary)
    必须完全匹配歌名或安全歌名，模糊匹配可能会返回错误的介绍
    """
    song = db.query(Song).filter(
        (Song.name == song_name) | 
        (Song.safe_name == song_name) |
        (Song.name.ilike(f"{song_name}"))
    ).first()
    
    if song:
        return song.introduction
    return None

def get_song_lyrics(db: Session, song_name: str) -> Optional[str]:
    """
    根据歌名查询歌词
    必须完全匹配歌名，模糊匹配可能会返回错误的歌词
    """
    song = db.query(Song).filter(
        (Song.name == song_name) | 
        (Song.safe_name == song_name) |
        (Song.name.ilike(f"{song_name}"))
    ).first()
    
    if song:
        return song.lyrics
    return None

def get_songs_by_uploader(db: Session, uploader_name: str) -> List[str]:
    """
    给定人名查询创作者（UP主）创作的歌曲
    """
    songs = db.query(Song).filter(
        Song.uploader.ilike(f"{uploader_name}")
    ).all()
    
    return [song.name for song in songs]

def get_random_songs_by_singer(db: Session, singer_name: str, n: int = 1) -> List[str]:
    """
    给定歌手名，随机返回n个这个歌手唱的歌
    """
    # 查找包含该歌手的歌曲
    # singers字段可能包含多个歌手，逗号分隔，或者是单个
    # 使用 ilike 进行模糊匹配
    songs = db.query(Song).filter(
        Song.singers.ilike(f"{singer_name}")
    ).all()
    
    if not songs:
        return []
    
    # 随机选择 n 个
    if len(songs) <= n:
        selected_songs = songs
    else:
        selected_songs = random.sample(songs, n)
        
    return [song.name for song in selected_songs]

def get_song_info(db: Session, song_name: str) -> Dict[str, str]:
    """
    获取歌曲完整信息辅助函数
    """
    song = db.query(Song).filter(
        (Song.name == song_name) | 
        (Song.safe_name == song_name) |
        (Song.name.ilike(f"{song_name}"))
    ).first()
    
    if song:
        return {
            "name": song.name,
            "uploader": song.uploader,
            "singers": song.singers,
            "introduction": song.introduction,
            "lyrics": song.lyrics
        }
    return {}

def search_songs_by_lyrics(db: Session, lyrics_snippet: str) -> List[str]:
    """
    根据歌词片段搜索歌曲
    """
    # 压缩歌词中的空白字符和emoji等非文本内容，进行模糊匹配
    
    songs = db.query(Song).filter(
        Song.lyrics.ilike(f"%{lyrics_snippet}%")
    ).all()
    
    return [song.name for song in songs]