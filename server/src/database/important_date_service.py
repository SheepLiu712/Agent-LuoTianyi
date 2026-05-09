"""
ImportantDate 数据库服务

管理用户重要日期（生日、纪念日、节假日等）的统一 CRUD 接口。
"""
from datetime import date, datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from ..database.sql_database import ImportantDate
from ..utils.logger import get_logger

logger = get_logger("important_date_service")


def add_or_update_date(
    db: Session,
    user_id: Optional[str],
    name: str,
    date_type: str,
    date_str: str,
    is_lunar: bool = False,
    is_recurring: bool = False,
    description: str = "",
    reminder_advance: str = "0",
) -> Tuple[bool, str]:
    """添加或更新重要日期。如果同用户同名称的日期已存在，则更新。"""
    existing = None
    query = db.query(ImportantDate).filter(
        ImportantDate.name == name,
        ImportantDate.date_type == date_type,
    )
    if user_id:
        query = query.filter(ImportantDate.user_id == user_id)
    else:
        query = query.filter(ImportantDate.user_id.is_(None))
    existing = query.first()

    now = datetime.now()
    if existing:
        existing.date_str = date_str
        existing.is_lunar = is_lunar
        existing.is_recurring = is_recurring
        existing.description = description or existing.description
        existing.reminder_advance = reminder_advance
        existing.updated_at = now
        logger.info(f"Updated important date: {name} ({date_type}) -> {date_str}")
    else:
        entry = ImportantDate(
            user_id=user_id,
            name=name,
            date_type=date_type,
            date_str=date_str,
            is_lunar=is_lunar,
            is_recurring=is_recurring,
            description=description,
            reminder_advance=reminder_advance,
            created_at=now,
            updated_at=now,
        )
        db.add(entry)
        logger.info(f"Added important date: {name} ({date_type}) -> {date_str}")

    db.commit()
    return True, "操作成功"


def get_user_dates(db: Session, user_id: str) -> List[ImportantDate]:
    """获取某个用户的所有重要日期（包括全局日期）。"""
    return (
        db.query(ImportantDate)
        .filter(
            (ImportantDate.user_id == user_id) | (ImportantDate.user_id.is_(None))
        )
        .all()
    )


def get_today_important_dates(db: Session, user_id: str) -> List[ImportantDate]:
    """获取今天对该用户重要的事件列表。

    匹配逻辑：
    - 非周期性：date_str 精确匹配今天 YYYY-MM-DD
    - 周期性：date_str 的 MM-DD 部分匹配今天
    - 包括全局事件（user_id is None）和用户专属事件
    """
    today = date.today()
    today_ymd = today.isoformat()  # YYYY-MM-DD
    today_md = today_ymd[5:]  # MM-DD

    all_dates = get_user_dates(db, user_id)
    result = []
    for d in all_dates:
        ds = d.date_str
        if d.is_recurring:
            # 周期性事件：比较 MM-DD 部分
            if ds.endswith(today_md) or ds == today_md:
                result.append(d)
        else:
            # 非周期性：精确匹配
            if ds == today_ymd:
                result.append(d)
    return result


def get_upcoming_dates(
    db: Session, user_id: str, days_ahead: int = 7
) -> List[ImportantDate]:
    """获取未来 N 天内的事件（用于提前提醒）。"""
    today = date.today()
    results = []
    for offset in range(days_ahead + 1):
        target = date.fromordinal(today.toordinal() + offset)
        target_str = target.isoformat()
        target_md = target_str[5:]

        all_dates = get_user_dates(db, user_id)
        for d in all_dates:
            if d.is_recurring:
                if d.date_str == target_md or d.date_str.endswith(target_md):
                    if d not in results:
                        results.append(d)
            else:
                if d.date_str == target_str and d not in results:
                    results.append(d)
    return results


def delete_date(db: Session, date_id: str) -> bool:
    """删除指定 ID 的重要日期。"""
    entry = db.query(ImportantDate).filter(ImportantDate.id == date_id).first()
    if not entry:
        return False
    db.delete(entry)
    db.commit()
    logger.info(f"Deleted important date: {entry.name} (id={date_id})")
    return True


def seed_holidays(db: Session):
    """预写入常见节假日（周期性事件）。"""
    holidays = [
        ("元旦", "节日", "01-01", "元旦节"),
        ("春节", "节日", "01-29", "农历正月初一"),  # 简化：实际需农历
        ("元宵节", "节日", "02-12", "农历正月十五"),
        ("情人节", "节日", "02-14", "情人节"),
        ("妇女节", "节日", "03-08", "国际妇女节"),
        ("植树节", "节日", "03-12", "植树节"),
        ("愚人节", "节日", "04-01", "愚人节"),
        ("劳动节", "节日", "05-01", "劳动节"),
        ("青年节", "节日", "05-04", "青年节"),
        ("端午节", "节日", "05-31", "农历五月初五"),
        ("儿童节", "节日", "06-01", "儿童节"),
        ("七夕节", "节日", "08-29", "农历七月初七"),
        ("中秋节", "节日", "10-06", "农历八月十五"),
        ("国庆节", "节日", "10-01", "国庆节"),
        ("重阳节", "节日", "10-29", "农历九月初九"),
        ("平安夜", "节日", "12-24", "平安夜"),
        ("圣诞节", "节日", "12-25", "圣诞节"),
        ("洛天依诞生日", "节日", "07-12", "洛天依的诞生日（官方出道日）"),
    ]
    count = 0
    for name, date_type, date_str, desc in holidays:
        try:
            add_or_update_date(
                db=db,
                user_id=None,
                name=name,
                date_type=date_type,
                date_str=date_str,
                is_lunar=False,
                is_recurring=True,
                description=desc,
            )
            count += 1
        except Exception as e:
            logger.warning(f"Failed to seed holiday {name}: {e}")
    logger.info(f"Seeded {count} holidays")
    return count
