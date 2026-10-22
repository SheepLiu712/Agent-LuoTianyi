"""注册用例：把账号、协议签署、邀请码消耗与注册请求结果放进同一次提交（UA-2 · issue #296）。

失败以 :class:`RegistrationError` 的子类抛出，由 HTTP 入口映射成稳定错误码；
本模块不依赖 FastAPI，便于直接用真实数据库事务测试。
"""

from __future__ import annotations

import json
from typing import Optional

from src.application.user.agreement_service import (
    AgreementService,
    Clock,
    agreement_now,
    format_agreement_time,
    record_signature,
    validate_signature_time,
)
from src.infrastructure.persistence.database.sql_database import InviteCode, RegistrationRequest, User

AGREEMENT_UPGRADE_DETAIL = "请升级到支持用户协议签署的版本，阅读并同意用户协议后再登录。"
REGISTRATION_FAILED_DETAIL = "注册失败，请检查邀请码或用户名"


class RegistrationError(Exception):
    """注册失败；`code` 与 `status_code` 供 HTTP 入口映射。"""

    code: Optional[str] = None
    status_code = 400
    detail = REGISTRATION_FAILED_DETAIL

    def __init__(self, detail: Optional[str] = None, *, extra: Optional[dict] = None) -> None:
        self.detail = detail or self.detail
        self.extra = dict(extra or {})
        super().__init__(self.detail)


class AgreementRequiredError(RegistrationError):
    """旧客户端未提交同意信息：不创建账号、不消耗邀请码。"""

    code = "AGREEMENT_REQUIRED"
    status_code = 403
    detail = AGREEMENT_UPGRADE_DETAIL


class InvalidAgreementInputError(RegistrationError):
    """同意字段不合法（非严格 true、缺少请求标识等）。"""

    code = "INVALID_AGREEMENT_INPUT"
    status_code = 422
    detail = "协议提交字段不合法"


class AgreementChangedError(RegistrationError):
    """未提交成功的同意针对旧版本。"""

    code = "AGREEMENT_CHANGED"
    status_code = 409
    detail = "用户协议已更新，请重新阅读"

    def __init__(self, current_version: str) -> None:
        super().__init__(extra={"agreement_version": current_version})
        self.current_version = current_version


class RegistrationRequestConflictError(RegistrationError):
    """同一注册请求 ID 被用于不同内容。"""

    code = "REGISTRATION_REQUEST_CONFLICT"
    status_code = 409
    detail = "该注册请求与先前提交的内容不一致，请勿盲目重试"


class RegistrationRequestUnverifiableError(RegistrationError):
    """请求 ID 已成功过，但凭据无法核验（例如账号被重置）：不创建替代账号。"""

    code = "REGISTRATION_REQUEST_UNVERIFIABLE"
    status_code = 409
    detail = "原注册结果无法核验，请用账号密码登录确认；不会创建替代账号"


class RegistrationService:
    """注册用例：协调当前协议版本、注册请求恢复与账号持久化。"""

    def __init__(
        self, *, agreement_service: AgreementService, credential_service, clock: Optional[Clock] = None
    ) -> None:
        self._agreements = agreement_service
        self._credentials = credential_service
        self._clock = clock

    def register(
        self,
        *,
        username: str,
        password: str,
        invite_code: str,
        registration_request_id: Optional[str] = None,
        agreement_version: Optional[str] = None,
        accepted: Optional[bool] = None,
    ) -> dict:
        """完成一次注册提交；返回可直接回给客户端的成功响应。"""
        self._require_agreement_input(registration_request_id, agreement_version, accepted)

        db = self._credentials.new_session()
        try:
            replayed = self._replay(
                db,
                username=username,
                password=password,
                invite_code=invite_code,
                registration_request_id=registration_request_id,
                agreement_version=agreement_version,
            )
            if replayed is not None:
                return replayed

            if not self._agreements.is_current(agreement_version):
                raise AgreementChangedError(self._agreements.current_version)

            ok, message, user_uuid = self._credentials.create_account_with_invite(db, username, password, invite_code)
            if not ok or user_uuid is None:
                raise RegistrationError(message)

            now = agreement_now(self._clock)
            accepted_at = format_agreement_time(now)
            validate_signature_time(accepted_at, now)
            record_signature(db, user_uuid=user_uuid, agreement_version=agreement_version, accepted_at=accepted_at)

            payload = {"message": "注册成功", "user_id": username}
            db.add(
                RegistrationRequest(
                    registration_request_id=registration_request_id,
                    user_uuid=user_uuid,
                    agreement_version=agreement_version,
                    response_json=json.dumps(payload, ensure_ascii=False),
                    created_at=accepted_at,
                )
            )
            db.commit()
        except RegistrationError as error:
            db.rollback()
            # 两个相同 request ID 可能同时通过首次 replay 检查；若另一事务已提交，
            # 本事务会在邀请码占用处失败。回滚后重新核验原请求，保证幂等重试最终返回同一结果。
            if error.code is None:
                replayed = self._recover_after_race(
                    username=username,
                    password=password,
                    invite_code=invite_code,
                    registration_request_id=registration_request_id,
                    agreement_version=agreement_version,
                )
                if replayed is not None:
                    return replayed
            raise
        except Exception:
            db.rollback()
            # 并发同 ID 时另一方可能已先提交，本事务会在用户名/邀请码的唯一约束上抛 IntegrityError；
            # 同样尝试按原请求恢复，避免把"已经成功的注册"变成 500。
            replayed = self._recover_after_race(
                username=username,
                password=password,
                invite_code=invite_code,
                registration_request_id=registration_request_id,
                agreement_version=agreement_version,
            )
            if replayed is not None:
                return replayed
            raise
        finally:
            db.close()

        self._credentials.cache_user_uuid(username, user_uuid)
        return payload

    def _recover_after_race(
        self,
        *,
        username: str,
        password: str,
        invite_code: str,
        registration_request_id: Optional[str],
        agreement_version: str,
    ) -> Optional[dict]:
        """竞争失败后在独立会话里复核原请求；复核自身出错时保留原失败原因。

        边界：复核时若另一方尚未提交，返回 None，调用方仍抛原错误——
        因此"并发相同 ID 归一"保证的是重试后结果一致，而不是单次请求必然返回原结果。
        """
        if not registration_request_id:
            return None
        db = self._credentials.new_session()
        try:
            return self._replay(
                db,
                username=username,
                password=password,
                invite_code=invite_code,
                registration_request_id=registration_request_id,
                agreement_version=agreement_version,
            )
        except RegistrationError:
            # 冲突 / 无法核验是确定的业务结论，必须原样返回（409），不能回退成 500。
            raise
        except Exception:
            return None
        finally:
            db.close()

    @staticmethod
    def _require_agreement_input(
        registration_request_id: Optional[str], agreement_version: Optional[str], accepted: Optional[bool]
    ) -> None:
        if agreement_version is None and accepted is None:
            raise AgreementRequiredError()
        if not registration_request_id:
            raise InvalidAgreementInputError("缺少注册请求标识")
        if not agreement_version:
            raise InvalidAgreementInputError("缺少协议版本")
        if accepted is not True:
            raise InvalidAgreementInputError("必须明确提交同意")

    def _replay(
        self,
        db,
        *,
        username: str,
        password: str,
        invite_code: str,
        registration_request_id: str,
        agreement_version: str,
    ) -> Optional[dict]:
        """已成功的请求 ID：核验原操作后返回原成功响应，否则报冲突或无法核验。"""
        request = (
            db.query(RegistrationRequest)
            .filter(RegistrationRequest.registration_request_id == registration_request_id)
            .first()
        )
        if request is None:
            return None

        user = db.query(User).filter(User.uuid == request.user_uuid).first()
        if user is None:
            raise RegistrationRequestUnverifiableError()
        # 核验“原操作”，而不是账号当前状态：账号被重置后 username 可能已经改掉，
        # 只有原响应里记录的用户名才代表这次注册提交的内容。
        original_payload = json.loads(request.response_json)
        if original_payload.get("user_id") != username:
            raise RegistrationRequestConflictError()
        if user.username != username:
            raise RegistrationRequestConflictError()
        if request.agreement_version != agreement_version:
            raise RegistrationRequestConflictError()

        owned_invite = (
            db.query(InviteCode).filter(InviteCode.code == invite_code, InviteCode.user_id == request.user_uuid).first()
        )
        if owned_invite is None:
            raise RegistrationRequestConflictError()

        if not self._credentials.verify_password(password, user.password or ""):
            raise RegistrationRequestUnverifiableError()

        return json.loads(request.response_json)
