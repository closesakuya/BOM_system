from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.app.machine_model_backfill import (
    MACHINE_MODELS,
    OTHER_MODEL,
    apply_backfill,
    classify_machine_name,
)


SCHEMA = """
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    item_type TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    machine_model TEXT,
    updated_at TEXT
);
CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY,
    actor_id INTEGER,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    reason TEXT NOT NULL,
    batch_key TEXT,
    before_json TEXT,
    after_json TEXT,
    created_at TEXT NOT NULL
);
"""


def _database(path: Path, *, ambiguous: bool = False) -> None:
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        names = [f"测试整机-{model}-标准配置" for model in MACHINE_MODELS]
        names.append("不含已知型号的整机")
        if ambiguous:
            names.append("Y60-D60 混合名称")
        for index, name in enumerate(names, 1):
            db.execute(
                "INSERT INTO items VALUES (?, 'machine', ?, ?, NULL, '2026-01-01')",
                (index, f"00.001.{index:02d}", name),
            )
        db.execute(
            "INSERT INTO items VALUES (100, 'machine', '00.100.01', '人工已分类', '人工机型', '2026-01-01')"
        )
        db.execute(
            "INSERT INTO items VALUES (101, 'material', '10.1001.0', 'Y60 原材料', NULL, '2026-01-01')"
        )
        db.commit()


def test_machine_model_backfill_matches_name_is_audited_and_idempotent(tmp_path: Path):
    database = tmp_path / "models.db"
    backups = tmp_path / "backups"
    reports = tmp_path / "reports"
    _database(database)

    first = apply_backfill(database, backup_dir=backups, report_dir=reports)
    assert first["status"] == "success"
    assert first["total_machines"] == len(MACHINE_MODELS) + 2
    assert first["updated"] == len(MACHINE_MODELS) + 1
    assert first["skipped_existing"] == 1
    assert first["integrity"] == "ok"
    assert Path(first["backup"]).is_file()
    assert Path(first["report"]).is_file()
    assert first["distribution"] == {
        "D60": 1,
        "G65": 1,
        "J60B": 1,
        "R60": 1,
        "T60": 1,
        "T65": 1,
        "T70": 1,
        "Y60": 1,
        "人工机型": 1,
        OTHER_MODEL: 1,
    }
    with sqlite3.connect(database) as db:
        values = dict(db.execute("SELECT name, machine_model FROM items WHERE item_type = 'machine'"))
        for model in MACHINE_MODELS:
            assert values[f"测试整机-{model}-标准配置"] == model
        assert values["不含已知型号的整机"] == OTHER_MODEL
        assert values["人工已分类"] == "人工机型"
        assert db.execute(
            "SELECT count(*) FROM audit_events WHERE action = 'backfill_machine_model'"
        ).fetchone()[0] == len(MACHINE_MODELS) + 1
        assert db.execute(
            "SELECT machine_model FROM items WHERE item_type = 'material'"
        ).fetchone()[0] is None

    second = apply_backfill(database, create_backup=False, write_report=False)
    assert second["updated"] == 0
    assert second["skipped_existing"] == len(MACHINE_MODELS) + 2
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM audit_events").fetchone()[0] == len(MACHINE_MODELS) + 1


def test_machine_model_backfill_rejects_ambiguous_names_and_rolls_back(tmp_path: Path):
    database = tmp_path / "ambiguous.db"
    _database(database, ambiguous=True)

    with pytest.raises(ValueError, match="同时匹配多个机型"):
        apply_backfill(database, create_backup=False, write_report=False)

    with sqlite3.connect(database) as db:
        assert db.execute(
            "SELECT count(*) FROM items WHERE machine_model IS NOT NULL"
        ).fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 0


def test_classify_machine_name_is_case_insensitive():
    assert classify_machine_name("cod 分析仪-y60") == "Y60"
    assert classify_machine_name("无匹配") == OTHER_MODEL
