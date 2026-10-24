import logging
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import Body, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

@asynccontextmanager
async def lifespan(app):
    logging.getLogger("uvicorn.error").info(
        "Открой в браузере (при запуске на порту 8000): http://localhost:8000/docs"
    )
    yield


app = FastAPI(title="Электронный дневник", lifespan=lifespan)

students = {}
next_id = 1
logger = logging.getLogger("uvicorn.error")


@app.get("/", include_in_schema=False)
async def home():
    return RedirectResponse(url="/docs")


def bad_request(message, field):
    raise HTTPException(400, detail={"error": message, "field": field})


def check_class(value):
    if not isinstance(value, str):
        bad_request("Класс должен быть строкой", "school_class")

    value = value.strip()
    if len(value) < 2 or value[:-1] not in [str(n) for n in range(1, 12)]:
        bad_request("Укажите класс от 1 до 11 с буквой, например 8А", "school_class")
    if value[-1] not in "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯABCDEFGHIJKLMNOPQRSTUVWXYZ":
        bad_request("После номера класса нужна заглавная буква", "school_class")
    return value


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


@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    if isinstance(exc.detail, dict):
        body = exc.detail
    else:
        body = {"error": str(exc.detail), "field": "request"}
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


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


def find_student(student_id):
    if student_id not in students:
        raise HTTPException(404, detail={"error": "Ученик не найден", "field": "id"})
    return students[student_id]


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/students", status_code=201)
async def create_student(
    response: Response,
    data: dict = Body(examples=[{"full_name": "Иванов Иван", "school_class": "8А", "status": "active"}]),
):
    global next_id
    student = check_student(data, creating=True)
    student["id"] = next_id
    students[next_id] = student
    next_id += 1
    response.headers["Location"] = f"/api/students/{student['id']}"
    return student


@app.get("/api/students")
async def list_students(limit: int = 10, offset: int = 0,
                        school_class: str | None = None, status: str | None = None):
    if limit < 1 or limit > 100:
        bad_request("limit должен быть от 1 до 100", "limit")
    if offset < 0:
        bad_request("offset не может быть отрицательным", "offset")
    if school_class is not None:
        school_class = check_class(school_class)
    if status is not None and status not in ["active", "inactive"]:
        bad_request("Статус: active или inactive", "status")

    result = []
    for student in students.values():
        if school_class is not None and student["school_class"] != school_class:
            continue
        if status is not None and student["status"] != status:
            continue
        result.append(student)

    return result[offset:offset + limit]


@app.get("/api/students/{student_id}")
async def get_student(student_id: int):
    return find_student(student_id)


@app.patch("/api/students/{student_id}")
async def update_student(student_id: int, data: dict = Body(examples=[{"school_class": "9А"}])):
    student = find_student(student_id)
    changes = check_student(data)
    student.update(changes)
    return student


@app.delete("/api/students/{student_id}", status_code=204)
async def delete_student(student_id: int):
    find_student(student_id)
    del students[student_id]
    return Response(status_code=204)
