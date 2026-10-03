"""Offline CLI and async-module contracts for the prompt experiment tool."""

from __future__ import annotations

import copy
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
import requests

from scripts import vcpedia_prompt_lab as lab
from src.world.get_new_songs.source_extraction import collect_materials, material_text, merge_missing
from src.world.get_new_songs.wikitext_parser import parse_details

EMPTY_NEEDED = {"infobox": [], "summary": False, "lyrics": False}
SECRET = "sk-private-test-credential"


def forbidden(*args, **kwargs):
    raise AssertionError("Unexpected credential/network/model access")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def config():
    return {
        "world": {
            "song_knowledge": {
                "crawler": {
                    "extraction_llm_module": {
                        "prompt_name": "production",
                        "llm": {
                            "name": "extractor",
                            "use_json": True,
                            "enable_thinking": False,
                            "params": {"temperature": 0.25},
                        },
                    },
                    "llm_module": {"llm": {"name": "summary-only"}},
                }
            }
        },
        "llm_service": {
            "available_llms": {
                "extractor": {
                    "api_type": "openai",
                    "api_key": SECRET,
                    "base_url": "https://invalid.example",
                    "model": "configured-model",
                },
                "experiment": {
                    "api_type": "openai",
                    "api_key": "other-private-credential",
                    "base_url": "https://invalid.example",
                    "model": "other",
                },
            }
        },
    }


class FakeModule:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []
        self.recent_response = {"usage": {"prompt_tokens": 3, "total_tokens": 5, "unexpected": SECRET}}

    async def generate_response(self, **variables):
        self.calls.append(copy.deepcopy(variables))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def fake_live(monkeypatch, answers):
    modules, directories = [], []
    monkeypatch.setattr(lab, "load_live_config", lambda artifacts, provider_override=None: config())

    def create(settings, directory, name):
        assert (directory / "experiment.json").is_file()
        module = FakeModule(answers[len(modules)])
        modules.append(module)
        directories.append(directory)
        return module

    monkeypatch.setattr(lab, "create_module", create)
    return modules, directories


def report(out):
    return json.loads((out / "report.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("flags", [[], ["--dry-run"]])
def test_default_and_dry_run_are_offline_with_production_material(monkeypatch, tmp_path, flags):
    monkeypatch.setattr(lab, "load_live_config", forbidden)
    monkeypatch.setattr(lab, "create_module", forbidden)
    out = tmp_path / "output"
    assert lab.main([*flags, "--out", str(out)]) == 0
    result = report(out)
    source, title = lab.load_material("title:Foxy")
    data, needed = parse_details(source, title, with_missing=True)
    expected = collect_materials(data, needed, source, "https://vcpedia.cn", title, merge_fragments=False)
    assert result["materials"] == expected == {"text": material_text(source)}
    assert "raw" not in result["materials"]
    assert result["mode"] == "offline"
    assert result["fragment_post_attempts"] == 0
    assert result["full_production_coverage"] is False
    assert result["runs"]["A"]["model_call_attempted"] is False
    assert not (out / "response-A.txt").exists()


def test_help_exits_before_importing_services_or_creating_outputs(tmp_path):
    result = subprocess.run(
        [sys.executable, "-B", str(Path(lab.__file__)), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
        check=False,
    )
    assert result.returncode == 0
    assert "--live" in result.stdout and "默认离线" in result.stdout
    assert not list(tmp_path.iterdir())
    assert not result.stderr


@pytest.mark.parametrize("flags", [["--live", "--dry-run"], ["--provider", "extractor"]])
def test_conflicting_network_options_fail_without_artifacts(tmp_path, flags):
    with pytest.raises(SystemExit) as error:
        lab.main([*flags, "--out", str(tmp_path / "unused")])
    assert error.value.code == 2
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("spec", ["yishen", "lyrics:疑神疑鬼", "title:疑神疑鬼"])
def test_legacy_alias_requires_real_corpus_mapping(spec):
    assert lab.load_material(spec) == lab.load_material("title:疑神疑鬼")


@pytest.mark.parametrize("spec", ["lyrics:no-such-title", "fixed:0", "consecutive:1", "title:no-such-title"])
def test_missing_old_material_fails_explicitly(spec):
    with pytest.raises(lab.LabError):
        lab.load_material(spec)


def test_file_material_and_title_override(tmp_path):
    source = tmp_path / "local.wikitext"
    source.write_text("本地素材", encoding="utf-8")
    assert lab.load_material(f"file:{source}", "实验标题") == ("本地素材", "实验标题")


def test_drop_infobox_preserves_original_keys_and_requested_keys():
    data = {"infobox": {"演唱": "甲", "UP主": "乙"}}
    needed = {**EMPTY_NEEDED, "infobox": ["作曲"]}
    lab.apply_drop(data, needed, "infobox")
    assert data["infobox"] == {}
    assert needed["infobox"] == ["作曲", "演唱", "UP主"]
    with pytest.raises(lab.LabError, match="infobox"):
        lab.apply_drop(data, needed, "infobox")
    lab.apply_drop(data, needed, "infobox:调教")
    assert needed["infobox"][-1] == "调教"


@pytest.mark.parametrize("needed", [[], {}, {**EMPTY_NEEDED, "lyrics": 1}, {**EMPTY_NEEDED, "infobox": "演唱"}])
def test_invalid_needed_retains_error_report_and_nonzero(tmp_path, needed):
    out = tmp_path / "output"
    assert lab.main(["--needed", json.dumps(needed), "--out", str(out)]) == 1
    assert report(out)["error_type"] == "LabError"


def test_no_needed_live_never_loads_config_or_model(monkeypatch, tmp_path):
    monkeypatch.setattr(lab, "load_live_config", forbidden)
    monkeypatch.setattr(lab, "create_module", forbidden)
    assert lab.main(["--live", "--needed", json.dumps(EMPTY_NEEDED), "--out", str(tmp_path)]) == 0
    result = report(tmp_path)
    assert result["materials"] == {}
    assert result["runs"]["A"]["reason"] == "no_needed"
    assert not result["runs"]["A"]["model_call_attempted"]


def test_module_variables_match_production_text_and_real_prompt_rendering(monkeypatch, tmp_path):
    modules, directories = fake_live(monkeypatch, ['{"lyrics":"補提（和声）\\n\\n终句"}'])
    source = tmp_path / "sample.wikitext"
    source.write_text(
        "{{VOCALOID Songbox|演唱=洛天依}}\n已有{{bilibiliCount|1}}播放。結尾。\n" "== 歌词 ==\n{{embed|test}}",
        encoding="utf-8",
    )
    prompt = tmp_path / "prompt.json"
    prompt.write_text(
        json.dumps({"name": "arbitrary/name", "template": "{{ song_data }}|{{ needed }}|{{ materials }}"}),
        encoding="utf-8",
    )
    out = tmp_path / "output"
    assert (
        lab.main(
            ["--live", "--material", f"file:{source}", "--drop", "lyrics", "--prompt", str(prompt), "--out", str(out)]
        )
        == 0
    )
    variables = modules[0].calls[0]
    assert json.loads(variables["materials"]) == {"text": material_text(source.read_text(encoding="utf-8"))}
    assert "bilibiliCount" not in variables["materials"]
    assert (out / "prompt-A.txt").read_text(encoding="utf-8") == "|".join(variables.values())
    assert report(out)["runs"]["A"]["declared"] == ["materials", "needed", "song_data"]
    assert not any(directory.exists() for directory in directories)


def test_ab_isolation_and_production_merge_even_for_partial_existing_values(monkeypatch, tmp_path):
    answers = [{"lyrics": "replacement A", "summary": ["must not change"]}, {"lyrics": "replacement B"}]
    modules, directories = fake_live(monkeypatch, [json.dumps(answer) for answer in answers])
    needed = {**EMPTY_NEEDED, "lyrics": True}
    assert (
        lab.main(
            [
                "--live",
                "--material",
                "title:疑神疑鬼",
                "--needed",
                json.dumps(needed),
                "--prompt-b",
                str(lab.DEFAULT_PROMPT),
                "--out",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert modules[0].calls == modules[1].calls
    baseline = json.loads(modules[0].calls[0]["song_data"])
    assert baseline["lyrics"]
    result = report(tmp_path)
    for label, answer in zip(("A", "B"), answers):
        expected, remaining = copy.deepcopy(baseline), copy.deepcopy(needed)
        merge_missing(expected, answer, remaining)
        assert json.loads((tmp_path / f"merged-{label}.json").read_text(encoding="utf-8")) == expected
        assert result["runs"][label]["needed_before"] == needed
        assert result["runs"][label]["needed_after"] == remaining
    assert not any(directory.exists() for directory in directories)


@pytest.mark.parametrize(
    "answer,error_type",
    [
        ("{malformed", "JSONDecodeError"),
        ("[]", "ValueError"),
        ("null", "ValueError"),
        ('{"lyrics":"' + "字" * 24000 + '"}', "ValueError"),
        ({"lyrics": "字" * 24000}, "ValueError"),
        ('{"lyrics":NaN}', "ValueError"),
        ('{"lyrics":Infinity}', "ValueError"),
        ('{"lyrics":-Infinity}', "ValueError"),
        ('{"lyrics":1e10000}', "ValueError"),
        ({"lyrics": float("nan")}, "ValueError"),
        ({"lyrics": float("inf")}, "ValueError"),
        ({"lyrics": float("-inf")}, "ValueError"),
        (RuntimeError(f"provider leaked {SECRET}"), "RuntimeError"),
    ],
    ids=[
        "malformed",
        "array",
        "null",
        "oversize",
        "oversize-dict",
        "nan",
        "infinity",
        "negative-infinity",
        "exponent-overflow",
        "nan-dict",
        "infinity-dict",
        "negative-infinity-dict",
        "provider-exception",
    ],
)
def test_failed_response_ab_retains_artifacts_cleans_temp_and_exits_nonzero(
    monkeypatch, tmp_path, capsys, answer, error_type
):
    modules, directories = fake_live(monkeypatch, [answer, '{"lyrics":"B success"}'])
    assert lab.main(["--live", "--drop", "lyrics", "--prompt-b", str(lab.DEFAULT_PROMPT), "--out", str(tmp_path)]) == 1
    result = report(tmp_path)
    assert result["runs"]["A"]["error_type"] == error_type
    assert result["runs"]["B"]["status"] == "ok"
    assert all(len(module.calls) == 1 for module in modules)
    assert (tmp_path / "prompt-A.txt").is_file()
    assert (tmp_path / "merged-B.json").is_file()
    assert not (tmp_path / "merged-A.json").exists()
    if not isinstance(answer, Exception):
        response_record = json.loads((tmp_path / "response-A.txt").read_text(encoding="utf-8"))
        assert response_record["response_withheld"] is True
        assert result["runs"]["A"]["response_storage"] == "withheld_invalid_response"
        assert result["runs"]["A"]["stage"] == "decode_extraction_response"
    assert not any(directory.exists() for directory in directories)
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    assert all(SECRET not in path.read_text(encoding="utf-8") for path in tmp_path.iterdir())


def test_missing_extraction_config_never_falls_back(monkeypatch, tmp_path):
    live_config = config()
    del live_config["world"]["song_knowledge"]["crawler"]["extraction_llm_module"]
    monkeypatch.setattr(lab, "load_live_config", lambda artifacts, provider_override=None: live_config)
    monkeypatch.setattr(lab, "create_module", forbidden)
    assert lab.main(["--live", "--drop", "lyrics", "--out", str(tmp_path)]) == 1
    assert "不回退" in report(tmp_path)["error"]
    assert report(tmp_path)["runs"] == {}


def test_provider_override_report_and_secret_redaction(monkeypatch, tmp_path, capsys):
    fake_live(monkeypatch, [json.dumps({"lyrics": f"response {SECRET}"})])
    assert lab.main(["--live", "--provider", "experiment", "--drop", "lyrics", "--out", str(tmp_path)]) == 0
    result = report(tmp_path)
    assert result["configuration"]["provider"] == "experiment"
    assert result["configuration"]["provider_override"] is True
    assert result["configuration"]["base"] == "extraction_llm_module"
    assert "[REDACTED]" in (tmp_path / "response-A.txt").read_text(encoding="utf-8")
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    assert all(SECRET not in path.read_text(encoding="utf-8") for path in tmp_path.iterdir())


@pytest.mark.parametrize("encoding", ["literal", "unicode", "double-escaped"])
def test_response_credentials_are_redacted_after_decoding_without_changing_merge(
    monkeypatch, tmp_path, capsys, encoding
):
    secret = "sk-probe-not-a-real-key"
    escaped = chr(92) + "u0073" + secret[1:]
    answers = {
        "literal": json.dumps({"lyrics": secret, "extra": {"nested": [secret]}}),
        "unicode": '{"lyrics":"' + escaped + '"}',
        "double-escaped": json.dumps({"lyrics": escaped, "extra": {"nested": [escaped]}}),
    }
    fake_live(monkeypatch, [answers[encoding]])
    live_config = config()
    live_config["llm_service"]["available_llms"]["extractor"]["api_key"] = secret
    monkeypatch.setattr(lab, "load_live_config", lambda artifacts, provider_override=None: live_config)
    merged_inputs = []

    def observe_merge(data, parsed, needed):
        merged_inputs.append(copy.deepcopy(parsed))
        merge_missing(data, parsed, needed)

    monkeypatch.setattr("src.world.get_new_songs.source_extraction.merge_missing", observe_merge)
    assert lab.main(["--live", "--drop", "lyrics", "--out", str(tmp_path)]) == 0
    saved = json.loads((tmp_path / "response-A.txt").read_text(encoding="utf-8"))
    assert saved["lyrics"] == "[REDACTED]"
    assert saved["lyrics"] != secret
    assert merged_inputs == [json.loads(answers[encoding])]
    assert report(tmp_path)["runs"]["A"]["response_storage"] == "normalized_redacted_json"
    assert report(tmp_path)["runs"]["A"]["parsed"]["lyrics"] == "[REDACTED]"
    for path in tmp_path.iterdir():
        text = path.read_text(encoding="utf-8")
        assert secret not in text and escaped not in text
    output = capsys.readouterr()
    assert secret not in output.out + output.err


def test_malformed_escaped_response_body_is_withheld(monkeypatch, tmp_path):
    escaped = chr(92) + "u0073" + SECRET[1:]
    fake_live(monkeypatch, ['{"lyrics":"' + escaped + '"'])
    assert lab.main(["--live", "--out", str(tmp_path)]) == 1
    saved = json.loads((tmp_path / "response-A.txt").read_text(encoding="utf-8"))
    assert saved["response_withheld"] is True
    assert saved["response_chars"] > 0
    for path in tmp_path.iterdir():
        text = path.read_text(encoding="utf-8")
        assert SECRET not in text and escaped not in text


@pytest.mark.parametrize("api_type", ["requests", "unsupported", None])
def test_unsupported_provider_fails_before_secrets_and_module(monkeypatch, tmp_path, api_type):
    from src.infrastructure.config.secrets import SecretStore
    from src.infrastructure.config.store import ConfigStore

    live_config = config()
    live_config["llm_service"]["available_llms"]["extractor"] = {
        "api_type": api_type,
        "url": "https://invalid.example/endpoint",
        "model": "requests-model",
    }
    monkeypatch.setattr(ConfigStore, "read_raw", lambda self: live_config)
    monkeypatch.setattr(ConfigStore, "read_resolved", forbidden)
    monkeypatch.setattr(SecretStore, "read", forbidden)
    monkeypatch.setattr(SecretStore, "load_into_environment", forbidden)
    monkeypatch.setattr(lab, "create_module", forbidden)
    assert lab.main(["--live", "--out", str(tmp_path)]) == 1
    assert "api_type=openai" in report(tmp_path)["error"]
    assert report(tmp_path)["runs"] == {}


def test_credentials_in_template_are_not_sent_and_are_redacted(monkeypatch, tmp_path):
    modules, _ = fake_live(monkeypatch, ["{}"])
    prompt = tmp_path / "secret.json"
    prompt.write_text(json.dumps({"name": "secret", "template": SECRET + " {{ materials }}"}), encoding="utf-8")
    out = tmp_path / "output"
    assert lab.main(["--live", "--prompt", str(prompt), "--out", str(out)]) == 1
    assert not modules
    assert not report(out)["runs"]["A"]["model_call_attempted"]
    assert all(SECRET not in path.read_text(encoding="utf-8") for path in out.iterdir())


def test_scratch_cleanup_on_render_failure(monkeypatch, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(lab.tempfile, "tempdir", str(scratch))
    prompt = tmp_path / "prompt.json"
    prompt.write_text(json.dumps({"name": "bad", "template": "{{ missing_variable }}"}), encoding="utf-8")
    out = tmp_path / "output"
    assert lab.main(["--prompt", str(prompt), "--out", str(out)]) == 1
    assert report(out)["runs"]["A"]["error_type"] == "LabError"
    assert not list(scratch.iterdir())


def test_service_registration_reuses_extraction_config_without_overrides(monkeypatch, tmp_path):
    from src.infrastructure.models import service

    seen = {}

    class FakeService:
        def __init__(self, value):
            seen["service"] = value

        def register_llm_module(self, name, value):
            seen["module"] = (name, value)
            return "module"

    monkeypatch.setattr(service, "LLMService", FakeService)
    settings = lab.live_settings(config(), None)
    assert lab.create_module(settings, tmp_path, "experiment") == "module"
    expected = copy.deepcopy(config()["world"]["song_knowledge"]["crawler"]["extraction_llm_module"])
    expected["prompt_name"] = "experiment"
    assert seen["module"] == (lab.MODULE_NAME, expected)
    assert list(seen["service"]["available_llms"]) == ["extractor"]
    assert seen["service"]["prompt_manager"] == {"template_dir": str(tmp_path)}


@pytest.mark.parametrize("value", ["", "${MISSING_API_KEY}", "$UNRESOLVED"])
def test_unresolved_provider_stops_before_registration(monkeypatch, tmp_path, value):
    live_config = config()
    live_config["llm_service"]["available_llms"]["extractor"]["api_key"] = value
    monkeypatch.setattr(lab, "load_live_config", lambda artifacts, provider_override=None: live_config)
    monkeypatch.setattr(lab, "create_module", forbidden)
    assert lab.main(["--live", "--out", str(tmp_path)]) == 1
    assert "未解析" in report(tmp_path)["error"]
    assert report(tmp_path)["runs"] == {}


def test_json_object_response_and_null_leave_production_needed(monkeypatch, tmp_path):
    fake_live(monkeypatch, [{"lyrics": None}])
    assert lab.main(["--live", "--drop", "lyrics", "--out", str(tmp_path)]) == 0
    result = report(tmp_path)["runs"]["A"]
    assert result["needed_after"]["lyrics"] is True
    assert result["merged_diff"] == {}
    assert result["parsed"] == {"lyrics": None}


def test_existing_artifacts_are_never_overwritten(tmp_path):
    previous = tmp_path / "report.json"
    previous.write_text("previous experiment", encoding="utf-8")
    assert lab.main(["--out", str(tmp_path)]) == 1
    assert previous.read_text(encoding="utf-8") == "previous experiment"


def test_live_config_restores_environment_and_remembers_secrets(monkeypatch, tmp_path):
    from src.infrastructure.config.secrets import SecretStore
    from src.infrastructure.config.store import ConfigStore

    monkeypatch.delenv("LAB_TEST_KEY", raising=False)
    monkeypatch.setattr(SecretStore, "read", lambda self: {"LAB_TEST_KEY": SECRET})

    def resolved(self):
        assert os.environ["LAB_TEST_KEY"] == SECRET
        return config()

    monkeypatch.setattr(ConfigStore, "read_raw", lambda self: config())
    monkeypatch.setattr(ConfigStore, "read_resolved", resolved)
    artifacts = lab.Artifacts(tmp_path)
    assert lab.load_live_config(artifacts) == config()
    assert "LAB_TEST_KEY" not in os.environ
    assert SECRET in artifacts.secrets
