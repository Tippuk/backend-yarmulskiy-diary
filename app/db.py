import os
import sqlite3
from contextlib import closing


def connect():
    db = sqlite3.connect(os.getenv("DATABASE_PATH", "diary.db"))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.create_function("casefold", 1, str.casefold)
    return db


# Подключение закрывается после запроса.
async def get_db():
    with closing(connect()) as db:
        yield db
