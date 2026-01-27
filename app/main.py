# app/main.py
from fastapi import FastAPI, WebSocket, Request, Depends, HTTPException, status, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from urllib.parse import parse_qs
from jose import jwt, JWTError
from datetime import timedelta
from pathlib import Path
from app.auth import create_access_token
import uuid
import os

from app import models, schemas, crud, auth
from app.database import engine, get_db

models.Base.metadata.create_all(bind=engine)


app = FastAPI()
    
templates = Jinja2Templates(directory="app/templates")

# Хранилище активных соединений: {websocket: user}
active_connections = []

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

messages = []

@app.get("/", response_class=HTMLResponse)
async def get_chat_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/messages")
def get_messages():
    return messages

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Вы написали: {data}")


# добавления файла
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    # Генерируем безопасное уникальное имя
    ext = Path(file.filename).suffix  # .jpg, .pdf и т.д.
    safe_filename = f"{uuid.uuid4().hex}{ext}"
    file_path = UPLOAD_DIR / safe_filename

    # Сохраняем файл
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    return {"filename": safe_filename}
 

@app.post("/register", response_model=schemas.User)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    if len(user.password.encode('utf-8')) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is too long (max 72 bytes)"
        )
    db_user = crud.get_user_by_username(db, user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    return crud.create_user(db=db, user=user)

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
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
    users = crud.get_all_users(db)
    return users

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    from app.database import SessionLocal
    db = SessionLocal()

    query_params = parse_qs(websocket.scope["query_string"].decode())
    token = query_params.get("token", [None])[0]

    if not token:
        await websocket.close(code=4000)
        db.close()
        return

    try:
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise JWTError()
    except JWTError:
        await websocket.close(code=4001)
        db.close()
        return

    user = crud.get_user_by_username(db, username)
    db.close()

    if not user:
        await websocket.close(code=4002)
        return

    await websocket.accept()
    active_connections.append({"websocket": websocket, "user": user})

    try:
        while True:
            data = await websocket.receive_text()
            message = f"{user.username}: {data}"
            disconnected = []
            for conn in active_connections:
                try:
                    await conn["websocket"].send_text(message)
                except:
                    disconnected.append(conn)
            for conn in disconnected:
                active_connections.remove(conn)
    except:
        active_connections[:] = [c for c in active_connections if c["websocket"] != websocket]