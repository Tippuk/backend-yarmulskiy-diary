-- Таблица учеников
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    school_class TEXT NOT NULL,
    status TEXT NOT NULL
);

-- Таблица оценок с привязкой к ученику
CREATE TABLE IF NOT EXISTS grades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    score INTEGER NOT NULL CHECK (score BETWEEN 2 AND 5),
    date TEXT NOT NULL
);
