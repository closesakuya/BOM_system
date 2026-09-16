from __future__ import annotations

import io
import json
import shutil
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased

from . import auth, excel_io, models, ops, schemas, services
from .config import settings
from .database import get_db


router = APIRouter(prefix=settings.api_prefix)
Db = Annotated[Session, Depends(get_db)]


def reject_retired_alternatives(db: Session):
    # Historical setup helpers remain for baseline migration tests only.
    if db.scalar(select(models.AuditEvent.id).where(models.AuditEvent.action=='migrate_v1_2').limit(1)):
        raise HTTPException(410,'独立替代组已停用，请在所属物料 BOM 层级树中配置路径选配')


def download(content: bytes, filename: str, media_type: str) -> StreamingResponse:
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


def require_item(db: Session, item_id: int, include_deleted: bool = False) -> models.Item:
    item = db.get(models.Item, item_id)
    if not item or (item.deleted_at and not include_deleted):
        raise HTTPException(status_code=404, detail="对象不存在")
    return item


def attach_combination_flags(db: Session, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = [int(row['id']) for row in rows]
    composed = set(db.scalars(select(models.BOMLine.parent_item_id).where(models.BOMLine.parent_item_id.in_(ids)).distinct())) if ids else set()
    for row in rows:
        row['requires_assembly'] = row['id'] in composed
    semi_ids = {int(row["id"]) for row in rows if row.get("item_type") == "semi_finished"}
    combination_ids = set()
    if semi_ids:
        combination_ids = set(
            db.scalars(
                select(models.BOMLine.parent_item_id)
                .join(models.Item, models.Item.id == models.BOMLine.child_item_id)
                .where(
                    models.BOMLine.parent_item_id.in_(semi_ids),
                    models.Item.item_type == "semi_finished",
                )
                .distinct()
            )
        )
    for row in rows:
        row["is_combination"] = row.get("item_type") == "semi_finished" and row.get("id") in combination_ids
    return rows


def audit_dict(event: models.AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "actor_id": event.actor_id,
        "action": event.action,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "reason": event.reason,
        "batch_key": event.batch_key,
        "before": json.loads(event.before_json) if event.before_json else None,
        "after": json.loads(event.after_json) if event.after_json else None,
        "created_at": event.created_at,
    }


def _item_label(item: dict[str, Any] | None) -> str | None:
    if not item:
        return None
    code = item.get("code") or f"物料 #{item.get('id', '—')}"
    name = item.get("name") or "未命名"
    return f"{code}｜{name}"


def _snapshot_child(snapshot: Any, items_by_id: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict):
        return None
    child = snapshot.get("child")
    if isinstance(child, dict):
        return child
    child_id = snapshot.get("child_item_id")
    return items_by_id.get(child_id) if isinstance(child_id, int) else None


def _history_changes(
    entity_type: str,
    before: Any,
    after: Any,
    items_by_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    if entity_type == 'path_alternative':
        def describe(value):
            if not isinstance(value,dict):return '无配置（继承）'
            mode={'custom':'本路径自定义','disabled':'本路径禁用','inherit':'继承下级'}.get(value.get('mode'),'选配')
            selected=value.get('selected_item') or {}
            candidates='；'.join(f"{m.get('item',{}).get('code','')} {m.get('item',{}).get('name','')} {m.get('market_share','')}%" for m in value.get('members',[]) if isinstance(m,dict))
            return f"{mode}，当前：{selected.get('code','—')} {selected.get('name','')}；{candidates}"
        return [{'field':'路径选配','before':describe(before),'after':describe(after)}]
    if entity_type == "bom_line":
        before_dict = before if isinstance(before, dict) else {}
        after_dict = after if isinstance(after, dict) else {}
        before_child = _snapshot_child(before, items_by_id)
        after_child = _snapshot_child(after, items_by_id)
        before_child_id = before_dict.get("child_item_id")
        after_child_id = after_dict.get("child_item_id")
        if before is None or after is None or before_child_id != after_child_id:
            changes.append({
                "field": "component",
                "before": _item_label(before_child),
                "after": _item_label(after_child),
            })
        for field in ("quantity", "line_remark", "alternative_group_id"):
            before_value = before_dict.get(field)
            after_value = after_dict.get(field)
            if before_value != after_value:
                changes.append({"field": field, "before": before_value, "after": after_value})
        return changes

    if isinstance(before, dict) and isinstance(after, dict):
        business_fields = (
            "code", "name", "specification", "unit", "status", "source_type", "remark",
            "previous_version_name", "invoice_name", "material_attribute", "key_component_code",
            "historical_item_code", "machine_model", "is_formally_imported", "unofficial_status",
            "requires_assembly", "deleted_at",
        )
        for field in business_fields:
            if before.get(field) != after.get(field):
                changes.append({"field": field, "before": before.get(field), "after": after.get(field)})
    return changes


@router.post("/auth/login", response_model=schemas.TokenOut)
def login(payload: schemas.LoginIn, db: Db) -> dict[str, Any]:
    user = db.scalar(select(models.User).where(models.User.username == payload.username))
    if not user or not user.active or not auth.verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {"access_token": auth.create_access_token(user), "user": services.user_dict(user)}


@router.get("/auth/me")
def me(user: auth.CurrentUser) -> dict[str, Any]:
    return services.user_dict(user)


@router.get("/dashboard")
def dashboard(db: Db, user: auth.CurrentUser) -> dict[str, Any]:
    counts = {
        kind: db.scalar(
            select(func.count()).select_from(models.Item).where(
                models.Item.item_type == kind, models.Item.deleted_at.is_(None)
            )
        ) or 0
        for kind in services.ITEM_TYPES
    }
    recent = list(db.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id.desc()).limit(10)))
    return {
        "counts": counts,
        "bom_lines": db.scalar(select(func.count()).select_from(models.BOMLine)) or 0,
        "disabled": db.scalar(
            select(func.count()).select_from(models.Item).where(models.Item.status == "disabled")
        ) or 0,
        "recent_events": [audit_dict(row) for row in recent],
        "user": services.user_dict(user),
    }


@router.get("/users")
def list_users(db: Db, user: auth.AdminUser) -> list[dict[str, Any]]:
    return [services.user_dict(row) for row in db.scalars(select(models.User).order_by(models.User.id))]


@router.post("/users", status_code=201)
def create_user(payload: schemas.UserCreate, db: Db, actor: auth.AdminUser) -> dict[str, Any]:
    if db.scalar(select(models.User.id).where(models.User.username == payload.username)):
        raise HTTPException(status_code=409, detail="用户名已存在")
    row = models.User(
        username=payload.username.strip(), password_hash=auth.hash_password(payload.password),
        display_name=payload.display_name.strip(), department=payload.department,
        role=payload.role, active=payload.active,
    )
    db.add(row)
    db.flush()
    services.audit(db, actor.id, "create", "user", row.id, "创建账户", after=services.user_dict(row))
    db.commit()
    return services.user_dict(row)


@router.patch("/users/{user_id}")
def update_user(user_id: int, payload: schemas.UserUpdate, db: Db, actor: auth.AdminUser) -> dict[str, Any]:
    row = db.get(models.User, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="账户不存在")
    before = services.user_dict(row)
    values = payload.model_dump(exclude_unset=True)
    if any(values.get(key) is None for key in ('username', 'role', 'active', 'display_name') if key in values):
        raise HTTPException(422, '用户名、角色、状态和显示名称不能为空')
    if 'username' in values:
        values['username'] = values['username'].strip()
        if len(values['username']) < 3:
            raise HTTPException(422, '用户名至少 3 个字符')
        if db.scalar(select(models.User.id).where(models.User.username == values['username'], models.User.id != user_id)):
            raise HTTPException(409, '用户名已存在')
    if row.id == actor.id and values.get('role', row.role) != 'admin':
        raise HTTPException(409, '不能移除当前登录账户的管理员角色')
    password = values.pop("password", None)
    for key, value in values.items():
        setattr(row, key, value)
    if password:
        row.password_hash = auth.hash_password(password)
    if row.id == actor.id and not row.active:
        raise HTTPException(status_code=409, detail="不能停用当前登录账户")
    services.audit(db, actor.id, "update", "user", row.id, "修改账户", before, services.user_dict(row))
    db.commit()
    return services.user_dict(row)


@router.get("/items")
def list_items(
    db: Db,
    user: auth.CurrentUser,
    q: str | None = None,
    item_type: str | None = None,
    status: str | None = None,
    source_type: str | None = None,
    is_formally_imported: bool | None = None,
    unofficial_status: str | None = None,
    machine_model: str | None = None,
    semi_kind: str | None = None,
    include_deleted: bool = False,
    include_disabled: bool = False,
    has_components: bool | None = None,
    limit: int = Query(100, ge=1, le=10000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    filters, ordering = item_query_parts(
        q=q,
        item_type=item_type,
        status=status,
        source_type=source_type,
        is_formally_imported=is_formally_imported,
        unofficial_status=unofficial_status,
        machine_model=machine_model,
        semi_kind=semi_kind,
        include_deleted=include_deleted,
        include_disabled=include_disabled,
        has_components=has_components,
    )
    total = db.scalar(select(func.count()).select_from(models.Item).where(*filters)) or 0
    rows = list(db.scalars(select(models.Item).where(*filters).order_by(*ordering).offset(offset).limit(limit)))
    return {"total": total, "items": attach_combination_flags(db, [services.item_dict(row) for row in rows])}


def item_query_parts(
    *,
    q: str | None,
    item_type: str | None,
    status: str | None,
    source_type: str | None,
    is_formally_imported: bool | None,
    unofficial_status: str | None,
    machine_model: str | None,
    semi_kind: str | None,
    include_deleted: bool,
    include_disabled: bool = False,
    has_components: bool | None = None,
) -> tuple[list[Any], list[Any]]:
    filters: list[Any] = []
    ordering: list[Any] = [models.Item.code, models.Item.id]
    if not include_deleted:
        filters.append(models.Item.deleted_at.is_(None))
    if not include_disabled and not status:
        filters.append(or_(models.Item.status.is_(None), models.Item.status != 'disabled'))
    if has_components is not None:
        parents = select(models.BOMLine.parent_item_id)
        filters.append(models.Item.id.in_(parents) if has_components else models.Item.id.not_in(parents))
    query_text = q.strip() if q else ""
    if query_text:
        matchers: list[Any] = [
            models.Item.code.contains(query_text, autoescape=True),
            models.Item.name.contains(query_text, autoescape=True),
            models.Item.specification.contains(query_text, autoescape=True),
            models.Item.key_component_code.contains(query_text, autoescape=True),
            models.Item.historical_item_code.contains(query_text, autoescape=True),
        ]
        filters.append(or_(*matchers))
        ordering = [
            case(
                (models.Item.name == query_text, 0),
                (models.Item.name.startswith(query_text, autoescape=True), 1),
                (models.Item.name.contains(query_text, autoescape=True), 2),
                (models.Item.code == query_text, 3),
                (models.Item.code.startswith(query_text, autoescape=True), 4),
                (models.Item.code.contains(query_text, autoescape=True), 5),
                (models.Item.historical_item_code.contains(query_text, autoescape=True), 6),
                (models.Item.key_component_code.contains(query_text, autoescape=True), 7),
                else_=8,
            ),
            models.Item.code,
            models.Item.id,
        ]
    if item_type:
        filters.append(models.Item.item_type == item_type)
    if status:
        filters.append(models.Item.status == status)
    if source_type:
        filters.append(models.Item.source_type == source_type)
    if is_formally_imported is not None:
        filters.append(models.Item.is_formally_imported.is_(is_formally_imported))
    if unofficial_status:
        if unofficial_status not in services.UNOFFICIAL_STATUSES:
            raise HTTPException(status_code=422, detail="未正式状态只能选择待转正式或已转正式封存")
        filters.append(models.Item.unofficial_status == unofficial_status)
    if machine_model:
        filters.append(models.Item.machine_model == machine_model)
    if semi_kind:
        if item_type != "semi_finished" or semi_kind not in {"normal", "combination"}:
            raise HTTPException(status_code=422, detail="半成品分类只能选择普通半成品或组合半成品")
        semi_child_ids = select(models.Item.id).where(models.Item.item_type == "semi_finished")
        combination_parent_ids = select(models.BOMLine.parent_item_id).where(
            models.BOMLine.child_item_id.in_(semi_child_ids)
        )
        filters.append(
            models.Item.id.in_(combination_parent_ids)
            if semi_kind == "combination"
            else models.Item.id.not_in(combination_parent_ids)
        )
    return filters, ordering


@router.get("/items-basic-export")
def export_item_basics(
    db: Db,
    user: auth.ExportUser,
    item_type: schemas.ItemType,
    q: str | None = None,
    status: str | None = None,
    source_type: str | None = None,
    is_formally_imported: bool | None = None,
    unofficial_status: str | None = None,
    machine_model: str | None = None,
    semi_kind: str | None = None,
    item_ids: list[int] = Query(default=[]),
    include_disabled: bool = False,
    has_components: bool | None = None,
) -> StreamingResponse:
    filters, ordering = item_query_parts(
        q=q,
        item_type=item_type,
        status=status,
        source_type=source_type,
        is_formally_imported=is_formally_imported,
        unofficial_status=unofficial_status,
        machine_model=machine_model,
        semi_kind=semi_kind,
        include_deleted=False,
        include_disabled=include_disabled,
        has_components=has_components,
    )
    if item_ids:
        filters.append(models.Item.id.in_(set(item_ids)))
    rows = list(db.scalars(select(models.Item).where(*filters).order_by(*ordering)))
    filename, content = excel_io.item_basics_workbook(db, rows, item_type, selected=bool(item_ids))
    return download(
        content,
        filename,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/items/import-code-preview")
def import_code_preview(code: str, db: Db, user: auth.CurrentUser, item_type: str = 'material', code_rule_id: int | None = None):
    from .material_import import complete_code
    try:
        result, rule, auto = complete_code(db, code, item_type, code_rule_id)
        available = services.code_availability(db, result, rule, item_type, True)
        return {**available, 'recommended_code': result, 'code_rule_id': rule, 'auto_code': auto}
    except HTTPException as exc:
        return {'valid': False, 'exists': False, 'message': str(exc.detail)}


@router.get("/machine-models")
def machine_models(db: Db, user: auth.CurrentUser) -> list[str]:
    return [
        str(value)
        for value in db.scalars(
            select(models.Item.machine_model)
            .where(
                models.Item.item_type == "machine",
                models.Item.deleted_at.is_(None),
                models.Item.machine_model.is_not(None),
                models.Item.machine_model != "",
            )
            .distinct()
            .order_by(models.Item.machine_model)
        )
    ]


@router.get("/key-component-codes")
def key_component_codes(db: Db, user: auth.CurrentUser) -> list[str]:
    return [
        str(value)
        for value in db.scalars(
            select(models.Item.key_component_code)
            .where(
                models.Item.item_type == "material",
                models.Item.key_component_code.is_not(None),
                models.Item.key_component_code != "",
            )
            .distinct()
            .order_by(models.Item.key_component_code)
        )
    ]


@router.get("/items/similarity")
def check_similarity(
    name: str, db: Db, user: auth.CurrentUser, specification: str | None = None,
    item_type: str | None = None, exclude_id: int | None = None,
) -> list[dict[str, Any]]:
    return services.similarity_candidates(db, name, specification, item_type, exclude_id)


@router.get("/items/code-availability")
def check_code_availability(
    code: str, db: Db, user: auth.CurrentUser, code_rule_id: int | None = None,
    item_type: schemas.ItemType | None = None,
    is_formally_imported: bool = True,
) -> dict[str, Any]:
    return services.code_availability(db, code, code_rule_id, item_type, is_formally_imported)


@router.get("/items/unofficial-code-preview")
def unofficial_code_preview(db: Db, user: auth.CurrentUser) -> dict[str, str]:
    return {"estimated_code": services.preview_unofficial_code(db)}


@router.get("/items/key-component-code-availability")
def key_component_code_availability(
    value: str,
    db: Db,
    user: auth.CurrentUser,
    exclude_id: int | None = None,
) -> dict[str, Any]:
    normalized = services.normalize_key_component_code(value)
    query = select(models.Item).where(
        models.Item.item_type == "material",
        models.Item.key_component_code == normalized,
    )
    if exclude_id:
        query = query.where(models.Item.id != exclude_id)
    rows = list(db.scalars(query.order_by(models.Item.code, models.Item.id).limit(20)))
    return {
        "valid": True,
        "normalized": normalized,
        "duplicate_items": [services.item_dict(row) for row in rows],
        "message": "关键器件码可用" if not rows else f"该关键器件码已关联 {len(rows)} 条物料，可继续保存",
    }


@router.post("/items", status_code=201)
def create_item(payload: schemas.ItemCreate, db: Db, actor: auth.MaterialWriteUser) -> dict[str, Any]:
    auth.check_material_write(actor, payload=payload)
    return services.item_dict(services.create_item(db, payload, actor))


@router.get("/items/{item_id}")
def get_item(item_id: int, db: Db, user: auth.CurrentUser) -> dict[str, Any]:
    item = require_item(db, item_id)
    components = list(db.scalars(select(models.BOMLine).where(models.BOMLine.parent_item_id == item_id).order_by(models.BOMLine.sort_order, models.BOMLine.id)))
    from .path_bom import EffectiveBOM
    direct = {r['line_path'][0]: r for r in EffectiveBOM(db).rows(item_id, expand_materials=False) if len(r['line_path'])==1}
    component_rows = []
    for line in components:
        value = services.bom_line_dict(line)
        if line.id in direct:
            value['base_child_item_id'] = line.child_item_id
            value['child_item_id'] = direct[line.id]['item']['id']
            value['child'] = direct[line.id]['item']
        component_rows.append(value)
    result = {
        **services.item_dict(item),
        "components": component_rows,
        "ownership": services.product_ownership(db, item_id),
        "promotion_trace": services.promotion_trace(db, item),
    }
    return attach_combination_flags(db, [result])[0]


@router.patch("/items/{item_id}")
def update_item(item_id: int, payload: schemas.ItemUpdate, db: Db, actor: auth.MaterialWriteUser) -> dict[str, Any]:
    auth.check_material_write(actor, require_item(db, item_id), payload)
    return services.item_dict(services.update_item(db, require_item(db, item_id), payload, actor))


@router.post("/items/{item_id}/promote")
def promote_item(
    item_id: int,
    payload: schemas.PromoteMaterialIn,
    db: Db,
    actor: auth.WriteUser,
) -> dict[str, Any]:
    return services.item_dict(
        services.promote_material(db, require_item(db, item_id), payload, actor)
    )


@router.delete("/items/{item_id}")
def delete_item(item_id: int, reason: str, db: Db, actor: auth.MaterialWriteUser) -> dict[str, bool]:
    auth.check_material_write(actor, require_item(db, item_id))
    services.soft_delete_item(db, require_item(db, item_id), actor, reason)
    return {"ok": True}


@router.post("/items/{item_id}/restore")
def restore_item(item_id: int, reason: str, db: Db, actor: auth.WriteUser) -> dict[str, Any]:
    item = require_item(db, item_id, include_deleted=True)
    return services.item_dict(services.restore_item(db, item, actor, reason))


@router.post("/items/{item_id}/copy", status_code=201)
def copy_item(item_id: int, payload: schemas.CopyItemIn, db: Db, actor: auth.WriteUser) -> dict[str, Any]:
    source = require_item(db, item_id)
    services.ensure_item_writable(source)
    if payload.mode == "new_version":
        max_version = db.scalar(select(func.max(models.Item.version_number)).where(
            models.Item.version_series == source.version_series,
            models.Item.is_formally_imported.is_(source.is_formally_imported),
        )) or 0
        code = payload.code or f"{source.code_body}.{max_version + 1:02d}"
    elif payload.code or not source.is_formally_imported:
        code = payload.code
    else:
        raise HTTPException(status_code=422, detail="复制为新物料时必须填写新编码")
    components = [
        schemas.BOMComponentIn(
            child_item_id=line.child_item_id, quantity=line.quantity, sort_order=line.sort_order,
            line_remark=line.line_remark, alternative_group_id=line.alternative_group_id,
        )
        for line in db.scalars(select(models.BOMLine).where(models.BOMLine.parent_item_id == source.id))
    ]
    create = schemas.ItemCreate(
        item_type=source.item_type, code=code, auxiliary_code=source.auxiliary_code,
        name=source.name, specification=source.specification, source_type=source.source_type,
        unit=source.unit, remark=source.remark, previous_version_name=source.name,
        invoice_name=source.invoice_name, material_attribute=source.material_attribute,
        key_component_code=source.key_component_code, machine_model=source.machine_model,
        is_formally_imported=source.is_formally_imported,
        status="trial" if source.item_type != "material" else None,
        similarity_confirmed=True, reason=payload.reason, components=components,
    )
    copied = services.create_item(db, create, actor, commit=False)
    copied.copied_from_id = source.id
    from .item_lifecycle import copy_configurations
    copy_configurations(db, source.id, copied.id)
    from .path_bom import EffectiveBOM
    EffectiveBOM(db).rows(copied.id,show_alternatives=True)
    if payload.mode == "new_version" and source.is_formally_imported:
        copied.version_series = source.version_series
    services.audit(db, actor.id, "copy", "item", copied.id, payload.reason, before=services.item_dict(source), after=services.item_dict(copied))
    db.commit()
    return services.item_dict(copied)


@router.get("/items/{item_id}/bom")
def list_bom(item_id: int, db: Db, user: auth.CurrentUser) -> list[dict[str, Any]]:
    require_item(db, item_id)
    return [services.bom_line_dict(row) for row in db.scalars(select(models.BOMLine).where(models.BOMLine.parent_item_id == item_id).order_by(models.BOMLine.sort_order, models.BOMLine.id))]


@router.post("/items/{item_id}/bom", status_code=201)
def add_bom(item_id: int, payload: schemas.BOMLineCreate, db: Db, actor: auth.WriteUser) -> dict[str, Any]:
    return services.bom_line_dict(services.add_bom_line(db, require_item(db, item_id), payload, actor, payload.reason))


@router.patch("/bom-lines/{line_id}")
def update_bom(line_id: int, payload: schemas.BOMLineUpdate, db: Db, actor: auth.WriteUser) -> dict[str, Any]:
    line = db.get(models.BOMLine, line_id)
    if not line:
        raise HTTPException(status_code=404, detail="BOM 行不存在")
    services.ensure_item_writable(line.parent)
    before = services.bom_line_dict(line)
    values = payload.model_dump(exclude_unset=True, exclude={"reason", "confirm_clear"})
    group_id = values.get("alternative_group_id", line.alternative_group_id)
    if group_id:
        reject_retired_alternatives(db)
    next_child_id = values.get("child_item_id", line.child_item_id)
    if group_id:
        group = db.get(models.AlternativeGroup, group_id)
        member = db.scalar(select(models.AlternativeMember).where(models.AlternativeMember.group_id == group_id, models.AlternativeMember.item_id == next_child_id, models.AlternativeMember.active.is_(True)))
        if not group or not group.active or not member:
            raise HTTPException(status_code=409, detail="当前子物料不是该有效替代组成员")
    if "child_item_id" in values:
        from .item_lifecycle import clear_line_configurations
        if values['child_item_id'] != line.child_item_id:
            clear_line_configurations(db,line.id,actor,payload.reason,payload.confirm_clear)
        child = require_item(db, values["child_item_id"])
        services.validate_bom_relation(db, line.parent, child, line_id=line.id)
    for key, value in values.items():
        setattr(line, key, value)
    if "child_item_id" in values:
        # Keep the loaded relationship aligned with the changed foreign key so
        # the response and audit snapshot do not expose the previous child.
        line.child = child
    db.flush()
    services.audit(db, actor.id, "update", "bom_line", line.id, payload.reason, before, services.bom_line_dict(line))
    from .path_bom import EffectiveBOM
    if 'child_item_id' in values or group_id:
        EffectiveBOM(db).validate([line.parent_item_id])
    db.commit()
    return services.bom_line_dict(line)


@router.post("/bom-lines/{line_id}/alternative-selection")
def select_bom_alternative(line_id: int, payload: schemas.AlternativeSelectionIn, db: Db, actor: auth.WriteUser) -> dict[str, Any]:
    reject_retired_alternatives(db)
    line = db.get(models.BOMLine, line_id)
    if not line:
        raise HTTPException(status_code=404, detail="BOM 行不存在")
    services.ensure_item_writable(line.parent)
    group_id = payload.alternative_group_id or line.alternative_group_id
    if not group_id:
        raise HTTPException(status_code=404, detail="BOM 行未关联替代组")
    group = db.get(models.AlternativeGroup, group_id)
    member = db.scalar(select(models.AlternativeMember).where(models.AlternativeMember.group_id == group.id, models.AlternativeMember.item_id == payload.item_id, models.AlternativeMember.active.is_(True))) if group else None
    target = db.get(models.Item, payload.item_id)
    if not group or not group.active or not member or not target or target.deleted_at or target.status == "disabled":
        raise HTTPException(status_code=409, detail="目标不是可用的替代组成员")
    services.validate_bom_relation(db, line.parent, target, line_id=line.id)
    before = services.bom_line_dict(line)

    duplicate = db.scalar(
        select(models.BOMLine).where(
            models.BOMLine.parent_item_id == line.parent_item_id,
            models.BOMLine.child_item_id == target.id,
            models.BOMLine.id != line.id,
        ).limit(1)
    )
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail=(
                f"无法保存选配：父项 {line.parent.code}｜{line.parent.name} "
                f"已经直接包含 {target.code}｜{target.name}。系统不会合并数量，请选择其他候选物料。"
            ),
        )

    # Only direct siblings conflict. The same target may already exist deeper
    # inside a semi-finished/unit subtree without blocking this selection.
    line.child_item_id = target.id
    line.child = target
    line.alternative_group_id = group.id
    db.flush()
    services.audit(db, actor.id, "alternative_select", "bom_line", line.id, payload.reason, before, services.bom_line_dict(line))
    db.commit()
    db.refresh(line)
    result = services.bom_line_dict(line)
    result.update({
        "message": f"已保存选配：{target.code}｜{target.name}；本行数量保持 {format(Decimal(line.quantity).normalize(), 'f')}",
    })
    return result


@router.post("/bom-lines/{line_id}/replace")
def replace_bom_line(
    line_id: int,
    payload: schemas.BOMLineReplaceIn,
    db: Db,
    actor: auth.WriteUser,
) -> dict[str, Any]:
    line = db.get(models.BOMLine, line_id)
    if not line:
        raise HTTPException(status_code=404, detail="BOM 行不存在")
    services.ensure_item_writable(line.parent)
    target = require_item(db, payload.child_item_id)
    if target.id == line.child_item_id:
        from .path_bom import EffectiveBOM
        actual=next((r for r in EffectiveBOM(db).rows(line.parent_item_id,expand_materials=False) if r['line_path']==[line.id]),None)
        if not actual or actual['item']['id']==target.id:
            raise HTTPException(status_code=409, detail="替换后的物料与当前物料相同")
    services.validate_bom_relation(db, line.parent, target, line_id=line.id)
    duplicate = db.scalar(
        select(models.BOMLine).where(
            models.BOMLine.parent_item_id == line.parent_item_id,
            models.BOMLine.child_item_id == target.id,
            models.BOMLine.id != line.id,
        ).limit(1)
    )
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail=(
                f"不能替换：父项 {services.displayed_item_code(line.parent)}｜{line.parent.name} 已直接包含 "
                f"{services.displayed_item_code(target)}｜{target.name}；系统不会合并数量。"
            ),
        )

    from .item_lifecycle import clear_line_configurations
    clear_line_configurations(db, line.id, actor, payload.reason, payload.confirm_clear)
    before = services.bom_line_dict(line)
    previous_group_id = line.alternative_group_id
    group_cleared = False
    if previous_group_id:
        same_group_member = db.scalar(
            select(models.AlternativeMember.id).where(
                models.AlternativeMember.group_id == previous_group_id,
                models.AlternativeMember.item_id == target.id,
                models.AlternativeMember.active.is_(True),
            )
        )
        group = db.get(models.AlternativeGroup, previous_group_id)
        if not group or not group.active or not same_group_member:
            line.alternative_group_id = None
            group_cleared = True
    line.child_item_id = target.id
    line.child = target
    db.flush()
    from .path_bom import EffectiveBOM
    EffectiveBOM(db).validate([line.parent_item_id])
    after = services.bom_line_dict(line)
    services.audit(db, actor.id, "replace", "bom_line", line.id, payload.reason, before, after)
    db.commit()
    db.refresh(line)
    result = services.bom_line_dict(line)
    result.update({
        "alternative_group_cleared": group_cleared,
        "message": (
            f"已将 {before['child']['code']}｜{before['child']['name']} 替换为 "
            f"{services.displayed_item_code(target)}｜{target.name}；数量、顺序和行备注保持不变"
            + ("；原替代组因新物料不属于该组已自动清除" if group_cleared else "")
        ),
    })
    return result


@router.delete("/bom-lines/{line_id}")
def delete_bom(line_id: int, reason: str, db: Db, actor: auth.WriteUser, confirm_clear: bool = False) -> dict[str, bool]:
    line = db.get(models.BOMLine, line_id)
    if not line:
        raise HTTPException(status_code=404, detail="BOM 行不存在")
    services.ensure_item_writable(line.parent)
    from .item_lifecycle import clear_line_configurations
    clear_line_configurations(db, line.id, actor, reason, confirm_clear)
    before = services.bom_line_dict(line)
    parent = line.parent
    db.delete(line)
    services.audit(db, actor.id, "delete", "bom_line", line_id, reason, before=before)
    db.flush()
    services.sync_material_assembly_flag(db, parent)
    db.commit()
    return {"ok": True}


@router.post("/items/{item_id}/bom/reorder")
def reorder_bom(item_id: int, payload: schemas.ReorderIn, db: Db, actor: auth.WriteUser) -> list[dict[str, Any]]:
    services.ensure_item_writable(require_item(db, item_id))
    lines = list(db.scalars(select(models.BOMLine).where(models.BOMLine.parent_item_id == item_id)))
    if {row.id for row in lines} != set(payload.line_ids) or len(lines) != len(payload.line_ids):
        raise HTTPException(status_code=422, detail="排序清单必须完整且不能重复")
    order = {line_id: index for index, line_id in enumerate(payload.line_ids, 1)}
    for line in lines:
        line.sort_order = order[line.id]
    services.audit(db, actor.id, "reorder", "bom", item_id, payload.reason, after=payload.line_ids)
    db.commit()
    return list_bom(item_id, db, actor)


@router.get("/items/{item_id}/technical-bom")
def technical_bom(
    item_id: int, db: Db, user: auth.CurrentUser,
    show_alternatives: bool = True, expand_materials: bool | None = None,
) -> list[dict[str, Any]]:
    rows = services.technical_bom(
        db, item_id, show_alternatives=show_alternatives, expand_materials=expand_materials,
    )
    reasons = excel_io.latest_item_change_reasons(db, {int(row["item"]["id"]) for row in rows})
    for row in rows:
        row["latest_change_reason"] = reasons.get(row["item"]["id"])
    return rows


@router.get("/items/{item_id}/production-bom")
def production_bom(
    item_id: int, db: Db, user: auth.CurrentUser,
    show_alternatives: bool = True, expand_materials: bool | None = None,
) -> list[dict[str, Any]]:
    rows = services.production_bom(
        db, item_id, show_alternatives=show_alternatives, expand_materials=expand_materials,
    )
    reasons = excel_io.latest_item_change_reasons(db, {int(row["item"]["id"]) for row in rows})
    for row in rows:
        row["latest_change_reason"] = reasons.get(row["item"]["id"])
    return rows


@router.get("/items/{item_id}/references")
def references(item_id: int, db: Db, user: auth.CurrentUser) -> list[dict[str, Any]]:
    return services.reverse_paths(db, item_id)


@router.get("/items/{item_id}/history")
def item_history(item_id: int, db: Db, user: auth.CurrentUser) -> list[dict[str, Any]]:
    root = require_item(db, item_id, include_deleted=True)
    item_rows = list(db.scalars(select(models.Item)))
    items_by_id = {item.id: services.item_dict(item) for item in item_rows}
    graph: dict[int, dict[int, int]] = {}
    for line in db.scalars(select(models.BOMLine)):
        graph.setdefault(line.parent_item_id, {})[line.id] = line.child_item_id
    configurations = {(c.owner_item_id,c.line_path):c.selected_item_id for c in db.scalars(select(models.PathAlternative))}

    def current_paths(max_paths: int = 20000) -> dict[int, list[list[int]]]:
        paths: dict[int, list[list[int]]] = {root.id: [[root.id]]}
        stack = [(root.id, [root.id], [])]
        path_count = 1
        while stack:
            parent_id, parent_path, line_path = stack.pop()
            for line_id, base_child_id in sorted(graph.get(parent_id, {}).items(), reverse=True):
                position=[*line_path,line_id]
                child_id=base_child_id
                for offset,owner_id in enumerate(parent_path):
                    key=(owner_id,'/'.join(map(str,position[offset:])))
                    if key in configurations:
                        child_id=configurations[key]
                        break
                if child_id in parent_path:
                    continue
                child_path = [*parent_path, child_id]
                paths.setdefault(child_id, []).append(child_path)
                path_count += 1
                if path_count > max_paths:
                    raise HTTPException(status_code=409, detail="BOM 历史路径过多，已停止展开")
                stack.append((child_id, child_path, position))
        return paths

    def readable_paths(path_ids: list[list[int]]) -> list[list[dict[str, Any]]]:
        return [[items_by_id[path_item_id] for path_item_id in path if path_item_id in items_by_id] for path in path_ids]

    result: list[dict[str, Any]] = []
    events = list(db.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id.desc())))
    # Deleted descendants still need readable identities in historical paths.
    for event in events:
        if event.entity_type=='item' and event.entity_id not in items_by_id:
            value=json.loads(event.before_json or event.after_json or '{}')
            if isinstance(value,dict) and value.get('id'):
                items_by_id[event.entity_id]=value
    for event in events:
        before = json.loads(event.before_json) if event.before_json else None
        after = json.loads(event.after_json) if event.after_json else None
        paths_by_item = current_paths()
        belongs = False
        scope = "self"
        subject: dict[str, Any] | None = None
        parent: dict[str, Any] | None = None
        event_path_ids: list[list[int]] = []

        if event.entity_type == "item" and event.entity_id in paths_by_item:
            belongs = True
            subject = (after if isinstance(after, dict) else before) or items_by_id.get(event.entity_id)
            event_path_ids = paths_by_item[event.entity_id]
            scope = "self" if event.entity_id == root.id else "descendant"

        if event.entity_type == "bom_line":
            snapshots = [value for value in (after, before) if isinstance(value, dict)]
            relevant_snapshots = [value for value in snapshots if value.get("parent_item_id") in paths_by_item]
            if relevant_snapshots:
                belongs = True
                primary = relevant_snapshots[0]
                parent_id = primary.get("parent_item_id")
                parent = items_by_id.get(parent_id)
                subject = _snapshot_child(primary, items_by_id)
                scope = "direct_component" if parent_id == root.id else "descendant"
                seen_paths: set[tuple[int, ...]] = set()
                for snapshot in relevant_snapshots:
                    snapshot_parent_id = snapshot.get("parent_item_id")
                    child = _snapshot_child(snapshot, items_by_id)
                    child_id = child.get("id") if child else snapshot.get("child_item_id")
                    for parent_path in paths_by_item.get(snapshot_parent_id, []):
                        full_path = [*parent_path]
                        if isinstance(child_id, int) and (not full_path or full_path[-1] != child_id):
                            full_path.append(child_id)
                        key = tuple(full_path)
                        if key not in seen_paths:
                            seen_paths.add(key)
                            event_path_ids.append(full_path)

        if event.entity_type == "bom" and event.entity_id in paths_by_item:
            belongs = True
            subject = items_by_id.get(event.entity_id)
            event_path_ids = paths_by_item[event.entity_id]
            scope = "direct_component" if event.entity_id == root.id else "descendant"

        if event.entity_type == 'path_alternative':
            snapshot=after if isinstance(after,dict) else before if isinstance(before,dict) else {}
            owner_id=snapshot.get('owner_item_id') or (snapshot.get('owner') or {}).get('id')
            if owner_id in paths_by_item:
                belongs=True
                subject=items_by_id.get(owner_id)
                event_path_ids=paths_by_item[owner_id]
                scope='self' if owner_id==root.id else 'descendant'

        if belongs:
            row = audit_dict(event)
            row["changes"] = _history_changes(event.entity_type, before, after, items_by_id)
            row["scope"] = scope
            row["subject"] = subject
            row["parent"] = parent
            row["paths"] = readable_paths(event_path_ids)
            result.append(row)

        if event.entity_type == "bom_line":
            before_edge = (
                (before.get("parent_item_id"), before.get("child_item_id"))
                if isinstance(before, dict) else None
            )
            after_edge = (
                (after.get("parent_item_id"), after.get("child_item_id"))
                if isinstance(after, dict) else None
            )
            if before_edge != after_edge:
                if after_edge and all(isinstance(value, int) for value in after_edge):
                    graph.get(after_edge[0],{}).pop(event.entity_id,None)
                if before_edge and all(isinstance(value, int) for value in before_edge):
                    graph.setdefault(before_edge[0], {})[event.entity_id]=before_edge[1]
        if event.entity_type=='path_alternative':
            snapshot=after if isinstance(after,dict) else before if isinstance(before,dict) else {}
            owner_id=snapshot.get('owner_item_id') or (snapshot.get('owner') or {}).get('id')
            path=snapshot.get('line_path')
            if owner_id and path:
                key=(owner_id,'/'.join(map(str,path)) if isinstance(path,list) else str(path))
                configurations.pop(key,None)
                if isinstance(before,dict) and before.get('mode')!='inherit' and before.get('selected_item_id'):
                    configurations[key]=int(before['selected_item_id'])
    return result


@router.get("/items/{item_id}/export/{bom_type}")
def export_bom(
    item_id: int, bom_type: str, db: Db, user: auth.ExportUser,
    show_alternatives: bool = True, expand_materials: bool | None = None,
) -> StreamingResponse:
    if bom_type not in {"technical", "production"}:
        raise HTTPException(status_code=422, detail="导出类型无效")
    filename, content = (
        excel_io.technical_workbook(db, item_id, show_alternatives=show_alternatives, expand_materials=expand_materials)
        if bom_type == "technical"
        else excel_io.production_workbook(db, item_id, show_alternatives=show_alternatives, expand_materials=expand_materials)
    )
    return download(content, filename, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.post("/bom/batch-export/{bom_type}")
def batch_export(
    bom_type: str, item_ids: list[int], db: Db, user: auth.ExportUser,
    show_alternatives: bool = True, expand_materials: bool | None = None,
) -> StreamingResponse:
    if bom_type not in {"technical", "production"}:
        raise HTTPException(status_code=422, detail="导出类型无效")
    filename, content = excel_io.batch_bom_zip(
        db, item_ids, bom_type,
        show_alternatives=show_alternatives, expand_materials=expand_materials,
    )
    return download(content, filename, "application/zip")


@router.get("/compare")
def compare(item_ids: str, db: Db, user: auth.CurrentUser, expand_materials: bool = False) -> dict[str, Any]:
    try:
        ids = [int(value) for value in item_ids.split(",") if value]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="比较对象参数错误") from exc
    return services.compare_items(db, ids, expand_materials=expand_materials)


@router.get("/compare/export")
def export_compare(item_ids: str, db: Db, user: auth.ExportUser, expand_materials: bool = False) -> StreamingResponse:
    result = compare(item_ids, db, user, expand_materials)
    return download(excel_io.compare_workbook(result), "BOM差异比较.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/code-rules")
def list_code_rules(db: Db, user: auth.CurrentUser) -> list[dict[str, Any]]:
    return [
        {column.name: getattr(row, column.name) for column in models.CodeRule.__table__.columns}
        for row in db.scalars(select(models.CodeRule).order_by(models.CodeRule.sort_order, models.CodeRule.id))
    ]


@router.post("/code-rule-imports/preview")
async def preview_code_rule_import(db: Db, actor: auth.WriteUser, file: UploadFile = File(...)) -> dict[str, Any]:
    return await excel_io.preview_code_rule_import(db, file)


def rule_payload(row: models.CodeRule) -> dict[str, Any]:
    return {field: getattr(row, field) for field in schemas.CodeRuleIn.model_fields}


@router.post("/code-rule-imports/apply")
def apply_code_rule_import(payload: schemas.CodeRuleReplaceIn, db: Db, actor: auth.WriteUser) -> dict[str, Any]:
    if not payload.rules:
        raise HTTPException(status_code=422, detail="规则清单不能为空")
    if any(rule.item_type == "material" and (rule.prefix.strip().startswith("99.") or "99." in rule.pattern) for rule in payload.rules):
        raise HTTPException(status_code=422, detail="99.XXXX.X 为未正式原材料专属号段，不能用于正式编码规则")
    before = [rule_payload(row) for row in db.scalars(select(models.CodeRule).order_by(models.CodeRule.id))]
    snapshot = models.CodeRuleSnapshot(rules_json=services.dumps(before), reason=payload.reason, actor_id=actor.id)
    db.add(snapshot)
    db.flush()
    try:
        imported_types = {rule.item_type for rule in payload.rules}
        db.query(models.CodeRule).filter(models.CodeRule.item_type.in_(imported_types)).delete(synchronize_session=False)
        db.flush()
        for rule in payload.rules:
            db.add(models.CodeRule(**rule.model_dump()))
        db.flush()
        after = [rule_payload(row) for row in db.scalars(select(models.CodeRule).order_by(models.CodeRule.id))]
        services.audit(db, actor.id, "replace", "code_rules", None, payload.reason, before=before, after=after, batch_key=f"rules-{snapshot.id}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"snapshot_id": snapshot.id, "rules": len(payload.rules), "item_types": sorted(imported_types)}


@router.get("/code-rule-snapshots")
def list_code_rule_snapshots(db: Db, user: auth.WriteUser) -> list[dict[str, Any]]:
    return [{"id": row.id, "reason": row.reason, "actor_id": row.actor_id, "created_at": row.created_at, "rules": len(json.loads(row.rules_json))} for row in db.scalars(select(models.CodeRuleSnapshot).order_by(models.CodeRuleSnapshot.id.desc()).limit(20))]


@router.post("/code-rule-snapshots/{snapshot_id}/restore")
def restore_code_rule_snapshot(snapshot_id: int, reason: str, db: Db, actor: auth.WriteUser) -> dict[str, Any]:
    snapshot = db.get(models.CodeRuleSnapshot, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="规则快照不存在")
    target = json.loads(snapshot.rules_json)
    current = [rule_payload(row) for row in db.scalars(select(models.CodeRule).order_by(models.CodeRule.id))]
    safety = models.CodeRuleSnapshot(rules_json=services.dumps(current), reason=f"恢复前快照：{reason}", actor_id=actor.id)
    db.add(safety)
    db.flush()
    db.query(models.CodeRule).delete()
    db.flush()
    for row in target:
        db.add(models.CodeRule(**row))
    services.audit(db, actor.id, "restore", "code_rules", snapshot_id, reason, before=current, after=target, batch_key=f"rules-restore-{snapshot_id}")
    db.commit()
    return {"restored_from": snapshot_id, "safety_snapshot_id": safety.id, "rules": len(target)}


@router.post("/code-rules", status_code=201)
def create_code_rule(payload: schemas.CodeRuleIn, db: Db, actor: auth.WriteUser) -> dict[str, Any]:
    if payload.item_type == "material" and (payload.prefix.strip().startswith("99.") or "99." in payload.pattern):
        raise HTTPException(status_code=422, detail="99.XXXX.X 为未正式原材料专属号段，不能用于正式编码规则")
    row = models.CodeRule(**payload.model_dump())
    db.add(row)
    db.flush()
    services.audit(db, actor.id, "create", "code_rule", row.id, "新增编码规则", after=payload.model_dump())
    db.commit()
    return {column.name: getattr(row, column.name) for column in models.CodeRule.__table__.columns}


@router.patch("/code-rules/{rule_id}")
def update_code_rule(rule_id: int, payload: schemas.CodeRuleUpdateIn, db: Db, actor: auth.WriteUser) -> dict[str, Any]:
    row = db.get(models.CodeRule, rule_id)
    if not row:
        raise HTTPException(status_code=404, detail="编码规则不存在")
    before = {column.name: getattr(row, column.name) for column in models.CodeRule.__table__.columns}
    values = payload.model_dump(exclude={"reason"})
    for key, value in values.items():
        setattr(row, key, value)
    after = {column.name: getattr(row, column.name) for column in models.CodeRule.__table__.columns}
    services.audit(db, actor.id, "update", "code_rule", row.id, payload.reason, before, after)
    db.commit()
    return after


@router.get("/code-rules/{rule_id}/recommend")
def recommend_code(rule_id: int, db: Db, user: auth.CurrentUser) -> dict[str, Any]:
    rule = db.get(models.CodeRule, rule_id)
    if not rule or not rule.active:
        raise HTTPException(status_code=404, detail="有效编码规则不存在")
    return services.next_code(db, rule.prefix, rule.pattern)


@router.get("/alternatives")
def list_alternatives(db: Db, user: auth.CurrentUser) -> list[dict[str, Any]]:
    return [alternative_group_dict(db, group) for group in db.scalars(select(models.AlternativeGroup).order_by(models.AlternativeGroup.name))]


@router.get("/path-alternatives")
def path_alternatives(db: Db, user: auth.CurrentUser) -> list[dict[str, Any]]:
    from .path_bom import configuration_dict
    return [configuration_dict(db, row) for row in db.scalars(select(models.PathAlternative))]


@router.put("/items/{item_id}/path-alternatives")
def configure_path_alternative(item_id: int, payload: dict[str, Any], db: Db, actor: auth.WriteUser):
    from .path_bom import save_configuration
    return save_configuration(db, item_id, payload, actor)


def alternative_group_dict(db: Session, group: models.AlternativeGroup) -> dict[str, Any]:
    members = list(db.scalars(
        select(models.AlternativeMember)
        .where(models.AlternativeMember.group_id == group.id)
        .order_by(models.AlternativeMember.priority, models.AlternativeMember.id)
    ))
    return {
        "id": group.id, "name": group.name, "item_type": group.item_type,
        "default_item_id": group.default_item_id, "active": group.active,
        "members": [
            {"id": row.id, "item_id": row.item_id, "priority": row.priority, "is_default": row.is_default, "active": row.active, "market_share": str(row.market_share)}
            for row in members
        ],
    }


def validate_alternative_payload(db: Session, payload: schemas.AlternativeGroupIn, exclude_group_id: int | None = None) -> list[int]:
    name = payload.name.strip()
    duplicate_query = select(models.AlternativeGroup.id).where(models.AlternativeGroup.name == name)
    if exclude_group_id:
        duplicate_query = duplicate_query.where(models.AlternativeGroup.id != exclude_group_id)
    if db.scalar(duplicate_query):
        raise HTTPException(status_code=409, detail="替代组名称已存在")
    member_ids = list(dict.fromkeys([payload.default_item_id, *payload.member_item_ids]))
    members = [db.get(models.Item, item_id) for item_id in member_ids]
    if any(
        row is None
        or row.deleted_at
        or row.item_type != payload.item_type
        or row.status == "disabled"
        or not row.is_formally_imported
        for row in members
    ):
        raise HTTPException(status_code=409, detail="替代组成员必须是同类型有效物料")
    if payload.member_market_shares is not None:
        shares = payload.member_market_shares
        if set(shares) != set(member_ids):
            raise HTTPException(status_code=422, detail="市场占比必须完整覆盖替代组全部成员")
        if any(value < 0 or value > 100 or value != value.quantize(Decimal("0.01")) for value in shares.values()):
            raise HTTPException(status_code=422, detail="市场占比须为 0–100 之间且最多保留两位小数")
        if sum(shares.values(), Decimal("0")) != Decimal("100.00"):
            raise HTTPException(status_code=422, detail="替代组市场占比合计必须等于 100%")
    return member_ids


def alternative_market_shares(payload: schemas.AlternativeGroupIn, member_ids: list[int]) -> dict[int, Decimal]:
    if payload.member_market_shares is not None:
        return {item_id: payload.member_market_shares[item_id].quantize(Decimal("0.01")) for item_id in member_ids}
    count = len(member_ids)
    base = (Decimal("100") / count).quantize(Decimal("0.01"))
    shares = {item_id: base for item_id in member_ids}
    shares[member_ids[-1]] = Decimal("100.00") - base * (count - 1)
    return shares


@router.post("/alternatives", status_code=201)
def create_alternative(payload: schemas.AlternativeGroupIn, db: Db, actor: auth.WriteUser) -> dict[str, Any]:
    reject_retired_alternatives(db)
    member_ids = validate_alternative_payload(db, payload)
    shares = alternative_market_shares(payload, member_ids)
    group = models.AlternativeGroup(name=payload.name.strip(), item_type=payload.item_type, default_item_id=payload.default_item_id, active=payload.active)
    db.add(group)
    db.flush()
    for index, item_id in enumerate(member_ids):
        db.add(models.AlternativeMember(group_id=group.id, item_id=item_id, priority=index, is_default=item_id == payload.default_item_id, active=True, market_share=shares[item_id]))
    services.audit(db, actor.id, "create", "alternative_group", group.id, payload.reason, after=payload.model_dump())
    db.commit()
    return alternative_group_dict(db, group)


@router.patch("/alternatives/{group_id}")
def update_alternative(group_id: int, payload: schemas.AlternativeGroupIn, db: Db, actor: auth.WriteUser) -> dict[str, Any]:
    reject_retired_alternatives(db)
    group = db.get(models.AlternativeGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="替代组不存在")
    member_ids = validate_alternative_payload(db, payload, exclude_group_id=group.id)
    shares = alternative_market_shares(payload, member_ids)
    referenced_lines = list(db.scalars(select(models.BOMLine).where(models.BOMLine.alternative_group_id == group.id)))
    selected_ids = {line.child_item_id for line in referenced_lines}
    removed_selected_ids = selected_ids - set(member_ids)
    if removed_selected_ids:
        removed_items = [db.get(models.Item, item_id) for item_id in sorted(removed_selected_ids)]
        labels = "、".join(f"{item.code}｜{item.name}" for item in removed_items if item)
        raise HTTPException(status_code=409, detail=f"以下成员仍被 BOM 当前选用，不能移出替代组：{labels}")
    if referenced_lines and not payload.active:
        raise HTTPException(status_code=409, detail="替代组仍被 BOM 使用，不能停用")

    before = alternative_group_dict(db, group)
    group.name = payload.name.strip()
    group.item_type = payload.item_type
    group.default_item_id = payload.default_item_id
    group.active = payload.active
    db.query(models.AlternativeMember).filter(models.AlternativeMember.group_id == group.id).delete(synchronize_session=False)
    db.flush()
    for index, item_id in enumerate(member_ids):
        db.add(models.AlternativeMember(
            group_id=group.id, item_id=item_id, priority=index,
            is_default=item_id == payload.default_item_id, active=True, market_share=shares[item_id],
        ))
    db.flush()
    after = alternative_group_dict(db, group)
    services.audit(db, actor.id, "update", "alternative_group", group.id, payload.reason, before, after)
    db.commit()
    return after


@router.post("/imports/materials/preview")
async def preview_import(db: Db, actor: auth.WriteUser, file: UploadFile = File(...)) -> dict[str, Any]:
    from .material_import import preview
    return await preview(db, file, actor)


@router.get("/imports/{batch_id}")
def get_import(batch_id: int, db: Db, user: auth.CurrentUser) -> dict[str, Any]:
    batch = db.get(models.ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    rows = list(db.scalars(select(models.ImportRow).where(models.ImportRow.batch_id == batch_id).order_by(models.ImportRow.row_number)))
    return {"batch": {"id": batch.id, "filename": batch.filename, "status": batch.status, "stats": json.loads(batch.stats_json)}, "rows": [excel_io.import_row_dict(row) for row in rows]}


@router.patch("/imports/{batch_id}/rows/{row_id}")
def edit_import_row(
    batch_id: int,
    row_id: int,
    payload: schemas.ImportRowEditIn,
    db: Db,
    actor: auth.WriteUser,
) -> dict[str, Any]:
    batch = db.get(models.ImportBatch, batch_id)
    row = db.get(models.ImportRow, row_id)
    if not batch or not row or row.batch_id != batch.id:
        raise HTTPException(status_code=404, detail="导入预览行不存在")
    if batch.status == "completed" or row.status == "imported":
        raise HTTPException(status_code=409, detail="已完成导入的行不能修改")
    from .material_import import update_row
    return update_row(db, batch, row, payload, actor)


@router.post("/imports/{batch_id}/commit")
def commit_import(batch_id: int, payload: schemas.ImportCommitIn, db: Db, actor: auth.WriteUser) -> dict[str, Any]:
    batch = db.get(models.ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    from .material_import import commit
    return commit(db, batch, payload, actor)


@router.get("/imports/{batch_id}/report")
def import_report(batch_id: int, db: Db, user: auth.ExportUser) -> StreamingResponse:
    if not db.get(models.ImportBatch, batch_id):
        raise HTTPException(status_code=404, detail="导入批次不存在")
    return download(excel_io.import_error_report(db, batch_id), f"导入批次-{batch_id}-结果.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def maintenance_matches(db: Session, payload: schemas.MaintenancePreviewIn) -> list[models.BOMLine]:
    active_parent = aliased(models.Item)
    query = (
        select(models.BOMLine)
        .join(active_parent, active_parent.id == models.BOMLine.parent_item_id)
        .where(
            models.BOMLine.parent_item_id.in_(payload.parent_item_ids),
            or_(active_parent.unofficial_status.is_(None), active_parent.unofficial_status != "archived"),
        )
    )
    if payload.operation in {"replace", "adjust", "delete"}:
        if not payload.source_item_id:
            raise HTTPException(status_code=422, detail="该操作必须选择原物料")
        query = query.where(models.BOMLine.child_item_id == payload.source_item_id)
    return list(db.scalars(query.order_by(models.BOMLine.parent_item_id, models.BOMLine.sort_order)))


@router.get("/maintenance/parent-candidates")
def maintenance_parent_candidates(
    operation: str, db: Db, user: auth.CurrentUser,
    source_item_id: int | None = None, target_item_id: int | None = None,
) -> dict[str, Any]:
    if operation not in {"replace", "adjust", "add", "delete"}:
        raise HTTPException(status_code=422, detail="批量维护操作无效")
    if operation != "add":
        if not source_item_id:
            return {"items": [], "message": "请先选择原物料"}
        require_item(db, source_item_id)
        active_parent = aliased(models.Item)
        lines = list(db.scalars(
            select(models.BOMLine).join(active_parent, active_parent.id == models.BOMLine.parent_item_id).where(
                models.BOMLine.child_item_id == source_item_id,
                or_(active_parent.unofficial_status.is_(None), active_parent.unofficial_status != "archived"),
            )
            .order_by(models.BOMLine.parent_item_id)
        ))
        target = require_item(db, target_item_id) if operation == "replace" and target_item_id else None
        candidates = []
        for line in lines:
            if target:
                try:
                    services.validate_bom_relation(db, line.parent, target, line_id=line.id)
                except HTTPException:
                    continue
            candidates.append(services.item_dict(line.parent))
        unique = list({row["id"]: row for row in candidates}.values())
        return {"items": unique, "message": f"找到 {len(unique)} 个直接包含该物料的父项"}

    if not target_item_id:
        return {"items": [], "message": "请先选择要新增的子物料"}
    target = require_item(db, target_item_id)
    allowed_parent_types = {
        parent_type for parent_type, child_types in services.ALLOWED_CHILDREN.items()
        if target.item_type in child_types
    }
    descendants: set[int] = set()
    stack = [target.id]
    while stack:
        current = stack.pop()
        for child_id in db.scalars(select(models.BOMLine.child_item_id).where(models.BOMLine.parent_item_id == current)):
            if child_id not in descendants:
                descendants.add(child_id)
                stack.append(child_id)
    rows = list(db.scalars(
        select(models.Item).where(
            models.Item.item_type.in_(allowed_parent_types), models.Item.deleted_at.is_(None),
            models.Item.id != target.id,
            or_(models.Item.unofficial_status.is_(None), models.Item.unofficial_status != "archived"),
        ).order_by(models.Item.item_type, models.Item.code)
    ))
    candidates = [row for row in rows if row.id not in descendants]
    if target.item_type != "material" and target.status == "disabled":
        candidates = []
    return {"items": [services.item_dict(row) for row in candidates], "message": f"找到 {len(candidates)} 个层级合法的父项"}


@router.post("/maintenance/preview")
def preview_maintenance(payload: schemas.MaintenancePreviewIn, db: Db, user: auth.WriteUser) -> dict[str, Any]:
    if payload.operation == "add":
        if not payload.target_item_id or payload.quantity is None:
            raise HTTPException(status_code=422, detail="新增必须选择目标物料并填写数量")
        target = require_item(db, payload.target_item_id)
        additions = []
        for parent_id in payload.parent_item_ids:
            parent = require_item(db, parent_id)
            services.ensure_item_writable(parent)
            services.validate_bom_relation(db, parent, target)
            existing = db.scalar(select(models.BOMLine).where(
                models.BOMLine.parent_item_id == parent.id,
                models.BOMLine.child_item_id == target.id,
            ).order_by(models.BOMLine.sort_order, models.BOMLine.id).limit(1))
            before_quantity = Decimal(existing.quantity) if existing else Decimal("0")
            additions.append({
                "parent": services.item_dict(parent), "child": services.item_dict(target),
                "effect": "merge" if existing else "add",
                "before_quantity": str(before_quantity),
                "after_quantity": str(before_quantity + payload.quantity),
            })
        return {"affected_count": len(additions), "lines": additions}
    matches = maintenance_matches(db, payload)
    return {"affected_count": len(matches), "lines": [services.bom_line_dict(row) for row in matches]}


@router.post("/maintenance/apply")
def apply_maintenance(payload: schemas.MaintenanceApplyIn, db: Db, actor: auth.WriteUser) -> dict[str, Any]:
    matches = maintenance_matches(db, payload)
    batch_key = services.new_batch_key()
    changed = 0
    try:
        if payload.operation == "add":
            if not payload.target_item_id or payload.quantity is None:
                raise HTTPException(status_code=422, detail="新增必须选择目标物料并填写数量")
            for parent_id in payload.parent_item_ids:
                parent = require_item(db, parent_id)
                services.add_bom_line(db, parent, schemas.BOMComponentIn(child_item_id=payload.target_item_id, quantity=payload.quantity), actor, payload.reason, commit=False)
                changed += 1
        else:
            deleted_material_parents: dict[int, models.Item] = {}
            if payload.operation in {'delete','replace'}:
                from .item_lifecycle import clear_line_configurations
                clear_line_configurations(db,[line.id for line in matches],actor,payload.reason,payload.confirm_clear)
            for line in matches:
                services.ensure_item_writable(line.parent)
                before = services.bom_line_dict(line)
                if payload.operation == "delete":
                    if line.parent.item_type == "material":
                        deleted_material_parents[line.parent.id] = line.parent
                    db.delete(line)
                elif payload.operation == "adjust":
                    if payload.quantity is None:
                        raise HTTPException(status_code=422, detail="调整数量不能为空")
                    line.quantity = payload.quantity
                elif payload.operation == "replace":
                    if not payload.target_item_id:
                        raise HTTPException(status_code=422, detail="替换必须选择目标物料")
                    target = require_item(db, payload.target_item_id)
                    services.validate_bom_relation(db, line.parent, target, line_id=line.id)
                    line.child_item_id = target.id
                    line.child = target
                services.audit(db, actor.id, payload.operation, "bom_line", line.id, payload.reason, before, None if payload.operation == "delete" else services.bom_line_dict(line), batch_key)
                changed += 1
            if deleted_material_parents:
                db.flush()
                for parent in deleted_material_parents.values():
                    services.sync_material_assembly_flag(db, parent)
        db.flush()
        from .path_bom import EffectiveBOM
        if payload.operation!='adjust':
            EffectiveBOM(db).validate(payload.parent_item_ids)
        services.audit(db, actor.id, "bulk_maintenance", "bom", None, payload.reason, after={"operation": payload.operation, "changed": changed}, batch_key=batch_key)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"changed": changed, "batch_key": batch_key}


@router.get("/audit")
def list_audit(
    db: Db, user: auth.CurrentUser, entity_type: str | None = None,
    actor_id: int | None = None, entity_id: int | None = None,
    limit: int = Query(200, ge=1, le=2000),
) -> list[dict[str, Any]]:
    query = select(models.AuditEvent)
    if entity_type:
        query = query.where(models.AuditEvent.entity_type == entity_type)
    if actor_id:
        query = query.where(models.AuditEvent.actor_id == actor_id)
    if entity_id:
        query = query.where(models.AuditEvent.entity_id == entity_id)
    return [audit_dict(row) for row in db.scalars(query.order_by(models.AuditEvent.id.desc()).limit(limit))]


@router.get("/audit/export")
def export_audit(db: Db, user: auth.ExportUser) -> StreamingResponse:
    events = list(db.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id)))
    return download(excel_io.audit_workbook(events), "变更日志.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.post("/backups")
def create_backup(payload: schemas.BackupIn, db: Db, actor: auth.WriteUser) -> dict[str, Any]:
    if not settings.database_url.startswith("sqlite:///"):
        raise HTTPException(status_code=409, detail="当前数据库不是 SQLite，不能使用文件备份")
    db.commit()
    result = ops.backup(payload.label or "manual", retain=30)
    filename = Path(str(result["path"])).name
    services.audit(db, actor.id, "backup", "database", None, "创建数据库备份", after={"filename": filename, "integrity": result["integrity"]})
    db.commit()
    return {"filename": filename, "size": result["size"], "integrity": result["integrity"]}
