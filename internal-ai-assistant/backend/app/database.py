from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DATABASE_URL

connect_args = {"check_same_thread": False}
if DATABASE_URL.startswith("sqlite"):
    connect_args["timeout"] = 30

engine = create_engine(DATABASE_URL, connect_args=connect_args)


@event.listens_for(engine, "connect")
def configure_sqlite_connection(dbapi_connection, _connection_record):
    if not DATABASE_URL.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA busy_timeout=30000")
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except Exception:
            # Docker Desktop + Windows bind mounts can reject SQLite WAL with disk I/O error.
            # Keep the service available and let SQLite use its default journal mode instead.
            pass
    finally:
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
