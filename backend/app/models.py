from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120))
    department: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), default="viewer", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Item(Base, TimestampMixin):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_type: Mapped[str] = mapped_column(String(20), index=True)
    code: Mapped[str] = mapped_column(String(120), index=True)
    code_body: Mapped[str] = mapped_column(String(100), index=True)
    version_label: Mapped[str] = mapped_column(String(20))
    version_number: Mapped[int] = mapped_column(Integer, default=0)
    version_series: Mapped[str] = mapped_column(String(120), index=True)
    auxiliary_code: Mapped[str | None] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    specification: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(String(20), index=True)
    unit: Mapped[str] = mapped_column(String(30), default="pcs")
    remark: Mapped[str | None] = mapped_column(Text)
    previous_version_name: Mapped[str | None] = mapped_column(String(255))
    invoice_name: Mapped[str | None] = mapped_column(String(255))
    material_attribute: Mapped[str | None] = mapped_column(String(255))
    key_component_code: Mapped[str | None] = mapped_column(String(120), index=True)
    historical_item_code: Mapped[str | None] = mapped_column(String(120), index=True)
    machine_model: Mapped[str | None] = mapped_column(String(80), index=True)
    is_formally_imported: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    unofficial_status: Mapped[str | None] = mapped_column(String(20), index=True)
    requires_assembly: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str | None] = mapped_column(String(20), index=True)
    copied_from_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    copied_from: Mapped[Item | None] = relationship(remote_side="Item.id", foreign_keys=[copied_from_id])

    __table_args__ = (
        CheckConstraint(
            "item_type = 'material' OR is_formally_imported = 1",
            name="ck_unofficial_only_material",
        ),
        CheckConstraint(
            "(is_formally_imported = 1 AND unofficial_status IS NULL) OR "
            "(is_formally_imported = 0 AND unofficial_status IN ('pending', 'archived'))",
            name="ck_unofficial_status",
        ),
        CheckConstraint(
            "is_formally_imported = 1 OR code GLOB '99.[0-9][0-9][0-9][0-9].[0-9]'",
            name="ck_unofficial_code_range",
        ),
        CheckConstraint(
            "NOT (is_formally_imported = 1 AND code GLOB '99.[0-9][0-9][0-9][0-9].[0-9]')",
            name="ck_formal_code_outside_unofficial_range",
        ),
        Index(
            "uq_item_official_code",
            "code",
            unique=True,
            sqlite_where=text("is_formally_imported = 1"),
        ),
        Index(
            "uq_item_official_series_version",
            "version_series",
            "version_number",
            unique=True,
            sqlite_where=text("is_formally_imported = 1"),
        ),
        Index(
            "uq_item_unofficial_code",
            "code",
            unique=True,
            sqlite_where=text("is_formally_imported = 0"),
        ),
        Index("ix_item_name_spec", "name", "specification"),
    )


class CodeSequence(Base):
    __tablename__ = "code_sequences"

    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, default=0)


class PathAlternative(Base, TimestampMixin):
    """A configuration owned by a root, addressed by stable BOM line IDs."""
    __tablename__ = "path_alternatives"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    line_path: Mapped[str] = mapped_column(String(1000))
    mode: Mapped[str] = mapped_column(String(20), default="custom")
    selected_item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    members_json: Mapped[str] = mapped_column(Text, default="[]")
    __table_args__ = (UniqueConstraint("owner_item_id", "line_path", name="uq_path_alternative"),)


class DeletedMaterialPromotion(Base):
    """Immutable target description kept when a promoted material is deleted."""
    __tablename__ = "deleted_material_promotions"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    target_item_id: Mapped[int] = mapped_column(Integer)
    target_code: Mapped[str] = mapped_column(String(120))
    target_name: Mapped[str] = mapped_column(String(255))
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MaterialPromotionLink(Base):
    __tablename__ = "material_promotion_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), unique=True, index=True)
    target_item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    is_historical: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CodeRule(Base, TimestampMixin):
    __tablename__ = "code_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_type: Mapped[str] = mapped_column(String(20), index=True)
    large_category: Mapped[str | None] = mapped_column(String(255))
    small_category: Mapped[str | None] = mapped_column(String(255))
    material_attribute: Mapped[str | None] = mapped_column(String(255))
    prefix: Mapped[str] = mapped_column(String(80), index=True)
    pattern: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("item_type", "prefix", "pattern", name="uq_code_rule_pattern"),
    )


class CodeRuleSnapshot(Base):
    __tablename__ = "code_rule_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    rules_json: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlternativeGroup(Base, TimestampMixin):
    __tablename__ = "alternative_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    item_type: Mapped[str] = mapped_column(String(20), index=True)
    default_item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AlternativeMember(Base, TimestampMixin):
    __tablename__ = "alternative_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("alternative_groups.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    market_share: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"))

    __table_args__ = (UniqueConstraint("group_id", "item_id", name="uq_alternative_member"),)


class BOMLine(Base, TimestampMixin):
    __tablename__ = "bom_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    child_item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("1"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    line_remark: Mapped[str | None] = mapped_column(Text)
    alternative_group_id: Mapped[int | None] = mapped_column(ForeignKey("alternative_groups.id"))

    parent: Mapped[Item] = relationship(foreign_keys=[parent_item_id])
    child: Mapped[Item] = relationship(foreign_keys=[child_item_id])

    __table_args__ = (
        UniqueConstraint("parent_item_id", "child_item_id", name="uq_bom_parent_child"),
        Index("ix_bom_parent_sort", "parent_item_id", "sort_order"),
    )


class ImportBatch(Base, TimestampMixin):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="preview", index=True)
    stats_json: Mapped[str] = mapped_column(Text, default="{}")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class ImportRow(Base, TimestampMixin):
    __tablename__ = "import_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), index=True)
    similarity_json: Mapped[str] = mapped_column(Text, default="[]")
    error_message: Mapped[str | None] = mapped_column(Text)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    decision: Mapped[str | None] = mapped_column(String(30))

    __table_args__ = (UniqueConstraint("batch_id", "row_number", name="uq_import_batch_row"),)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(50), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, index=True)
    reason: Mapped[str] = mapped_column(Text)
    batch_key: Mapped[str | None] = mapped_column(String(80), index=True)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
