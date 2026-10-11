import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.application.user.agreement_loader import AgreementConfigError
from src.application.user.agreement_service import init_agreements, prepare_agreements, publish_agreements
from src.infrastructure.persistence.database.sql_database import AgreementVersion, Base


def _write_manifest(root, *, current_version="v1", files=None):
    if files is None:
        files = {"v1": "agreement_v1.json"}
    manifest = {"current_version": current_version, "files": files}
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


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_init_agreements_persists_new_versions(tmp_path, session):
    agreement_path = tmp_path / "agreement_v1.json"
    raw_doc = _write_valid_doc(agreement_path)
    _write_manifest(tmp_path)

    service = init_agreements(session, tmp_path)

    assert service.get_current().version == "v1"
    stored = session.query(AgreementVersion).one()
    assert stored.version == "v1"
    assert stored.title == "服务协议"
    assert stored.format == "agreement.richtext.v1"
    assert stored.content_json == json.dumps(raw_doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert stored.content_sha256 == hashlib.sha256(stored.content_json.encode("utf-8")).hexdigest()


def test_init_agreements_rejects_orphan_database_versions(tmp_path, session):
    agreement_path = tmp_path / "agreement_v1.json"
    _write_valid_doc(agreement_path)
    _write_manifest(tmp_path)
    session.add(
        AgreementVersion(
            version="v2",
            title="归档旧版本",
            format="agreement.richtext.v1",
            content_json="{}",
            content_sha256="deadbeef",
            created_at="2026-10-11T00:00:00+08:00",
        )
    )
    session.commit()

    with pytest.raises(AgreementConfigError, match="数据库归档"):
        init_agreements(session, tmp_path)


def test_init_agreements_rejects_modified_content_sha(tmp_path, session):
    agreement_path = tmp_path / "agreement_v1.json"
    raw_doc = _write_valid_doc(agreement_path)
    _write_manifest(tmp_path)
    canonical = json.dumps(raw_doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    session.add(
        AgreementVersion(
            version="v1",
            title="服务协议",
            format="agreement.richtext.v1",
            content_json=canonical,
            content_sha256="not-the-real-sha",
            created_at="2026-10-11T00:00:00+08:00",
        )
    )
    session.commit()

    with pytest.raises(AgreementConfigError, match="原文被覆盖"):
        init_agreements(session, tmp_path)


def test_init_agreements_rejects_modified_content_json(tmp_path, session):
    agreement_path = tmp_path / "agreement_v1.json"
    raw_doc = _write_valid_doc(agreement_path)
    _write_manifest(tmp_path)
    canonical = json.dumps(raw_doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    session.add(
        AgreementVersion(
            version="v1",
            title="服务协议",
            format="agreement.richtext.v1",
            content_json='{"tampered": true}',
            content_sha256=sha,
            created_at="2026-10-11T00:00:00+08:00",
        )
    )
    session.commit()

    with pytest.raises(AgreementConfigError, match="规范化正文被覆盖"):
        init_agreements(session, tmp_path)


def test_init_agreements_accepts_packaged_agreement_resources(session):
    service = init_agreements(session, files("res.user_agreements"))

    current = service.get_current()
    assert current.version
    assert current.blocks

    # 归档的是发布清单里的**全部**版本（历史版本必须留档），所以这里断言集合相等：
    # 一旦发布第二个版本，`query(AgreementVersion).one()` 这类"只有一个版本"的断言会误报失败。
    manifest = json.loads(files("res.user_agreements").joinpath("manifest.json").read_text(encoding="utf-8"))
    stored = {row.version: row for row in session.query(AgreementVersion).all()}
    assert set(stored) == set(manifest["files"])
    assert stored[current.version].content_json == current.content_json
    assert stored[current.version].content_sha256 == current.sha256


def test_publish_agreements_is_idempotent_across_concurrent_sessions(tmp_path):
    agreement_path = tmp_path / "agreement_v1.json"
    _write_valid_doc(agreement_path)
    _write_manifest(tmp_path)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'agreements.db'}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    barrier = threading.Barrier(2)

    def publish() -> None:
        with SessionLocal() as concurrent_session:
            service = prepare_agreements(concurrent_session, tmp_path)
            barrier.wait(timeout=5)
            publish_agreements(concurrent_session, service)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(publish) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)

    with SessionLocal() as verify_session:
        stored = verify_session.query(AgreementVersion).all()
        assert [row.version for row in stored] == ["v1"]

    engine.dispose()


def test_publish_agreements_rejects_conflicting_concurrent_content(tmp_path):
    agreement_path = tmp_path / "agreement_v1.json"
    _write_valid_doc(agreement_path)
    _write_manifest(tmp_path)
    engine = create_engine(f"sqlite:///{tmp_path / 'agreements.db'}")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as publishing_session:
        service = prepare_agreements(publishing_session, tmp_path)
        with SessionLocal() as competing_session:
            competing_session.add(
                AgreementVersion(
                    version="v1",
                    title="被篡改的协议",
                    format="agreement.richtext.v1",
                    content_json="{}",
                    content_sha256="deadbeef",
                    created_at="2026-10-11T00:00:00+08:00",
                )
            )
            competing_session.commit()

        with pytest.raises(AgreementConfigError, match="原文被覆盖"):
            publish_agreements(publishing_session, service)

    engine.dispose()
