import os
from time import monotonic, time

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBearer
from pydantic import BaseModel, Field

from app.db import get_db

router = APIRouter(prefix="/auth", tags=["Пользователи"])
basic = HTTPBasic(auto_error=False)
bearer = HTTPBearer(auto_error=False)
hasher = PasswordHasher()
dummy_hash = hasher.hash("not-a-user-password")
failures = {}


class Credentials(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,64}$")
    password: str = Field(min_length=1, max_length=128)


def unauthorized():
    raise HTTPException(401, "Неверные данные для входа",
                        headers={"WWW-Authenticate": 'Basic realm="diary", Bearer'})


# Проверка пароля и лимит из пяти ошибок за минуту.
def verify_password(db, request, username, password):
    now = monotonic()
    for key, times in list(failures.items()):
        active = [stamp for stamp in times if now - stamp < 60]
        if active:
            failures[key] = active
        else:
            del failures[key]
    key = (request.client.host if request.client else "", username)
    attempts = failures.get(key, [])
    if len(attempts) >= 5:
        raise HTTPException(429, "Слишком много попыток входа",
                            headers={"Retry-After": str(int(60 - (now - attempts[0])) + 1)})
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if len(password) <= 128:
        try:
            hasher.verify(user["password_hash"] if user else dummy_hash, password)
        except VerifyMismatchError:
            pass
        else:
            if user:
                failures.pop(key, None)
                return {"id": user["id"], "username": user["username"], "role": user["role"]}
    failures[key] = attempts + [now]
    unauthorized()


# Один способ получить текущего пользователя для всех защищённых маршрутов.
async def current_user(request: Request, db=Depends(get_db),
                       credentials=Depends(basic), token=Depends(bearer)):
    if credentials:
        return verify_password(db, request, credentials.username, credentials.password)
    secret = os.getenv("JWT_SECRET")
    if token and secret:
        try:
            claims = jwt.decode(token.credentials, secret, algorithms=["HS256"],
                                options={"require": ["sub", "exp"]})
        except jwt.InvalidTokenError:
            unauthorized()
        user = db.execute(
            "SELECT id, username, role FROM users WHERE username = ?", (claims["sub"],)
        ).fetchone()
        if user:
            return dict(user)
    unauthorized()


@router.post("/register", status_code=201, summary="Зарегистрироваться")
async def register(data: Credentials, db=Depends(get_db)):
    if len(data.password) < 8:
        raise HTTPException(400, "Пароль должен содержать хотя бы 8 символов")
    with db:
        cursor = db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?) "
            "ON CONFLICT(username) DO NOTHING",
            (data.username, hasher.hash(data.password)),
        )
        if not cursor.rowcount:
            raise HTTPException(409, "Логин уже занят")
    return {"id": cursor.lastrowid, "username": data.username, "role": "user"}


@router.get("/me", summary="Посмотреть текущего пользователя")
async def me(user=Depends(current_user)):
    return user


@router.post("/login", summary="Получить токен JWT")
async def login(data: Credentials, request: Request, db=Depends(get_db)):
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise HTTPException(503, "JWT не настроен")
    user = verify_password(db, request, data.username, data.password)
    expires = int(time()) + int(os.getenv("JWT_TTL_SECONDS", "3600"))
    token = jwt.encode({"sub": user["username"], "exp": expires}, secret, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer"}


# Администратор создаётся только из настроек сервера.
def create_admin(db):
    username = os.getenv("ADMIN_USERNAME")
    password = os.getenv("ADMIN_PASSWORD")
    if not username and not password:
        return
    if not username or not password or not 8 <= len(password) <= 128:
        raise RuntimeError("Задайте ADMIN_USERNAME и ADMIN_PASSWORD (от 8 до 128 символов)")
    Credentials(username=username, password=password)
    with db:
        row = db.execute("SELECT role FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            db.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
                       (username, hasher.hash(password)))
        elif row["role"] != "admin":
            raise RuntimeError("Логин администратора занят обычным пользователем")
