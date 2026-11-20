from alembic import op

revision = "003"
down_revision = "002"


def upgrade():
    op.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin'))
        )
    """)
    op.execute("ALTER TABLE students ADD COLUMN owner_id INTEGER REFERENCES users(id)")


def downgrade():
    op.execute("ALTER TABLE students DROP COLUMN owner_id")
    op.drop_table("users")
