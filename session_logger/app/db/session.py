import os
import time
import logging
from sqlalchemy import create_engine, text as sa_text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from ..core.config import settings

logger = logging.getLogger(__name__)

connect_args = {}
USE_SQLITE = False
db_url = None

if settings.MYSQL_USER and settings.MYSQL_PASSWORD:
    _mysql_url = settings.DATABASE_URL
    for _attempt in range(5):
        try:
            _test_engine = create_engine(_mysql_url, pool_pre_ping=True)
            with _test_engine.connect() as conn:
                conn.execute(sa_text("SELECT 1"))
            db_url = _mysql_url
            logger.info("Connected to MySQL via Cloud SQL Proxy: %s:%s/%s",
                         settings.MYSQL_HOST, settings.MYSQL_PORT, settings.MYSQL_DB)
            break
        except Exception as exc:
            if _attempt < 4:
                logger.info("MySQL connection attempt %d/5 failed, retrying in 3s...", _attempt + 1)
                time.sleep(3)
            else:
                logger.warning("MySQL connection failed after 5 attempts (%s) — falling back to SQLite", exc)

if db_url is None:
    USE_SQLITE = True
    _db_dir = os.environ.get('SQLITE_DATA_DIR', os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    os.makedirs(_db_dir, exist_ok=True)
    _db_path = os.path.join(_db_dir, "local_session.db")
    db_url = f"sqlite:///{_db_path}"
    connect_args = {"check_same_thread": False, "timeout": 30}
    if not (settings.MYSQL_USER and settings.MYSQL_PASSWORD):
        logger.info("MySQL credentials not found — using local SQLite: %s", _db_path)

engine = create_engine(
    db_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency — yields a DB session and ensures it is closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
