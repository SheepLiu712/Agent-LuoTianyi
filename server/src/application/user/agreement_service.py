from datetime import datetime, timedelta, timezone
from importlib.abc import Traversable
from typing import Callable, Optional

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.application.user.agreement_loader import (
    AgreementConfigError,
    AgreementDoc,
    load_manifest,
)
from src.infrastructure.persistence.database.sql_database import AgreementSignature, AgreementVersion

UTC8 = timezone(timedelta(hours=8))

# 签署时间由服务端受控时钟产生；测试可注入固定时钟，不接受客户端上报的时间。
Clock = Callable[[], datetime]


class AgreementTimeError(ValueError):
    """签署时间不符合服务端约定。"""


class AgreementAcceptanceError(Exception):
    code: str
    status_code: int

    def __init__(self, detail: str, *, code: str, status_code: int, extra: Optional[dict] = None) -> None:
        self.detail = detail
        self.code = code
        self.status_code = status_code
        self.extra = dict(extra or {})
        super().__init__(detail)


def agreement_now(clock: Optional[Clock] = None) -> datetime:
    """取当前签署时刻（UTC+8）；注入时钟必须返回带时区的时间。"""
    moment = clock() if clock is not None else datetime.now(UTC8)
    if moment.tzinfo is None:
        raise AgreementTimeError("协议签署时钟必须返回带时区的时间")
    return moment.astimezone(UTC8)


def format_agreement_time(moment: datetime) -> str:
    """规范化签署时间：UTC+8、秒精度、不带小数秒。"""
    if moment.tzinfo is None:
        raise AgreementTimeError("协议签署时间必须带时区")
    return moment.astimezone(UTC8).replace(microsecond=0).isoformat()


def parse_agreement_time(value: str) -> datetime:
    """解析已存储的签署时间，拒绝小数秒与非 +08:00 偏移。"""
    if not isinstance(value, str) or "." in value:
        raise AgreementTimeError("签署时间必须是不含小数秒的字符串")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise AgreementTimeError("签署时间无法解析") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(hours=8):
        raise AgreementTimeError("签署时间必须带 +08:00 偏移")
    return parsed


def validate_signature_time(value: str, now: datetime) -> str:
    """写入边界校验：可解析、偏移正确、无小数秒、不晚于本次服务端当前时刻。"""
    parsed = parse_agreement_time(value)
    if parsed > now:
        raise AgreementTimeError("签署时间不得晚于服务端当前时间")
    return value


class AgreementService:
    def __init__(
        self, current_version: str, docs: dict[str, AgreementDoc], exempt_user_uuids: Optional[set[str]] = None
    ):
        self._current_version = current_version
        self._docs = docs
        self._exempt_user_uuids = frozenset(exempt_user_uuids or ())

    @property
    def current_version(self) -> str:
        return self._current_version

    def is_current(self, version: Optional[str]) -> bool:
        return version == self._current_version

    def get_current(self) -> AgreementDoc:
        return self._docs[self._current_version]

    def is_exempt(self, user_uuid: str) -> bool:
        return user_uuid in self._exempt_user_uuids

    def is_login_eligible(self, session, user_uuid: str) -> bool:
        return self.is_exempt(user_uuid) or first_signed_at(session, user_uuid, self.current_version) is not None

    def accept(self, session, *, user_uuid: str, version: str, accepted: bool, clock: Optional[Clock] = None) -> str:
        if accepted is not True:
            raise AgreementAcceptanceError("必须明确提交同意", code="INVALID_AGREEMENT_INPUT", status_code=422)
        if not self.is_current(version):
            raise AgreementAcceptanceError(
                "用户协议已更新，请重新阅读",
                code="AGREEMENT_CHANGED",
                status_code=409,
                extra={"agreement_version": self.current_version},
            )
        now = agreement_now(clock)
        accepted_at = format_agreement_time(now)
        validate_signature_time(accepted_at, now)
        stored, _ = record_signature(session, user_uuid=user_uuid, agreement_version=version, accepted_at=accepted_at)
        session.commit()
        return stored


def first_signed_at(session, user_uuid: str, agreement_version: str) -> Optional[str]:
    """返回该账号对该版本的首次签署时间；未签署返回 None。"""
    row = (
        session.query(AgreementSignature)
        .filter(
            AgreementSignature.user_uuid == user_uuid,
            AgreementSignature.agreement_version == agreement_version,
        )
        .first()
    )
    return row.accepted_at if row is not None else None


def record_signature(session, *, user_uuid: str, agreement_version: str, accepted_at: str) -> tuple[str, bool]:
    """幂等写入签署记录：已有记录时返回原时间且不覆盖，返回 (首次时间, 是否新建)。"""
    existing = first_signed_at(session, user_uuid, agreement_version)
    if existing is not None:
        return existing, False

    statement = (
        sqlite_insert(AgreementSignature)
        .values(user_uuid=user_uuid, agreement_version=agreement_version, accepted_at=accepted_at)
        .on_conflict_do_nothing(index_elements=["user_uuid", "agreement_version"])
    )
    session.execute(statement)
    stored = first_signed_at(session, user_uuid, agreement_version)
    if stored is None:
        raise AgreementTimeError("签署记录写入后无法读回")
    return stored, stored == accepted_at


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
