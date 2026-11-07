from alembic import op

revision = "002"
down_revision = "001"


def upgrade():
    op.create_index("ix_students_class", "students", ["school_class"])
    op.create_index("ux_grades_student_subject_date", "grades",
                    ["student_id", "subject", "date"], unique=True)


def downgrade():
    op.drop_index("ux_grades_student_subject_date", table_name="grades")
    op.drop_index("ix_students_class", table_name="students")
