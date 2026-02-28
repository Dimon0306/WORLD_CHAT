# app/main.py
import os
import uuid
import logging
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, WebSocket, Request, Depends, HTTPException, status, File, UploadFile, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from datetime import timedelta

# Локальные импорты
from app import models, schemas, crud, auth
from app.database import engine, SessionLocal, get_db
from app.models import User  # ← Добавлен недостающий импорт

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Инициализация FastAPI ===
app = FastAPI(title="Chat App")

# Шаблоны и статика
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Директория для загрузок
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Хранилище сообщений (в памяти)
messages = []

# Активные WebSocket соединения
active_connections: list[dict] = []

# === Проверка DATABASE_URL ===
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("❌ DATABASE_URL не задан в переменных окружения!")
    # Не выбрасываем ошибку здесь, чтобы приложение хотя бы запустилось для проверки

# === Инициализация БД при старте ===
@app.on_event("startup")
def startup_event():
    """Создание таблиц при запуске (безопасно)"""
    try:
        logger.info("🔄 Инициализация базы данных...")
        # Создаём таблицы, если их нет
        models.Base.metadata.create_all(bind=engine)
        logger.info("✅ Таблицы созданы/проверены")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        # Не останавливаем сервер, но логируем ошибку

@app.on_event("shutdown")
def shutdown_event():
    """Очистка при завершении"""
    logger.info("🛑 Завершение работы приложения")
    engine.dispose()

# === Маршруты ===

@app.get("/", response_class=HTMLResponse)
async def get_chat_page(request: Request):
    """Главная страница чата"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
def health_check():
    """Эндпоинт для проверки работоспособности (для Render)"""
    return {"status": "ok", "service": "chat-app"}

@app.head("/health")
def health_check_head():
    """Поддержка HEAD-запросов от Render"""
    return JSONResponse(content={"status": "ok"})

@app.get("/messages")
def get_messages():
    """Получение всех сообщений"""
    return messages

@app.get("/api/check-username")
def check_username(username: str = Query(...), db: Session = Depends(get_db)):
    """Проверка доступности имени пользователя"""
    # User теперь импортирован корректно
    exists = db.query(User).filter(User.username == username).first() is not None
    return {"available": not exists}

# === Загрузка файлов ===
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Загрузка файла с генерацией уникального имени"""
    ext = Path(file.filename).suffix
    safe_filename = f"{uuid.uuid4().hex}{ext}"
    file_path = UPLOAD_DIR / safe_filename

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    logger.info(f"📁 Файл загружен: {safe_filename}")
    return {"filename": safe_filename, "url": f"/static/{safe_filename}"}

# === Регистрация и авторизация ===
@app.post("/register", response_model=schemas.User)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    """Регистрация нового пользователя"""
    # Проверка длины пароля для bcrypt
    if len(user.password.encode('utf-8')) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is too long (max 72 bytes for bcrypt)"
        )
    
    db_user = crud.get_user_by_username(db, user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    return crud.create_user(db=db, user=user)

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Вход пользователя и получение токена"""
    user = crud.get_user_by_username(db, form_data.username)
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = auth.create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users", response_model=list[schemas.User])
def get_users(db: Session = Depends(get_db)):
    """Получение списка всех пользователей"""
    return crud.get_all_users(db)

# === WebSocket для чата ===
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Обработчик WebSocket соединений для чата"""
    # Получаем токен из query-параметров
    query_string = websocket.scope.get("query_string", b"").decode()
    query_params = parse_qs(query_string)
    token = query_params.get("token", [None])[0]

    # Проверка наличия токена
    if not token:
        logger.warning("⚠️ WebSocket подключился без токена")
        await websocket.close(code=4000)
        return

    # Валидация JWT токена
    try:
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise JWTError("Username not in token")
    except JWTError as e:
        logger.warning(f"⚠️ Неверный токен: {e}")
        await websocket.close(code=4001)
        return

    # Проверка пользователя в БД
    db = SessionLocal()
    try:
        user = crud.get_user_by_username(db, username)
        if not user:
            logger.warning(f"⚠️ Пользователь {username} не найден")
            await websocket.close(code=4002)
            return
    finally:
        db.close()

    # Принимаем соединение
    await websocket.accept()
    active_connections.append({"websocket": websocket, "user": user})
    logger.info(f"🔗 Подключился пользователь: {user.username}")

    try:
        while True:
            data = await websocket.receive_text()
            message = f"{user.username}: {data}"
            messages.append({"user": user.username, "text": data})  # Сохраняем в историю
            
            # Рассылаем сообщение всем подключённым
            disconnected = []
            for conn in active_connections:
                try:
                    await conn["websocket"].send_text(message)
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки: {e}")
                    disconnected.append(conn)
            
            # Удаляем отключившихся
            for conn in disconnected:
                if conn in active_connections:
                    active_connections.remove(conn)
                    
    except Exception as e:
        logger.info(f"🔌 Пользователь {user.username} отключился: {e}")
    finally:
        # Гарантированная очистка
        active_connections[:] = [c for c in active_connections if c["websocket"] != websocket]
        logger.info(f"🧹 Соединение {user.username} очищено")
