from pathlib import Path

from alembic import op

revision = "001"
down_revision = None


def upgrade():
    schema = Path(__file__).resolve().parents[2] / "app" / "schema.sql"
    for statement in schema.read_text(encoding="utf-8").split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade():
    op.drop_table("grades")
    op.drop_table("students")
