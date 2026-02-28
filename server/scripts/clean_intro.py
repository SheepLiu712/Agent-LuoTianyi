import sys
import os

# Ensure valid import paths
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.music.song_database import get_song_session, Song

def clean_text(text: str) -> str:
    """Remove all whitespace characters"""
    if not text:
        return ""
    return "".join(text.split())

def clean_database_introductions():
    session = get_song_session()
    try:
        print("Fetching all songs...")
        songs = session.query(Song).all()
        print(f"Found {len(songs)} songs. Starting cleanup...")
        
        count = 0
        modified_count = 0
        
        for song in songs:
            count += 1
            if song.introduction:
                original_len = len(song.introduction)
                cleaned = clean_text(song.introduction)
                # Only update if changed
                if cleaned != song.introduction:
                    song.introduction = cleaned
                    modified_count += 1
            
            if count % 500 == 0:
                print(f"Checked {count} songs...")
                    
        session.commit()
        print(f"Successfully cleaned introductions for {modified_count} songs out of {count}.")
        
    except Exception as e:
        session.rollback()
        print(f"Error: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    clean_database_introductions()
