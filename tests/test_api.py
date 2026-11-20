from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import failures
from app.db import connect

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def test_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("JWT_SECRET", "test-secret-with-at-least-32-bytes")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-test-pass")
    failures.clear()
    with client:
        assert client.post("/auth/register", json={"username": "teacher", "password": "test-pass"}).status_code == 201
        client.auth = ("teacher", "test-pass")
        try:
            yield
        finally:
            client.auth = None


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_registration_and_ownership():
    credentials = {"username": "other", "password": "other-pass", "role": "admin"}
    assert client.post("/auth/register", json=credentials).json()["role"] == "user"
    assert client.post("/auth/register", json=credentials).status_code == 409
    with closing(connect()) as db:
        row = db.execute("SELECT password_hash FROM users WHERE username = ?", ("other",)).fetchone()
        assert row["password_hash"].startswith("$argon2id$")

    user = client.get("/auth/me").json()
    assert set(user) == {"id", "username", "role"}
    data = {"full_name": "Иванов Иван", "school_class": "8А", "owner_id": 999}
    assert client.post("/api/students", json=data, auth=None).status_code == 401
    student = client.post("/api/students", json=data).json()
    assert student["owner_id"] == user["id"]
    path = f"/api/students/{student['id']}"
    assert client.get(path, auth=None).status_code == 200
    other = ("other", "other-pass")
    assert client.patch(path, json={"school_class": "9А"}, auth=other).status_code == 403
    assert client.delete(path, auth=other).status_code == 403
    grade = {"subject": "Математика", "score": 5, "date": "2026-11-07"}
    assert client.post(path + "/grades", json=grade, auth=other).status_code == 403
    assert client.delete(path, auth=("admin", "admin-test-pass")).status_code == 204


def test_jwt_and_login_limit(monkeypatch):
    data = {"username": "teacher", "password": "test-pass"}
    token = client.post("/auth/login", json=data).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert client.get("/auth/me", headers=auth, auth=None).json()["username"] == "teacher"
    assert client.get("/auth/me", headers={"Authorization": "Bearer invalid"}, auth=None).status_code == 401
    monkeypatch.setenv("JWT_TTL_SECONDS", "-1")
    expired = client.post("/auth/login", json=data).json()["access_token"]
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"}, auth=None).status_code == 401
    wrong = {"username": "teacher", "password": "wrong-pass"}
    for _ in range(5):
        assert client.post("/auth/login", json=wrong).status_code == 401
    assert client.post("/auth/login", json=wrong).status_code == 429


def test_home():
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"
    assert client.get("/").status_code == 200


def test_create_student():
    response = client.post("/api/students", json={
        "full_name": "Иванов Иван",
        "school_class": "8А",
    })
    assert response.status_code == 201
    student = response.json()
    assert student["id"] == 1
    assert student["full_name"] == "Иванов Иван"
    assert student["status"] == "active"


def test_get_student():
    client.post("/api/students", json={
        "full_name": "Иванов Иван",
        "school_class": "8А",
    })
    response = client.get("/api/students/1")
    assert response.status_code == 200
    assert response.json()["full_name"] == "Иванов Иван"
    assert len(client.get("/api/students").json()) == 1


def test_update_student():
    client.post("/api/students", json={
        "full_name": "Иванов Иван",
        "school_class": "8А",
    })
    response = client.patch("/api/students/1", json={"school_class": "9А"})
    assert response.status_code == 200
    assert response.json()["school_class"] == "9А"
    assert response.json()["full_name"] == "Иванов Иван"
    assert client.get("/api/students/1").json()["school_class"] == "9А"


def test_delete_student():
    client.post("/api/students", json={
        "full_name": "Иванов Иван",
        "school_class": "8А",
    })
    response = client.delete("/api/students/1")
    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/api/students/1").status_code == 404


def test_grades():
    student = {"full_name": "Иванов Иван", "school_class": "8А"}
    client.post("/api/students", json=student)
    client.post("/api/students", json=student)
    grade = {"subject": "Математика", "score": 5, "date": "2026-11-07"}
    path = "/api/students/1/grades"

    response = client.post(path, json=grade)
    assert response.status_code == 201
    assert response.json()["student_id"] == 1
    assert client.get(path).json() == [response.json()]
    assert client.get("/api/students/2/grades").json() == []
    assert client.post("/api/students/999999/grades", json=grade).status_code == 404
    assert client.post(path, json={**grade, "score": 6}).status_code == 400
    assert client.post(path, json={**grade, "date": "2026-02-30"}).status_code == 400

    assert client.delete("/api/students/1").status_code == 204
    assert client.get(path).status_code == 404


def test_sql_is_stored_as_text():
    name = "'); DROP TABLE students;--"
    response = client.post("/api/students", json={"full_name": name, "school_class": "8А"})
    assert response.status_code == 201
    assert client.get("/api/students/1").json()["full_name"] == name


def test_search_ignores_case():
    client.post("/api/students", json={"full_name": "ИВАНОВ Иван", "school_class": "8А"})
    client.post("/api/students", json={"full_name": "Иванова Анна", "school_class": "9Б"})
    rows = client.get("/api/students", params={"q": "иванов", "school_class": "8А"}).json()
    assert [row["full_name"] for row in rows] == ["ИВАНОВ Иван"]
    assert client.get("/api/students", params={"q": "%' OR 1=1 --"}).json() == []


def test_duplicate_grade_and_stats():
    student = {"full_name": "Иванов Иван", "school_class": "8А"}
    client.post("/api/students", json=student)
    client.post("/api/students", json=student)
    grade = {"subject": "Математика", "score": 5, "date": "2026-11-07"}
    path = "/api/students/1/grades"
    assert client.post(path, json=grade).status_code == 201
    assert client.post(path, json={**grade, "score": 4}).status_code == 409
    assert len(client.get(path).json()) == 1
    assert client.post("/api/students/2/grades", json={**grade, "score": 3}).status_code == 201
    assert client.get("/api/students/stats").json() == [
        {"subject": "Математика", "average_score": 4.0, "grade_count": 2}
    ]


def test_missing_student():
    assert client.get("/api/students/999999").status_code == 404
    assert client.patch("/api/students/999999", json={}).status_code == 404
    assert client.delete("/api/students/999999").status_code == 404


def test_bad_fields():
    bad_values = [
        ("full_name", ""),
        ("full_name", "   "),
        ("full_name", 123),
        ("school_class", "12А"),
        ("school_class", ""),
        ("school_class", 8),
        ("status", "unknown"),
        ("id", 5),
    ]
    client.post("/api/students", json={
        "full_name": "Иванов Иван",
        "school_class": "8А",
    })
    for field, value in bad_values:
        data = {"full_name": "Иванов Иван", "school_class": "8А"}
        data[field] = value
        response = client.post("/api/students", json=data)
        assert response.status_code == 400
        assert response.json()["field"] == field

        response = client.patch("/api/students/1", json=data)
        assert response.status_code == 400
        assert response.json()["field"] == field


def test_bad_json():
    response = client.post(
        "/api/students",
        content='{"full_name":',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert client.get("/health").status_code == 200


def test_required_fields():
    response = client.post("/api/students", json={})
    assert response.status_code == 400
    response = client.post("/api/students", json={"full_name": "Иванов Иван"})
    assert response.status_code == 400
    assert response.json()["field"] == "school_class"


def test_bad_update_does_not_change_student():
    client.post("/api/students", json={
        "full_name": "Иванов Иван",
        "school_class": "8А",
    })
    response = client.patch("/api/students/1", json={
        "full_name": "Петров Пётр",
        "status": "unknown",
    })
    assert response.status_code == 400
    assert client.get("/api/students/1").json()["full_name"] == "Иванов Иван"

    for field in ["full_name", "school_class", "status"]:
        response = client.patch("/api/students/1", json={field: None})
        assert response.status_code == 400
        assert response.json()["field"] == field


def test_filter_and_pages():
    for school_class in ["8А", "9Б", "8А", "8А"]:
        client.post("/api/students", json={
            "full_name": "Иванов Иван",
            "school_class": school_class,
        })

    response = client.get("/api/students?school_class=8А&limit=1&offset=1")
    students = response.json()
    assert len(students) == 1
    assert students[0]["id"] == 3
    assert client.get("/api/students?offset=100").json() == []

def test_bad_filters():
    for query in ["limit=0", "offset=-1", "limit=abc", "school_class=12А"]:
        response = client.get("/api/students?" + query)
        assert response.status_code == 400


def test_docs():
    assert client.get("/docs").status_code == 200
    response = client.get("/openapi.json")
    paths = response.json()["paths"]
    assert paths["/api/students"]["post"]["summary"] == "Добавить ученика"
    assert paths["/api/students/{student_id}/grades"]["get"]["tags"] == ["Оценки"]


def test_request_log(caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        client.get("/health")
    assert "GET /health 200" in caplog.text
    assert "ms" in caplog.text
