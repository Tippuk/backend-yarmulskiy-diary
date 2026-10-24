# Электронный дневник

Тема №21. Первая лабораторная: API для добавления, просмотра, изменения и удаления учеников.
Python 3.10+, FastAPI. Данные хранятся в памяти и пропадают после перезапуска сервера.

## Запуск

Windows PowerShell:

```powershell
git clone https://github.com/Tippuk/backend-yarmulskiy-diary.git
cd backend-yarmulskiy-diary
git switch lab-1
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

На Linux/macOS используй python3 для создания окружения,
а вместо `.\.venv\Scripts\python` — `.venv/bin/python`.
Запускай один процесс сервера: база данных пока не используется.

Адрес сервера: http://localhost:8000.
Swagger: http://localhost:8000/docs.
Примеры запросов находятся в requests.http.

## Запросы

| Метод | Адрес | Что делает | Код ответа |
| --- | --- | --- | --- |
| GET | /health | Проверка сервера | 200 |
| POST | /api/students | Добавить ученика | 201; 400 |
| GET | /api/students | Список учеников | 200; 400 |
| GET | /api/students/{id} | Получить ученика | 200; 400; 404 |
| PATCH | /api/students/{id} | Изменить переданные поля | 200; 400; 404 |
| DELETE | /api/students/{id} | Удалить ученика | 204; 400; 404 |

Пример тела POST:

```json
{"full_name": "Иванов Иван", "school_class": "8А", "status": "active"}
```

ФИО и класс обязательны. Статус: active или inactive, по умолчанию active.
id назначается сервером.

Фильтр и пагинация: `/api/students?school_class=8А&status=active&limit=10&offset=0`.
limit — от 1 до 100, offset — от 0.
Ошибки возвращаются в формате `{"error": "описание", "field": "поле"}`.
В терминале выводятся метод, путь, статус и время каждого запроса.

## Проверка

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q
```

Чекер запускается при работающем сервере в отдельном терминале:

```powershell
.\.venv\Scripts\python -m pip install "git+https://github.com/bozhedom/backcheck@v1"
.\.venv\Scripts\python -m backcheck --lab 1 --stars
```
