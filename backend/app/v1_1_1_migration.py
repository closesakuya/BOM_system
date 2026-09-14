from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from .config import settings


VERSION = "V1.1.1"
MIGRATION_ACTION = "v1_1_1_upgrade"
KEY_CODE_PATTERN = re.compile(r"^[A-Z0-9]{3}\.[A-Z0-9]$")
UNOFFICIAL_PATTERN = re.compile(r"^99\.(\d{4})\.(\d)$")


def database_path() -> Path:
    prefix = "sqlite:///"
    if not settings.database_url.startswith(prefix):
        raise RuntimeError("V1.1.1 升级当前只支持项目使用的 SQLite 数据库")
    return Path(settings.database_url.removeprefix(prefix))


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in db.execute(f'PRAGMA table_info("{table}")')}


def _backup(path: Path, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = directory / f"{path.stem}-before-v1.1.1-{stamp}{path.suffix}"
    shutil.copy2(path, target)
    with sqlite3.connect(target) as copied:
        if copied.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            target.unlink(missing_ok=True)
            raise RuntimeError("V1.1.1 升级前数据库备份完整性检查失败")
    return target


def _audit(
    db: sqlite3.Connection,
    action: str,
    entity_type: str,
    entity_id: int | None,
    reason: str,
    before: Any = None,
    after: Any = None,
    batch_key: str = "v1_1_1-upgrade",
) -> None:
    db.execute(
        """
        INSERT INTO audit_events
            (actor_id, action, entity_type, entity_id, reason, batch_key,
             before_json, after_json, created_at)
        VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            action,
            entity_type,
            entity_id,
            reason,
            batch_key,
            json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
            json.dumps(after, ensure_ascii=False, default=str) if after is not None else None,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def _format_unofficial(value: int) -> str:
    if value < 0 or value >= 99990:
        raise RuntimeError("未正式原材料编号已超出 99.9999.9")
    body, version = divmod(value, 10)
    return f"99.{body + 1:04d}.{version}"


def _sequence_value(code: str) -> int:
    match = UNOFFICIAL_PATTERN.fullmatch(code)
    if not match:
        raise RuntimeError(f"未正式原材料编号格式错误：{code}")
    return (int(match.group(1)) - 1) * 10 + int(match.group(2))


def _upgrade_schema(db: sqlite3.Connection) -> bool:
    columns = _columns(db, "items")
    changed = False
    if "key_component_code" not in columns:
        if "platform_code_rule" not in columns:
            raise RuntimeError("items 表缺少平台编号规则字段，无法执行 V1.1.1 迁移")
        db.execute("ALTER TABLE items RENAME COLUMN platform_code_rule TO key_component_code")
        changed = True
        columns = _columns(db, "items")
    additions = {
        "historical_item_code": "VARCHAR(120)",
        "unofficial_status": "VARCHAR(20)",
    }
    for name, definition in additions.items():
        if name not in columns:
            db.execute(f"ALTER TABLE items ADD COLUMN {name} {definition}")
            changed = True
    db.execute("DROP INDEX IF EXISTS ix_items_platform_code_rule")
    db.execute("CREATE INDEX IF NOT EXISTS ix_items_key_component_code ON items (key_component_code)")
    db.execute("CREATE INDEX IF NOT EXISTS ix_items_historical_item_code ON items (historical_item_code)")
    db.execute("CREATE INDEX IF NOT EXISTS ix_items_unofficial_status ON items (unofficial_status)")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS code_sequences (
            name VARCHAR(80) PRIMARY KEY,
            next_value INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS material_promotion_links (
            id INTEGER PRIMARY KEY,
            source_item_id INTEGER NOT NULL UNIQUE REFERENCES items(id),
            target_item_id INTEGER NOT NULL REFERENCES items(id),
            is_historical BOOLEAN NOT NULL DEFAULT 0,
            reason TEXT NOT NULL,
            actor_id INTEGER REFERENCES users(id),
            created_at DATETIME NOT NULL
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS ix_material_promotion_links_source_item_id "
        "ON material_promotion_links (source_item_id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS ix_material_promotion_links_target_item_id "
        "ON material_promotion_links (target_item_id)"
    )
    return changed


def _create_guards(db: sqlite3.Connection) -> None:
    for trigger in ("items_v111_insert_guard", "items_v111_update_guard"):
        db.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    guard = """
        SELECT CASE
          WHEN NEW.is_formally_imported = 0 AND (
            NEW.item_type <> 'material'
            OR NEW.code NOT GLOB '99.[0-9][0-9][0-9][0-9].[0-9]'
            OR length(NEW.code) <> 9
            OR NEW.unofficial_status NOT IN ('pending', 'archived')
          ) THEN RAISE(ABORT, 'invalid unofficial material')
          WHEN NEW.is_formally_imported = 1 AND (
            NEW.code GLOB '99.[0-9][0-9][0-9][0-9].[0-9]'
            OR NEW.unofficial_status IS NOT NULL
          ) THEN RAISE(ABORT, 'invalid formal material')
        END;
    """
    db.execute(f"CREATE TRIGGER items_v111_insert_guard BEFORE INSERT ON items BEGIN {guard} END")
    db.execute(f"CREATE TRIGGER items_v111_update_guard BEFORE UPDATE ON items BEGIN {guard} END")


def _normalize_key_codes(db: sqlite3.Connection) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    rows = list(
        db.execute(
            "SELECT id, key_component_code FROM items "
            "WHERE key_component_code IS NOT NULL AND trim(key_component_code) <> '' ORDER BY id"
        )
    )
    for item_id, original in rows:
        normalized = re.sub(r"\s+", "", str(original)).upper()
        if not KEY_CODE_PATTERN.fullmatch(normalized):
            raise RuntimeError(f"物料 ID {item_id} 的关键器件码格式无效：{original}")
        if normalized != original:
            db.execute(
                "UPDATE items SET key_component_code = ?, updated_at = ? WHERE id = ?",
                (normalized, datetime.now(timezone.utc).isoformat(), item_id),
            )
            _audit(
                db,
                "normalize_key_component_code",
                "item",
                int(item_id),
                "V1.1.1 迁移：规范化关键器件码",
                {"key_component_code": original},
                {"key_component_code": normalized},
            )
            changes.append({"item_id": item_id, "before": original, "after": normalized})
    return changes


def _legacy_original_code(db: sqlite3.Connection, item_id: int, fallback: str) -> str:
    row = db.execute(
        """
        SELECT before_json FROM audit_events
        WHERE action = 'mark_unofficial_material' AND entity_type = 'item' AND entity_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (item_id,),
    ).fetchone()
    if row and row[0]:
        try:
            return str(json.loads(row[0]).get("code") or fallback)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return fallback


def _migrate_unofficial(db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = list(
        db.execute(
            """
            SELECT id, code, name FROM items
            WHERE item_type = 'material' AND is_formally_imported = 0
              AND code NOT GLOB '99.[0-9][0-9][0-9][0-9].[0-9]'
            ORDER BY id
            """
        )
    )
    existing_99 = [str(row[0]) for row in db.execute(
        "SELECT code FROM items WHERE is_formally_imported = 0 "
        "AND code GLOB '99.[0-9][0-9][0-9][0-9].[0-9]'"
    )]
    next_value = max((_sequence_value(code) for code in existing_99), default=-1) + 1
    migrated: list[dict[str, Any]] = []
    for item_id, old_code, name in rows:
        official = db.execute(
            "SELECT id, code, name FROM items WHERE is_formally_imported = 1 AND code = ? ORDER BY id LIMIT 1",
            (old_code,),
        ).fetchone()
        if official is None:
            raise RuntimeError(f"历史未正式原材料 {old_code} 找不到 V1.1 对应正式物料")
        new_code = _format_unofficial(next_value)
        next_value += 1
        body, version = new_code.rsplit(".", 1)
        historical_code = _legacy_original_code(db, int(item_id), str(old_code))
        db.execute(
            """
            UPDATE items SET code = ?, code_body = ?, version_label = ?, version_number = ?,
                version_series = ?, historical_item_code = ?, unofficial_status = 'archived',
                updated_at = ? WHERE id = ?
            """,
            (
                new_code,
                body,
                version,
                int(version),
                body,
                historical_code,
                datetime.now(timezone.utc).isoformat(),
                item_id,
            ),
        )
        db.execute(
            """
            INSERT OR IGNORE INTO material_promotion_links
                (source_item_id, target_item_id, is_historical, reason, actor_id, created_at)
            VALUES (?, ?, 1, ?, NULL, ?)
            """,
            (
                item_id,
                official[0],
                "V1.1.1 历史迁移：关联 V1.1 已确定的正式物料",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        before = {"code": old_code, "display_code": f"Y{old_code}", "is_formally_imported": False}
        after = {
            "code": new_code,
            "historical_item_code": historical_code,
            "is_formally_imported": False,
            "unofficial_status": "archived",
            "promoted_to_item_id": official[0],
        }
        _audit(
            db,
            "migrate_unofficial_material_v1_1_1",
            "item",
            int(item_id),
            f"V1.1.1 迁移：{old_code}｜{name} 改为 {new_code} 并封存",
            before,
            after,
        )
        migrated.append(
            {
                "item_id": item_id,
                "old_code": old_code,
                "historical_item_code": historical_code,
                "new_code": new_code,
                "official_item_id": official[0],
                "official_code": official[1],
            }
        )
    all_99 = [str(row[0]) for row in db.execute(
        "SELECT code FROM items WHERE is_formally_imported = 0 ORDER BY code"
    )]
    final_next = max((_sequence_value(code) for code in all_99), default=-1) + 1
    db.execute(
        """
        INSERT INTO code_sequences (name, next_value) VALUES ('unofficial_material', ?)
        ON CONFLICT(name) DO UPDATE SET next_value = MAX(code_sequences.next_value, excluded.next_value)
        """,
        (final_next,),
    )
    db.execute(
        "UPDATE items SET unofficial_status = 'pending' "
        "WHERE is_formally_imported = 0 AND unofficial_status IS NULL"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_item_unofficial_code "
        "ON items (code) WHERE is_formally_imported = 0"
    )
    return migrated


def _validate(db: sqlite3.Connection) -> dict[str, Any]:
    result = {
        "foreign_key_errors": len(list(db.execute("PRAGMA foreign_key_check"))),
        "duplicate_unofficial_codes": int(db.execute(
            "SELECT count(*) FROM (SELECT code FROM items WHERE is_formally_imported = 0 GROUP BY code HAVING count(*) > 1)"
        ).fetchone()[0]),
        "invalid_unofficial_codes": int(db.execute(
            "SELECT count(*) FROM items WHERE is_formally_imported = 0 AND "
            "(code NOT GLOB '99.[0-9][0-9][0-9][0-9].[0-9]' OR length(code) <> 9)"
        ).fetchone()[0]),
        "formal_in_reserved_range": int(db.execute(
            "SELECT count(*) FROM items WHERE is_formally_imported = 1 AND "
            "code GLOB '99.[0-9][0-9][0-9][0-9].[0-9]'"
        ).fetchone()[0]),
        "invalid_unofficial_status": int(db.execute(
            "SELECT count(*) FROM items WHERE (is_formally_imported = 0 AND unofficial_status NOT IN ('pending','archived')) "
            "OR (is_formally_imported = 1 AND unofficial_status IS NOT NULL)"
        ).fetchone()[0]),
        "archived_without_link": int(db.execute(
            "SELECT count(*) FROM items i LEFT JOIN material_promotion_links l ON l.source_item_id = i.id "
            "WHERE i.unofficial_status = 'archived' AND l.id IS NULL"
        ).fetchone()[0]),
        "invalid_key_component_codes": 0,
    }
    for (value,) in db.execute(
        "SELECT key_component_code FROM items WHERE key_component_code IS NOT NULL AND key_component_code <> ''"
    ):
        if not KEY_CODE_PATTERN.fullmatch(str(value)):
            result["invalid_key_component_codes"] += 1
    if any(result.values()):
        raise RuntimeError(f"V1.1.1 迁移后业务完整性检查失败：{result}")
    return result


def write_report(report: dict[str, Any], directory: Path | None = None) -> list[Path]:
    target = directory or settings.report_dir
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = target / f"v1.1.1-migration-{stamp}.json"
    xlsx_path = target / f"v1.1.1-migration-{stamp}.xlsx"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    wb = Workbook()
    summary = wb.active
    summary.title = "升级摘要"
    summary.append(["项目", "结果"])
    for key in ("version", "database", "status", "backup", "schema_upgraded", "key_codes_normalized", "unofficial_materials_migrated", "integrity"):
        summary.append([key, report.get(key)])
    materials = wb.create_sheet("未正式物料迁移")
    materials.append(["内部ID", "升级前编码", "历史物料号", "新编码", "正式物料ID", "正式物料编码"])
    for row in report.get("migrated_unofficial_materials", []):
        materials.append([row.get("item_id"), row.get("old_code"), row.get("historical_item_code"), row.get("new_code"), row.get("official_item_id"), row.get("official_code")])
    wb.save(xlsx_path)
    return [json_path, xlsx_path]


def apply_upgrade(
    path: Path | None = None,
    *,
    create_backup: bool = True,
    backup_dir: Path | None = None,
    write_reports: bool = True,
    report_dir: Path | None = None,
) -> dict[str, Any]:
    target = (path or database_path()).resolve()
    if not target.is_file():
        raise FileNotFoundError(target)
    backup_path = _backup(target, backup_dir or settings.backup_dir) if create_backup else None
    report: dict[str, Any] = {
        "version": VERSION,
        "database": str(target),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "backup": str(backup_path) if backup_path else None,
        "schema_upgraded": False,
        "key_codes_normalized": 0,
        "unofficial_materials_migrated": 0,
        "migrated_unofficial_materials": [],
    }
    db = sqlite3.connect(target, timeout=30)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("BEGIN IMMEDIATE")
        report["schema_upgraded"] = _upgrade_schema(db)
        key_changes = _normalize_key_codes(db)
        migrated = _migrate_unofficial(db)
        _create_guards(db)
        report["key_codes_normalized"] = len(key_changes)
        report["unofficial_materials_migrated"] = len(migrated)
        report["migrated_unofficial_materials"] = migrated
        already_logged = db.execute(
            "SELECT 1 FROM audit_events WHERE action = ? LIMIT 1", (MIGRATION_ACTION,)
        ).fetchone()
        if not already_logged:
            _audit(
                db,
                MIGRATION_ACTION,
                "database",
                None,
                "BOM V1.1.1 未正式原材料与关键器件码升级",
                after={
                    "key_codes_normalized": len(key_changes),
                    "unofficial_materials_migrated": len(migrated),
                },
            )
        report["validation"] = _validate(db)
        db.commit()
        report["integrity"] = db.execute("PRAGMA integrity_check").fetchone()[0]
        if report["integrity"] != "ok":
            raise RuntimeError("V1.1.1 迁移后数据库完整性检查失败")
        report["status"] = "success"
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        db.rollback()
        report["status"] = "failed"
        report["error"] = str(exc)
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        if write_reports:
            report["reports"] = [str(path) for path in write_report(report, report_dir)]
        raise
    finally:
        db.close()
    if write_reports:
        report["reports"] = [str(path) for path in write_report(report, report_dir)]
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="BOM V1.1.1 数据库升级")
    parser.add_argument("--database", type=Path, help="指定数据库；默认使用正式数据库")
    parser.add_argument("--no-backup", action="store_true", help="仅供测试副本使用")
    parser.add_argument("--no-report", action="store_true", help="不生成迁移报告")
    args = parser.parse_args()
    report = apply_upgrade(
        args.database,
        create_backup=not args.no_backup,
        write_reports=not args.no_report,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
