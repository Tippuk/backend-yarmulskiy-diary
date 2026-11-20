from contextlib import closing

from app.main import connect, migrate


def seed():
    migrate()
    with closing(connect()) as db, db:
        if db.execute("SELECT id FROM students LIMIT 1").fetchone():
            print("В базе уже есть ученики. Данные не изменены.")
            return
        for name, school_class, score in [
            ("Иванов Иван", "8А", 5),
            ("Петрова Анна", "8А", 4),
            ("Сидоров Олег", "9Б", 3),
        ]:
            student = db.execute(
                "INSERT INTO students (full_name, school_class, status) VALUES (?, ?, ?)",
                (name, school_class, "active"),
            )
            db.execute(
                "INSERT INTO grades (student_id, subject, score, date) VALUES (?, ?, ?, ?)",
                (student.lastrowid, "Математика", score, "2026-11-07"),
            )
    print("Добавлены три ученика и их оценки.")


if __name__ == "__main__":
    seed()
