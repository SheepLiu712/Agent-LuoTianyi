from datetime import datetime, timedelta, timezone
from importlib.abc import Traversable

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.application.user.agreement_loader import (
    AgreementConfigError,
    AgreementDoc,
    load_manifest,
)
from src.infrastructure.persistence.database.sql_database import AgreementVersion

UTC8 = timezone(timedelta(hours=8))


class AgreementService:
    def __init__(self, current_version: str, docs: dict[str, AgreementDoc]):
        self._current_version = current_version
        self._docs = docs

    def get_current(self) -> AgreementDoc:
        return self._docs[self._current_version]


def _validate_archived_agreements(session, docs: dict[str, AgreementDoc]) -> dict[str, AgreementVersion]:
    existing = {row.version: row for row in session.query(AgreementVersion).all()}

    db_versions = set(existing)
    doc_versions = set(docs)

    orphan_versions = db_versions - doc_versions
    if orphan_versions:
        raise AgreementConfigError(f"数据库归档 {sorted(orphan_versions)} 不在发布清单中")

    for version in db_versions & doc_versions:
        row = existing[version]
        doc = docs[version]
        if row.title != doc.title:
            raise AgreementConfigError(f"协议 {version} 标题被覆盖")
        if row.format != doc.format:
            raise AgreementConfigError(f"协议 {version} 格式被覆盖")
        if row.content_sha256 != doc.sha256:
            raise AgreementConfigError(f"协议 {version} 原文被覆盖")
        if row.content_json != doc.content_json:
            raise AgreementConfigError(f"协议 {version} 规范化正文被覆盖")

    return existing


def prepare_agreements(session, root: Traversable) -> AgreementService:
    current_version, docs = load_manifest(root)
    _validate_archived_agreements(session, docs)
    return AgreementService(current_version, docs)


def publish_agreements(session, service: AgreementService) -> None:
    try:
        created_at = datetime.now(UTC8).replace(microsecond=0).isoformat()
        for doc in service._docs.values():
            statement = (
                sqlite_insert(AgreementVersion)
                .values(
                    version=doc.version,
                    title=doc.title,
                    format=doc.format,
                    content_json=doc.content_json,
                    content_sha256=doc.sha256,
                    created_at=created_at,
                )
                .on_conflict_do_nothing(index_elements=[AgreementVersion.version])
            )
            session.execute(statement)

        existing = _validate_archived_agreements(session, service._docs)
        missing_versions = set(service._docs) - set(existing)
        if missing_versions:
            raise AgreementConfigError(f"协议版本未完成归档: {sorted(missing_versions)}")
        session.commit()
    except BaseException:
        session.rollback()
        raise


def init_agreements(session, root: Traversable) -> AgreementService:
    service = prepare_agreements(session, root)
    publish_agreements(session, service)
    return service
