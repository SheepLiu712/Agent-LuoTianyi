from sqlalchemy import create_engine, Column, String, Integer, DateTime, Boolean, ForeignKey, Text, Engine, event, text
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


class ImportantDate(Base):
    """用户重要日期记录"""
    __tablename__ = "important_dates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    date_type = Column(String, nullable=False)       # 生日/纪念日/节日/其他
    date_mmdd = Column(String, nullable=False)        # MM-DD
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


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
    for migration in [
        "ALTER TABLE users ADD COLUMN preferences Text DEFAULT '{}'",
        "ALTER TABLE users ADD COLUMN affection_score Integer DEFAULT 0",
        "ALTER TABLE users ADD COLUMN affection_total_gained Integer DEFAULT 0",
    ]:
        try:
            with engine.connect() as conn:
                conn.execute(text(migration))
                conn.commit()
        except Exception as e:
            print(f"列已存在或迁移失败，跳过: {migration}")
            print(f"错误详情: {e}")
                conn.execute(migration)
                conn.commit()
        except Exception:
            pass  # 列已存在，无需迁移

def get_sql_db(): # Generator for FastAPI
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_sql_session(): # Direct session for scripts
    return SessionLocal()
