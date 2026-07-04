import asyncio
import copy
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

from src.system.admin.auth import AdminAuthService
from src.system.admin.config_store import ConfigStore
from src.system.admin.config_validator import RuntimeConfigValidator
from src.system.admin.qq_music_credential_refresh import QQMusicCredentialRefreshService
from src.system.admin import qq_music_credential_refresh as qq_refresh_module
from src.system.admin.runtime_supervisor import RuntimeSupervisor
from src.system.admin.secret_store import SecretStore
from src.system.admin.admin_shell import init_admin_shell, shutdown_admin_shell
from src.system.admin.llm_config_editor import apply_llm_config_draft, build_llm_config_view
from src.system.observability import ObservabilityService
from src.system.user_interface.admin_interface import _collect_llm_api_key_names
from src.utils.helpers import apply_env_variables
from src.world.world_runtime import WorldRuntime


def minimal_config(tmp_path: Path) -> dict:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    for file_name in [
        "persona.json",
        "tone.json",
        "song_name_keywords.txt",
        "song_lyric_keywords.txt",
        "knowledge_db.db",
        "lyrics.json",
        "tts.yaml",
        "tts_interface.json",
    ]:
        (tmp_path / file_name).write_text("{}", encoding="utf-8")
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "ref_audio").mkdir()
    (tmp_path / "sing").mkdir()
    return {
        "llm_service": {
            "prompt_manager": {"template_dir": str(prompt_dir)},
            "available_llms": {
                "main": {
                    "api_type": "openai",
                    "model": "test",
                    "api_key": "key",
                    "base_url": "http://example.invalid",
                }
            },
            "available_vlms": {
                "vision": {
                    "api_type": "openai",
                    "model": "vision",
                    "api_key": "key",
                    "base_url": "http://example.invalid",
                }
            },
        },
        "database": {
            "event_store": {"llm_module": {"llm": {"name": "main"}, "prompt_name": "p"}},
            "memory_store": {"llm_module": {"llm": {"name": "main"}, "prompt_name": "p"}},
        },
        "chat_session_manager": {
            "conversation_service": {"llm_module": {"llm": {"name": "main"}, "prompt_name": "p"}}
        },
        "capabilities": {
            "tts": {
                "luotianyi": {
                    "reference_audio_dir": str(tmp_path / "ref_audio"),
                    "reference_audio_lyrics": str(tmp_path / "lyrics.json"),
                    "server_config_path": str(tmp_path / "tts.yaml"),
                    "interface_config_path": str(tmp_path / "tts_interface.json"),
                }
            },
            "sing": {"luotianyi": {"resource_path": str(tmp_path / "sing")}},
            "image_understanding": {"vlm_module": {"vlm": {"name": "vision"}, "prompt_name": "p"}},
        },
        "agent_runtime": {
            "character_registry": {
                "characters": {
                    "luotianyi": {
                        "static_variables_file": str(tmp_path / "persona.json"),
                        "llm_tone_mapping_file": str(tmp_path / "tone.json"),
                    }
                }
            },
            "agent": {
                "preprocessing": {
                    "song_entity_linker": {
                        "songname_file": str(tmp_path / "song_name_keywords.txt"),
                        "lyric_file": str(tmp_path / "song_lyric_keywords.txt"),
                    }
                },
                "memory": {
                    "knowledge_graph": {"graph_data_dir": str(tmp_path / "knowledge")},
                    "memory_writer": {"llm_module": {"llm": {"name": "main"}, "prompt_name": "p"}},
                    "user_profile": {"llm_module": {"llm": {"name": "main"}, "prompt_name": "p"}},
                },
                "topic_extractor": {"llm_module": {"llm": {"name": "main"}, "prompt_name": "p"}},
                "main_chat": {"llm_module": {"llm": {"name": "main"}, "prompt_name": "p"}},
                "date_detector": {"llm_module": {"llm": {"name": "main"}, "prompt_name": "p"}},
                "song_knowledge": {
                    "song_database": {
                        "db_folder": str(tmp_path),
                        "db_file": "knowledge_db.db",
                    }
                },
            },
        },
        "world": {
            "citywalk": {"amap": {"api_key": "$AMAP_KEY"}},
            "bili_dynamic_fetcher": {"bili_cookie_file": str(tmp_path / "missing_cookie.txt")},
            "auto_song_learner": {"qq_credential_file": str(tmp_path / "missing_qq.json")},
        },
    }


def test_admin_auth_requires_setup_token_and_login(tmp_path):
    auth = AdminAuthService(tmp_path / "admin_auth.json", tmp_path / "setup_token.txt")
    assert auth.status()["setup_required"] is True
    token = (tmp_path / "setup_token.txt").read_text(encoding="utf-8").strip()

    auth.setup(token, "password-123")
    assert auth.status()["configured"] is True

    response = SimpleNamespace(set_cookie=lambda *args, **kwargs: None)
    login_result = auth.login("password-123", response)
    assert login_result["ok"] is True
    assert login_result["token"]

    try:
        auth.login("wrong-password", response)
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("bad admin password should fail")


def test_validator_blocks_core_but_only_disables_world(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "jwt")
    monkeypatch.setenv("AMAP_KEY", "amap")
    secret_store = SecretStore(tmp_path / "secrets.local.env")
    validator = RuntimeConfigValidator(root_dir=tmp_path, secret_store=secret_store)
    config = minimal_config(tmp_path)

    result = validator.validate(config)

    assert result["core_ok"] is True
    item_names = {item["name"] for item in result["items"]}
    assert "resource.song names" not in item_names
    assert "resource.lyrics" not in item_names
    assert "resource.song knowledge db" in item_names
    assert "resource.song name keywords" in item_names
    assert "resource.song lyric keywords" in item_names
    disabled_names = {item["name"] for item in result["world_disabled"]}
    assert {"citywalk", "bili_dynamic_fetcher", "auto_song_learner.qq_music"} <= disabled_names

    runtime_config = validator.apply_world_disablements(config, result)
    assert runtime_config["world"]["citywalk"]["enabled"] is False
    assert runtime_config["world"]["bili_dynamic_fetcher"]["enabled"] is False
    assert runtime_config["world"]["auto_song_learner"]["enabled"] is False


def test_validator_uses_custom_llm_api_keys_without_hardcoded_provider_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "jwt")
    monkeypatch.setenv("AMAP_KEY", "amap")
    monkeypatch.setenv("CUSTOM_CHAT_API_KEY", "chat-key")
    monkeypatch.setenv("CUSTOM_VISION_API_KEY", "vision-key")
    for key in ["QWEN_API_KEY", "SILICONFLOW_API_KEY", "DEEPSEEK_API_KEY"]:
        monkeypatch.delenv(key, raising=False)
    secret_store = SecretStore(tmp_path / "secrets.local.env")
    validator = RuntimeConfigValidator(root_dir=tmp_path, secret_store=secret_store)
    config = minimal_config(tmp_path)
    config["llm_service"]["available_llms"]["main"]["api_key"] = "$CUSTOM_CHAT_API_KEY"
    config["llm_service"]["available_vlms"]["vision"]["api_key"] = "$CUSTOM_VISION_API_KEY"

    result = validator.validate(apply_env_variables(copy.deepcopy(config)))

    assert result["core_ok"] is True
    secret_names = {item["name"] for item in result["items"] if item["name"].startswith("secret.")}
    assert secret_names == {"secret.JWT_SECRET", "secret.AMAP_KEY"}
    assert _collect_llm_api_key_names(config) == {"CUSTOM_CHAT_API_KEY", "CUSTOM_VISION_API_KEY"}


def test_supervisor_blocks_start_when_core_validation_fails(tmp_path, monkeypatch):
    for key in ["JWT_SECRET", "AMAP_KEY"]:
        monkeypatch.delenv(key, raising=False)
    config_store = ConfigStore(tmp_path / "config.json", root_dir=tmp_path)
    config_store.write_raw(minimal_config(tmp_path), backup=False)
    secret_store = SecretStore(tmp_path / "secrets.local.env")
    validator = RuntimeConfigValidator(root_dir=tmp_path, secret_store=secret_store)
    observability = ObservabilityService({"db_path": str(tmp_path / "metrics.sqlite3")})
    supervisor = RuntimeSupervisor(
        config_store=config_store,
        secret_store=secret_store,
        validator=validator,
        observability=observability,
    )
    try:
        status = asyncio.run(supervisor.start())
        assert status["state"] == "blocked"
        assert status["validation"]["core_ok"] is False
    finally:
        observability.close()


def test_supervisor_reports_invalid_json_as_validation_error(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"agent": {"bad": true,}', encoding="utf-8")
    config_store = ConfigStore(config_path, root_dir=tmp_path)
    secret_store = SecretStore(tmp_path / "secrets.local.env")
    validator = RuntimeConfigValidator(root_dir=tmp_path, secret_store=secret_store)
    observability = ObservabilityService({"db_path": str(tmp_path / "metrics.sqlite3")})
    supervisor = RuntimeSupervisor(
        config_store=config_store,
        secret_store=secret_store,
        validator=validator,
        observability=observability,
    )
    try:
        validation = supervisor.validate_current_config()
        assert validation["core_ok"] is False
        assert validation["items"][0]["name"] == "config.json"
        assert "不是合法 JSON" in validation["items"][0]["message"]

        status = asyncio.run(supervisor.start())
        assert status["state"] == "blocked"
        assert status["validation"]["items"][0]["name"] == "config.json"
    finally:
        observability.close()


def test_supervisor_reports_busy_transition_states(tmp_path):
    config_store = ConfigStore(tmp_path / "config.json", root_dir=tmp_path)
    secret_store = SecretStore(tmp_path / "secrets.local.env")
    validator = RuntimeConfigValidator(root_dir=tmp_path, secret_store=secret_store)
    observability = ObservabilityService({"db_path": str(tmp_path / "metrics.sqlite3")})
    supervisor = RuntimeSupervisor(
        config_store=config_store,
        secret_store=secret_store,
        validator=validator,
        observability=observability,
    )
    try:
        supervisor.state = "starting"
        assert supervisor.status()["busy"] is True
        supervisor.state = "stopping"
        assert supervisor.status()["busy"] is True
        supervisor.state = "stopped"
        assert supervisor.status()["busy"] is False
    finally:
        observability.close()


def test_world_runtime_skips_disabled_optional_tasks():
    runtime = WorldRuntime(
        {
            "citywalk": {"enabled": False},
            "bili_dynamic_fetcher": {"enabled": False},
            "auto_song_learner": {"enabled": False},
        }
    )
    runtime.system_runtime = SimpleNamespace(
        capability_manager=SimpleNamespace(singing=None),
        llm_service=SimpleNamespace(register_llm_module=lambda *args, **kwargs: object()),
        database_manager=SimpleNamespace(event_store=SimpleNamespace(purge_expired_events=lambda: 0)),
    )

    runtime.initialize_modules()

    task_names = [task.get_task_name() for task in runtime.tasks]
    assert "try_citywalk" not in task_names
    assert "bili_event_update" not in task_names
    assert not any(name.startswith("learn_sing_songs") for name in task_names)


def test_server_main_runtime_dependency_reports_not_ready(tmp_path):
    import server_main

    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    asyncio.run(init_admin_shell(root_dir=tmp_path, config_path="config.json"))
    try:
        try:
            server_main.get_runtime()
        except HTTPException as exc:
            assert exc.status_code == 503
            assert exc.detail["code"] == "SYSTEM_RUNTIME_NOT_READY"
        else:
            raise AssertionError("runtime dependency should reject when runtime is not started")
    finally:
        asyncio.run(shutdown_admin_shell())


def test_admin_success_access_log_filter_keeps_user_and_errors():
    import logging
    from src.utils.logger import AdminSuccessAccessLogFilter

    access_filter = AdminSuccessAccessLogFilter()

    admin_ok = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "GET", "/admin/api/runtime/status", "1.1", 200),
        None,
    )
    admin_error = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "GET", "/admin/api/runtime/status", "1.1", 500),
        None,
    )
    user_ok = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "POST", "/auth/login", "1.1", 200),
        None,
    )

    assert access_filter.filter(admin_ok) is False
    assert access_filter.filter(admin_error) is True
    assert access_filter.filter(user_ok) is True


def test_llm_config_draft_updates_interfaces_and_bindings(tmp_path):
    config = minimal_config(tmp_path)
    view = build_llm_config_view(config)
    assert any(binding["path"] == "agent_runtime.agent.main_chat.llm_module" for binding in view["module_bindings"])

    payload = {
        "available_llms": {
            "main2": {
                "api_type": "openai",
                "model": "next-model",
                "api_key": "$QWEN_API_KEY",
                "base_url": "https://example.invalid/v1",
                "default_params": {"temperature": 0.3},
                "default_params_text": "{\"temperature\": 0.3}",
            }
        },
        "available_vlms": view["available_vlms"],
        "module_bindings": [
            {
                **binding,
                "interface_name": "main2" if binding["path"] == "agent_runtime.agent.main_chat.llm_module" else binding["interface_name"],
                "enable_thinking": binding["path"] in {
                    "agent_runtime.agent.main_chat.llm_module",
                    "capabilities.image_understanding.vlm_module",
                },
                "use_json": binding["path"] in {
                    "agent_runtime.agent.main_chat.llm_module",
                    "capabilities.image_understanding.vlm_module",
                },
                "params": (
                    {"temperature": 0.1}
                    if binding["path"] == "agent_runtime.agent.main_chat.llm_module"
                    else {"max_tokens": 512}
                    if binding["path"] == "capabilities.image_understanding.vlm_module"
                    else binding.get("params", {})
                ),
            }
            for binding in view["module_bindings"]
        ],
    }

    next_config = apply_llm_config_draft(config, payload)

    assert "main2" in next_config["llm_service"]["available_llms"]
    assert "default_params_text" not in next_config["llm_service"]["available_llms"]["main2"]
    main_chat_llm = next_config["agent_runtime"]["agent"]["main_chat"]["llm_module"]["llm"]
    assert main_chat_llm["name"] == "main2"
    assert main_chat_llm["enable_thinking"] is True
    assert main_chat_llm["use_json"] is True
    assert main_chat_llm["params"] == {"temperature": 0.1}
    image_vlm_module = next_config["capabilities"]["image_understanding"]["vlm_module"]
    assert image_vlm_module["enable_thinking"] is True
    assert image_vlm_module["use_json"] is True
    assert image_vlm_module["params"] == {"max_tokens": 512}


def test_validator_accepts_legacy_qq_music_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "jwt")
    monkeypatch.setenv("AMAP_KEY", "amap")
    legacy_dir = tmp_path / "res" / "song_learner"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / ".qq_music_credential.json").write_text("{}", encoding="utf-8")
    secret_store = SecretStore(tmp_path / "secrets.local.env")
    validator = RuntimeConfigValidator(root_dir=tmp_path, secret_store=secret_store)
    config = minimal_config(tmp_path)
    config["world"]["auto_song_learner"] = {
        "qq_credential_file": str(tmp_path / "config" / "qq_music_credential.json"),
        "songlearner_resource_dir": str(legacy_dir),
    }

    result = validator.validate(config)

    qq_item = next(item for item in result["items"] if item["name"] == "auto_song_learner.qq_music")
    assert qq_item["status"] == "ok"
    assert "旧路径" in qq_item["message"]


def test_qq_music_credential_refresh_runs_in_background(tmp_path, monkeypatch):
    config_store = ConfigStore(tmp_path / "config.json", root_dir=tmp_path)
    config_store.write_raw(
        {
            "world": {
                "auto_song_learner": {
                    "qq_credential_file": "config/qq_music_credential.json",
                    "songlearner_resource_dir": "res/song_learner",
                }
            }
        },
        backup=False,
    )
    credential_file = tmp_path / "config" / "qq_music_credential.json"
    legacy_file = tmp_path / "res" / "song_learner" / ".qq_music_credential.json"

    def fake_login(*, credential_file: Path, login_timeout: int, force_login: bool):
        assert login_timeout == 30
        assert force_login is True
        credential_file.parent.mkdir(parents=True, exist_ok=True)
        credential_file.write_text('{"musicid": 123}', encoding="utf-8")
        (credential_file.parent / "qq_login_qr.png").write_bytes(b"png")

    monkeypatch.setattr(qq_refresh_module.download_qq_song, "QQ_SDK_AVAILABLE", True)
    monkeypatch.setattr(qq_refresh_module.download_qq_song, "ensure_qr_login", fake_login)
    monkeypatch.setattr(qq_refresh_module.download_qq_song, "load_saved_credential", lambda path: {"musicid": 123})
    monkeypatch.setattr(qq_refresh_module.download_qq_song, "validate_credential", lambda credential: True)

    learner = SimpleNamespace(_credential_file=credential_file, qq_credential_valid=False)
    runtime = SimpleNamespace(
        world=SimpleNamespace(
            learn_sing_songs_tasks=[
                SimpleNamespace(auto_song_learner=learner),
            ],
        )
    )
    service = QQMusicCredentialRefreshService(
        root_dir=tmp_path,
        config_store=config_store,
        runtime_getter=lambda: runtime,
    )

    start_status = service.start(timeout_seconds=30)
    assert start_status["running"] is True

    for _ in range(50):
        status = service.status()
        if not status["running"]:
            break
        time.sleep(0.02)
    else:
        raise AssertionError("QQ music credential refresh did not finish")

    status = service.status()
    assert status["state"] == "success"
    assert status["success"] is True
    assert credential_file.exists()
    assert legacy_file.exists()
    assert learner.qq_credential_valid is True
