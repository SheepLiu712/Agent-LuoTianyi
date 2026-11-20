import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from src.agent.skills.cognitive.song_entity_linker import SongEntityLinker

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


def test_song_import_and_keyword_tools_update_the_selected_instance(tmp_path, monkeypatch):
    data_dir = tmp_path / "instance"
    monkeypatch.setenv("AGENTLUO_DATA_DIR", str(data_dir))
    knowledge = data_dir / "knowledge"
    corpus = knowledge / "歌曲合集"
    corpus.mkdir(parents=True)
    song, lyric = "测试歌曲", "这是一句用于识别歌曲的歌词"
    (corpus / f"{song}.json").write_text(
        json.dumps({"name": song, "lyrics": lyric, "summary": "测试简介"}), encoding="utf-8"
    )

    for script in (
        "add_song.py",
        "music/build_song_keywords.py",
        "music/clean_short_lyric_keywords.py",
        "rewrite_lyric_keyword_values.py",
    ):
        subprocess.run([sys.executable, str(SCRIPTS / script)], cwd=tmp_path, check=True)

    with sqlite3.connect((knowledge / "knowledge_db.db").as_uri() + "?mode=ro", uri=True) as conn:
        assert conn.execute("SELECT name FROM songs").fetchall() == [(song,)]
    linker = SongEntityLinker({})
    assert linker.extract_and_verify(lyric) == [f"{lyric}是《{song}》的歌词"]
