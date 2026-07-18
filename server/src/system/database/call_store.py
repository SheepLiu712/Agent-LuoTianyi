from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable

from src.chat_session.call_models import CallExitCode, CallTurnDraft
from src.system.database.sql_database import CallSession, CallTurn, Conversation
from src.utils.enum_type import ContextType
from src.utils.logger import get_logger


def _sanitize_event(value: Any, *, event_type: str = "") -> Any:
    """保留事件结构和文本，剥离原始音频/Base64正文。"""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        current_type = str(value.get("type") or event_type)
        for key, item in value.items():
            if key == "audio":
                if isinstance(item, str):
                    result[key] = {"base64_length": len(item), "redacted": True}
                else:
                    result[key] = {"redacted": True}
                continue
            if key == "delta" and "audio" in current_type:
                result[key] = {"base64_length": len(item) if isinstance(item, str) else 0, "redacted": True}
                continue
            result[key] = _sanitize_event(item, event_type=current_type)
        return result
    if isinstance(value, list):
        return [_sanitize_event(item, event_type=event_type) for item in value]
    return value


class CallStore:
    """同步 SQL 存储门面，由 CallStream 通过 asyncio.to_thread 调用。"""

    def __init__(self, database_manager) -> None:
        self.database = database_manager
        self.logger = get_logger("CallStore")

    def _session(self):
        return self.database.open_sql_session()

    def create_active_session(
        self,
        *,
        call_id: str,
        user_id: str,
        character_id: str,
        requested_at: datetime,
        connected_at: datetime,
    ) -> bool:
        db = self._session()
        try:
            existing = db.query(CallSession).filter(CallSession.call_id == call_id).first()
            if existing:
                return existing.status == "active"
            db.add(
                CallSession(
                    call_id=call_id,
                    user_id=user_id,
                    character_id=character_id,
                    status="active",
                    requested_at=requested_at,
                    connected_at=connected_at,
                )
            )
            db.commit()
            return True
        except Exception:
            db.rollback()
            self.logger.exception("create active call session failed: call_id=%s", call_id)
            return False
        finally:
            db.close()

    def create_preconnect_hangup(
        self,
        *,
        call_id: str,
        user_id: str,
        character_id: str,
        requested_at: datetime,
        ended_at: datetime,
        exit_code: int = int(CallExitCode.HANGUP_BEFORE_CONNECTED),
        summary: str = "未接通就挂断",
    ) -> str | None:
        """接通前挂断的特殊结算，同时创建 conversation。"""
        db = self._session()
        try:
            session = db.query(CallSession).filter(CallSession.call_id == call_id).first()
            if session and session.conversation_id:
                return session.conversation_id
            if not session:
                session = CallSession(
                    call_id=call_id,
                    user_id=user_id,
                    character_id=character_id,
                    status="ended",
                    requested_at=requested_at,
                    ended_at=ended_at,
                    duration_seconds=0,
                    exit_code=int(exit_code),
                    summary=summary,
                    summary_status="success",
                    memory_status="skipped",
                    profile_status="skipped",
                )
                db.add(session)
            conversation = Conversation(
                user_id=user_id,
                character_id=character_id,
                timestamp=ended_at,
                source="agent",
                type=ContextType.CALL.value,
                content="语音通话0秒",
                meta_data=json.dumps({"summary": summary}, ensure_ascii=False),
            )
            db.add(conversation)
            db.flush()
            session.conversation_id = conversation.uuid
            db.commit()
            return conversation.uuid
        except Exception:
            db.rollback()
            self.logger.exception("preconnect hangup settlement failed: call_id=%s", call_id)
            return None
        finally:
            db.close()

    def append_turn(self, turn: CallTurnDraft) -> bool:
        if not turn.text.strip():
            return False
        db = self._session()
        try:
            exists = (
                db.query(CallTurn)
                .filter(CallTurn.call_id == turn.call_id, CallTurn.seq == turn.seq)
                .first()
            )
            if exists:
                return True
            raw_events = [_sanitize_event(item) for item in turn.raw_events]
            db.add(
                CallTurn(
                    call_id=turn.call_id,
                    seq=turn.seq,
                    speaker=turn.speaker,
                    text=turn.text,
                    started_at=turn.started_at,
                    ended_at=turn.ended_at,
                    raw_events_json=json.dumps(raw_events, ensure_ascii=False) if raw_events else None,
                )
            )
            db.commit()
            return True
        except Exception:
            db.rollback()
            self.logger.exception("append call turn failed: call_id=%s seq=%s", turn.call_id, turn.seq)
            return False
        finally:
            db.close()

    def settle_call_and_conversation(
        self,
        *,
        call_id: str,
        ended_at: datetime,
        exit_code: int,
        duration_seconds: int,
    ) -> str | None:
        db = self._session()
        try:
            session = db.query(CallSession).filter(CallSession.call_id == call_id).first()
            if not session:
                return None
            if session.conversation_id:
                return session.conversation_id
            session.status = "ended"
            session.ended_at = ended_at
            session.exit_code = int(exit_code)
            session.duration_seconds = max(0, int(duration_seconds))
            conversation = Conversation(
                user_id=session.user_id,
                character_id=session.character_id,
                timestamp=ended_at,
                source="agent",
                type=ContextType.CALL.value,
                content=f"语音通话{max(0, int(duration_seconds))}秒",
                meta_data=json.dumps({"summary": session.summary or ""}, ensure_ascii=False),
            )
            db.add(conversation)
            db.flush()
            session.conversation_id = conversation.uuid
            db.commit()
            return conversation.uuid
        except Exception:
            db.rollback()
            self.logger.exception("call settlement failed: call_id=%s", call_id)
            return None
        finally:
            db.close()

    def update_summary(self, call_id: str, summary: str, status: str, error: str | None = None) -> bool:
        db = self._session()
        try:
            session = db.query(CallSession).filter(CallSession.call_id == call_id).first()
            if not session:
                return False
            session.summary = summary
            session.summary_status = status
            session.summary_error = error
            if session.conversation_id:
                conversation = db.query(Conversation).filter(Conversation.uuid == session.conversation_id).first()
                if conversation:
                    conversation.meta_data = json.dumps({"summary": summary}, ensure_ascii=False)
            db.commit()
            return True
        except Exception:
            db.rollback()
            self.logger.exception("update call summary failed: call_id=%s", call_id)
            return False
        finally:
            db.close()

    def update_postprocess_status(self, call_id: str, field: str, status: str, error: str | None = None) -> bool:
        if field not in {"memory", "profile"}:
            raise ValueError(f"unsupported call postprocess field: {field}")
        db = self._session()
        try:
            session = db.query(CallSession).filter(CallSession.call_id == call_id).first()
            if not session:
                return False
            setattr(session, f"{field}_status", status)
            setattr(session, f"{field}_error", error)
            db.commit()
            return True
        except Exception:
            db.rollback()
            self.logger.exception("update call %s status failed: call_id=%s", field, call_id)
            return False
        finally:
            db.close()

    def get_postprocess_state(self, call_id: str) -> dict[str, Any] | None:
        db = self._session()
        try:
            row = db.query(CallSession).filter(CallSession.call_id == call_id).first()
            if not row:
                return None
            return {
                "summary_status": row.summary_status,
                "memory_status": row.memory_status,
                "profile_status": row.profile_status,
                "summary": row.summary or "",
            }
        finally:
            db.close()

    def list_turns(self, call_id: str) -> list[dict[str, Any]]:
        db = self._session()
        try:
            rows = db.query(CallTurn).filter(CallTurn.call_id == call_id).order_by(CallTurn.seq.asc()).all()
            return [
                {
                    "id": row.id,
                    "call_id": row.call_id,
                    "seq": row.seq,
                    "speaker": row.speaker,
                    "text": row.text,
                    "started_at": row.started_at,
                    "ended_at": row.ended_at,
                }
                for row in rows
            ]
        finally:
            db.close()

    def list_sessions(
        self,
        *,
        limit: int = 100,
        user_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """返回管理员列表所需的摘要，不暴露 transcript 或原始音频。"""
        db = self._session()
        try:
            query = db.query(CallSession)
            if user_id:
                query = query.filter(CallSession.user_id == user_id)
            if status:
                query = query.filter(CallSession.status == status)
            rows = query.order_by(CallSession.requested_at.desc()).limit(max(1, int(limit))).all()
            return [self._session_summary(db, row) for row in rows]
        finally:
            db.close()

    def get_session_summary(self, call_id: str) -> dict[str, Any] | None:
        db = self._session()
        try:
            row = db.query(CallSession).filter(CallSession.call_id == call_id).first()
            return self._session_summary(db, row) if row else None
        finally:
            db.close()

    @staticmethod
    def _session_summary(db, row: CallSession) -> dict[str, Any]:
        return {
            "call_id": row.call_id,
            "user_id": row.user_id,
            "character_id": row.character_id,
            "status": row.status,
            "requested_at": row.requested_at,
            "connected_at": row.connected_at,
            "ended_at": row.ended_at,
            "duration_seconds": row.duration_seconds,
            "exit_code": row.exit_code,
            "summary": row.summary or "",
            "summary_status": row.summary_status,
            "summary_error": row.summary_error,
            "memory_status": row.memory_status,
            "profile_status": row.profile_status,
            "conversation_id": row.conversation_id,
            "turn_count": db.query(CallTurn).filter(CallTurn.call_id == row.call_id).count(),
        }

    def get_recent_conversations(
        self,
        *,
        user_id: str,
        character_id: str,
        since: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        db = self._session()
        try:
            rows = (
                db.query(Conversation)
                .filter(
                    Conversation.user_id == user_id,
                    Conversation.character_id == character_id,
                    Conversation.timestamp >= since,
                )
                .order_by(Conversation.timestamp.desc())
                .limit(max(0, int(limit)))
                .all()
            )
            result: list[dict[str, Any]] = []
            for row in reversed(rows):
                metadata = None
                if row.meta_data:
                    try:
                        metadata = json.loads(row.meta_data)
                    except json.JSONDecodeError:
                        metadata = None
                result.append(
                    {
                        "uuid": row.uuid,
                        "timestamp": row.timestamp,
                        "source": row.source,
                        "type": row.type,
                        "content": row.content,
                        "meta_data": metadata,
                    }
                )
            return result
        finally:
            db.close()
