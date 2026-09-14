from __future__ import annotations

import os
import mimetypes
import sqlite3
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from . import auth, models, services
from .api import router
from .config import settings
from .database import SessionLocal, init_db


mimetypes.add_type("application/javascript", ".js", strict=True)
mimetypes.add_type("application/javascript", ".mjs", strict=True)


def seed_admin() -> None:
    with SessionLocal() as db:
        if db.scalar(select(models.User.id).limit(1)):
            return
        username = os.getenv("BOM_INITIAL_ADMIN", "admin")
        password = os.getenv("BOM_INITIAL_PASSWORD", "admin123")
        db.add(models.User(
            username=username,
            password_hash=auth.hash_password(password),
            display_name="系统管理员",
            department="",
            role="admin",
            active=True,
        ))
        db.commit()


def seed_default_code_rules() -> None:
    with SessionLocal() as db:
        services.ensure_default_non_material_code_rules(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.database_url.startswith('sqlite:///'):
        target=Path(settings.database_url.removeprefix('sqlite:///')).resolve()
        try:
            with sqlite3.connect(target.as_uri()+'?mode=ro',uri=True) as db:
                applied=db.execute("SELECT 1 FROM audit_events WHERE action='migrate_v1_2' LIMIT 1").fetchone()
            if not applied:
                raise RuntimeError('数据库尚未升级到 V1.2，请先运行 scripts/install_v1.ps1；启动未修改数据库')
        except sqlite3.DatabaseError as exc:
            raise RuntimeError('数据库不存在、尚未初始化或完整性异常，请先运行安装检查并查看数据库备份；启动未修改数据库') from exc
    settings.ensure_directories()
    init_db()
    seed_admin()
    seed_default_code_rules()
    yield


app = FastAPI(title=settings.app_name, version="1.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "1.2.0"}


if settings.frontend_dist.exists():
    assets = settings.frontend_dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    def frontend(full_path: str) -> FileResponse:
        candidate = (settings.frontend_dist / full_path).resolve()
        if candidate.is_file() and settings.frontend_dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(settings.frontend_dist / "index.html")
