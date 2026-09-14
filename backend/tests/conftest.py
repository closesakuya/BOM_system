from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import auth, models  # noqa: E402
from backend.app.api import router  # noqa: E402
from backend.app.database import Base, get_db  # noqa: E402


@pytest.fixture()
def db(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are immutable'); END"))
        connection.execute(text("CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are immutable'); END"))
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    session = factory()
    admin = models.User(
        username="admin", password_hash=auth.hash_password("admin123"),
        display_name="管理员", role="admin", active=True,
    )
    session.add(admin)
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db: Session):
    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def token(client: TestClient) -> str:
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.fixture()
def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
