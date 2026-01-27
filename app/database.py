from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# Получаем DATABASE_URL из переменной окружения (Render задаёт её автоматически)
DATABASE_URL = os.getenv("DATABASE_URL")

# Убедимся, что URL начинается с postgresql:// (а не postgres://)
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Настройка движка для PostgreSQL (без connect_args для SQLite!)
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "sslmode": "require"  # Обязательно для Render
    }
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
