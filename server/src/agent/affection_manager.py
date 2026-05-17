"""
好感度管理器 (Affection Manager)

管理用户与洛天依之间的好感度数值系统。
好感度升降由 LLM 分析用户消息后动态决定，而非固定数值。
"""

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..database.sql_database import AffectionLog, User
from ..utils.llm.llm_api_interface import LLMAPIFactory, LLMAPIInterface
from ..utils.logger import get_logger

# 好感度等级定义: (最低分数, 中文名称, 英文名称)
AFFECTION_LEVELS: List[Tuple[int, str, str]] = [
    (0, "萍水相逢", "Stranger"),    (100, "相识", "Acquaintance"),
    (300, "朋友", "Friend"),
    (600, "挚友", "Close Friend"),
    (1000, "知己", "Soulmate"),
    (1500, "羁绊", "Deep Bond"),
]

# 每日好感度变动上限（绝对值）
DAILY_AFFECTION_CAP = 5

# LLM 分析好感度的系统提示词
AFFECTION_ANALYSIS_PROMPT = """你是一个好感度分析专家，负责分析用户与虚拟角色"洛天依"之间的对话，判断好感度变化。

当前好感度等级：{level_name}（{level_score}分）

分析原则：
1. 根据用户消息的语气、态度、内容来判断好感度变化
2. 好感度变化范围：-3 到 +3
   - +3：用户表现出极大的喜爱、关心、称赞，或分享了很私密的感受
   - +2：用户很开心、热情，或表达了信任、依赖
   - +1：用户态度友好、积极，或进行了有意义的交流
   - 0：日常普通对话，无明显情感倾向
   - -1：用户态度略显冷淡、不耐烦，或轻微抱怨
   - -2：用户表现出明显的不满、生气、失望
   - -3：用户非常愤怒、厌恶，或表达了强烈的负面情绪
3. 考虑当前好感度等级：高好感度时，负面言语影响更大；低好感度时，正面互动提升更快
4. 仅根据本条消息的内容判断，不要过度解读

请以 JSON 格式输出：
{{
    "delta": <整数 -3 到 +3>,
    "reason": "<简短的中文原因>"
}}
"""


class AffectionManager:
    """好感度管理器"""

    def __init__(self, llm_config: Optional[Dict[str, Any]] = None):
        self.logger = get_logger("AffectionManager")
        self._llm_client: Optional[LLMAPIInterface] = None
        if llm_config:
            try:
                self._llm_client = LLMAPIFactory.create_interface(llm_config)
                self.logger.info(
                    f"好感度 LLM 客户端已初始化，模型: {llm_config.get('model')}"
                )
            except Exception as e:
                self.logger.warning(f"好感度 LLM 客户端初始化失败: {e}，将使用默认值")

    def set_llm_client(self, llm_config: Dict[str, Any]) -> None:
        """延迟设置 LLM 客户端"""
        if self._llm_client is None:
            try:
                self._llm_client = LLMAPIFactory.create_interface(llm_config)
            except Exception as e:
                self.logger.warning(f"设置好感度 LLM 客户端失败: {e}")

    async def analyze_affection(
        self, user_message: str, current_score: int
    ) -> Tuple[int, str]:
        """调用 LLM 分析用户消息，返回 (delta, reason)"""
        if self._llm_client is None:
            return 0, "LLM未初始化，不调整"

        level_cn, _ = self.get_level(current_score)
        prompt = AFFECTION_ANALYSIS_PROMPT.format(
            level_name=level_cn, level_score=current_score
        )
        user_prompt = f"用户消息：{user_message}"

        try:
            response = await self._llm_client.generate_response(
                f"{prompt}\n\n{user_prompt}", use_json=True
            )
            result = json.loads(response)
            delta = int(result.get("delta", 0))
            delta = max(-3, min(3, delta))  # 限制在 -3 到 +3
            reason = str(result.get("reason", "LLM分析"))[:50]
            return delta, reason
        except Exception as e:
            self.logger.warning(f"好感度 LLM 分析失败: {e}，使用默认值")
            return 0, "分析失败，不调整"

    def get_level(self, score: int) -> Tuple[str, str]:
        """根据分数返回好感度等级 (中文, 英文)"""
        level_cn = AFFECTION_LEVELS[0][1]
        level_en = AFFECTION_LEVELS[0][2]
        for min_score, cn, en in reversed(AFFECTION_LEVELS):
            if score >= min_score:
                level_cn = cn
                level_en = en
                break
        return level_cn, level_en

    def get_next_level_info(self, score: int) -> Optional[Tuple[str, str, int]]:
        """返回下一个等级的信息 (中文, 英文, 距升级所需分数)"""
        for min_score, cn, en in AFFECTION_LEVELS:
            if score < min_score:
                return cn, en, min_score - score
        return None

    def get_score(self, db: Session, user_id: str) -> int:
        """获取用户当前好感度"""
        user = db.query(User).filter(User.uuid == user_id).first()
        if user is None:
            return 0
        return user.affection_score or 0

    def get_today_net(self, db: Session, user_id: str) -> int:
        """获取用户今日好感度净变化量（绝对值之和）"""
        today = date.today()
        logs = (
            db.query(AffectionLog)
            .filter(
                AffectionLog.user_id == user_id,
                AffectionLog.created_at >= today,
            )
            .all()
        )
        return sum(abs(log.delta) for log in logs)

    def add_affection(
        self,
        db: Session,
        user_id: str,
        delta: int,
        reason: str,
    ) -> Tuple[int, int, int]:
        """记录好感度变化。返回 (actual_delta, score_after, today_total)"""
        user = db.query(User).filter(User.uuid == user_id).first()
        if user is None:
            self.logger.warning(f"User {user_id} not found, cannot add affection")
            return delta, 0, 0

        today_total = self.get_today_net(db, user_id)
        remaining = DAILY_AFFECTION_CAP - today_total
        if remaining <= 0:
            self.logger.info(
                f"User {user_id} daily affection cap reached ({today_total}), skipping"
            )
            return 0, user.affection_score or 0, today_total

        # 按剩余额度缩放 delta
        if abs(delta) > remaining:
            delta = remaining if delta > 0 else -remaining

        new_score = (user.affection_score or 0) + delta
        user.affection_score = max(0, new_score)
        if delta > 0:
            user.affection_total_gained = (user.affection_total_gained or 0) + delta

        log = AffectionLog(
            user_id=user_id,
            delta=delta,
            score_after=user.affection_score,
            reason=reason,
            created_at=datetime.now(),
        )
        db.add(log)
        db.commit()

        today_total = self.get_today_net(db, user_id)
        self.logger.info(
            f"Affection {delta:+d} for user {user_id}, "
            f"score={user.affection_score}, reason={reason}, today_total={today_total}"
        )
        return delta, user.affection_score, today_total

    def get_affection_context(self, db: Session, user_id: str) -> str:
        """生成用于注入 LLM prompt 的好感度上下文文本"""
        score = self.get_score(db, user_id)
        level_cn, level_en = self.get_level(score)
        next_level = self.get_next_level_info(score)

        parts = [f"当前好感度：{score}（{level_cn}）"]
        if next_level:
            parts.append(
                f"距离下一等级（{next_level[0]}）还差 {next_level[2]} 好感度"
            )
        return "（" + "，".join(parts) + "）"
