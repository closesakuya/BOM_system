from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, schemas, services
from .database import SessionLocal, init_db
from .main import seed_admin


DEMO_MACHINE_CODE = "00.999.01"
DEMO_MACHINE_CHANGE = "V1.1 演示：整机说明由初始结构说明更新为结构核对完成"
DEMO_REASON = "创建虚拟演示数据集"
DEMO_COMBINATION_PARENT_CODE = "05.999.04"
DEMO_COMBINATION_CHILD_CODE = "05.999.01"
DEMO_COMBINATION_LINE_REMARK = "组合半成品示例：包含水质采集半成品"
DEMO_CODES = (
    *(f"90.{number:04d}.01" for number in range(9001, 9013)),
    *(f"05.999.{number:02d}" for number in range(1, 6)),
    *(f"03.999.{number:02d}" for number in range(1, 5)),
    *(f"00.999.{number:02d}" for number in range(1, 4)),
)
DEMO_GROUP_NAMES = (
    "演示-光学传感器选配",
    "演示-泵组选配",
    "演示-显示屏选配",
    "演示-采集模块选配",
    "演示-分析单元选配",
)


def historical_digest(db: Session) -> tuple[str, dict[str, int]]:
    """Digest every non-demo item, BOM relation, alternative group and code rule."""
    demo_codes = set(DEMO_CODES)
    demo_groups = set(DEMO_GROUP_NAMES)
    items = list(db.scalars(select(models.Item).order_by(models.Item.code)))
    original_items = [item for item in items if item.code not in demo_codes]
    code_by_id = {item.id: item.code for item in items}
    item_rows = [
        {
            "type": item.item_type, "code": item.code, "body": item.code_body,
            "version": item.version_label, "version_number": item.version_number,
            "series": item.version_series, "auxiliary": item.auxiliary_code,
            "name": item.name, "specification": item.specification,
            "source": item.source_type, "unit": item.unit, "remark": item.remark,
            "previous": item.previous_version_name, "invoice": item.invoice_name,
            "attribute": item.material_attribute,
            "key_component_code": item.key_component_code,
            "machine_model": item.machine_model,
            "is_formally_imported": item.is_formally_imported,
            "assembly": item.requires_assembly, "status": item.status,
            "deleted": item.deleted_at.isoformat() if item.deleted_at else None,
        }
        for item in original_items
    ]
    line_rows = []
    for line in db.scalars(select(models.BOMLine).order_by(models.BOMLine.id)):
        parent_code = code_by_id.get(line.parent_item_id)
        child_code = code_by_id.get(line.child_item_id)
        if parent_code in demo_codes or child_code in demo_codes:
            continue
        group = db.get(models.AlternativeGroup, line.alternative_group_id) if line.alternative_group_id else None
        line_rows.append({
            "parent": parent_code, "child": child_code, "quantity": str(line.quantity),
            "sort": line.sort_order, "remark": line.line_remark,
            "alternative_group": group.name if group else None,
        })
    group_rows = []
    groups = list(db.scalars(select(models.AlternativeGroup).order_by(models.AlternativeGroup.name)))
    for group in groups:
        if group.name in demo_groups:
            continue
        members = list(db.scalars(
            select(models.AlternativeMember)
            .where(models.AlternativeMember.group_id == group.id)
            .order_by(models.AlternativeMember.priority, models.AlternativeMember.id)
        ))
        group_rows.append({
            "name": group.name, "type": group.item_type,
            "default": code_by_id.get(group.default_item_id), "active": group.active,
            "members": [
                (
                    code_by_id.get(member.item_id), member.priority, member.is_default,
                    member.active, str(member.market_share),
                )
                for member in members
            ],
        })
    rule_rows = [
        {
            "type": rule.item_type, "large": rule.large_category, "small": rule.small_category,
            "attribute": rule.material_attribute, "prefix": rule.prefix, "pattern": rule.pattern,
            "description": rule.description, "active": rule.active, "sort": rule.sort_order,
        }
        for rule in db.scalars(select(models.CodeRule).order_by(models.CodeRule.id))
    ]
    payload = {"items": item_rows, "bom_lines": line_rows, "alternative_groups": group_rows, "code_rules": rule_rows}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), {
        "items": len(item_rows), "bom_lines": len(line_rows),
        "alternative_groups": len(group_rows), "code_rules": len(rule_rows),
    }


def _group_dict(group: models.AlternativeGroup, members: list[models.AlternativeMember]) -> dict[str, Any]:
    return {
        "id": group.id, "name": group.name, "item_type": group.item_type,
        "default_item_id": group.default_item_id, "active": group.active,
        "members": [
            {
                "id": member.id, "item_id": member.item_id, "priority": member.priority,
                "is_default": member.is_default, "active": member.active,
            }
            for member in members
        ],
    }


def _ensure_combination_demo(
    db: Session,
    actor: models.User,
    items_by_code: dict[str, models.Item],
) -> bool:
    """Upgrade an older complete demo set with the combination-semi example."""
    parent = items_by_code[DEMO_COMBINATION_PARENT_CODE]
    child = items_by_code[DEMO_COMBINATION_CHILD_CODE]
    existing = db.scalar(select(models.BOMLine).where(
        models.BOMLine.parent_item_id == parent.id,
        models.BOMLine.child_item_id == child.id,
    ))
    if existing:
        return False

    digest_before, counts_before = historical_digest(db)
    sibling_orders = list(db.scalars(
        select(models.BOMLine.sort_order).where(models.BOMLine.parent_item_id == parent.id)
    ))
    line = models.BOMLine(
        parent_item_id=parent.id,
        child_item_id=child.id,
        quantity=Decimal("1"),
        sort_order=max(sibling_orders, default=0) + 1,
        line_remark=DEMO_COMBINATION_LINE_REMARK,
    )
    db.add(line)
    db.flush()
    services.audit(
        db, actor.id, "add", "bom_line", line.id,
        "补充组合半成品演示关系",
        after=services.bom_line_dict(line),
    )
    digest_after, counts_after = historical_digest(db)
    if digest_before != digest_after or counts_before != counts_after:
        db.rollback()
        raise RuntimeError("组合半成品演示升级影响了历史物料或关系，事务已回滚")
    db.commit()
    return True


def seed_demo_in_session(db: Session, actor: models.User) -> dict[str, object]:
    if db.scalar(select(models.AuditEvent.id).where(models.AuditEvent.action=='migrate_v1_2').limit(1)):
        from .v1_2_demo import seed_in_session
        return seed_in_session(db,actor)
    existing_items = list(db.scalars(select(models.Item).where(models.Item.code.in_(DEMO_CODES))))
    existing_groups = list(db.scalars(select(models.AlternativeGroup).where(models.AlternativeGroup.name.in_(DEMO_GROUP_NAMES))))
    if existing_items or existing_groups:
        item_codes = {item.code for item in existing_items}
        group_names = {group.name for group in existing_groups}
        if item_codes == set(DEMO_CODES) and group_names == set(DEMO_GROUP_NAMES):
            combination_upgraded = _ensure_combination_demo(
                db, actor, {item.code: item for item in existing_items}
            )
            digest, original_counts = historical_digest(db)
            return {
                "created": False,
                "combination_upgraded": combination_upgraded,
                "message": (
                    "完整虚拟演示数据集已存在，已补充组合半成品示例"
                    if combination_upgraded
                    else "完整虚拟演示数据集已存在，未修改任何记录"
                ),
                "demo_items": len(item_codes), "demo_groups": len(group_names),
                "historical_digest": digest, "historical_counts": original_counts,
            }
        conflicts = sorted(item_codes | group_names)
        raise RuntimeError(f"演示保留编码或组名存在部分冲突，已拒绝修改原记录：{', '.join(conflicts)}")

    digest_before, original_counts = historical_digest(db)
    created: dict[str, models.Item] = {}

    def create(
        code: str,
        item_type: str,
        name: str,
        specification: str,
        *,
        source_type: str | None = None,
        status: str | None = None,
        unit: str = "pcs",
        material_attribute: str | None = None,
        remark: str = "虚拟演示数据，不属于历史迁移物料",
        invoice_name: str | None = None,
        components: tuple[tuple[str, str, str], ...] = (),
    ) -> models.Item:
        component_rows = [
            schemas.BOMComponentIn(
                child_item_id=created[child_code].id,
                quantity=Decimal(quantity), sort_order=index,
                line_remark=line_remark,
            )
            for index, (child_code, quantity, line_remark) in enumerate(components, start=1)
        ]
        item = services.create_item(db, schemas.ItemCreate(
            item_type=item_type, code=code, name=name, specification=specification,
            source_type=source_type, status=status, unit=unit,
            material_attribute=material_attribute, remark=remark,
            invoice_name=invoice_name, components=component_rows,
            similarity_confirmed=True, reason=DEMO_REASON,
        ), actor, commit=False)
        created[code] = item
        return item

    # 原材料：包含普通叶子原材料和一个“原材料组合原材料”的自制组件。
    screw = create("90.9001.01", "material", "演示-M4不锈钢螺钉", "M4×12，304不锈钢", source_type="purchased", material_attribute="紧固件", invoice_name="不锈钢螺钉")
    board = create("90.9002.01", "material", "演示-水质采集电路板", "DEMO-PCB-V1", source_type="purchased", material_attribute="电路板", invoice_name="采集电路板")
    create("90.9003.01", "material", "演示-自制采集板组件", "DEMO-ASSY-V1", source_type="self_made", material_attribute="电路板组件", components=((board.code, "1", "主电路板"), (screw.code, "4", "组件固定")))
    create("90.9004.01", "material", "演示-标准光学传感器", "OPT-STD-0~100NTU", source_type="purchased", material_attribute="传感器", invoice_name="光学传感器")
    create("90.9005.01", "material", "演示-高精度光学传感器", "OPT-PRO-0~100NTU", source_type="outsourced", material_attribute="传感器", invoice_name="高精度光学传感器")
    create("90.9006.01", "material", "演示-12V蠕动泵", "PUMP-12V-60ML", source_type="purchased", material_attribute="泵", invoice_name="蠕动泵")
    create("90.9007.01", "material", "演示-24V耐腐蚀蠕动泵", "PUMP-24V-80ML", source_type="outsourced", material_attribute="泵", invoice_name="耐腐蚀蠕动泵")
    create("90.9008.01", "material", "演示-7英寸触摸屏", "HMI-7-1024×600", source_type="purchased", material_attribute="显示器", invoice_name="触摸显示屏")
    create("90.9009.01", "material", "演示-10英寸触摸屏", "HMI-10-1280×800", source_type="purchased", material_attribute="显示器", invoice_name="触摸显示屏")
    create("90.9010.01", "material", "演示-IP54机箱", "CASE-IP54-DEMO", source_type="outsourced", material_attribute="结构件", invoice_name="仪器机箱")
    create("90.9011.01", "material", "演示-宽压电源模块", "PSU-24V-150W", source_type="purchased", material_attribute="电源", invoice_name="开关电源")
    create("90.9012.01", "material", "演示-屏蔽连接线", "CABLE-SHIELD-1M", source_type="purchased", unit="m", material_attribute="线缆", invoice_name="屏蔽线缆")

    # 半成品：标准/增强采集模块用于半成品级替代展示。
    create("05.999.01", "semi_finished", "演示-水质采集半成品", "DEMO-SEMI-ACQ-STD", status="trial", remark="初始创建，稍后演示字段变更", components=(("90.9003.01", "1", "采集板组件"), ("90.9004.01", "1", "默认标准传感器")))
    create("05.999.02", "semi_finished", "演示-流路驱动半成品", "DEMO-SEMI-FLUID", status="active", components=(("90.9006.01", "1", "默认12V泵"), ("90.9012.01", "2", "泵组线缆")))
    create("05.999.03", "semi_finished", "演示-人机界面半成品", "DEMO-SEMI-HMI", status="active", components=(("90.9008.01", "1", "默认7英寸屏"), ("90.9012.01", "1", "显示连接线")))
    create("05.999.04", "semi_finished", "演示-供电安装半成品", "DEMO-SEMI-POWER", status="active", components=(("90.9011.01", "1", "宽压电源"), ("90.9001.01", "4", "电源固定"), (DEMO_COMBINATION_CHILD_CODE, "1", DEMO_COMBINATION_LINE_REMARK)))
    create("05.999.05", "semi_finished", "演示-增强采集半成品", "DEMO-SEMI-ACQ-PRO", status="trial", components=(("90.9003.01", "1", "采集板组件"), ("90.9005.01", "1", "高精度传感器")))

    # 单元：标准与增强分析单元用于单元级替代展示。
    create("03.999.01", "unit", "演示-水质分析单元（初版）", "DEMO-UNIT-ANALYSIS-STD", status="trial", components=(("05.999.01", "2", "标准采集模块"), ("90.9001.01", "2", "单元固定")))
    create("03.999.02", "unit", "演示-取样流路单元", "DEMO-UNIT-FLUID", status="active", components=(("05.999.02", "1", "流路驱动"), ("90.9010.01", "1", "流路防护箱")))
    create("03.999.03", "unit", "演示-控制显示单元", "DEMO-UNIT-CONTROL", status="active", components=(("05.999.03", "1", "人机界面"), ("05.999.04", "1", "供电安装")))
    create("03.999.04", "unit", "演示-增强水质分析单元", "DEMO-UNIT-ANALYSIS-PRO", status="trial", components=(("05.999.05", "1", "增强采集模块"), ("90.9001.01", "2", "单元固定")))

    # 三台整机分别展示基础主链、标准组合和增强选配组合。
    create(DEMO_MACHINE_CODE, "machine", "演示-V1完整水质分析仪", "DEMO-MACHINE-V1", status="trial", unit="set", remark="用于展示整机→单元→半成品→原材料完整层级", components=(("03.999.01", "1", "标准分析单元"), ("90.9002.01", "1", "整机扩展电路板")))
    create("00.999.02", "machine", "演示-标准模块化水质分析仪", "DEMO-MACHINE-STANDARD", status="active", unit="set", components=(("03.999.01", "1", "标准分析单元，可选增强单元"), ("03.999.02", "1", "取样流路"), ("03.999.03", "1", "控制显示"), ("90.9010.01", "1", "整机机箱")))
    create("00.999.03", "machine", "演示-增强模块化水质分析仪", "DEMO-MACHINE-PRO", status="trial", unit="set", components=(("03.999.04", "1", "当前选用增强分析单元"), ("03.999.02", "2", "双流路取样"), ("03.999.03", "1", "控制显示"), ("90.9010.01", "1", "整机机箱")))

    groups: dict[str, models.AlternativeGroup] = {}

    def create_group(name: str, item_type: str, default_code: str, candidate_code: str) -> models.AlternativeGroup:
        group = models.AlternativeGroup(
            name=name, item_type=item_type,
            default_item_id=created[default_code].id, active=True,
        )
        db.add(group)
        db.flush()
        members = [
            models.AlternativeMember(
                group_id=group.id, item_id=created[code].id, priority=index,
                is_default=index == 0, active=True, market_share=Decimal("50.00"),
            )
            for index, code in enumerate((default_code, candidate_code))
        ]
        db.add_all(members)
        db.flush()
        services.audit(db, actor.id, "create", "alternative_group", group.id, DEMO_REASON, after=_group_dict(group, members))
        groups[name] = group
        return group

    create_group("演示-光学传感器选配", "material", "90.9004.01", "90.9005.01")
    create_group("演示-泵组选配", "material", "90.9006.01", "90.9007.01")
    create_group("演示-显示屏选配", "material", "90.9008.01", "90.9009.01")
    create_group("演示-采集模块选配", "semi_finished", "05.999.01", "05.999.05")
    create_group("演示-分析单元选配", "unit", "03.999.01", "03.999.04")

    def bind_group(parent_code: str, child_code: str, group_name: str) -> None:
        line = db.scalar(select(models.BOMLine).where(
            models.BOMLine.parent_item_id == created[parent_code].id,
            models.BOMLine.child_item_id == created[child_code].id,
        ))
        if not line:
            raise RuntimeError(f"演示 BOM 行不存在：{parent_code} → {child_code}")
        before = services.bom_line_dict(line)
        line.alternative_group_id = groups[group_name].id
        db.flush()
        services.audit(db, actor.id, "update", "bom_line", line.id, f"绑定{group_name}", before, services.bom_line_dict(line))

    for binding in (
        ("05.999.01", "90.9004.01", "演示-光学传感器选配"),
        ("05.999.02", "90.9006.01", "演示-泵组选配"),
        ("05.999.03", "90.9008.01", "演示-显示屏选配"),
        ("03.999.01", "05.999.01", "演示-采集模块选配"),
        ("00.999.01", "03.999.01", "演示-分析单元选配"),
        ("00.999.02", "03.999.01", "演示-分析单元选配"),
        ("00.999.03", "03.999.04", "演示-分析单元选配"),
    ):
        bind_group(*binding)

    def record_item_change(item: models.Item, reason: str, **values: object) -> None:
        before = services.item_dict(item)
        for field, value in values.items():
            setattr(item, field, value)
        db.flush()
        services.audit(db, actor.id, "update", "item", item.id, reason, before, services.item_dict(item))

    record_item_change(
        created["05.999.01"], "演示半成品字段变更记录",
        remark="已完成装配检查，进入演示试制状态",
    )
    record_item_change(
        created["03.999.01"], "演示单元名称变更记录",
        name="演示-水质分析单元",
    )
    record_item_change(
        created[DEMO_MACHINE_CODE], "演示整机说明变更记录",
        remark="完整演示层级已核对，可用于树形展开与跳转验收",
    )
    quantity_line = db.scalar(select(models.BOMLine).where(
        models.BOMLine.parent_item_id == created["03.999.01"].id,
        models.BOMLine.child_item_id == created["05.999.01"].id,
    ))
    if not quantity_line:
        raise RuntimeError("演示数量变更 BOM 行不存在")
    before = services.bom_line_dict(quantity_line)
    quantity_line.quantity = Decimal("3")
    db.flush()
    services.audit(db, actor.id, "adjust", "bom_line", quantity_line.id, "演示 BOM 数量由 2 调整为 3", before, services.bom_line_dict(quantity_line))

    digest_after, after_counts = historical_digest(db)
    if digest_before != digest_after or original_counts != after_counts:
        db.rollback()
        raise RuntimeError("演示数据写入影响了历史物料或关系，事务已回滚")
    db.commit()
    return {
        "created": True,
        "message": "已创建完整虚拟演示数据集，历史物料及关系摘要保持不变",
        "demo_items": len(created), "demo_bom_lines": 31,
        "demo_groups": len(groups), "demo_group_members": 10,
        "machine_codes": ["00.999.01", "00.999.02", "00.999.03"],
        "historical_digest_before": digest_before,
        "historical_digest_after": digest_after,
        "historical_counts": original_counts,
    }


def seed_demo() -> dict[str, object]:
    init_db()
    seed_admin()
    with SessionLocal() as db:
        actor = db.scalar(select(models.User).where(models.User.role == "admin").order_by(models.User.id))
        if not actor:
            raise RuntimeError("缺少管理员账户")
        return seed_demo_in_session(db, actor)


if __name__ == "__main__":
    print(json.dumps(seed_demo(), ensure_ascii=False, indent=2))
