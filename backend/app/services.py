from __future__ import annotations

import json
import re
import unicodedata
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any, Iterable

from fastapi import HTTPException
from rapidfuzz import fuzz
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from . import models, schemas
from .item_lifecycle import allocate_id


ITEM_TYPES = {"material", "semi_finished", "unit", "machine"}
ITEM_STATUSES = {"active", "trial", "disabled"}
SOURCE_TYPES = {"purchased", "outsourced", "self_made"}
UNOFFICIAL_STATUSES = {"pending", "archived"}
UNOFFICIAL_SEQUENCE_NAME = "unofficial_material"
UNOFFICIAL_CODE_PATTERN = re.compile(r"^99\.(\d{4})\.(\d)$")
KEY_COMPONENT_CODE_PATTERN = re.compile(r"^[A-Z0-9]{3}\.[A-Z0-9]$")
ALLOWED_CHILDREN = {
    "material": {"material"},
    "semi_finished": {"semi_finished", "material"},
    "unit": {"semi_finished", "material"},
    "machine": {"unit", "semi_finished", "material"},
}

DEFAULT_NON_MATERIAL_CODE_RULES: tuple[dict[str, Any], ...] = (
    {
        "item_type": "machine",
        "large_category": "整机",
        "small_category": "包装后的成品机",
        "material_attribute": "产品",
        "prefix": "00.",
        "pattern": "00.XXX.01",
        "description": "依据《物料编码标准》：包装后的成品机。",
        "active": True,
        "sort_order": 1001,
    },
    {
        "item_type": "unit",
        "large_category": "单元",
        "small_category": "分析单元或电气机柜",
        "material_attribute": "产品",
        "prefix": "03.",
        "pattern": "03.XXX.01",
        "description": "依据《物料编码标准》：分析单元或电气机柜。",
        "active": True,
        "sort_order": 1002,
    },
    {
        "item_type": "semi_finished",
        "large_category": "半成品",
        "small_category": "模块和组件（CBB）",
        "material_attribute": "CBB",
        "prefix": "05.",
        "pattern": "05.XXX.01",
        "description": "依据《物料编码标准》：模块和组件（CBB）。",
        "active": True,
        "sort_order": 1003,
    },
)


def ensure_default_non_material_code_rules(db: Session) -> int:
    """Add the three baseline product rules only when a type has no rules yet."""
    added = 0
    for values in DEFAULT_NON_MATERIAL_CODE_RULES:
        exists = db.scalar(
            select(models.CodeRule.id)
            .where(models.CodeRule.item_type == values["item_type"])
            .limit(1)
        )
        if exists:
            continue
        db.add(models.CodeRule(**values))
        added += 1
    if added:
        db.commit()
    return added


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, Decimal)):
        return str(value)
    raise TypeError(f"Unsupported JSON type: {type(value)!r}")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=json_default)


def parse_code(code: str) -> tuple[str, str, int]:
    code = code.strip()
    if not code or "." not in code:
        raise HTTPException(status_code=422, detail="系统物料编码必须包含版本尾号")
    body, version = code.rsplit(".", 1)
    if not body or not version.isdigit():
        raise HTTPException(status_code=422, detail="版本尾号必须是数字")
    return body, version, int(version)


def code_rule_template(rule: models.CodeRule) -> str:
    match = re.search(r"\d[\d.Xx]*", rule.pattern or "")
    return match.group(0) if match else rule.prefix.strip()


def code_rule_fixed_prefix(rule: models.CodeRule) -> str:
    template = code_rule_template(rule)
    marker = template.upper().find("X")
    return template[:marker] if marker >= 0 else rule.prefix.strip()


def code_matches_rule(code: str, rule: models.CodeRule) -> bool:
    template = code_rule_template(rule)
    body_template, separator, _version_template = template.rpartition(".")
    if not separator:
        return code.startswith(code_rule_fixed_prefix(rule))
    body_expression = "".join(r"\d" if character.upper() == "X" else re.escape(character) for character in body_template)
    return re.fullmatch(rf"{body_expression}\.\d+", code) is not None


def code_rule_error(rule: models.CodeRule) -> str:
    return f"系统物料编码必须符合所选规则 {code_rule_template(rule)}（固定前缀 {code_rule_fixed_prefix(rule)}）"


def code_availability(
    db: Session,
    code: str,
    code_rule_id: int | None = None,
    item_type: str | None = None,
    is_formally_imported: bool = True,
) -> dict[str, Any]:
    normalized = code.strip()
    rule = db.get(models.CodeRule, code_rule_id) if code_rule_id else None
    if item_type is not None and item_type not in ITEM_TYPES:
        return {
            "valid": False, "code": normalized, "exists": False,
            "message": "未知物料类型", "maximum": None,
            "same_body_maximum": None, "next_body_code": None, "next_version_code": None,
        }
    if not is_formally_imported and item_type != "material":
        return {
            "valid": False, "code": normalized, "exists": False,
            "message": "只有原材料可以设为未正式导入", "maximum": None,
            "same_body_maximum": None, "next_body_code": None, "next_version_code": None,
        }
    if not is_formally_imported:
        estimated = preview_unofficial_code(db)
        return {
            "valid": True,
            "code": estimated,
            "exists": False,
            "message": "未正式原材料编号由系统在提交时自动分配",
            "maximum": None,
            "same_body_maximum": None,
            "next_body_code": estimated,
            "next_version_code": None,
            "duplicate_items": [],
        }
    if UNOFFICIAL_CODE_PATTERN.fullmatch(normalized):
        return {
            "valid": False, "code": normalized, "exists": False,
            "message": "99.XXXX.X 为未正式原材料专属号段，正式物料不能使用", "maximum": None,
            "same_body_maximum": None, "next_body_code": None, "next_version_code": None,
        }
    if code_rule_id and (not rule or not rule.active or (item_type is not None and rule.item_type != item_type)):
        return {
            "valid": False, "code": normalized, "exists": False,
            "message": "所选编码规则不存在、已停用或不适用于当前物料类型", "maximum": None,
            "same_body_maximum": None, "next_body_code": None, "next_version_code": None,
        }
    try:
        body, version_label, _version_number = parse_code(normalized)
    except HTTPException as exc:
        return {
            "valid": False, "code": normalized, "exists": False,
            "message": str(exc.detail), "maximum": None,
            "same_body_maximum": None, "next_body_code": None, "next_version_code": None,
        }
    if rule and not code_matches_rule(normalized, rule):
        return {
            "valid": False, "code": normalized, "exists": False,
            "message": code_rule_error(rule), "maximum": None,
            "same_body_maximum": None, "next_body_code": None, "next_version_code": None,
        }

    exact = db.scalar(
        select(models.Item).where(
            models.Item.code == normalized,
            models.Item.is_formally_imported.is_(True),
        )
    )
    same_body = list(db.scalars(
        select(models.Item).where(
            models.Item.code_body == body,
            models.Item.is_formally_imported.is_(True),
        ).order_by(models.Item.version_number.desc(), models.Item.id.desc())
    ))
    maximum_version_item = same_body[0] if same_body else None
    version_width = max([len(version_label), *[len(item.version_label) for item in same_body if item.version_label.isdigit()]])
    next_version = (maximum_version_item.version_number + 1) if maximum_version_item else 1
    next_version_code = f"{body}.{next_version:0{version_width}d}"
    while db.scalar(select(models.Item.id).where(
        models.Item.code == next_version_code,
        models.Item.is_formally_imported.is_(True),
    )):
        next_version += 1
        next_version_code = f"{body}.{next_version:0{version_width}d}"

    body_match = re.fullmatch(r"(.*?)(\d+)", body)
    maximum_family_item = None
    next_body_code = None
    family_prefix = None
    if body_match:
        family_prefix, serial_label = body_match.groups()
        serial_width = len(serial_label)
        family_candidates: list[tuple[int, int, models.Item]] = []
        for item in db.scalars(select(models.Item).where(
            models.Item.code_body.like(f"{family_prefix}%"),
            models.Item.is_formally_imported.is_(True),
        )):
            candidate_match = re.fullmatch(rf"{re.escape(family_prefix)}(\d{{{serial_width}}})", item.code_body)
            if candidate_match:
                family_candidates.append((int(candidate_match.group(1)), item.version_number, item))
        if family_candidates:
            maximum_serial, _maximum_version, maximum_family_item = max(family_candidates, key=lambda row: (row[0], row[1]))
            next_serial = maximum_serial + 1
        else:
            next_serial = int(serial_label)
        next_body_code = f"{family_prefix}{next_serial:0{serial_width}d}.01"
        while db.scalar(select(models.Item.id).where(
            models.Item.code == next_body_code,
            models.Item.is_formally_imported.is_(True),
        )):
            next_serial += 1
            next_body_code = f"{family_prefix}{next_serial:0{serial_width}d}.01"

    result = {
        "valid": True, "code": normalized,
        "exists": exact is not None,
        "message": "系统物料编码已存在" if exact else "系统物料编码可用",
        "conflict_item": item_dict(exact) if exact else None,
        "duplicate_items": [],
        "family_prefix": family_prefix,
        "maximum": item_dict(maximum_family_item) if maximum_family_item else None,
        "same_body_maximum": item_dict(maximum_version_item) if maximum_version_item else None,
        "next_body_code": next_body_code,
        "next_version_code": next_version_code,
    }
    if rule:
        recommendation = next_code(db, rule.prefix, rule.pattern)
        result["maximum"] = recommendation["maximum"]
        result["next_body_code"] = recommendation["recommended_code"]
        result["rule_prefix"] = code_rule_fixed_prefix(rule)
        result["rule_pattern"] = code_rule_template(rule)
    return result


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).casefold().strip()
    text = re.sub(r"[\s,，。;；:：、/\\\-_]+", "", text)
    unit_map = {"毫米": "mm", "厘米": "cm", "米": "m", "千克": "kg", "克": "g"}
    for source, target in unit_map.items():
        text = text.replace(source, target)
    return text


def displayed_item_code(item: models.Item) -> str:
    return item.code


def unofficial_code_from_sequence(value: int) -> str:
    if value < 0 or value >= 99990:
        raise HTTPException(status_code=409, detail="未正式原材料编号已用尽（最大 99.9999.9）")
    body, version = divmod(value, 10)
    return f"99.{body + 1:04d}.{version}"


def unofficial_sequence_floor(db: Session) -> int:
    # Imported 99 codes retain their numbers; never start allocation back at zero.
    return int(db.execute(text("""
        SELECT coalesce(max((cast(substr(code,4,4) AS INTEGER)-1)*10 + cast(substr(code,9,1) AS INTEGER)), -1)+1
        FROM items WHERE code GLOB '99.[0-9][0-9][0-9][0-9].[0-9]'
    """)).scalar_one())


def preview_unofficial_code(db: Session, offset: int = 0) -> str:
    next_value = db.scalar(
        select(models.CodeSequence.next_value).where(
            models.CodeSequence.name == UNOFFICIAL_SEQUENCE_NAME
        )
    )
    return unofficial_code_from_sequence(max(int(next_value or 0), unofficial_sequence_floor(db)) + offset)


def allocate_unofficial_code(db: Session) -> str:
    value = db.execute(
        text(
            "INSERT INTO code_sequences (name, next_value) VALUES (:name, :floor + 1) "
            "ON CONFLICT(name) DO UPDATE SET next_value = max(code_sequences.next_value + 1, excluded.next_value) "
            "RETURNING next_value - 1"
        ),
        {"name": UNOFFICIAL_SEQUENCE_NAME, "floor": unofficial_sequence_floor(db)},
    ).scalar_one()
    return unofficial_code_from_sequence(int(value))


def normalize_key_component_code(value: str | None) -> str | None:
    normalized = re.sub(r"\s+", "", value or "").upper()
    if not normalized:
        return None
    if not KEY_COMPONENT_CODE_PATTERN.fullmatch(normalized):
        raise HTTPException(
            status_code=422,
            detail="关键器件码格式必须为三位字母或数字、点号、一位字母或数字，例如 F33.A",
        )
    return normalized


def item_dict(item: models.Item) -> dict[str, Any]:
    display_code = displayed_item_code(item)
    return {
        "id": item.id,
        "item_type": item.item_type,
        "code": display_code,
        "code_body": item.code_body,
        "version_label": item.version_label,
        "version_number": item.version_number,
        "version_series": item.version_series,
        "auxiliary_code": item.auxiliary_code,
        "name": item.name,
        "specification": item.specification,
        "source_type": item.source_type,
        "unit": item.unit,
        "remark": item.remark,
        "previous_version_name": item.previous_version_name,
        "invoice_name": item.invoice_name,
        "material_attribute": item.material_attribute,
        "key_component_code": item.key_component_code,
        "historical_item_code": item.historical_item_code,
        "machine_model": item.machine_model,
        "is_formally_imported": item.is_formally_imported,
        "unofficial_status": item.unofficial_status,
        "requires_assembly": item.requires_assembly,
        "status": item.status,
        "copied_from_id": item.copied_from_id,
        "deleted_at": item.deleted_at.isoformat() if item.deleted_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def user_dict(user: models.User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "department": user.department,
        "role": user.role,
        "active": user.active,
    }


def audit(
    db: Session,
    actor_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None,
    reason: str,
    before: Any = None,
    after: Any = None,
    batch_key: str | None = None,
) -> models.AuditEvent:
    event = models.AuditEvent(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        reason=reason,
        batch_key=batch_key,
        before_json=dumps(before) if before is not None else None,
        after_json=dumps(after) if after is not None else None,
    )
    db.add(event)
    return event


def similarity_candidates(
    db: Session,
    name: str,
    specification: str | None,
    item_type: str | None = None,
    exclude_id: int | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    query = select(models.Item).where(models.Item.deleted_at.is_(None))
    if item_type:
        query = query.where(models.Item.item_type == item_type)
    if exclude_id:
        query = query.where(models.Item.id != exclude_id)
    normalized_name = normalize_text(name)
    normalized_full = normalize_text(f"{name}|{specification or ''}")
    results: list[dict[str, Any]] = []
    for candidate in db.scalars(query):
        name_score = fuzz.ratio(normalized_name, normalize_text(candidate.name))
        full_score = fuzz.ratio(
            normalized_full,
            normalize_text(f"{candidate.name}|{candidate.specification or ''}"),
        )
        level = "red" if full_score >= 95 else "yellow" if name_score >= 50 else "none"
        if level != "none":
            results.append(
                {
                    "item": item_dict(candidate),
                    "name_score": round(name_score, 2),
                    "full_score": round(full_score, 2),
                    "level": level,
                }
            )
    results.sort(key=lambda row: (row["level"] == "red", row["full_score"], row["name_score"]), reverse=True)
    return results[:limit]


def validate_item_business(item_type: str, source_type: str | None, status: str | None) -> tuple[str | None, bool]:
    if item_type not in ITEM_TYPES:
        raise HTTPException(status_code=422, detail="未知物料类型")
    if item_type == "material":
        if source_type not in SOURCE_TYPES:
            raise HTTPException(status_code=422, detail="原材料必须选择外购、外协或自制")
        if status not in {None, "active", "disabled"}:
            raise HTTPException(422, "原材料状态只能为在用或停用")
        return status or "active", source_type == "self_made"
    if source_type is not None:
        raise HTTPException(status_code=422, detail="只有原材料可以设置来源属性")
    resolved_status = status or "trial"
    if resolved_status not in ITEM_STATUSES:
        raise HTTPException(status_code=422, detail="无效状态")
    return resolved_status, False


def create_item(
    db: Session,
    payload: schemas.ItemCreate,
    actor: models.User,
    commit: bool = True,
    historical_item_code: str | None = None,
    similarity_exclude_id: int | None = None,
) -> models.Item:
    if not payload.is_formally_imported and payload.item_type != "material":
        raise HTTPException(status_code=422, detail="只有原材料可以设为未正式导入")
    if payload.is_formally_imported:
        normalized_code = (payload.code or "").strip()
        if not normalized_code:
            raise HTTPException(status_code=422, detail="正式物料必须填写系统物料编码")
        if UNOFFICIAL_CODE_PATTERN.fullmatch(normalized_code):
            raise HTTPException(status_code=422, detail="99.XXXX.X 为未正式原材料专属号段")
    else:
        if payload.code_rule_id is not None:
            raise HTTPException(status_code=422, detail="未正式原材料不使用正式物料编码规则")
        normalized_code = allocate_unofficial_code(db)
    code_body, version_label, version_number = parse_code(normalized_code)
    if payload.code_rule_id is not None:
        rule = db.get(models.CodeRule, payload.code_rule_id)
        if not rule or not rule.active or rule.item_type != payload.item_type:
            raise HTTPException(status_code=422, detail="所选编码规则不存在、已停用或不适用于当前物料类型")
        if not code_matches_rule(normalized_code, rule):
            raise HTTPException(status_code=422, detail=code_rule_error(rule))
    if payload.is_formally_imported and db.scalar(select(models.Item).where(
        models.Item.code == normalized_code,
        models.Item.is_formally_imported.is_(True),
    )):
        raise HTTPException(status_code=409, detail="系统物料编码已存在")
    candidates = similarity_candidates(
        db, payload.name, payload.specification, payload.item_type, exclude_id=similarity_exclude_id
    )
    if any(row["level"] == "red" for row in candidates) and not payload.similarity_confirmed:
        raise HTTPException(status_code=409, detail={"message": "存在高度相似物料，需要二次确认", "candidates": candidates})
    status_value, _source_requires_components = validate_item_business(payload.item_type, payload.source_type, payload.status)
    key_component_code = normalize_key_component_code(payload.key_component_code)
    if key_component_code and payload.item_type != "material":
        raise HTTPException(status_code=422, detail="只有原材料可以设置关键器件码")
    if payload.machine_model and payload.item_type != "machine":
        raise HTTPException(status_code=422, detail="只有整机可以设置机型")
    item = models.Item(
        id=allocate_id(db, 'items', 'item'),
        item_type=payload.item_type,
        code=normalized_code,
        code_body=code_body,
        version_label=version_label,
        version_number=version_number,
        version_series=code_body,
        auxiliary_code=payload.auxiliary_code,
        name=payload.name.strip(),
        specification=payload.specification,
        source_type=payload.source_type,
        unit=payload.unit.strip() or "pcs",
        remark=payload.remark,
        previous_version_name=payload.previous_version_name,
        invoice_name=payload.invoice_name,
        material_attribute=payload.material_attribute,
        key_component_code=key_component_code,
        historical_item_code=historical_item_code.strip() if historical_item_code else None,
        machine_model=payload.machine_model.strip() if payload.machine_model else None,
        is_formally_imported=payload.is_formally_imported,
        unofficial_status=None if payload.is_formally_imported else "pending",
        requires_assembly=bool(payload.components),
        status=status_value,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(item)
    try:
        db.flush()
        for component in payload.components:
            add_bom_line(db, item, component, actor, payload.reason, commit=False)
        if payload.copy_source_id:
            from .item_lifecycle import copy_configurations
            source=db.get(models.Item,payload.copy_source_id)
            if not source or source.deleted_at or source.item_type!=item.item_type:
                raise HTTPException(409,'复制来源无效或类型不同')
            item.copied_from_id=source.id
            copy_configurations(db,source.id,item.id)
            from .path_bom import EffectiveBOM
            EffectiveBOM(db).rows(item.id,show_alternatives=True)
        audit(db, actor.id, "create", "item", item.id, payload.reason, after=item_dict(item))
        if commit:
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="编码或版本记录发生冲突") from exc
    except Exception:
        db.rollback()
        raise
    if commit:
        db.refresh(item)
    return item


def update_item(db: Session, item: models.Item, payload: schemas.ItemUpdate, actor: models.User) -> models.Item:
    if item.unofficial_status == "archived":
        raise HTTPException(status_code=409, detail="已转正式的封存来源只供历史查看，不能修改")
    before = item_dict(item)
    values = payload.model_dump(exclude_unset=True, exclude={"reason", "similarity_confirmed", "requires_assembly"})
    new_name = values.get("name", item.name)
    new_spec = values.get("specification", item.specification)
    candidates = similarity_candidates(db, new_name, new_spec, item.item_type, exclude_id=item.id)
    if any(row["level"] == "red" for row in candidates) and not payload.similarity_confirmed:
        raise HTTPException(status_code=409, detail={"message": "存在高度相似物料，需要二次确认", "candidates": candidates})
    next_source = values.get("source_type", item.source_type)
    next_status = values.get("status", item.status)
    resolved_status, _source_requires_components = validate_item_business(item.item_type, next_source, next_status)
    component_count = (
        db.scalar(select(func.count()).select_from(models.BOMLine).where(models.BOMLine.parent_item_id == item.id)) or 0
        if item.item_type == "material" else 0
    )
    if item.item_type == "material" and item.source_type in {"outsourced", "self_made"} and next_source == "purchased" and component_count:
        raise HTTPException(status_code=409, detail="请先清空组装来源后再改为外购")
    if "key_component_code" in values:
        values["key_component_code"] = normalize_key_component_code(values["key_component_code"])
    if values.get("key_component_code") and item.item_type != "material":
        raise HTTPException(status_code=422, detail="只有原材料可以设置关键器件码")
    if values.get("machine_model") and item.item_type != "machine":
        raise HTTPException(status_code=422, detail="只有整机可以设置机型")
    for key, value in values.items():
        setattr(item, key, value)
    item.status = resolved_status
    item.requires_assembly = bool(component_count) if item.item_type == "material" else False
    item.updated_by = actor.id
    db.flush()
    audit(db, actor.id, "update", "item", item.id, payload.reason, before, item_dict(item))
    db.commit()
    db.refresh(item)
    return item


def promote_material(
    db: Session,
    item: models.Item,
    payload: schemas.PromoteMaterialIn,
    actor: models.User,
) -> models.Item:
    if (
        item.item_type != "material"
        or item.is_formally_imported
        or item.unofficial_status != "pending"
        or item.deleted_at
    ):
        raise HTTPException(status_code=409, detail="只有待转正式的未正式原材料可以转为正式物料")
    if db.scalar(
        select(models.MaterialPromotionLink.id).where(
            models.MaterialPromotionLink.source_item_id == item.id
        )
    ):
        raise HTTPException(status_code=409, detail="该未正式原材料已经存在转正式记录")
    normalized_code = payload.code.strip()
    if UNOFFICIAL_CODE_PATTERN.fullmatch(normalized_code):
        raise HTTPException(status_code=422, detail="转正式必须重新选择正式原材料编码，不能使用 99 专属号段")
    rule = db.get(models.CodeRule, payload.code_rule_id)
    if not rule or not rule.active or rule.item_type != "material":
        raise HTTPException(status_code=422, detail="转正式必须选择有效的原材料编码规则")
    if not code_matches_rule(normalized_code, rule):
        raise HTTPException(status_code=422, detail=code_rule_error(rule))
    conflict = db.scalar(select(models.Item).where(
        models.Item.code == normalized_code,
        models.Item.is_formally_imported.is_(True),
    ))
    if conflict:
        suggestions = code_availability(db, normalized_code, payload.code_rule_id, "material", True)
        raise HTTPException(status_code=409, detail={
            "message": "正式物料编码已存在，请修改编码后再转正式",
            "conflict_item": item_dict(conflict),
            "next_body_code": suggestions.get("next_body_code"),
            "next_version_code": suggestions.get("next_version_code"),
        })
    validation_errors = validate_promotion_bom(db, item)
    if validation_errors:
        raise HTTPException(
            status_code=409,
            detail={"message": "来源 BOM 校验失败，不能转正式", "errors": validation_errors},
        )
    components = [
        schemas.BOMComponentIn(
            child_item_id=line.child_item_id,
            quantity=line.quantity,
            sort_order=line.sort_order,
            line_remark=line.line_remark,
            alternative_group_id=line.alternative_group_id,
        )
        for line in db.scalars(
            select(models.BOMLine)
            .where(models.BOMLine.parent_item_id == item.id)
            .order_by(models.BOMLine.sort_order, models.BOMLine.id)
        )
    ]
    create_payload = schemas.ItemCreate(
        item_type="material",
        code=normalized_code,
        code_rule_id=payload.code_rule_id,
        auxiliary_code=payload.auxiliary_code,
        name=payload.name,
        specification=payload.specification,
        source_type=payload.source_type,
        unit=payload.unit,
        remark=payload.remark,
        previous_version_name=payload.previous_version_name,
        invoice_name=payload.invoice_name,
        material_attribute=payload.material_attribute,
        key_component_code=payload.key_component_code,
        is_formally_imported=True,
        similarity_confirmed=payload.similarity_confirmed,
        reason=payload.reason,
        components=components,
    )
    before = item_dict(item)
    try:
        promoted = create_item(
            db,
            create_payload,
            actor,
            commit=False,
            similarity_exclude_id=item.id,
        )
        link = models.MaterialPromotionLink(
            source_item_id=item.id,
            target_item_id=promoted.id,
            is_historical=False,
            reason=payload.reason,
            actor_id=actor.id,
        )
        db.add(link)
        item.unofficial_status = "archived"
        item.updated_by = actor.id
        db.flush()
        batch_key = new_batch_key()
        audit(
            db, actor.id, "archive_after_promotion", "item", item.id, payload.reason,
            before, item_dict(item), batch_key=batch_key,
        )
        audit(
            db, actor.id, "promote", "material_promotion_link", link.id, payload.reason,
            after={"source": item_dict(item), "target": item_dict(promoted)}, batch_key=batch_key,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="正式物料编码或版本记录发生冲突") from exc
    db.refresh(promoted)
    return promoted


def validate_promotion_bom(db: Session, source: models.Item) -> list[str]:
    errors: list[str] = []
    visited_paths: set[tuple[int, ...]] = set()

    def walk(parent: models.Item, path: tuple[int, ...]) -> None:
        for line in db.scalars(
            select(models.BOMLine)
            .where(models.BOMLine.parent_item_id == parent.id)
            .order_by(models.BOMLine.sort_order, models.BOMLine.id)
        ):
            child = line.child
            label = f"{displayed_item_code(child)}｜{child.name}"
            next_path = (*path, child.id)
            if next_path in visited_paths:
                continue
            visited_paths.add(next_path)
            if child.id in path:
                errors.append(f"{label}：组成路径形成环路")
                continue
            if child.deleted_at:
                errors.append(f"{label}：物料已删除")
            if child.status == "disabled":
                errors.append(f"{label}：物料已停用")
            if not child.is_formally_imported:
                errors.append(f"{label}：未正式物料不能复制到正式 BOM")
            if child.item_type not in ALLOWED_CHILDREN.get(parent.item_type, set()):
                errors.append(f"{label}：不符合 {parent.item_type} 的组成层级")
            if line.alternative_group_id:
                group = db.get(models.AlternativeGroup, line.alternative_group_id)
                member = db.scalar(
                    select(models.AlternativeMember.id).where(
                        models.AlternativeMember.group_id == line.alternative_group_id,
                        models.AlternativeMember.item_id == child.id,
                        models.AlternativeMember.active.is_(True),
                    )
                )
                if not group or not group.active or not member:
                    errors.append(f"{label}：关联的替代组或成员已失效")
            walk(child, next_path)

    walk(source, (source.id,))
    return list(dict.fromkeys(errors))


def promotion_trace(db: Session, item: models.Item) -> dict[str, Any]:
    source_link = db.scalar(
        select(models.MaterialPromotionLink).where(
            models.MaterialPromotionLink.source_item_id == item.id
        )
    )
    target_links = list(
        db.scalars(
            select(models.MaterialPromotionLink)
            .where(models.MaterialPromotionLink.target_item_id == item.id)
            .order_by(models.MaterialPromotionLink.id)
        )
    )
    deleted_link=db.scalar(select(models.DeletedMaterialPromotion).where(models.DeletedMaterialPromotion.source_item_id==item.id))
    return {
        "deleted_promoted_to": {'code':deleted_link.target_code,'name':deleted_link.target_name} if deleted_link else None,
        "promoted_to": item_dict(db.get(models.Item, source_link.target_item_id)) if source_link else None,
        "promoted_from": [
            item_dict(source)
            for link in target_links
            if (source := db.get(models.Item, link.source_item_id)) is not None
        ],
    }


def validate_bom_relation(db: Session, parent: models.Item, child: models.Item, line_id: int | None = None) -> None:
    if parent.deleted_at or child.deleted_at:
        raise HTTPException(status_code=409, detail="已删除对象不能建立 BOM 关系")
    if parent.id == child.id:
        raise HTTPException(status_code=409, detail="父项不能包含自身")
    if child.item_type not in ALLOWED_CHILDREN.get(parent.item_type, set()):
        raise HTTPException(status_code=409, detail="该父子物料类型组合不允许")
    if not child.is_formally_imported:
        raise HTTPException(status_code=409, detail="未正式导入原材料不能作为 BOM 子项")
    if child.item_type != "material" and child.status == "disabled":
        raise HTTPException(status_code=409, detail="停用对象不能新增引用")
    cycle = bom_cycle_path(db, parent.id, child.id, line_id=line_id)
    if cycle:
        raise HTTPException(
            status_code=409,
            detail=f"该关系会形成 BOM 环路：{format_item_path(db, cycle)}",
        )


def format_item_path(db: Session, item_ids: list[int]) -> str:
    rows = {
        item.id: item
        for item in db.scalars(select(models.Item).where(models.Item.id.in_(set(item_ids))))
    }
    return " → ".join(
        f"{displayed_item_code(rows[item_id])}｜{rows[item_id].name}" if item_id in rows else f"物料 #{item_id}"
        for item_id in item_ids
    )


def bom_cycle_path(
    db: Session,
    parent_id: int,
    child_id: int,
    line_id: int | None = None,
    max_depth: int = 50,
) -> list[int] | None:
    """Return the proposed parent→child→…→parent cycle, if one exists."""
    stack: list[tuple[int, list[int]]] = [(child_id, [child_id])]
    visited_depth: dict[int, int] = {}
    while stack:
        current, path = stack.pop()
        if current == parent_id:
            return [parent_id, *path]
        depth = len(path) - 1
        if depth >= max_depth:
            raise HTTPException(
                status_code=409,
                detail=f"BOM 层级超过 {max_depth} 层，不能继续建立关系；当前路径：{format_item_path(db, path)}",
            )
        if visited_depth.get(current, max_depth + 1) <= depth:
            continue
        visited_depth[current] = depth
        query = select(models.BOMLine).where(models.BOMLine.parent_item_id == current)
        if line_id:
            query = query.where(models.BOMLine.id != line_id)
        for line in db.scalars(query):
            if line.child_item_id in path and line.child_item_id != parent_id:
                continue
            stack.append((line.child_item_id, [*path, line.child_item_id]))
    return None


def creates_cycle(db: Session, parent_id: int, child_id: int, line_id: int | None = None) -> bool:
    """Compatibility wrapper for existing callers."""
    return bom_cycle_path(db, parent_id, child_id, line_id=line_id) is not None


def bom_line_dict(line: models.BOMLine) -> dict[str, Any]:
    return {
        "id": line.id,
        "parent_item_id": line.parent_item_id,
        "child_item_id": line.child_item_id,
        "quantity": str(line.quantity),
        "sort_order": line.sort_order,
        "line_remark": line.line_remark,
        "alternative_group_id": line.alternative_group_id,
        "child": item_dict(line.child),
    }


def sync_material_assembly_flag(db: Session, parent: models.Item) -> None:
    """Keep the derived assembly flag aligned with actual child BOM rows."""
    if parent.item_type != "material":
        return
    count = db.scalar(
        select(func.count()).select_from(models.BOMLine).where(models.BOMLine.parent_item_id == parent.id)
    ) or 0
    parent.requires_assembly = bool(count)


def ensure_item_writable(item: models.Item) -> None:
    if item.unofficial_status == "archived":
        raise HTTPException(status_code=409, detail="已转正式的封存来源只供历史查看，不能执行修改操作")


def add_bom_line(
    db: Session,
    parent: models.Item,
    payload: schemas.BOMComponentIn,
    actor: models.User,
    reason: str,
    commit: bool = True,
) -> models.BOMLine:
    ensure_item_writable(parent)
    if payload.alternative_group_id and db.scalar(select(models.AuditEvent.id).where(models.AuditEvent.action=='migrate_v1_2').limit(1)):
        raise HTTPException(410,'独立替代组已停用，请使用路径选配')
    child = db.get(models.Item, payload.child_item_id)
    if not child:
        raise HTTPException(status_code=404, detail="子物料不存在")
    validate_bom_relation(db, parent, child)
    existing = db.scalar(
        select(models.BOMLine).where(
            models.BOMLine.parent_item_id == parent.id,
            models.BOMLine.child_item_id == child.id,
        ).order_by(models.BOMLine.sort_order, models.BOMLine.id).limit(1)
    )
    if existing:
        from .path_bom import EffectiveBOM
        actual=next((r for r in EffectiveBOM(db).rows(parent.id,expand_materials=False) if r['line_path']==[existing.id]),None)
        if actual and actual['item']['id']!=child.id:
            raise HTTPException(409,'该基础组件已被路径选配替代，不会累加到其他选用项；请先维护该行选配或替换基础组件，再新增')
        before = bom_line_dict(existing)
        existing.quantity = Decimal(existing.quantity) + payload.quantity
        existing.line_remark = payload.line_remark or existing.line_remark
        if payload.alternative_group_id is not None:
            existing.alternative_group_id = payload.alternative_group_id
        line = existing
        action = "merge_quantity"
    else:
        line = models.BOMLine(
            id=allocate_id(db, 'bom_lines', 'bom_line'),
            parent_item_id=parent.id,
            child_item_id=child.id,
            quantity=payload.quantity,
            sort_order=payload.sort_order,
            line_remark=payload.line_remark,
            alternative_group_id=payload.alternative_group_id,
        )
        db.add(line)
        db.flush()
        before = None
        action = "add"
    audit(db, actor.id, action, "bom_line", line.id, reason, before, bom_line_dict(line))
    if parent.item_type == "material":
        parent.requires_assembly = True
    if commit:
        from .path_bom import EffectiveBOM
        db.flush()
        if not existing:
            EffectiveBOM(db).validate([parent.id])
        db.commit()
        db.refresh(line)
    return line


def default_expand_materials(root: models.Item) -> bool:
    return root.item_type == "material"


def technical_bom(
    db: Session, root_id: int, max_nodes: int = 20000, max_depth: int = 50, *,
    show_alternatives: bool = False, expand_materials: bool | None = True,
) -> list[dict[str, Any]]:
    from .path_bom import EffectiveBOM
    root = db.get(models.Item, root_id)
    if not root:
        raise HTTPException(404, "对象不存在")
    return EffectiveBOM(db).rows(
        root_id, show_alternatives=show_alternatives,
        expand_materials=default_expand_materials(root) if expand_materials is None else expand_materials,
        max_depth=max_depth, max_nodes=max_nodes,
    )


def production_bom(
    db: Session, root_id: int, max_depth: int = 50, *,
    show_alternatives: bool = False, expand_materials: bool | None = True,
) -> list[dict[str, Any]]:
    from .path_bom import production_rows
    root = db.get(models.Item, root_id)
    if not root:
        raise HTTPException(404, "对象不存在")
    return production_rows(
        db, root_id, show_alternatives=show_alternatives, max_depth=max_depth,
        expand_materials=default_expand_materials(root) if expand_materials is None else expand_materials,
    )


def reverse_paths(db: Session, item_id: int, max_paths: int = 5000) -> list[dict[str, Any]]:
    from .path_bom import EffectiveBOM
    graph = EffectiveBOM(db)
    if item_id not in graph.items:
        raise HTTPException(404, "对象不存在")
    result = []
    for root in (graph.items[i] for i in sorted(graph.potential_ancestors(item_id))):
        if root.id == item_id or root.deleted_at or root.unofficial_status == "archived":
            continue
        for row in graph.rows(root.id):
            if row["item"]["id"] == item_id:
                result.append({"line_id": row["line_id"], "parent": item_dict(root), "path": row["path"],
                               "path_items": [item_dict(graph.items[i]) for i in row["path"]],
                               "is_direct": len(row["path"]) == 2, "quantity": row["total_quantity"]})
                if len(result) >= max_paths:
                    return result
    return result


def product_ownership(db: Session, item_id: int) -> dict[str, Any]:
    machines: dict[int, dict[str, Any]] = {}
    for row in reverse_paths(db, item_id):
        parent = row["parent"]
        if parent["item_type"] == "machine":
            machine = machines.setdefault(parent["id"], {**parent, "paths": []})
            machine["paths"].append(row["path_items"])
    current = [row for row in machines.values() if row["status"] in {"active", "trial"}]
    history = [row for row in machines.values() if row["status"] == "disabled"]

    def group_by_model(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[row.get("machine_model") or "未设置"].append(row)
        return [
            {"model": model, "machines": grouped[model]}
            for model in sorted(grouped, key=lambda value: (value == "未设置", value))
        ]

    return {
        "current": current,
        "history": history,
        "current_models": group_by_model(current),
        "history_models": group_by_model(history),
    }


def model_references_for_items(db: Session, item_ids: Iterable[int]) -> dict[int, dict[str, list[str]]]:
    from .path_bom import EffectiveBOM
    graph = EffectiveBOM(db)
    output = {int(i): {"current": set(), "history": set()} for i in item_ids}
    for machine in graph.items.values():
        if machine.item_type != "machine" or machine.deleted_at:
            continue
        key = "history" if machine.status == "disabled" else "current"
        if key == "current" and machine.status not in {"trial", "active"}:
            continue
        for row in graph.rows(machine.id):
            if row["item"]["id"] in output:
                output[row["item"]["id"]][key].add(machine.machine_model or "未设置")
    return {i: {k: sorted(v) for k, v in values.items()} for i, values in output.items()}


def soft_delete_item(db: Session, item: models.Item, actor: models.User, reason: str) -> None:
    from .item_lifecycle import delete_item
    return delete_item(db, item, actor, reason)


def restore_item(db: Session, item: models.Item, actor: models.User, reason: str) -> models.Item:
    ensure_item_writable(item)
    if not item.deleted_at:
        return item
    deleted_children = list(
        db.scalars(
            select(models.Item)
            .join(models.BOMLine, models.BOMLine.child_item_id == models.Item.id)
            .where(
                models.BOMLine.parent_item_id == item.id,
                models.Item.deleted_at.is_not(None),
            )
            .order_by(models.Item.code, models.Item.id)
        )
    )
    if deleted_children:
        labels = "、".join(f"{displayed_item_code(child)}｜{child.name}" for child in deleted_children[:10])
        suffix = "等" if len(deleted_children) > 10 else ""
        raise HTTPException(
            status_code=409,
            detail=f"恢复失败：该物料自身 BOM 中仍包含已删除子项 {labels}{suffix}，请先恢复或替换这些子项。",
        )
    before = item_dict(item)
    item.deleted_at = None
    audit(db, actor.id, "restore", "item", item.id, reason, before, item_dict(item))
    db.commit()
    db.refresh(item)
    return item


def compare_items(db: Session, item_ids: list[int], expand_materials: bool = False) -> dict[str, Any]:
    if not 1 <= len(item_ids) <= 5:
        raise HTTPException(status_code=422, detail="请选择 1–5 个对象")
    items = [db.get(models.Item, item_id) for item_id in item_ids]
    if any(item is None for item in items):
        raise HTTPException(status_code=404, detail="比较对象不存在")
    types = {item.item_type for item in items if item}
    if len(types) != 1 or "material" in types:
        raise HTTPException(status_code=409, detail="只能比较 1–5 个同类型半成品、单元或整机")
    matrices = {item.id: production_bom(db, item.id, expand_materials=expand_materials) for item in items if item}
    codes: list[str] = []
    seen: set[str] = set()
    for item in items:
        for row in matrices[item.id]:
            code = row["item"]["code"]
            if code not in seen:
                seen.add(code)
                codes.append(code)
    rows = []
    for code in codes:
        values = {}
        material = None
        for item in items:
            match = next((row for row in matrices[item.id] if row["item"]["code"] == code), None)
            values[str(item.id)] = match["quantity"] if match else None
            material = material or (match["item"] if match else None)
        non_null = {value for value in values.values() if value is not None}
        rows.append({"item": material, "values": values, "different": len(non_null) > 1 or any(v is None for v in values.values())})
    return {"items": [item_dict(item) for item in items], "rows": rows}


def next_code(db: Session, prefix: str, pattern: str | None = None) -> dict[str, Any]:
    template_match = re.search(r"\d[\d.Xx]*", pattern or "")
    template = template_match.group(0) if template_match else f"{prefix}XXX.01"
    if template.startswith("99.") or prefix.strip().startswith("99."):
        raise HTTPException(status_code=422, detail="99.XXXX.X 为未正式原材料专属号段，不能用于正式编码规则")
    placeholder = re.search(r"X+", template, re.IGNORECASE)
    if not placeholder:
        raise HTTPException(status_code=422, detail="编码规则必须包含 X 数字占位符")
    width = len(placeholder.group(0))
    capture_expression = "".join(
        rf"(\d{{{width}}})" if index == placeholder.start() else ("" if placeholder.start() < index < placeholder.end() else re.escape(character))
        for index, character in enumerate(template)
    )
    expression = re.compile(rf"^{capture_expression}$")
    candidates: list[tuple[int, models.Item]] = []
    for item in db.scalars(select(models.Item).where(
        models.Item.code.like(f"{prefix}%"),
        models.Item.is_formally_imported.is_(True),
    )):
        match = expression.fullmatch(item.code)
        if match:
            candidates.append((int(match.group(1)), item))
    if candidates:
        maximum_serial, maximum = max(candidates, key=lambda row: row[0])
        serial = maximum_serial + 1
    else:
        serial = 1
        maximum = None
    recommended_code = f"{template[:placeholder.start()]}{serial:0{width}d}{template[placeholder.end():]}"
    return {
        "prefix": prefix,
        "pattern": pattern,
        "maximum": item_dict(maximum) if maximum else None,
        "recommended_code": recommended_code,
    }


def new_batch_key() -> str:
    return uuid.uuid4().hex[:16]
