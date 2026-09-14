from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app import models, schemas, services
from backend.app.demo import DEMO_CODES, DEMO_GROUP_NAMES, seed_demo_in_session


def test_complete_demo_dataset_and_idempotency(db: Session):
    actor = db.scalar(select(models.User).where(models.User.username == "admin"))
    assert actor
    result = seed_demo_in_session(db, actor)

    assert result["created"] is True
    assert result["demo_items"] == 24
    assert result["demo_bom_lines"] == 31
    assert result["demo_groups"] == 5
    assert result["historical_digest_before"] == result["historical_digest_after"]
    assert db.scalar(select(func.count()).select_from(models.Item).where(models.Item.code.in_(DEMO_CODES))) == 24
    assert db.scalar(select(func.count()).select_from(models.AlternativeGroup).where(models.AlternativeGroup.name.in_(DEMO_GROUP_NAMES))) == 5

    machine = db.scalar(select(models.Item).where(models.Item.code == "00.999.02"))
    sensor = db.scalar(select(models.Item).where(models.Item.code == "90.9004.01"))
    enhanced_unit = db.scalar(select(models.Item).where(models.Item.code == "03.999.04"))
    assert machine and sensor and enhanced_unit
    assert len(services.technical_bom(db, machine.id)) >= 15
    production_codes = {row["item"]["code"] for row in services.production_bom(db, machine.id)}
    assert {"90.9001.01", "90.9002.01", "90.9004.01", "90.9006.01", "90.9008.01"} <= production_codes
    assert any(row["parent"]["code"] == "05.999.01" for row in services.reverse_paths(db, sensor.id))
    candidate_line = db.scalar(select(models.BOMLine).where(
        models.BOMLine.parent_item_id == machine.id,
        models.BOMLine.child_item_id == db.scalar(select(models.Item.id).where(models.Item.code == "03.999.01")),
    ))
    assert candidate_line and candidate_line.alternative_group_id
    combination_parent = db.scalar(select(models.Item).where(models.Item.code == "05.999.04"))
    combination_child = db.scalar(select(models.Item).where(models.Item.code == "05.999.01"))
    assert combination_parent and combination_child
    assert db.scalar(select(models.BOMLine).where(
        models.BOMLine.parent_item_id == combination_parent.id,
        models.BOMLine.child_item_id == combination_child.id,
    ))
    second = seed_demo_in_session(db, actor)
    assert second["created"] is False
    assert second["combination_upgraded"] is False
    assert second["demo_items"] == 24

    combination_line = db.scalar(select(models.BOMLine).where(
        models.BOMLine.parent_item_id == combination_parent.id,
        models.BOMLine.child_item_id == combination_child.id,
    ))
    assert combination_line
    db.delete(combination_line)
    db.commit()
    upgraded = seed_demo_in_session(db, actor)
    assert upgraded["created"] is False
    assert upgraded["combination_upgraded"] is True
    assert db.scalar(select(func.count()).select_from(models.BOMLine).where(
        models.BOMLine.parent_item_id == combination_parent.id,
        models.BOMLine.child_item_id == combination_child.id,
    )) == 1


def test_demo_seed_rejects_partial_reserved_code_collision(db: Session):
    actor = db.scalar(select(models.User).where(models.User.username == "admin"))
    assert actor
    services.create_item(db, schemas.ItemCreate(
        item_type="material", code="90.9001.01", name="人工已有物料",
        source_type="purchased", reason="测试保留编码冲突",
        similarity_confirmed=True,
    ), actor)

    with pytest.raises(RuntimeError, match="已拒绝修改原记录"):
        seed_demo_in_session(db, actor)
    existing = db.scalar(select(models.Item).where(models.Item.code == "90.9001.01"))
    assert existing and existing.name == "人工已有物料"
