"""计划投递的内部草稿样例与持久接收器 Fake；结果从公开 handle 观察。"""
from contextlib import closing
from dataclasses import asdict
from datetime import date
import importlib
import importlib.util
import json
import sqlite3
from types import SimpleNamespace

import src.domain.agent as d
from routing_support import settlement


def draft(*, text="计划正文", actions=None, sources=("m2", "m1")):
    values = dict(source_stimulus_ids=sources, actions=actions if actions is not None else (
        d.Say(action_id="say", content=text, sound_content=None, prepared_audio_ref=None,
              tone=d.Tone(value="normal"), expression=None, delivery=d.OutputDelivery.CONVERSATION),
    ))
    # RED 时仍从公开 handle 得到正常失败报告，不用缺少导入制造收集失败。
    if importlib.util.find_spec("src.agent.planning") is None:
        return SimpleNamespace(**values)
    cls = getattr(importlib.import_module("src.agent.planning.emitter"), "ActionPlanDraft", None)
    return cls(**values) if cls is not None else SimpleNamespace(**values)


async def one_plan(req, plans):
    receipt = await plans.emit(draft())
    return settlement(req, emitted=(receipt.plan_id,))


async def all_business_actions(req, plans):
    receipt = await plans.emit(draft(actions=(
        d.Say(action_id="say", content="显示", sound_content=None,
              prepared_audio_ref=d.MediaRef(media_id="prepared"), tone=d.Tone(value="soft"),
              expression=d.ChangeExpression(expression_id="happy"), delivery=d.OutputDelivery.CONVERSATION),
        d.Sing(action_id="sing", song_id="song", segment_id="chorus", expression=None),
        d.WriteDiary(action_id="diary", owner_user_id="u", local_date=date(2026, 9, 6), body="日记内容"),
        d.PublishDynamic(action_id="publish", body="动态内容", media_refs=(d.MediaRef(media_id="photo"),),
                         visibility=d.Visibility.PRIVATE, owner_user_id="u",
                         source=d.DynamicSource(source_type="test", source_id="source"), allow_comment=False),
        d.ReplyDynamic(action_id="reply", target=d.DynamicReplyTarget(dynamic_id="dynamic", parent_comment_id="parent"),
                       owner_user_id="u", body="评论内容"),
        d.RequestSongLearning(action_id="learn", song_id="song", dedup_key="learn-key"),
    )))
    return settlement(req, emitted=(receipt.plan_id,))


def encoded(plan):
    """Fake 的线格式保留完整领域值，用于观察跨进程传输内容是否一致。"""
    return json.dumps(asdict(plan), ensure_ascii=False, sort_keys=True, default=str)


class DurablePlanSink:
    """SQLite 模拟可识别 plan_id 重复的外部接收器，不模拟 Agent 账本。"""
    def __init__(self, path, *, lose_reply=False):
        self.path = str(path)
        self.lose_reply = lose_reply
        self.values = []
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS received (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    async def emit(self, plan):
        self.values.append(plan)
        payload = encoded(plan)
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute("SELECT payload FROM received WHERE id=?", (plan.plan_id,)).fetchone()
            if row is not None and row[0] != payload:
                raise d.SinkRejectedError("changed plan", code=d.SinkRejectionCode.CONTENT_CONFLICT)
            if row is None:
                db.execute("INSERT INTO received VALUES (?, ?)", (plan.plan_id, payload))
        if self.lose_reply:
            raise TimeoutError("response disappeared after commit")
        return d.PlanReceipt(plan_id=plan.plan_id, status=(d.PlanAcceptanceStatus.ALREADY_ACCEPTED
                             if row else d.PlanAcceptanceStatus.ACCEPTED))

    def accepted_payloads(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            return tuple(row[0] for row in db.execute("SELECT payload FROM received ORDER BY id"))
