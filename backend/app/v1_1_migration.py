from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from .config import PROJECT_ROOT, settings


MIGRATION_ACTION = "v1_1_upgrade"


def database_path() -> Path:
    if not settings.database_url.startswith("sqlite:///"):
        raise RuntimeError("V1.1 升级当前只支持项目使用的 SQLite 数据库")
    return Path(settings.database_url.removeprefix("sqlite:///"))


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in db.execute(f'PRAGMA table_info("{table}")')}


def _backup(source: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"bom-{datetime.now():%Y%m%d-%H%M%S}-pre-v1_1.db"
    with sqlite3.connect(source) as source_db, sqlite3.connect(target) as target_db:
        source_db.backup(target_db)
        if target_db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("V1.1 升级前数据库备份完整性检查失败")
    return target


def _audit(
    db: sqlite3.Connection,
    action: str,
    entity_type: str,
    entity_id: int | None,
    reason: str,
    before: Any = None,
    after: Any = None,
    batch_key: str | None = None,
) -> None:
    db.execute(
        """
        INSERT INTO audit_events (
            actor_id, action, entity_type, entity_id, reason, batch_key,
            before_json, after_json, created_at
        ) VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)
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


def _migrate_change_notes(db: sqlite3.Connection) -> int:
    if "change_note" not in _columns(db, "items"):
        return 0
    rows = list(
        db.execute(
            "SELECT id, code, name, change_note FROM items "
            "WHERE change_note IS NOT NULL AND trim(change_note) <> '' ORDER BY id"
        )
    )
    for item_id, code, name, note in rows:
        _audit(
            db,
            "migrate_change_note",
            "item",
            int(item_id),
            str(note),
            before={"change_note": note},
            after={"message": "基本信息变更说明已迁移至审计历史"},
            batch_key="v1_1-change-note",
        )
    return len(rows)


def _rebuild_items(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE items_v1_1 (
            id INTEGER NOT NULL PRIMARY KEY,
            item_type VARCHAR(20) NOT NULL,
            code VARCHAR(120) NOT NULL,
            code_body VARCHAR(100) NOT NULL,
            version_label VARCHAR(20) NOT NULL,
            version_number INTEGER NOT NULL,
            version_series VARCHAR(120) NOT NULL,
            auxiliary_code VARCHAR(120),
            name VARCHAR(255) NOT NULL,
            specification TEXT,
            source_type VARCHAR(20),
            unit VARCHAR(30) NOT NULL,
            remark TEXT,
            previous_version_name VARCHAR(255),
            invoice_name VARCHAR(255),
            material_attribute VARCHAR(255),
            platform_code_rule VARCHAR(120),
            machine_model VARCHAR(80),
            is_formally_imported BOOLEAN NOT NULL DEFAULT 1,
            requires_assembly BOOLEAN NOT NULL,
            status VARCHAR(20),
            copied_from_id INTEGER,
            deleted_at DATETIME,
            created_by INTEGER,
            updated_by INTEGER,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            CONSTRAINT ck_unofficial_only_material
                CHECK (item_type = 'material' OR is_formally_imported = 1),
            FOREIGN KEY(copied_from_id) REFERENCES items_v1_1 (id),
            FOREIGN KEY(created_by) REFERENCES users (id),
            FOREIGN KEY(updated_by) REFERENCES users (id)
        )
        """
    )
    db.execute(
        """
        INSERT INTO items_v1_1 (
            id, item_type, code, code_body, version_label, version_number,
            version_series, auxiliary_code, name, specification, source_type,
            unit, remark, previous_version_name, invoice_name, material_attribute,
            platform_code_rule, machine_model, is_formally_imported,
            requires_assembly, status, copied_from_id, deleted_at, created_by,
            updated_by, created_at, updated_at
        )
        SELECT
            id, item_type, code, code_body, version_label, version_number,
            version_series, auxiliary_code, name, specification, source_type,
            unit, remark, previous_version_name, invoice_name, material_attribute,
            CASE WHEN item_type = 'material' THEN auxiliary_code ELSE NULL END,
            NULL, 1, requires_assembly, status, copied_from_id, deleted_at,
            created_by, updated_by, created_at, updated_at
        FROM items
        """
    )
    db.execute("DROP TABLE items")
    db.execute("ALTER TABLE items_v1_1 RENAME TO items")
    for statement in (
        "CREATE INDEX ix_items_item_type ON items (item_type)",
        "CREATE INDEX ix_items_code ON items (code)",
        "CREATE INDEX ix_items_code_body ON items (code_body)",
        "CREATE INDEX ix_items_version_series ON items (version_series)",
        "CREATE INDEX ix_items_auxiliary_code ON items (auxiliary_code)",
        "CREATE INDEX ix_items_name ON items (name)",
        "CREATE INDEX ix_items_source_type ON items (source_type)",
        "CREATE INDEX ix_items_status ON items (status)",
        "CREATE INDEX ix_items_deleted_at ON items (deleted_at)",
        "CREATE INDEX ix_items_platform_code_rule ON items (platform_code_rule)",
        "CREATE INDEX ix_items_machine_model ON items (machine_model)",
        "CREATE INDEX ix_items_is_formally_imported ON items (is_formally_imported)",
        "CREATE INDEX ix_item_name_spec ON items (name, specification)",
        "CREATE UNIQUE INDEX uq_item_official_code ON items (code) WHERE is_formally_imported = 1",
        "CREATE UNIQUE INDEX uq_item_official_series_version "
        "ON items (version_series, version_number) WHERE is_formally_imported = 1",
    ):
        db.execute(statement)


def _add_market_share(db: sqlite3.Connection) -> int:
    if "market_share" in _columns(db, "alternative_members"):
        return 0
    db.execute(
        "ALTER TABLE alternative_members "
        "ADD COLUMN market_share NUMERIC(5, 2) NOT NULL DEFAULT 0"
    )
    initialized = 0
    group_ids = [int(row[0]) for row in db.execute("SELECT id FROM alternative_groups ORDER BY id")]
    for group_id in group_ids:
        member_ids = [
            int(row[0])
            for row in db.execute(
                "SELECT id FROM alternative_members WHERE group_id = ? ORDER BY priority, id",
                (group_id,),
            )
        ]
        if not member_ids:
            continue
        base = (Decimal("100.00") / len(member_ids)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        assigned = Decimal("0.00")
        for index, member_id in enumerate(member_ids):
            share = Decimal("100.00") - assigned if index == len(member_ids) - 1 else base
            db.execute(
                "UPDATE alternative_members SET market_share = ? WHERE id = ?",
                (str(share), member_id),
            )
            assigned += share
            initialized += 1
    return initialized


def _parse_base_code(code: str) -> tuple[str, str, int]:
    match = re.fullmatch(r"(.+)\.([^.]+)", code.strip())
    if not match:
        raise RuntimeError(f"Y/J 原材料去前缀后的编码格式无效：{code}")
    body, version_label = match.groups()
    version_number = int(version_label) if version_label.isdigit() else 0
    return body, version_label, version_number


def _normalize_yj_materials(db: sqlite3.Connection) -> tuple[list[dict[str, Any]], int]:
    rows = list(
        db.execute(
            """
            SELECT id, code, name FROM items
            WHERE item_type = 'material' AND is_formally_imported = 1
              AND (code LIKE 'Y%' OR code LIKE 'J%')
            ORDER BY id
            """
        )
    )
    normalized: list[dict[str, Any]] = []
    rewired_count = 0
    for legacy_id, legacy_code, legacy_name in rows:
        base_code = str(legacy_code)[1:]
        official = db.execute(
            """
            SELECT id, code, name FROM items
            WHERE is_formally_imported = 1 AND code = ? AND id <> ?
            ORDER BY id
            """,
            (base_code, legacy_id),
        ).fetchone()
        if official is None:
            raise RuntimeError(f"历史未正式原材料 {legacy_code} 找不到对应正式物料 {base_code}")
        if db.execute(
            "SELECT 1 FROM alternative_members WHERE item_id = ? LIMIT 1", (legacy_id,)
        ).fetchone():
            raise RuntimeError(f"历史未正式原材料 {legacy_code} 仍在替代组中，不能自动迁移")

        inbound = list(
            db.execute(
                "SELECT id, parent_item_id, quantity, sort_order, line_remark "
                "FROM bom_lines WHERE child_item_id = ? ORDER BY id",
                (legacy_id,),
            )
        )
        rewires: list[dict[str, Any]] = []
        for line_id, parent_id, quantity, sort_order, line_remark in inbound:
            conflict = db.execute(
                "SELECT id FROM bom_lines WHERE parent_item_id = ? AND child_item_id = ? AND id <> ?",
                (parent_id, official[0], line_id),
            ).fetchone()
            if conflict:
                raise RuntimeError(
                    f"历史引用改接发生同层重复：父项ID {parent_id} 同时包含 "
                    f"{legacy_code} 和 {base_code}"
                )
            parent = db.execute("SELECT code, name FROM items WHERE id = ?", (parent_id,)).fetchone()
            before = {
                "parent": {"id": parent_id, "code": parent[0], "name": parent[1]},
                "child": {"id": legacy_id, "code": legacy_code, "name": legacy_name},
                "quantity": str(quantity),
                "sort_order": sort_order,
                "line_remark": line_remark,
            }
            after = {
                **before,
                "child": {"id": official[0], "code": official[1], "name": official[2]},
            }
            db.execute("UPDATE bom_lines SET child_item_id = ? WHERE id = ?", (official[0], line_id))
            _audit(
                db,
                "rewire_unofficial_material",
                "bom_line",
                int(line_id),
                f"V1.1 历史迁移：{legacy_code}｜{legacy_name} 改接为 {official[1]}｜{official[2]}",
                before,
                after,
                "v1_1-yj-rewire",
            )
            rewires.append({"bom_line_id": line_id, "parent": before["parent"]})
            rewired_count += 1

        body, version_label, version_number = _parse_base_code(base_code)
        db.execute(
            """
            UPDATE items
            SET code = ?, code_body = ?, version_label = ?, version_number = ?,
                version_series = ?, is_formally_imported = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (
                base_code,
                body,
                version_label,
                version_number,
                body,
                datetime.now(timezone.utc).isoformat(),
                legacy_id,
            ),
        )
        _audit(
            db,
            "mark_unofficial_material",
            "item",
            int(legacy_id),
            f"V1.1 历史迁移：去除前导 {str(legacy_code)[0]}，标记为未正式导入",
            {"code": legacy_code, "is_formally_imported": True},
            {"code": base_code, "display_code": f"Y{base_code}", "is_formally_imported": False},
            "v1_1-yj-normalize",
        )
        normalized.append(
            {
                "item_id": legacy_id,
                "old_code": legacy_code,
                "base_code": base_code,
                "display_code": f"Y{base_code}",
                "official_item_id": official[0],
                "official_name": official[2],
                "rewired_lines": rewires,
            }
        )
    return normalized, rewired_count


def _validate(db: sqlite3.Connection) -> dict[str, Any]:
    foreign_key_errors = [tuple(row) for row in db.execute("PRAGMA foreign_key_check")]
    duplicate_official_codes = int(
        db.execute(
            """
            SELECT count(*) FROM (
                SELECT code FROM items WHERE is_formally_imported = 1
                GROUP BY code HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
    )
    duplicate_official_versions = int(
        db.execute(
            """
            SELECT count(*) FROM (
                SELECT version_series, version_number FROM items
                WHERE is_formally_imported = 1
                GROUP BY version_series, version_number HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
    )
    unofficial_child_refs = int(
        db.execute(
            """
            SELECT count(*) FROM bom_lines b
            JOIN items i ON i.id = b.child_item_id
            WHERE i.is_formally_imported = 0
            """
        ).fetchone()[0]
    )
    unofficial_alternatives = int(
        db.execute(
            """
            SELECT count(*) FROM alternative_members a
            JOIN items i ON i.id = a.item_id
            WHERE i.is_formally_imported = 0
            """
        ).fetchone()[0]
    )
    invalid_unofficial_types = int(
        db.execute(
            "SELECT count(*) FROM items WHERE is_formally_imported = 0 AND item_type <> 'material'"
        ).fetchone()[0]
    )
    result = {
        "foreign_key_errors": foreign_key_errors,
        "duplicate_official_codes": duplicate_official_codes,
        "duplicate_official_versions": duplicate_official_versions,
        "unofficial_child_refs": unofficial_child_refs,
        "unofficial_alternatives": unofficial_alternatives,
        "invalid_unofficial_types": invalid_unofficial_types,
    }
    if any(
        (
            foreign_key_errors,
            duplicate_official_codes,
            duplicate_official_versions,
            unofficial_child_refs,
            unofficial_alternatives,
            invalid_unofficial_types,
        )
    ):
        raise RuntimeError(f"V1.1 迁移后业务完整性检查失败：{result}")
    return result


def write_report(report: dict[str, Any], report_dir: Path | None = None) -> tuple[Path, Path]:
    output_dir = (report_dir or settings.report_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = output_dir / f"v1_1-migration-{stamp}.json"
    xlsx_path = output_dir / f"v1_1-migration-{stamp}.xlsx"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    workbook = Workbook()
    summary = workbook.active
    summary.title = "迁移汇总"
    summary.append(["项目", "结果"])
    for key, value in report.items():
        if key != "normalized_materials":
            summary.append(
                [
                    key,
                    json.dumps(value, ensure_ascii=False, default=str)
                    if isinstance(value, (dict, list))
                    else str(value),
                ]
            )
    details = workbook.create_sheet("YJ迁移明细")
    details.append(
        ["物料ID", "原编码", "基础编码", "显示编码", "正式物料ID", "正式物料名称", "改接BOM行数"]
    )
    for row in report.get("normalized_materials", []):
        details.append(
            [
                row["item_id"],
                row["old_code"],
                row["base_code"],
                row["display_code"],
                row["official_item_id"],
                row["official_name"],
                len(row["rewired_lines"]),
            ]
        )
    workbook.save(xlsx_path)
    return json_path, xlsx_path


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
        "version": "V1.1",
        "database": str(target),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "backup": str(backup_path) if backup_path else None,
        "schema_rebuilt": False,
        "change_notes_migrated": 0,
        "alternative_members_initialized": 0,
        "normalized_materials": [],
        "rewired_bom_lines": 0,
    }
    db = sqlite3.connect(target, timeout=30)
    try:
        db.execute("PRAGMA foreign_keys = OFF")
        db.execute("BEGIN IMMEDIATE")
        item_columns = _columns(db, "items")
        if "is_formally_imported" not in item_columns:
            report["change_notes_migrated"] = _migrate_change_notes(db)
            _rebuild_items(db)
            report["schema_rebuilt"] = True
        report["alternative_members_initialized"] = _add_market_share(db)
        normalized, rewired = _normalize_yj_materials(db)
        report["normalized_materials"] = normalized
        report["rewired_bom_lines"] = rewired
        report["validation"] = _validate(db)
        already_logged = db.execute(
            "SELECT 1 FROM audit_events WHERE action = ? LIMIT 1", (MIGRATION_ACTION,)
        ).fetchone()
        if not already_logged:
            _audit(
                db,
                MIGRATION_ACTION,
                "database",
                None,
                "BOM V1.1 数据库结构与历史数据迁移",
                after={
                    "schema_rebuilt": report["schema_rebuilt"],
                    "change_notes_migrated": report["change_notes_migrated"],
                    "normalized_materials": len(normalized),
                    "rewired_bom_lines": rewired,
                },
                batch_key="v1_1-upgrade",
            )
        db.commit()
        db.execute("PRAGMA foreign_keys = ON")
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"V1.1 迁移后数据库完整性检查失败：{integrity}")
        report["integrity"] = integrity
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        report["status"] = "success"
    except Exception as exc:
        db.rollback()
        report["status"] = "failed"
        report["error"] = str(exc)
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        if write_reports:
            paths = write_report(report, report_dir)
            report["reports"] = [str(value) for value in paths]
        raise
    finally:
        db.close()
    if write_reports:
        paths = write_report(report, report_dir)
        report["reports"] = [str(value) for value in paths]
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="BOM V1.1 数据库升级")
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
