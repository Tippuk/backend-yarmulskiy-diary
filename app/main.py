import logging
import os
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import date
from pathlib import Path
from time import perf_counter

from alembic import command
from alembic.config import Config
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# Подключение к файлу SQLite
def connect():
    db = sqlite3.connect(os.getenv("DATABASE_PATH", "diary.db"))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.create_function("casefold", 1, str.casefold)
    return db


def migrate():
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")


# Применение миграций при запуске сервера
@asynccontextmanager
async def lifespan(app):
    migrate()
    yield


# Отдельное подключение к базе для каждого запроса
async def get_db():
    with closing(connect()) as db:
        yield db


app = FastAPI(title="Электронный дневник", lifespan=lifespan)
logger = logging.getLogger("uvicorn.error")


# Переход на Swagger с главной страницы
@app.get("/", include_in_schema=False)
async def home():
    return RedirectResponse(url="/docs")


# Ответ 400 при неверных данных
def bad_request(message, field):
    raise HTTPException(400, detail={"error": message, "field": field})


# Проверка номера и буквы класса
def check_class(value):
    if not isinstance(value, str):
        bad_request("Класс должен быть строкой", "school_class")

    value = value.strip()
    if len(value) < 2 or value[:-1] not in [str(n) for n in range(1, 12)]:
        bad_request("Укажите класс от 1 до 11 с буквой, например 8А", "school_class")
    if value[-1] not in "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯABCDEFGHIJKLMNOPQRSTUVWXYZ":
        bad_request("После номера класса нужна заглавная буква", "school_class")
    return value


# Проверка данных ученика
def check_student(data, creating=False):
    result = data.copy()
    for field in result:
        if field not in ["full_name", "school_class", "status"]:
            bad_request("Неизвестное поле", field)

    if creating:
        for field in ["full_name", "school_class"]:
            if field not in result:
                bad_request("Обязательное поле", field)
        if "status" not in result:
            result["status"] = "active"

    if "full_name" in result:
        name = result["full_name"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 150:
            bad_request("ФИО должно быть строкой от 1 до 150 символов", "full_name")
        result["full_name"] = name.strip()

    if "school_class" in result:
        result["school_class"] = check_class(result["school_class"])

    if "status" in result and result["status"] not in ["active", "inactive"]:
        bad_request("Статус: active или inactive", "status")
    return result


# Единый формат ответов с ошибками
@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    if isinstance(exc.detail, dict):
        body = exc.detail
    else:
        body = {"error": str(exc.detail), "field": "request"}
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


# Ответ 400, если FastAPI не смог разобрать запрос
@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    error = exc.errors()[0]
    field = str(error["loc"][-1])
    if error["type"] == "json_invalid":
        field = "body"
    return JSONResponse(
        status_code=400,
        content={"error": error["msg"], "field": field},
    )


# Запись запроса и времени обработки в лог
@app.middleware("http")
async def log_request(request: Request, call_next):
    start = perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        duration = (perf_counter() - start) * 1000
        logger.info(f"{request.method} {request.url.path} {status} {duration:.2f}ms")


# Поиск ученика по ID
def find_student(db, student_id):
    row = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if row is None:
        raise HTTPException(404, detail={"error": "Ученик не найден", "field": "id"})
    return dict(row)


# Проверка работы сервера
@app.get("/health", tags=["Сервер"], summary="Проверить работу сервера",
         response_description="Сервер работает")
async def health():
    return {"status": "ok"}


# Добавление ученика
@app.post("/api/students", status_code=201, tags=["Ученики"], summary="Добавить ученика",
          response_description="Ученик добавлен")
async def create_student(
    data: dict = Body(examples=[{"full_name": "Иванов Иван", "school_class": "8А"}]),
    db=Depends(get_db),
):
    student = check_student(data, creating=True)
    with db:
        cursor = db.execute(
            "INSERT INTO students (full_name, school_class, status) VALUES (?, ?, ?)",
            (student["full_name"], student["school_class"], student["status"]),
        )
    student["id"] = cursor.lastrowid
    return student


# Список учеников с фильтром и поиском по ФИО
@app.get("/api/students", tags=["Ученики"], summary="Посмотреть список учеников",
         response_description="Список учеников")
async def list_students(
    limit: int = Query(10, description="Сколько учеников показать"),
    offset: int = Query(0, description="Сколько учеников пропустить"),
    school_class: str | None = Query(None, description="Фильтр по классу, например 8А"),
    q: str = Query("", description="Поиск по ФИО без учёта регистра"),
    db=Depends(get_db),
):
    if limit < 1 or limit > 100:
        bad_request("limit должен быть от 1 до 100", "limit")
    if offset < 0:
        bad_request("offset не может быть отрицательным", "offset")
    conditions = []
    params = []
    if school_class is not None:
        conditions.append("school_class = ?")
        params.append(check_class(school_class))
    if q.strip():
        conditions.append("instr(casefold(full_name), casefold(?)) > 0")
        params.append(q.strip())
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows = db.execute("SELECT * FROM students" + where + " ORDER BY id LIMIT ? OFFSET ?",
                      (*params, limit, offset))
    return [dict(row) for row in rows]


# Средний балл и количество оценок по каждому предмету
@app.get("/api/students/stats", tags=["Оценки"], summary="Посмотреть статистику по предметам",
         response_description="Средний балл и количество оценок по каждому предмету")
async def student_stats(db=Depends(get_db)):
    rows = db.execute(
        """SELECT subject, AVG(score) AS average_score, COUNT(*) AS grade_count
           FROM grades GROUP BY subject ORDER BY subject"""
    )
    return [dict(row) for row in rows]


# Получение одного ученика
@app.get("/api/students/{student_id}", tags=["Ученики"], summary="Посмотреть ученика",
         response_description="Данные ученика")
async def get_student(student_id: int, db=Depends(get_db)):
    return find_student(db, student_id)


# Изменение переданных полей ученика
@app.patch("/api/students/{student_id}", tags=["Ученики"], summary="Изменить данные ученика",
           response_description="Обновлённые данные ученика")
async def update_student(
    student_id: int, data: dict = Body(examples=[{"school_class": "9А"}]), db=Depends(get_db)
):
    student = find_student(db, student_id)
    student.update(check_student(data))
    with db:
        db.execute(
            "UPDATE students SET full_name = ?, school_class = ?, status = ? WHERE id = ?",
            (student["full_name"], student["school_class"], student["status"], student_id),
        )
    return student


# Удаление ученика и его оценок
@app.delete("/api/students/{student_id}", status_code=204, tags=["Ученики"],
            summary="Удалить ученика", response_description="Ученик и его оценки удалены")
async def delete_student(student_id: int, db=Depends(get_db)):
    find_student(db, student_id)
    with db:
        db.execute("DELETE FROM students WHERE id = ?", (student_id,))
    return Response(status_code=204)


# Добавление оценки ученику
@app.post("/api/students/{student_id}/grades", status_code=201, tags=["Оценки"],
          summary="Поставить оценку", response_description="Оценка добавлена",
          responses={409: {"description": "Оценка по этому предмету за эту дату уже есть"}})
async def create_grade(
    student_id: int,
    data: dict = Body(examples=[{"subject": "Математика", "score": 5, "date": "2026-11-07"}]),
    db=Depends(get_db),
):
    subject = data.get("subject")
    score = data.get("score")
    if not isinstance(subject, str) or not subject.strip():
        bad_request("Укажите предмет", "subject")
    if type(score) is not int or not 2 <= score <= 5:
        bad_request("Оценка должна быть целым числом от 2 до 5", "score")
    try:
        day = date.fromisoformat(data.get("date")).isoformat()
    except (TypeError, ValueError):
        bad_request("Укажите дату в формате ГГГГ-ММ-ДД", "date")
    subject = subject.strip()
    with db:
        cursor = db.execute(
            """INSERT INTO grades (student_id, subject, score, date)
               SELECT id, ?, ?, ? FROM students WHERE id = ?
               ON CONFLICT(student_id, subject, date) DO NOTHING""",
            (subject, score, day, student_id),
        )
        if cursor.rowcount == 0:
            find_student(db, student_id)
            raise HTTPException(409, detail={
                "error": "У ученика уже есть оценка по этому предмету за эту дату",
                "field": "date",
            })
    return {"id": cursor.lastrowid, "student_id": student_id, "subject": subject, "score": score, "date": day}


# Список оценок ученика
@app.get("/api/students/{student_id}/grades", tags=["Оценки"],
         summary="Посмотреть оценки ученика", response_description="Список оценок ученика")
async def list_grades(student_id: int, db=Depends(get_db)):
    find_student(db, student_id)
    rows = db.execute("SELECT * FROM grades WHERE student_id = ? ORDER BY id", (student_id,))
    return [dict(row) for row in rows]
