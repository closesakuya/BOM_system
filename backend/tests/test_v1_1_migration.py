from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.app.v1_1_migration import apply_upgrade
from backend.app.v1_1_1_migration import apply_upgrade as apply_v1_1_1_upgrade


OLD_SCHEMA = """
CREATE TABLE users (id INTEGER NOT NULL PRIMARY KEY);
CREATE TABLE items (
    id INTEGER NOT NULL PRIMARY KEY,
    item_type VARCHAR(20) NOT NULL,
    code VARCHAR(120) NOT NULL UNIQUE,
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
    change_note TEXT,
    requires_assembly BOOLEAN NOT NULL,
    status VARCHAR(20),
    copied_from_id INTEGER,
    deleted_at DATETIME,
    created_by INTEGER,
    updated_by INTEGER,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT uq_item_series_version UNIQUE (version_series, version_number),
    FOREIGN KEY(copied_from_id) REFERENCES items (id),
    FOREIGN KEY(created_by) REFERENCES users (id),
    FOREIGN KEY(updated_by) REFERENCES users (id)
);
CREATE TABLE alternative_groups (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    item_type VARCHAR(20) NOT NULL,
    default_item_id INTEGER NOT NULL,
    active BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    FOREIGN KEY(default_item_id) REFERENCES items (id)
);
CREATE TABLE alternative_members (
    id INTEGER NOT NULL PRIMARY KEY,
    group_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    priority INTEGER NOT NULL,
    is_default BOOLEAN NOT NULL,
    active BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE (group_id, item_id),
    FOREIGN KEY(group_id) REFERENCES alternative_groups (id),
    FOREIGN KEY(item_id) REFERENCES items (id)
);
CREATE TABLE bom_lines (
    id INTEGER NOT NULL PRIMARY KEY,
    parent_item_id INTEGER NOT NULL,
    child_item_id INTEGER NOT NULL,
    quantity NUMERIC(18, 6) NOT NULL,
    sort_order INTEGER NOT NULL,
    line_remark TEXT,
    alternative_group_id INTEGER,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE (parent_item_id, child_item_id),
    FOREIGN KEY(parent_item_id) REFERENCES items (id),
    FOREIGN KEY(child_item_id) REFERENCES items (id),
    FOREIGN KEY(alternative_group_id) REFERENCES alternative_groups (id)
);
CREATE TABLE audit_events (
    id INTEGER NOT NULL PRIMARY KEY,
    actor_id INTEGER,
    action VARCHAR(80) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id INTEGER,
    reason TEXT NOT NULL,
    batch_key VARCHAR(80),
    before_json TEXT,
    after_json TEXT,
    created_at DATETIME NOT NULL,
    FOREIGN KEY(actor_id) REFERENCES users (id)
);
"""


def _insert_item(
    db: sqlite3.Connection,
    item_id: int,
    item_type: str,
    code: str,
    name: str,
    *,
    source_type: str | None = None,
    change_note: str | None = None,
) -> None:
    body, version = code.rsplit(".", 1)
    db.execute(
        """
        INSERT INTO items (
            id, item_type, code, code_body, version_label, version_number,
            version_series, auxiliary_code, name, specification, source_type,
            unit, remark, previous_version_name, invoice_name, material_attribute,
            change_note, requires_assembly, status, copied_from_id, deleted_at,
            created_by, updated_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 'pcs', NULL, NULL, NULL,
                  NULL, ?, 0, ?, NULL, NULL, 1, 1, '2026-01-01', '2026-01-01')
        """,
        (
            item_id,
            item_type,
            code,
            body,
            version,
            int(version),
            body,
            "B01.A" if item_type == "material" else None,
            name,
            source_type,
            change_note,
            None if item_type == "material" else "active",
        ),
    )


def _legacy_database(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.executescript(OLD_SCHEMA)
        db.execute("INSERT INTO users (id) VALUES (1)")
        _insert_item(db, 1, "material", "10.1001.0", "正式原材料", source_type="purchased", change_note="历史说明")
        _insert_item(db, 2, "material", "Y10.1001.0", "历史Y原材料", source_type="purchased")
        _insert_item(db, 3, "semi_finished", "05.001.01", "测试半成品")
        _insert_item(db, 4, "machine", "J00.001.01", "合法J前缀整机")
        _insert_item(db, 5, "material", "10.1002.0", "替代原材料", source_type="purchased")
        db.execute(
            "INSERT INTO bom_lines VALUES "
            "(1, 3, 2, 2, 1, '历史引用', NULL, '2026-01-01', '2026-01-01')"
        )
        db.execute(
            "INSERT INTO alternative_groups VALUES "
            "(1, '测试替代组', 'material', 1, 1, '2026-01-01', '2026-01-01')"
        )
        db.execute(
            "INSERT INTO alternative_members VALUES "
            "(1, 1, 1, 0, 1, 1, '2026-01-01', '2026-01-01'),"
            "(2, 1, 5, 1, 0, 1, '2026-01-01', '2026-01-01')"
        )
        db.commit()


def _unmappable_legacy_database(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.executescript(OLD_SCHEMA)
        db.execute("INSERT INTO users (id) VALUES (1)")
        _insert_item(db, 1, "material", "Y10.9999.0", "无对应正式物料", source_type="purchased", change_note="必须回滚")
        db.commit()


def test_v1_1_upgrade_is_atomic_and_idempotent(tmp_path: Path):
    database = tmp_path / "legacy.db"
    backups = tmp_path / "backups"
    _legacy_database(database)

    first = apply_upgrade(database, backup_dir=backups, write_reports=False)
    assert first["status"] == "success"
    assert first["schema_rebuilt"] is True
    assert first["change_notes_migrated"] == 1
    assert len(first["normalized_materials"]) == 1
    assert first["rewired_bom_lines"] == 1
    assert first["alternative_members_initialized"] == 2
    assert Path(first["backup"]).is_file()

    with sqlite3.connect(database) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(items)")}
        assert "change_note" not in columns
        assert {"platform_code_rule", "machine_model", "is_formally_imported"} <= columns
        assert db.execute("SELECT child_item_id FROM bom_lines WHERE id = 1").fetchone()[0] == 1
        assert db.execute("SELECT code, is_formally_imported FROM items WHERE id = 2").fetchone() == (
            "10.1001.0",
            0,
        )
        assert db.execute("SELECT code, is_formally_imported FROM items WHERE id = 4").fetchone() == (
            "J00.001.01",
            1,
        )
        assert db.execute("SELECT platform_code_rule FROM items WHERE id = 1").fetchone()[0] == "B01.A"
        assert [str(row[0]) for row in db.execute("SELECT market_share FROM alternative_members ORDER BY id")] == [
            "50",
            "50",
        ]
        assert db.execute("SELECT count(*) FROM items WHERE code = '10.1001.0'").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM audit_events WHERE action = 'migrate_change_note'").fetchone()[0] == 1
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE items SET is_formally_imported = 1 WHERE id = 2")

    second = apply_upgrade(database, create_backup=False, write_reports=False)
    assert second["schema_rebuilt"] is False
    assert second["change_notes_migrated"] == 0
    assert second["normalized_materials"] == []
    assert second["rewired_bom_lines"] == 0
    assert second["alternative_members_initialized"] == 0


def test_v1_1_upgrade_failure_rolls_back_and_writes_failure_report(tmp_path: Path):
    database = tmp_path / "unmappable.db"
    backups = tmp_path / "backups"
    reports = tmp_path / "reports"
    _unmappable_legacy_database(database)

    with pytest.raises(RuntimeError, match="找不到对应正式物料"):
        apply_upgrade(database, backup_dir=backups, report_dir=reports)

    with sqlite3.connect(database) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(items)")}
        assert "change_note" in columns
        assert "is_formally_imported" not in columns
        assert db.execute("SELECT code, change_note FROM items").fetchone() == (
            "Y10.9999.0",
            "必须回滚",
        )
        assert db.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 0
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    backup = next(backups.glob("*.db"))
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    report_path = next(reports.glob("*.json"))
    report = __import__("json").loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert "Y10.9999.0" in report["error"]
    assert next(reports.glob("*.xlsx")).is_file()


def test_v1_1_1_upgrade_assigns_99_codes_archives_and_is_idempotent(tmp_path: Path):
    database = tmp_path / "v1-legacy.db"
    _legacy_database(database)
    apply_upgrade(database, create_backup=False, write_reports=False)

    first = apply_v1_1_1_upgrade(database, create_backup=False, write_reports=False)
    assert first["status"] == "success"
    assert first["schema_upgraded"] is True
    assert first["unofficial_materials_migrated"] == 1
    assert first["validation"] == {
        "foreign_key_errors": 0,
        "duplicate_unofficial_codes": 0,
        "invalid_unofficial_codes": 0,
        "formal_in_reserved_range": 0,
        "invalid_unofficial_status": 0,
        "archived_without_link": 0,
        "invalid_key_component_codes": 0,
    }
    with sqlite3.connect(database) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(items)")}
        assert "platform_code_rule" not in columns
        assert {"key_component_code", "historical_item_code", "unofficial_status"} <= columns
        assert db.execute(
            "SELECT code, historical_item_code, unofficial_status FROM items WHERE id = 2"
        ).fetchone() == ("99.0001.0", "Y10.1001.0", "archived")
        assert db.execute(
            "SELECT source_item_id, target_item_id, is_historical FROM material_promotion_links"
        ).fetchone() == (2, 1, 1)
        assert db.execute(
            "SELECT next_value FROM code_sequences WHERE name = 'unofficial_material'"
        ).fetchone()[0] == 1
        assert db.execute("SELECT key_component_code FROM items WHERE id = 1").fetchone()[0] == "B01.A"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    second = apply_v1_1_1_upgrade(database, create_backup=False, write_reports=False)
    assert second["schema_upgraded"] is False
    assert second["unofficial_materials_migrated"] == 0
    assert second["key_codes_normalized"] == 0
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM material_promotion_links").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM audit_events WHERE action = 'v1_1_1_upgrade'").fetchone()[0] == 1


def test_v1_1_1_invalid_key_code_rolls_back_and_reports(tmp_path: Path):
    database = tmp_path / "invalid-key.db"
    reports = tmp_path / "reports"
    _legacy_database(database)
    apply_upgrade(database, create_backup=False, write_reports=False)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE items SET platform_code_rule = 'INVALID KEY' WHERE id = 1")
        db.commit()

    with pytest.raises(RuntimeError, match="关键器件码格式无效"):
        apply_v1_1_1_upgrade(
            database,
            create_backup=False,
            report_dir=reports,
        )
    with sqlite3.connect(database) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(items)")}
        assert "platform_code_rule" in columns
        assert "key_component_code" not in columns
        assert db.execute("SELECT code FROM items WHERE id = 2").fetchone()[0] == "10.1001.0"
        assert db.execute("SELECT count(*) FROM audit_events WHERE action = 'v1_1_1_upgrade'").fetchone()[0] == 0
    report = __import__("json").loads(next(reports.glob("*.json")).read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert "INVALID KEY" in report["error"]
    assert next(reports.glob("*.xlsx")).is_file()
