from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    app_name: str = "BOM 物料清单管理系统"
    api_prefix: str = "/api"
    secret_key: str = os.getenv("BOM_SECRET_KEY", "change-this-before-production")
    token_expire_minutes: int = int(os.getenv("BOM_TOKEN_EXPIRE_MINUTES", "720"))
    database_url: str = os.getenv(
        "BOM_DATABASE_URL",
        f"sqlite:///{(PROJECT_ROOT / 'runtime' / 'bom_v1.db').as_posix()}",
    )
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"
    runtime_dir: Path = PROJECT_ROOT / "runtime"
    upload_dir: Path = runtime_dir / "uploads"
    export_dir: Path = runtime_dir / "exports"
    report_dir: Path = runtime_dir / "reports"
    backup_dir: Path = Path(os.getenv('BOM_BACKUP_DIR', str(runtime_dir / 'backups')))

    def ensure_directories(self) -> None:
        for path in (
            self.runtime_dir,
            self.upload_dir,
            self.export_dir,
            self.report_dir,
            self.backup_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
