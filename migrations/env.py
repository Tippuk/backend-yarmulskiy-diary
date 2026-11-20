import os

from alembic import context
from sqlalchemy import URL, create_engine
from sqlalchemy.pool import NullPool

url = URL.create("sqlite", database=os.getenv("DATABASE_PATH", "diary.db"))
engine = create_engine(url, poolclass=NullPool)

with engine.begin() as db:
    db.exec_driver_sql("BEGIN")
    context.configure(connection=db)
    context.run_migrations()
