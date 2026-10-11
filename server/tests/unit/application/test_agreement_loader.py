import hashlib
import json
from importlib.resources import files

import pytest

from src.application.user.agreement_loader import AgreementConfigError, load_manifest


def _write_manifest(root, *, current_version="v1", filename="agreement_v1.json"):
    manifest = {"current_version": current_version, "files": {"v1": filename}}
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def _write_valid_doc(path, *, version="v1", title="服务协议"):
    doc = {
        "version": version,
        "title": title,
        "format": "agreement.richtext.v1",
        "blocks": [
            {
                "font_size": 16,
                "align": "justify",
                "runs": [
                    {"text": "欢迎使用本服务。", "bold": True},
                    {"text": "请认真阅读协议内容。", "bold": False},
                ],
            }
        ],
    }
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return doc


def test_load_manifest_reads_valid_manifest_and_doc(tmp_path):
    agreement_path = tmp_path / "agreement_v1.json"
    _write_valid_doc(agreement_path)
    _write_manifest(tmp_path)

    version, docs = load_manifest(tmp_path)

    assert version == "v1"
    assert set(docs) == {"v1"}
    assert docs["v1"].version == "v1"
    assert docs["v1"].title == "服务协议"
    assert docs["v1"].format == "agreement.richtext.v1"

    block = docs["v1"].blocks[0]
    assert isinstance(block, dict)
    runs = block["runs"]
    assert isinstance(runs, list)
    first_run = runs[0]
    assert isinstance(first_run, dict)
    assert first_run["text"] == "欢迎使用本服务。"


def test_doc_blocks_field_is_allowed(tmp_path):
    agreement_path = tmp_path / "agreement_v1.json"
    _write_valid_doc(agreement_path)
    _write_manifest(tmp_path)

    _, docs = load_manifest(tmp_path)

    assert docs["v1"].blocks[0]["runs"][0]["text"] == "欢迎使用本服务。"


def test_load_manifest_reads_packaged_agreement_resources():
    version, docs = load_manifest(files("res.user_agreements"))

    assert isinstance(version, str) and version
    assert version in docs
    assert docs[version].blocks
    assert docs[version].title


def test_doc_unknown_field_is_rejected(tmp_path):
    agreement_path = tmp_path / "agreement_v1.json"
    doc = _write_valid_doc(agreement_path)
    doc["extra_field"] = "not allowed"
    agreement_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    _write_manifest(tmp_path)

    with pytest.raises(AgreementConfigError, match="未知字段|extra_field"):
        load_manifest(tmp_path)


def test_doc_format_is_rejected_for_unknown_value(tmp_path):
    agreement_path = tmp_path / "agreement_v1.json"
    doc = _write_valid_doc(agreement_path)
    doc["format"] = "agreement.unsupported.v9"
    agreement_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    _write_manifest(tmp_path)

    with pytest.raises(AgreementConfigError, match="不支持的 format|agreement.unsupported"):
        load_manifest(tmp_path)


def test_doc_align_is_rejected_for_unknown_value(tmp_path):
    agreement_path = tmp_path / "agreement_v1.json"
    doc = _write_valid_doc(agreement_path)
    doc["blocks"] = [{"font_size": 16, "align": "left", "runs": [{"text": "x", "bold": False}]}]
    agreement_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    _write_manifest(tmp_path)

    with pytest.raises(AgreementConfigError, match="align 非法|left"):
        load_manifest(tmp_path)


def test_doc_bold_is_rejected_for_non_bool(tmp_path):
    agreement_path = tmp_path / "agreement_v1.json"
    doc = _write_valid_doc(agreement_path)
    doc["blocks"] = [{"font_size": 16, "align": "justify", "runs": [{"text": "x", "bold": "yes"}]}]
    agreement_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    _write_manifest(tmp_path)

    with pytest.raises(AgreementConfigError, match="bold 必须是布尔值|bold"):
        load_manifest(tmp_path)


def test_doc_sha256_matches_canonical_json(tmp_path):
    agreement_path = tmp_path / "agreement_v1.json"
    raw_doc = _write_valid_doc(agreement_path)
    _write_manifest(tmp_path)

    _, docs = load_manifest(tmp_path)
    doc = docs["v1"]
    canonical = json.dumps(raw_doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    assert doc.sha256 == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_load_manifest_raises_for_missing_manifest_file(tmp_path):
    with pytest.raises(AgreementConfigError, match="协议文件不存在|manifest"):
        load_manifest(tmp_path)


def test_load_manifest_raises_when_current_version_not_in_files(tmp_path):
    agreement_path = tmp_path / "agreement_v1.json"
    _write_valid_doc(agreement_path)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"current_version": "v2", "files": {"v1": "agreement_v1.json"}}),
        encoding="utf-8",
    )

    with pytest.raises(AgreementConfigError, match="current_version"):
        load_manifest(tmp_path)


def test_load_manifest_raises_for_empty_text_run(tmp_path):
    agreement_path = tmp_path / "agreement_v1.json"
    doc = _write_valid_doc(agreement_path)
    doc["blocks"] = [{"font_size": 16, "align": "justify", "runs": [{"text": "   ", "bold": False}]}]
    agreement_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"current_version": "v1", "files": {"v1": "agreement_v1.json"}}),
        encoding="utf-8",
    )

    with pytest.raises(AgreementConfigError, match="正文至少需要一个非空白字符|非空白字符"):
        load_manifest(tmp_path)


def test_manifest_unknown_field_is_rejected(tmp_path):
    agreement_path = tmp_path / "agreement_v1.json"
    _write_valid_doc(agreement_path)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"current_version": "v1", "files": {"v1": "agreement_v1.json"}, "extra": 1}),
        encoding="utf-8",
    )
    with pytest.raises(AgreementConfigError, match="未知字段|extra"):
        load_manifest(tmp_path)


def test_doc_version_mismatch_is_rejected(tmp_path):
    agreement_path = tmp_path / "agreement_v1.json"
    _write_valid_doc(agreement_path, version="v2")
    _write_manifest(tmp_path, current_version="v1", filename="agreement_v1.json")
    with pytest.raises(AgreementConfigError, match="不一致|version"):
        load_manifest(tmp_path)


def test_block_unknown_field_is_rejected(tmp_path):
    agreement_path = tmp_path / "agreement_v1.json"
    doc = _write_valid_doc(agreement_path)
    doc["blocks"][0]["style"] = {"color": "red"}
    agreement_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    _write_manifest(tmp_path)
    with pytest.raises(AgreementConfigError, match="未知字段|style"):
        load_manifest(tmp_path)


def test_run_unknown_field_is_rejected(tmp_path):
    agreement_path = tmp_path / "agreement_v1.json"
    doc = _write_valid_doc(agreement_path)
    doc["blocks"][0]["runs"][0]["style"] = {"bold": True}
    agreement_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    _write_manifest(tmp_path)
    with pytest.raises(AgreementConfigError, match="未知字段|style"):
        load_manifest(tmp_path)
