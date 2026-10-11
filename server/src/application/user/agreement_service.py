from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def init_agreements(session, root: Path) -> AgreementService:
    current_version, docs = load_manifest(root)

    existing = {row.version: row for row in session.query(AgreementVersion).all()}

    db_versions = set(existing)
    doc_versions = set(docs)

    orphan_versions = db_versions - doc_versions
    if orphan_versions:
        raise AgreementConfigError(f"数据库归档 {sorted(orphan_versions)} 不在发布清单中")

    new_versions = doc_versions - db_versions
    for version in new_versions:
        doc = docs[version]
        session.add(
            AgreementVersion(
                version=doc.version,
                title=doc.title,
                format=doc.format,
                content_json=doc.content_json,
                content_sha256=doc.sha256,
                created_at=datetime.now(UTC8).replace(microsecond=0).isoformat(),
            )
        )

    common_versions = db_versions & doc_versions
    for version in common_versions:
        row = existing[version]
        doc = docs[version]
        if row.content_sha256 != doc.sha256:
            raise AgreementConfigError(f"协议 {version} 原文被覆盖")
        if row.content_json != doc.content_json:
            raise AgreementConfigError(f"协议 {version} 规范化正文被覆盖")

    session.commit()
    return AgreementService(current_version, docs)
