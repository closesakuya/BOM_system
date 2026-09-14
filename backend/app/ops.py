from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .config import PROJECT_ROOT, settings


def database_path() -> Path:
    if not settings.database_url.startswith("sqlite:///"):
        raise RuntimeError("运维脚本只支持当前 V1 SQLite 数据库")
    return Path(settings.database_url.removeprefix("sqlite:///"))


def verify(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(path)
    with sqlite3.connect(path) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        tables = db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        items = db.execute("SELECT count(*) FROM items").fetchone()[0] if tables else 0
    return {"path": str(path), "integrity": integrity, "tables": tables, "items": items, "size": path.stat().st_size}


def backup(label: str = "daily", retain: int = 30) -> dict[str, object]:
    source = database_path()
    if not source.exists():
        raise FileNotFoundError(source)
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    safe_label = "".join(char if char.isalnum() or char in "-_" else "_" for char in label)[:50]
    target = settings.backup_dir / f"bom-{datetime.now():%Y%m%d-%H%M%S}-{safe_label or 'backup'}.db"
    with sqlite3.connect(source) as source_db, sqlite3.connect(target) as target_db:
        source_db.backup(target_db)
    result = verify(target)
    backups = sorted(settings.backup_dir.glob("bom-*.db"), key=lambda path: path.stat().st_mtime, reverse=True)
    removed = []
    for old in backups[max(retain, 1):]:
        old.unlink()
        removed.append(old.name)
    result["removed_by_retention"] = removed
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="BOM V1.1.1 SQLite 运维")
    sub = parser.add_subparsers(dest="command", required=True)
    backup_parser = sub.add_parser("backup")
    backup_parser.add_argument("--label", default="daily")
    backup_parser.add_argument("--retain", type=int, default=30)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("path", nargs="?", type=Path)
    args = parser.parse_args()
    result = backup(args.label, args.retain) if args.command == "backup" else verify(args.path or database_path())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
