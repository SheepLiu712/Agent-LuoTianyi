from sqlalchemy import create_engine, Column, String, Integer, DateTime, Boolean, ForeignKey, Text, Engine, event, text, UniqueConstraint
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from datetime import datetime
import uuid
import os

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    uuid = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False) # Plain text as per requirements
    created_at = Column(DateTime, default=datetime.now)
    last_login = Column(DateTime, nullable=True)
    nickname = Column(String, default="你")
    description = Column(Text, default="")
    context_summary = Column(Text, default="")
    context_memory_count = Column(Integer, default=0)
    all_memory_count = Column(Integer, default=0)
    auth_token = Column(String, nullable=True)
    preferences = Column(Text, default="{}")
    affection_score = Column(Integer, default=0)
    affection_total_gained = Column(Integer, default=0)

    # Relationships
    invite_code = relationship("InviteCode", uselist=False, back_populates="user")
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    knowledge_buffers = relationship("KnowledgeBuffer", back_populates="user", cascade="all, delete-orphan")
    memory_records = relationship("MemoryRecord", back_populates="user", cascade="all, delete-orphan")
    memory_update_records = relationship("MemoryUpdateRecord", back_populates="user", cascade="all, delete-orphan")
    affection_logs = relationship("AffectionLog", back_populates="user", cascade="all, delete-orphan")

class InviteCode(Base):
    __tablename__ = "invite_codes"
    
    code = Column(String, primary_key=True)
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    used_at = Column(DateTime, nullable=True)
    user_id = Column(String, ForeignKey("users.uuid"), nullable=True, unique=True)
    
    user = relationship("User", back_populates="invite_code")

class Conversation(Base):
    __tablename__ = "conversations"
    
    uuid = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.uuid"), nullable=False)
    timestamp = Column(DateTime, default=datetime.now)
    source = Column(String, nullable=False) # 'user' or 'agent'
    type = Column(String, nullable=False) # 'text' or 'audio' or 'image'
    content = Column(Text, nullable=False)
    meta_data = Column(Text, nullable=True)
    
    user = relationship("User", back_populates="conversations")

class MemoryRecord(Base):
    __tablename__ = "memory_records"
    
    uuid = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.uuid"), nullable=False)
    type = Column(String, default="text")
    content = Column(Text, nullable=False)
    meta_data = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("User", back_populates="memory_records")

class MemoryUpdateRecord(Base):
    __tablename__ = "memory_update_records"
    update_cmd_uuid = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.uuid"), nullable=False)
    update_command = Column(Text, nullable=False) # JSON serialized MemoryUpdateCommand
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("User", back_populates="memory_update_records")

class KnowledgeBuffer(Base):
    __tablename__ = "knowledge_buffers"

    uuid = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.uuid"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("User", back_populates="knowledge_buffers")


class AffectionLog(Base):
    __tablename__ = "affection_logs"

    uuid = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.uuid"), nullable=False)
    delta = Column(Integer, nullable=False)
    score_after = Column(Integer, nullable=False)
    reason = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("User", back_populates="affection_logs")


class Event(Base):
    """统一事件管理系统：存储所有类型的事件（包括用户生日/纪念日）。"""
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type = Column(String, nullable=False, index=True)        # concert / livestream / holiday / birthday / anniversary / travel / new_song / dynamic / general
    title = Column(String, nullable=False)                          # 事件标题
    description = Column(Text, default="")                          # 事件描述

    # 用户关联（针对 birthday / anniversary 等个人事件）
    user_id = Column(String, nullable=True, index=True)             # 关联的用户 UUID

    # 日期相关
    date_type = Column(String, default="solar")                     # solar / lunar
    date_mmdd = Column(String, nullable=True)                       # MM-DD（用于周期性事件）
    start_datetime = Column(DateTime, nullable=True)                # 开始日期时间（非周期性事件）
    end_datetime = Column(DateTime, nullable=True)                  # 结束日期时间
    duration_minutes = Column(Integer, nullable=True)               # 持续时间（分钟）

    # 触发条件
    trigger_conditions = Column(Text, default="[]")                # JSON list of trigger strings
    is_recurring = Column(Boolean, default=False)                   # 是否周期性（每年重复）
    is_personal = Column(Boolean, default=False)                    # 是否仅对特定用户有意义
    target_user_id = Column(String, nullable=True, index=True)      # 如果 is_personal，关联的用户 UUID

    # 来源信息
    source = Column(String, default="")                              # bilibili / system / user / citywalk / song_learner
    source_url = Column(String, default="")
    source_platform = Column(String, default="")

    # 状态
    is_active = Column(Boolean, default=True)                       # 是否活跃
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class EventNotification(Base):
    """事件通知记录：记录哪些事件已经通知过哪些用户。"""
    __tablename__ = "event_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, ForeignKey("events.id"), nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    trigger_key = Column(String, nullable=False)                    # 触发的条件名称，如 "day_of_event", "1_day_before"
    notified_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        # 同一事件同一用户的同一触发条件不重复通知
        UniqueConstraint("event_id", "user_id", "trigger_key", name="uq_event_notification"),
    )


# Database URL
SessionLocal = None
engine = None

def init_sql_db(db_folder: str = None, db_file: str = None):
    """Initialize database tables"""
    global engine, SessionLocal
    DATABASE_URL = f"sqlite:///{os.path.join(db_folder, db_file)}"

    # Create engine and session factory globally
    if not os.path.exists(db_folder):
        os.makedirs(db_folder, exist_ok=True)

    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

    # 2. 注册监听器：在每个连接建立时执行 WAL 开启指令
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        # 开启 WAL 模式
        cursor.execute("PRAGMA journal_mode=WAL")
        # 建议同时开启：同步模式设为 NORMAL，能显著提升写入速度且保证断电安全
        cursor.execute("PRAGMA synchronous=NORMAL")
        # 建议同时设置：忙等待超时时间（毫秒），防止并发写入时立刻报错
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    # 迁移：为已存在的数据库添加新列


def get_sql_db(): # Generator for FastAPI
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_sql_session(): # Direct session for scripts
    return SessionLocal()
