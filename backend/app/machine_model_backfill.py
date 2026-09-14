from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings


MACHINE_MODELS = ("Y60", "D60", "R60", "T60", "G65", "J60B", "T65")
OTHER_MODEL = "其他机型"
ACTION = "backfill_machine_model"
REASON = "根据整机名称批量匹配机型"


def database_path() -> Path:
    if not settings.database_url.startswith("sqlite:///"):
        raise RuntimeError("机型初始化当前只支持项目使用的 SQLite 数据库")
    return Path(settings.database_url.removeprefix("sqlite:///"))


def classify_machine_name(name: str) -> str:
    normalized = name.casefold()
    matches = [model for model in MACHINE_MODELS if model.casefold() in normalized]
    if len(matches) > 1:
        raise ValueError(f"整机名称同时匹配多个机型：{name}｜{', '.join(matches)}")
    return matches[0] if matches else OTHER_MODEL


def _backup(source: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"bom_v1-before-machine-model-{datetime.now():%Y%m%d-%H%M%S}.db"
    with sqlite3.connect(source) as source_db, sqlite3.connect(target) as target_db:
        source_db.backup(target_db)
        result = target_db.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"机型初始化前备份完整性检查失败：{result}")
    return target


def _write_report(report: dict[str, Any], target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"machine-model-backfill-{stamp}.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def apply_backfill(
    path: Path | None = None,
    *,
    create_backup: bool = True,
    backup_dir: Path | None = None,
    write_report: bool = True,
    report_dir: Path | None = None,
) -> dict[str, Any]:
    target = (path or database_path()).resolve()
    if not target.is_file():
        raise FileNotFoundError(target)
    backup = _backup(target, backup_dir or settings.backup_dir) if create_backup else None
    started_at = datetime.now(timezone.utc)
    batch_key = f"machine-model-{started_at:%Y%m%d%H%M%S%f}"
    report: dict[str, Any] = {
        "database": str(target),
        "started_at": started_at.isoformat(),
        "backup": str(backup) if backup else None,
        "models": [*MACHINE_MODELS, OTHER_MODEL],
    }
    db = sqlite3.connect(target, timeout=30)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("BEGIN IMMEDIATE")
        columns = {str(row[1]) for row in db.execute("PRAGMA table_info(items)")}
        if "machine_model" not in columns:
            raise RuntimeError("数据库尚无 machine_model 字段，请先完成 V1.1 数据库升级")
        rows = db.execute(
            """
            SELECT id, code, name, machine_model
            FROM items
            WHERE item_type = 'machine'
            ORDER BY id
            """
        ).fetchall()
        planned: list[tuple[int, str, str, str | None, str]] = []
        skipped_existing = 0
        distribution: Counter[str] = Counter()
        for item_id, code, name, current_model in rows:
            if current_model is not None and str(current_model).strip():
                skipped_existing += 1
                distribution[str(current_model).strip()] += 1
                continue
            model = classify_machine_name(str(name or ""))
            planned.append((int(item_id), str(code), str(name or ""), current_model, model))
            distribution[model] += 1

        now = datetime.now(timezone.utc).isoformat()
        for item_id, code, name, current_model, model in planned:
            db.execute(
                "UPDATE items SET machine_model = ?, updated_at = ? WHERE id = ?",
                (model, now, item_id),
            )
            db.execute(
                """
                INSERT INTO audit_events (
                    actor_id, action, entity_type, entity_id, reason, batch_key,
                    before_json, after_json, created_at
                ) VALUES (NULL, ?, 'item', ?, ?, ?, ?, ?, ?)
                """,
                (
                    ACTION,
                    item_id,
                    REASON,
                    batch_key,
                    json.dumps(
                        {"code": code, "name": name, "machine_model": current_model},
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {"code": code, "name": name, "machine_model": model},
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
        db.commit()
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"机型初始化后数据库完整性检查失败：{integrity}")
        report.update(
            {
                "status": "success",
                "total_machines": len(rows),
                "updated": len(planned),
                "skipped_existing": skipped_existing,
                "distribution": dict(sorted(distribution.items())),
                "integrity": integrity,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as exc:
        db.rollback()
        report.update(
            {
                "status": "failed",
                "error": str(exc),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        if write_report:
            report["report"] = str(_write_report(report, report_dir or settings.report_dir))
        raise
    finally:
        db.close()
    if write_report:
        report["report"] = str(_write_report(report, report_dir or settings.report_dir))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="根据整机名称初始化机型")
    parser.add_argument("--database", type=Path, help="指定数据库；默认使用正式数据库")
    parser.add_argument("--no-backup", action="store_true", help="仅供测试副本使用")
    parser.add_argument("--no-report", action="store_true", help="不生成 JSON 报告")
    args = parser.parse_args()
    report = apply_backfill(
        args.database,
        create_backup=not args.no_backup,
        write_report=not args.no_report,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
