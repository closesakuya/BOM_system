from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from sqlalchemy import delete, func, select

from . import models, services
from .config import PROJECT_ROOT, settings
from .database import SessionLocal, init_db
from .main import seed_admin


LEGACY_PATH = PROJECT_ROOT / "data" / "migration" / "BOM物料清单管理(1).xlsm"
RULE_PATH = PROJECT_ROOT / "data" / "templates" / "新增原材料编码登记表(模版).xlsx"
TYPE_MAP = {"原材料": "material", "半成品": "semi_finished", "单元": "unit", "整机": "machine"}
SOURCE_MAP = {"外购": "purchased", "外协": "outsourced", "自制": "self_made"}
INPUT_SHEETS = {"输入半成品": 4, "输入单元": 3, "输入整机": 3}


def text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def decimal_value(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 1))
    except InvalidOperation:
        return Decimal("1")


def read_legacy() -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if not LEGACY_PATH.is_file():
        raise FileNotFoundError(f"缺少历史迁移文件：{LEGACY_PATH}")
    wb = load_workbook(LEGACY_PATH, read_only=True, data_only=True, keep_vba=True)
    records: dict[str, dict[str, Any]] = {}
    declared_types: dict[str, set[str]] = defaultdict(set)
    raw_codes: set[str] = set()
    relationships: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for row_number, row in enumerate(wb["原材料清单"].iter_rows(min_row=3, values_only=True), 3):
        code = text(row[2])
        if not code:
            continue
        raw_codes.add(code)
        declared_types[code].add("material")
        records[code] = {
            "code": code,
            "item_type": "material",
            "auxiliary_code": text(row[1]),
            "name": text(row[3]) or code,
            "specification": text(row[4]),
            "source_type": SOURCE_MAP.get(text(row[5]) or "", "purchased"),
            "unit": text(row[6]) or "pcs",
            "remark": text(row[7]),
            "previous_version_name": text(row[8]),
            "invoice_name": text(row[9]),
            "material_attribute": text(row[10]),
            "change_note": text(row[11]),
            "source_sheet": "原材料清单",
            "source_row": row_number,
        }

    for sheet_name, start_row in INPUT_SHEETS.items():
        ws = wb[sheet_name]
        for row_number, row in enumerate(ws.iter_rows(min_row=start_row, values_only=True), start_row):
            code = text(row[2])
            if not code:
                continue
            category = text(row[7]) or ""
            item_type = TYPE_MAP.get(category)
            if not item_type:
                issues.append({"level": "error", "sheet": sheet_name, "row": row_number, "message": f"未知物料类别：{category}", "code": code})
                continue
            declared_types[code].add(item_type)
            if code not in records:
                records[code] = {
                    "code": code,
                    "item_type": item_type,
                    "auxiliary_code": None,
                    "name": text(row[3]) or code,
                    "specification": text(row[4]),
                    "source_type": "purchased" if item_type == "material" else None,
                    "unit": text(row[5]) or "pcs",
                    "remark": text(row[8]),
                    "previous_version_name": text(row[9]),
                    "invoice_name": text(row[10]),
                    "material_attribute": text(row[11]),
                    "change_note": text(row[12]),
                    "source_sheet": sheet_name,
                    "source_row": row_number,
                }
            parent_code = text(row[1])
            if parent_code:
                relationships.append({
                    "parent_code": parent_code,
                    "child_code": code,
                    "quantity": decimal_value(row[6]),
                    "line_remark": text(row[8]),
                    "sheet": sheet_name,
                    "row": row_number,
                })

    collisions = {code: sorted(types) for code, types in declared_types.items() if len(types) > 1}
    unresolved = {code: types for code, types in collisions.items() if not (set(types) == {"machine", "material"} and code in raw_codes)}
    for code, types in collisions.items():
        if code in raw_codes and set(types) == {"machine", "material"}:
            records[code]["item_type"] = "material"
            records[code]["requires_assembly"] = True
        else:
            issues.append({"level": "error", "code": code, "message": f"编码跨类型冲突：{','.join(types)}"})

    known = set(records)
    for row in relationships:
        if row["parent_code"] not in known or row["child_code"] not in known:
            issues.append({"level": "error", **row, "message": "BOM 父项或子项缺少主数据"})

    report = {
        "source": str(LEGACY_PATH.relative_to(PROJECT_ROOT)),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_item_rows": len(records),
        "source_bom_rows": len(relationships),
        "cross_type_collisions": len(collisions),
        "resolved_material_machine_collisions": len(collisions) - len(unresolved),
        "unresolved_collisions": len(unresolved),
        "issues": issues,
    }
    wb.close()
    return records, relationships, report


def read_code_rules() -> list[dict[str, Any]]:
    if not RULE_PATH.is_file():
        raise FileNotFoundError(f"缺少编码规则模板：{RULE_PATH}")
    wb = load_workbook(RULE_PATH, read_only=True, data_only=True)
    ws = wb["表2 原材料分类及编码规则表"]
    rules = []
    large_category = None
    seen: set[tuple[str, str]] = set()
    for row in ws.iter_rows(min_row=3, values_only=True):
        large_category = text(row[1]) or large_category
        prefix = text(row[4])
        pattern = text(row[5])
        if not prefix or not pattern or prefix == "/" or pattern == "/":
            continue
        key = (prefix, pattern)
        if key in seen:
            continue
        seen.add(key)
        rules.append({
            "item_type": "material",
            "large_category": large_category,
            "small_category": text(row[2]),
            "material_attribute": text(row[3]),
            "prefix": prefix,
            "pattern": pattern,
            "description": text(row[6]),
            "active": True,
            "sort_order": len(rules) + 1,
        })
    wb.close()
    return rules


def preflight() -> dict[str, Any]:
    records, relationships, report = read_legacy()
    relation_counter = Counter((row["parent_code"], row["child_code"]) for row in relationships)
    report.update({
        "unique_items": len(records),
        "unique_bom_lines": len(relation_counter),
        "duplicate_bom_rows_to_merge": sum(count - 1 for count in relation_counter.values()),
        "code_rules": len(read_code_rules()),
        "fatal": bool(report["unresolved_collisions"] or any(row["level"] == "error" for row in report["issues"])),
    })
    return report


def clear_business_data(db) -> None:  # type: ignore[no-untyped-def]
    for model in (
        models.ImportRow, models.ImportBatch, models.BOMLine,
        models.AlternativeMember, models.AlternativeGroup, models.CodeRuleSnapshot,
        models.CodeRule, models.Item,
    ):
        db.execute(delete(model))
    db.commit()


def apply_migration(reset: bool = False) -> dict[str, Any]:
    settings.ensure_directories()
    init_db()
    seed_admin()
    records, relationships, report = read_legacy()
    if report["unresolved_collisions"] or any(row["level"] == "error" for row in report["issues"]):
        raise RuntimeError("迁移预检存在未解决错误，请先查看报告")
    with SessionLocal() as db:
        existing = db.scalar(select(func.count()).select_from(models.Item)) or 0
        if existing and not reset:
            raise RuntimeError("数据库已有物料；如确认覆盖初始数据，请使用 --reset")
        if existing and reset:
            database = Path(settings.database_url.removeprefix("sqlite:///"))
            backup = settings.backup_dir / f"pre-migration-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.db"
            db.commit()
            shutil.copy2(database, backup)
            clear_business_data(db)
            report["pre_migration_backup"] = backup.name
        actor = db.scalar(select(models.User).where(models.User.username == "admin")) or db.scalar(select(models.User).order_by(models.User.id))
        item_by_code: dict[str, models.Item] = {}
        for record in records.values():
            body, version_label, version_number = services.parse_code(record["code"])
            item = models.Item(
                item_type=record["item_type"], code=record["code"], code_body=body,
                version_label=version_label, version_number=version_number, version_series=body,
                auxiliary_code=record["auxiliary_code"], name=record["name"],
                specification=record["specification"], source_type=record["source_type"],
                unit=record["unit"], remark=record["remark"],
                previous_version_name=record["previous_version_name"], invoice_name=record["invoice_name"],
                material_attribute=record["material_attribute"],
                key_component_code=record["auxiliary_code"] if record["item_type"] == "material" else None,
                is_formally_imported=True,
                requires_assembly=bool(record.get("requires_assembly")),
                status=None if record["item_type"] == "material" else "trial",
                created_by=actor.id if actor else None, updated_by=actor.id if actor else None,
            )
            db.add(item)
            item_by_code[record["code"]] = item
        db.flush()
        for record in records.values():
            if record.get("change_note"):
                item = item_by_code[record["code"]]
                services.audit(
                    db, actor.id if actor else None, "migrate_change_note", "item", item.id,
                    record["change_note"],
                    before={"change_note": record["change_note"]},
                    after={"message": "历史变更说明已保存到审计记录"},
                    batch_key="initial-change-note",
                )

        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for row in relationships:
            key = (row["parent_code"], row["child_code"])
            if key not in merged:
                merged[key] = {**row}
            else:
                merged[key]["quantity"] += row["quantity"]
                if row["line_remark"] and not merged[key]["line_remark"]:
                    merged[key]["line_remark"] = row["line_remark"]
        skipped = []
        transformed = []
        resolved: dict[tuple[str, str], dict[str, Any]] = {}
        children_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in merged.values():
            children_by_parent[row["parent_code"]].append(row)

        def add_resolved(row: dict[str, Any]) -> None:
            key = (row["parent_code"], row["child_code"])
            if key not in resolved:
                resolved[key] = {**row}
            else:
                resolved[key]["quantity"] += row["quantity"]

        def expand_to_materials(code: str, multiplier: Decimal, path: tuple[str, ...]) -> list[tuple[str, Decimal]]:
            if code in path:
                return []
            item = item_by_code[code]
            if item.item_type == "material":
                return [(code, multiplier)]
            expanded: list[tuple[str, Decimal]] = []
            for child_row in children_by_parent.get(code, []):
                expanded.extend(expand_to_materials(
                    child_row["child_code"], multiplier * child_row["quantity"], (*path, code)
                ))
            return expanded

        for row in merged.values():
            parent = item_by_code[row["parent_code"]]
            child = item_by_code[row["child_code"]]
            if parent.item_type == "material" and child.item_type != "material":
                leaves = expand_to_materials(row["child_code"], row["quantity"], (row["parent_code"],))
                if not leaves:
                    skipped.append({**row, "parent_type": parent.item_type, "child_type": child.item_type, "reason": "非原材料组件无法展开到叶子原材料"})
                    continue
                transformed.append({**row, "expanded_leaf_count": len(leaves)})
                for leaf_code, quantity in leaves:
                    add_resolved({**row, "child_code": leaf_code, "quantity": quantity, "line_remark": row["line_remark"] or f"历史迁移：由 {row['child_code']} 展开"})
                continue
            add_resolved(row)

        sort_orders: dict[str, int] = defaultdict(int)
        for row in resolved.values():
            parent = item_by_code[row["parent_code"]]
            child = item_by_code[row["child_code"]]
            if child.item_type not in services.ALLOWED_CHILDREN.get(parent.item_type, set()):
                skipped.append({**row, "parent_type": parent.item_type, "child_type": child.item_type, "reason": "父子类型规则不允许"})
                continue
            sort_orders[row["parent_code"]] += 1
            db.add(models.BOMLine(
                parent_item_id=parent.id, child_item_id=child.id, quantity=row["quantity"],
                sort_order=sort_orders[row["parent_code"]], line_remark=row["line_remark"],
            ))
        for rule in read_code_rules():
            db.add(models.CodeRule(**rule))
        db.flush()
        services.audit(
            db, actor.id if actor else None, "initial_migration", "database", None,
            "从历史 XLSM 建立 V1 初始数据库",
            after={"items": len(item_by_code), "bom_lines": len(resolved) - len(skipped), "transformed": len(transformed), "skipped": len(skipped)},
        )
        db.commit()
        report.update({
            "imported_items": len(item_by_code),
            "imported_bom_lines": len(resolved) - len(skipped),
            "transformed_nonmaterial_component_rows": len(transformed),
            "skipped_bom_lines": skipped,
            "imported_code_rules": len(read_code_rules()),
            "database": str(Path(settings.database_url.removeprefix("sqlite:///")).relative_to(PROJECT_ROOT)),
            "fatal": False,
        })
    write_report(report)
    return report


def write_report(report: dict[str, Any]) -> tuple[Path, Path]:
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = settings.report_dir / f"initial-migration-{stamp}.json"
    xlsx_path = settings.report_dir / f"initial-migration-{stamp}.xlsx"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    wb = Workbook()
    ws = wb.active
    ws.title = "迁移汇总"
    ws.append(["项目", "结果"])
    for key, value in report.items():
        if key not in {"issues", "skipped_bom_lines"}:
            ws.append([key, json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else str(value)])
    detail = wb.create_sheet("异常明细")
    detail.append(["级别", "工作表", "行号", "编码/父项", "子项", "说明"])
    for issue in [*report.get("issues", []), *report.get("skipped_bom_lines", [])]:
        detail.append([issue.get("level", "warning"), issue.get("sheet"), issue.get("row"), issue.get("code") or issue.get("parent_code"), issue.get("child_code"), issue.get("message") or issue.get("reason")])
    wb.save(xlsx_path)
    return json_path, xlsx_path


def main() -> None:
    parser = argparse.ArgumentParser(description="BOM V1.1 首次历史数据初始化")
    parser.add_argument("--apply", action="store_true", help="执行正式导入；默认仅预检")
    parser.add_argument("--reset", action="store_true", help="已有业务数据时先备份并清空后导入")
    args = parser.parse_args()
    report = apply_migration(reset=args.reset) if args.apply else preflight()
    if not args.apply:
        paths = write_report(report)
        report["reports"] = [str(path) for path in paths]
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
