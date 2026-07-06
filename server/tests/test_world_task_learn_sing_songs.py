import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.world.learn_sing_songs.task import LearnSingSongsTask
from src.world.learn_sing_songs.auto_song_learner import AutoSongLearner, WishlistManager
from src.world.learn_sing_songs.song_learner.src.pipeline import download_qq_song
from src.world.learn_sing_songs.song_learner.src.pipeline.download_qq_song import (
    rank_songs_by_title,
    safe_name as qq_safe_name,
)


class FakeEventStore:
    def __init__(self):
        self.events = []

    async def add_event(self, event):
        self.events.append(event)
        return "event-id"


def test_learn_sing_songs_initialize_sets_event_store_and_learner(monkeypatch):
    task = LearnSingSongsTask({})
    learner = object()
    monkeypatch.setattr(task, "_build_auto_song_learner", lambda: learner)
    event_store = object()
    character_runtime = object()
    runtime = SimpleNamespace(
        database_manager=SimpleNamespace(event_store=event_store),
        agent_runtime=SimpleNamespace(get_character_runtime=lambda character_id: character_runtime),
    )

    task.initialize(runtime)

    assert task.system_runtime is runtime
    assert task.event_store is event_store
    assert task.character_runtime is character_runtime
    assert task.auto_song_learner is learner


def test_learn_sing_songs_build_learner_skips_without_wishlist():
    task = LearnSingSongsTask(
        {},
        singing_manager=SimpleNamespace(resource_path="music"),
    )

    learner = task._build_auto_song_learner()

    assert learner is None
    assert "wishlist" in task._init_error


def test_learn_sing_songs_build_learner_uses_manager_resource_path(monkeypatch, tmp_path):
    monkeypatch.setattr(AutoSongLearner, "_check_songlearner_models", lambda self: True)
    monkeypatch.setattr(AutoSongLearner, "_validate_qq_credential", lambda self: True)
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)

    wishlist = WishlistManager(
        str(tmp_path / "metadata.json"),
        SimpleNamespace(info=lambda *_: None, warning=lambda *_: None),
    )
    manager = SimpleNamespace(
        wishlist=wishlist,
        resource_path=tmp_path / "character_music",
        character_name="初音未来",
    )
    task = LearnSingSongsTask(
        {"songlearner_resource_dir": str(tmp_path / "song_learner_res")},
        singing_manager=manager,
    )

    learner = task._build_auto_song_learner()

    assert learner is not None
    assert learner.resource_path == tmp_path / "character_music"
    assert learner.character_name == "初音未来"


def test_learn_sing_songs_run_once_skips_without_learner():
    task = LearnSingSongsTask({})
    task._init_error = "missing learner"

    result = task.run_once()

    assert result.ok is True
    assert result.skipped is True
    assert result.message == "missing learner"


def test_learn_sing_songs_run_once_records_result_without_learned():
    learner = SimpleNamespace(
        check_qq_credential=lambda: True,
        try_learn_pending=lambda: SimpleNamespace(learned=[], abandoned=["A"], awaiting=["B"]),
    )
    task = LearnSingSongsTask({})
    task.auto_song_learner = learner

    result = task.run_once()

    assert result.ok is True
    assert result.data["credential_ok"] is True
    assert result.data["learned"] == []
    assert result.data["abandoned"] == ["A"]
    assert result.data["awaiting"] == ["B"]


def test_learn_sing_songs_run_once_writes_event_for_learned_songs():
    learner = SimpleNamespace(
        check_qq_credential=lambda: False,
        try_learn_pending=lambda: SimpleNamespace(learned=["Song A", "Song B"], abandoned=[], awaiting=[]),
    )
    event_store = FakeEventStore()
    task = LearnSingSongsTask({})
    task.auto_song_learner = learner
    task.event_store = event_store

    result = task.run_once()

    assert result.ok is True
    assert result.data["credential_ok"] is False
    assert event_store.events
    event = event_store.events[0]
    assert event["character"] == "luotianyi"
    assert event["event_type"] == "new_song"
    assert event["source"] == "world_song_learner"
    assert "Song A" in event["description"]


def test_learn_sing_songs_run_once_reloads_singing_library_for_learned_songs():
    learner = SimpleNamespace(
        check_qq_credential=lambda: True,
        try_learn_pending=lambda: SimpleNamespace(learned=["Song A"], abandoned=[], awaiting=[]),
    )
    calls = []
    singing = SimpleNamespace(reload_songs=lambda character_id: calls.append(character_id))
    task = LearnSingSongsTask({}, character_id="luotianyi")
    task.auto_song_learner = learner
    task.system_runtime = SimpleNamespace(capability_manager=SimpleNamespace(singing=singing))

    result = task.run_once()

    assert result.ok is True
    assert calls == ["luotianyi"]


def test_learn_sing_songs_passes_full_lyrics_to_dynamic_capability():
    learner = SimpleNamespace(
        check_qq_credential=lambda: True,
        try_learn_pending=lambda: SimpleNamespace(learned=["Song A"], abandoned=[], awaiting=[]),
    )
    captured = {}

    class FakeCharacterRuntime:
        async def publish_learned_song_dynamic(self, **kwargs):
            captured.update(kwargs)
            return {"dynamic_id": "dynamic-song-a", "content": "learned song dynamic"}

    manager = SimpleNamespace(
        character_name="洛天依",
        can_i_sing_song=lambda song_name: ("Song A", ["主歌", "副歌"]),
        get_full_lyrics=lambda song_name: "第一句歌词\n第二句歌词\n副歌歌词",
    )
    task = LearnSingSongsTask({}, character_id="luotianyi", singing_manager=manager)
    task.auto_song_learner = learner
    task.character_runtime = FakeCharacterRuntime()
    task.system_runtime = SimpleNamespace(capability_manager=SimpleNamespace(singing=SimpleNamespace(reload_songs=lambda *_: None)))

    result = task.run_once()

    assert result.ok is True
    assert result.data["dynamic_ids"] == ["dynamic-song-a"]
    assert captured["song_name"] == "Song A"
    assert captured["segment_description"] == "主歌"
    assert captured["lyrics"] == "第一句歌词\n第二句歌词\n副歌歌词"


def test_learn_sing_songs_write_learned_event_skips_without_store():
    task = LearnSingSongsTask({})

    import asyncio

    asyncio.run(task._write_learned_event(["Song A"]))


def test_auto_song_learner_builds_child_pythonpath(monkeypatch, tmp_path):
    monkeypatch.setattr(AutoSongLearner, "_check_songlearner_models", lambda self: True)
    monkeypatch.setattr(AutoSongLearner, "_validate_qq_credential", lambda self: True)
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)

    wishlist = WishlistManager(str(tmp_path / "metadata.json"), SimpleNamespace(info=lambda *_: None, warning=lambda *_: None))
    learner = AutoSongLearner(
        {
            "songlearner_resource_dir": str(tmp_path / "song_learner_res"),
        },
        "洛天依",
        wishlist,
        resource_path=tmp_path / "music",
    )

    env = learner._build_songlearner_env()
    pythonpath_parts = env["PYTHONPATH"].split(os.pathsep)

    assert learner.resource_path == tmp_path / "music"
    assert str(Path(__file__).resolve().parent.parent) in pythonpath_parts
    assert str(learner.songlearner_dir / "src") in pythonpath_parts
    assert pythonpath_parts[:2] == [
        str(learner.songlearner_dir / "src"),
        str(Path(__file__).resolve().parent.parent),
    ]
    assert env["TEST_SONGS_DIR"] == str(learner.songs_dir)
    assert env["SONGLEARNER_RESOURCE_DIR"] == str(learner.songlearner_resource_dir)


def test_auto_song_learner_formats_structured_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(AutoSongLearner, "_check_songlearner_models", lambda self: True)
    monkeypatch.setattr(AutoSongLearner, "_validate_qq_credential", lambda self: True)
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)

    wishlist = WishlistManager(str(tmp_path / "metadata.json"), SimpleNamespace(info=lambda *_: None, warning=lambda *_: None))
    learner = AutoSongLearner(
        {
            "songlearner_resource_dir": str(tmp_path / "song_learner_res"),
        },
        "洛天依",
        wishlist,
        resource_path=tmp_path / "music",
    )
    proc = subprocess.CompletedProcess(
        args=[],
        returncode=40,
        stderr="[SONGLEARNER_ERROR] code=SL040 exit_code=40 step=clean_audio message=清洗后音频不存在\n",
    )

    assert learner._format_songlearner_failure(proc) == "SL040 clean_audio: 清洗后音频不存在 (exit_code=40)"


def test_auto_song_learner_passes_singer_name_to_workflow(monkeypatch, tmp_path):
    monkeypatch.setattr(AutoSongLearner, "_check_songlearner_models", lambda self: True)
    monkeypatch.setattr(AutoSongLearner, "_validate_qq_credential", lambda self: True)
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)

    wishlist = WishlistManager(str(tmp_path / "metadata.json"), SimpleNamespace(info=lambda *_: None, warning=lambda *_: None))
    wishlist.add("Song A")
    learner = AutoSongLearner(
        {
            "songlearner_dir": str(tmp_path / "song_learner"),
            "songlearner_resource_dir": str(tmp_path / "song_learner_res"),
            "qq_credential_file": str(tmp_path / "config" / "qq_music_credential.json"),
        },
        "初音未来",
        wishlist,
        resource_path=tmp_path / "music",
    )
    runner = learner.songlearner_dir / "run_song_workflow.py"
    runner.parent.mkdir(parents=True)
    runner.write_text("print('ok')", encoding="utf-8")
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sl_output = learner.songs_dir / "Song A"
    sl_output.mkdir(parents=True)
    (sl_output / "Song A.mp3").write_bytes(b"mp3")
    (sl_output / "Song A.lrc").write_text("[00:00.00]x", encoding="utf-8")
    (sl_output / "Song A.json").write_text('{"title": "Song A"}', encoding="utf-8")

    assert learner._learn_via_songlearner("Song A") == "Song A"
    assert "--singer_name" in captured["args"]
    assert captured["args"][captured["args"].index("--singer_name") + 1] == "初音未来"
    assert "--credential_file" in captured["args"]
    assert captured["args"][captured["args"].index("--credential_file") + 1] == str(learner._credential_file)
    assert "--no_auto_login" in captured["args"]
    assert captured["kwargs"]["env"]["SONGLEARNER_QQ_CREDENTIAL_FILE"] == str(learner._credential_file)
    metadata = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert "songa" not in metadata["wished_songs"]
    assert "songa" in metadata["recently_learned"]


def test_auto_song_learner_records_redirected_wish_and_learned_target(monkeypatch, tmp_path):
    monkeypatch.setattr(AutoSongLearner, "_check_songlearner_models", lambda self: True)
    monkeypatch.setattr(AutoSongLearner, "_validate_qq_credential", lambda self: True)
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)

    wishlist = WishlistManager(str(tmp_path / "metadata.json"), SimpleNamespace(info=lambda *_: None, warning=lambda *_: None))
    wishlist.add("海")
    learner = AutoSongLearner(
        {
            "songlearner_dir": str(tmp_path / "song_learner"),
            "songlearner_resource_dir": str(tmp_path / "song_learner_res"),
            "qq_credential_file": str(tmp_path / "config" / "qq_music_credential.json"),
        },
        "洛天依",
        wishlist,
        resource_path=tmp_path / "music",
    )
    runner = learner.songlearner_dir / "run_song_workflow.py"
    runner.parent.mkdir(parents=True)
    runner.write_text("print('ok')", encoding="utf-8")

    redirected_name = "想和你迎着台风去看海"

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                "[REDIRECT] requested_song_name=海 actual_song_name=想和你迎着台风去看海\n"
                "[RESULT] song_name: 想和你迎着台风去看海\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    sl_output = learner.songs_dir / redirected_name
    sl_output.mkdir(parents=True)
    (sl_output / f"{redirected_name}.mp3").write_bytes(b"mp3")
    (sl_output / f"{redirected_name}.lrc").write_text("[00:00.00]x", encoding="utf-8")
    (sl_output / f"{redirected_name}.json").write_text(
        json.dumps({"title": redirected_name}, ensure_ascii=False),
        encoding="utf-8",
    )

    assert learner._learn_via_songlearner("海") == redirected_name

    metadata = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    original = metadata["wished_songs"]["海"]
    assert original["status"] == "redirected"
    assert original["redirected_to"] == redirected_name
    assert original["redirected_unified_name"] == redirected_name
    assert original["redirected_status"] == "learned"
    assert redirected_name in metadata["recently_learned"]
    assert (learner.songs_dir / redirected_name).exists()
    assert not (learner.songs_dir / "海").exists()


def test_run_song_workflow_maps_credential_error(monkeypatch, tmp_path):
    from src.world.learn_sing_songs.song_learner import run_song_workflow

    def fail_download(**_kwargs):
        raise run_song_workflow.download_qq_song.QQMusicCredentialError("credential expired")

    monkeypatch.setattr(run_song_workflow, "download_song_and_lyric", fail_download)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_song_workflow.py",
            "Song A",
            "--output_dir",
            str(tmp_path / "songs"),
            "--resource_root",
            str(tmp_path / "resource"),
            "--credential_file",
            str(tmp_path / "config" / "qq_music_credential.json"),
            "--no_auto_login",
        ],
    )

    try:
        run_song_workflow.main()
    except run_song_workflow.SongWorkflowError as exc:
        assert exc.exit_code == 21
        assert exc.error_code == "SL021"
        assert exc.step == "qq_credential"
        assert "credential expired" in str(exc)
    else:
        raise AssertionError("Expected credential error to be mapped to SL021")


def test_wishlist_sync_existing_songs_removes_wished_song(tmp_path):
    logger = SimpleNamespace(info=lambda *_: None, warning=lambda *_: None)
    wishlist = WishlistManager(str(tmp_path / "metadata.json"), logger)
    wishlist.add("HelloByeDays")

    wishlist.sync_existing_songs({"HelloByeDays"})

    metadata = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert "hellobyedays" not in metadata["wished_songs"]
    assert "hellobyedays" in metadata["recently_learned"]


def test_wishlist_load_prunes_legacy_learned_entries(tmp_path):
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "wished_songs": {
                    "oldlearned": {
                        "safe_name": "Old Learned",
                        "unified_name": "oldlearned",
                        "status": "learned",
                    },
                    "stillpending": {
                        "safe_name": "Still Pending",
                        "unified_name": "stillpending",
                        "status": "pending",
                    },
                },
                "recently_learned": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    logger = SimpleNamespace(info=lambda *_: None, warning=lambda *_: None)

    wishlist = WishlistManager(str(metadata_path), logger)

    assert "oldlearned" not in wishlist.wished_songs
    assert "stillpending" in wishlist.wished_songs
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert "oldlearned" not in metadata["wished_songs"]
    assert "oldlearned" in metadata["recently_learned"]


def test_songlearner_safe_name_strips_trailing_spaces():
    assert qq_safe_name("虚拟歌舞《戏游九州》 ") == "虚拟歌舞《戏游九州》"


def test_songlearner_title_ranking_prefers_exact_but_allows_redirect():
    songs = [
        {"title": "虚拟歌舞《戏游九州》"},
        {"title": "恋爱色魔法"},
    ]
    ranked = rank_songs_by_title(songs, "恋爱色魔法")

    assert ranked[0]["title"] == "恋爱色魔法"
    assert qq_safe_name("想和你迎着台风去看海（Live版）") == "想和你迎着台风去看海"


def test_songlearner_allows_redirect_candidates_after_matching_download_failure(monkeypatch, tmp_path):
    songs = [
        {"title": "下等马", "mid": "bad-mid", "singer": [{"name": "洛天依"}]},
        {"title": "告死鸟", "mid": "target-mid", "singer": [{"name": "洛天依"}]},
    ]
    monkeypatch.setattr(download_qq_song, "qq_search_songs", lambda *_args, **_kwargs: songs)
    monkeypatch.setattr(download_qq_song, "qq_fetch_mp3_url", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(download_qq_song, "load_saved_credential", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(download_qq_song, "ensure_qr_login", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(download_qq_song, "qq_fetch_mp3_url_by_sdk", lambda *_args, **_kwargs: "")

    try:
        download_qq_song.download_song_and_lyric(
            "告死鸟",
            output_dir=tmp_path,
            credential_file=tmp_path / "credential.json",
        )
    except RuntimeError as exc:
        message = str(exc)
        assert "匹配到 告死鸟" in message
        assert "告死鸟: 登录后仍未获取到可下载链接" in message
        assert "下等马: 登录后仍未获取到可下载链接" in message
        assert "最佳标题与请求不匹配" not in message
    else:
        raise AssertionError("Expected matching candidate download failure")


def test_download_song_and_lyric_uses_qq_redirected_title(monkeypatch, tmp_path):
    songs = [
        {"title": "想和你迎着台风去看海（Live版）", "mid": "target-mid", "singer": [{"name": "洛天依"}]},
    ]
    monkeypatch.setattr(download_qq_song, "qq_search_songs", lambda *_args, **_kwargs: songs)
    monkeypatch.setattr(download_qq_song, "qq_fetch_mp3_url", lambda *_args, **_kwargs: "https://example.test/song.mp3")
    monkeypatch.setattr(download_qq_song, "load_saved_credential", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(download_qq_song, "qq_fetch_lyric", lambda *_args, **_kwargs: "[00:00.00]海风")

    def fake_download(url, target, **_kwargs):
        target.write_bytes(b"mp3")

    monkeypatch.setattr(download_qq_song, "download_song_file", fake_download)

    safe_song_name, mp3_path, lrc_path = download_qq_song.download_song_and_lyric(
        "海",
        output_dir=tmp_path,
        credential_file=tmp_path / "credential.json",
    )

    assert safe_song_name == "想和你迎着台风去看海"
    assert mp3_path == tmp_path / "想和你迎着台风去看海" / "想和你迎着台风去看海.mp3"
    assert lrc_path == tmp_path / "想和你迎着台风去看海" / "想和你迎着台风去看海.lrc"
    assert not (tmp_path / "海").exists()
