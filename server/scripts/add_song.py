import sys
import os
import json
import argparse
from sqlalchemy.exc import SQLAlchemyError

# Ensure valid import paths
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.music.song_database import get_song_session, Song, init_song_db


def clean_lyrics(lyrics_text: str) -> str:
    """Remove all whitespace characters from lyrics"""
    if not lyrics_text:
        return ""
    # Remove all whitespace characters (space, tab, newline, return, formfeed)
    # Using split() without arguments splits by any whitespace
    return "".join(lyrics_text.split())

def populate_database(json_dir: str):
    """Read JSON files from json_dir and populate the database"""
    session = get_song_session()
    
    try:
        if not os.path.exists(json_dir):
            print(f"Error: Directory '{json_dir}' does not exist.")
            return

        files = [f for f in os.listdir(json_dir) if f.endswith('.json')]
        print(f"Found {len(files)} JSON files in {json_dir}")
        
        count = 0
        skipped = 0
        existing = 0
        
        for filename in files:
            file_path = os.path.join(json_dir, filename)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Check required fields presence first
                if "summary" not in data or "lyrics" not in data:
                    skipped += 1
                    continue

                # Process Summary
                summary_raw = data.get("summary")
                introduction = ""
                if isinstance(summary_raw, list):
                    introduction = "\n".join([str(s) for s in summary_raw])
                elif isinstance(summary_raw, str):
                    introduction = summary_raw
                
                if not introduction.strip():
                    skipped += 1
                    continue
                    
                # Process Lyrics
                lyrics_raw = data.get("lyrics")
                if not isinstance(lyrics_raw, str):
                    skipped += 1
                    continue
                
                cleaned_lyrics = clean_lyrics(lyrics_raw)
                if not cleaned_lyrics:
                    print(f"Skipping {filename}: lyrics empty after cleaning.")
                    skipped += 1
                    continue

                # Extract other fields
                name = data.get("name") or "Unknown"
                safe_name = os.path.splitext(filename)[0]
                
                # Check if song already exists (by safe_name which should be unique per file)
                if session.query(Song).filter(Song.safe_name == safe_name).first():
                    existing += 1
                    continue

                infobox = data.get("infobox", {})
                uploader = infobox.get("UP主")
                singers_raw = infobox.get("演唱")
                
                singers = ""
                if isinstance(singers_raw, list):
                     singers = ",".join([str(s) for s in singers_raw])
                elif isinstance(singers_raw, str):
                    singers = singers_raw

                # Create record
                song = Song(
                    name=name,
                    safe_name=safe_name,
                    uploader=uploader,
                    singers=singers,
                    introduction=introduction,
                    lyrics=cleaned_lyrics
                )
                session.add(song)
                count += 1
                
                if count % 100 == 0:
                    print(f"Processed {count} new songs...")
                    
            except Exception as e:
                print(f"Error processing {filename}: {e}")
                skipped += 1
        
        session.commit()
        print(f"Database update complete.")
        print(f"Added: {count}")
        print(f"Skipped (missing data): {skipped}")
        print(f"Existing (skipped): {existing}")
        
    except SQLAlchemyError as e:
        print(f"Database error: {e}")
        session.rollback()
    except Exception as e:
        print(f"Critical error: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add songs to knowledge database.")
    parser.add_argument("--dir", type=str, default="res/knowledge/歌曲合集", help="Directory containing song JSON files")
    parser.add_argument("--db_dir", type=str, default="res/knowledge", help="Directory for the database")
    parser.add_argument("--db_name", type=str, default="knowledge_db.db", help="Database filename")
    
    args = parser.parse_args()
    
    # Initialize DB specifically with args
    init_song_db(args.db_dir, args.db_name)
    
    populate_database(args.dir)
