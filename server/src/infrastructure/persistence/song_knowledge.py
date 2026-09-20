import uuid
from pathlib import Path
from typing import Dict

from sqlalchemy import Column, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

Base = declarative_base()


class Song(Base):
    __tablename__ = "songs"

    uuid = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    safe_name = Column(String, nullable=False)
    uploader = Column(String, nullable=True)  # UP主
    singers = Column(String, nullable=True)  # 演唱
    introduction = Column(Text, nullable=False)  # short_summary
    lyrics = Column(Text, nullable=False)  # lyrics (cleaned)


SessionLocal = None
engine = None


def init_song_db(config: Dict):
    """Initialize database tables"""
    global engine, SessionLocal

    db_folder: str = config.get("db_folder", None)
    db_file: str = config.get("db_file", None)

    # Ensure directory exists
    Path(db_folder).mkdir(parents=True, exist_ok=True)

    database_url = f"sqlite:///{Path(db_folder) / db_file}"

    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)


def get_song_db():
    """Generator for database session"""
    global SessionLocal
    if SessionLocal is None:
        # Fallback default path if not initialized explicitly
        init_song_db(
            {
                "db_folder": str(Path(__file__).resolve().parents[3] / "res" / "knowledge"),
                "db_file": "knowledge_db.db",
            }
        )
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_song_session() -> Session:
    """Direct session"""
    global SessionLocal
    if SessionLocal is None:
        # Fallback default path if not initialized explicitly
        init_song_db(
            {
                "db_folder": str(Path(__file__).resolve().parents[3] / "res" / "knowledge"),
                "db_file": "knowledge_db.db",
            }
        )
    return SessionLocal()
