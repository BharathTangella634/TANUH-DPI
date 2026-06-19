import uuid
import hashlib
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, Boolean, UniqueConstraint
from sqlalchemy.sql import text
from ..db.session import Base, USE_SQLITE


def _new_hex_uuid() -> str:
    return uuid.uuid4().hex


_CREATED_AT_DEFAULT = text("CURRENT_TIMESTAMP") if USE_SQLITE else text("convert_tz(now(),'UTC','+05:30')")


class SessionLog(Base):
    __tablename__ = "session_logs"

    session_id    = Column(String(32), primary_key=True, default=_new_hex_uuid)
    user_id       = Column(String(32), nullable=False)
    ip_address    = Column(String(45),   nullable=False)
    state         = Column(String(100),  nullable=True)
    city          = Column(String(100),  nullable=True)
    document_type = Column(String(30),   nullable=True)
    pdf_location  = Column(Text,         nullable=True)
    json_location = Column(Text,         nullable=True)
    created_at    = Column(DateTime,     server_default=_CREATED_AT_DEFAULT)


class AuthToken(Base):
    __tablename__ = "auth_tokens"
    __table_args__ = (
        UniqueConstraint('email', 'service', 'created_date', name='uq_email_service_date'),
    )

    id                = Column(Integer,      primary_key=True, autoincrement=True)
    name              = Column(String(200),  nullable=False)
    email             = Column(String(255),  nullable=False)
    service           = Column(String(50),   nullable=False)
    token_hash        = Column(String(64),   nullable=False)
    access_granted_at = Column(DateTime,     nullable=False)
    access_expires_at = Column(DateTime,     nullable=False)
    expiry_days       = Column(Integer,      nullable=False, default=1)
    ip_address        = Column(String(45),   nullable=True)
    user_agent        = Column(String(512),  nullable=True)
    revoked           = Column(Boolean,      nullable=False, default=False)
    revoked_at        = Column(DateTime,     nullable=True)
    notes             = Column(Text,         nullable=True)
    encrypted_token   = Column(Text,         nullable=True)
    created_date      = Column(String(10),   nullable=True)
    created_at        = Column(DateTime,     server_default=_CREATED_AT_DEFAULT)

    @staticmethod
    def hash_token(raw_jwt: str) -> str:
        return hashlib.sha256(raw_jwt.encode()).hexdigest()


class Feedback(Base):
    __tablename__ = "feedbacks"

    id         = Column(Integer,      primary_key=True, autoincrement=True)
    service    = Column(String(50),   nullable=False)
    name       = Column(String(200),  nullable=False, default="Anonymous")
    place      = Column(String(200),  nullable=False, default="Anonymous place")
    feedback   = Column(Text,         nullable=False)
    ip_address = Column(String(45),   nullable=True)
    created_at = Column(DateTime,     server_default=_CREATED_AT_DEFAULT)


class User(Base):
    __tablename__ = "users"

    id           = Column(Integer,      primary_key=True, autoincrement=True)
    firebase_uid = Column(String(128),  nullable=False, unique=True)
    email        = Column(String(255),  nullable=False)
    full_name    = Column(String(200),  nullable=True)
    role         = Column(String(50),   nullable=False, default="user")
    created_at   = Column(DateTime,     server_default=_CREATED_AT_DEFAULT)
    updated_at   = Column(DateTime,     server_default=_CREATED_AT_DEFAULT, onupdate=datetime.now)
