"""Small, persistent, account-owned chat images."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.dialects.sqlite import insert

from src.infrastructure.persistence.database.sql_database import ChatAvatar


class AvatarStore:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def get(self, user_id: str) -> dict:
        with self._session_factory() as session:
            rows = session.query(ChatAvatar).filter_by(user_id=user_id).all()
            images = {row.side: row.image for row in rows}
        snapshot = {side: images.get(side) for side in ("user", "agent")}
        revision = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        return {"revision": revision, **snapshot}

    def put(self, user_id: str, side: str, image: str | None) -> dict:
        statement = insert(ChatAvatar).values(user_id=user_id, side=side, image=image)
        with self._session_factory() as session:
            session.execute(statement.on_conflict_do_update(index_elements=["user_id", "side"], set_={"image": image}))
            session.commit()
        return self.get(user_id)
