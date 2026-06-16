"""
Separate SQLAlchemy engine + session for the CRM database (ctr_db).

Kept completely isolated from the main scanner_db engine so migrations,
table creation, and sessions never cross databases.
"""
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from core.config import get_settings

logger = logging.getLogger(__name__)

CrmBase = declarative_base()


def _make_crm_engine():
    url = get_settings().crm_database_url
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        return create_engine(url, connect_args={"check_same_thread": False}, echo=False)
    return create_engine(
        url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=False,
    )


crm_engine = _make_crm_engine()

CrmSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=crm_engine,
)


def get_crm_db():
    """FastAPI dependency — yields a ctr_db session."""
    db: Session = CrmSessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
