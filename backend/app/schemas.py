from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ItemType = Literal["material", "semi_finished", "unit", "machine"]
ItemStatus = Literal["active", "trial", "disabled"]
SourceType = Literal["purchased", "outsourced", "self_made"]
RoleType = Literal["admin", "dev", "product", "guest", "maintainer", "viewer"]


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    department: str | None = None
    role: RoleType = "viewer"
    active: bool = True


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=80)
    display_name: str | None = None
    department: str | None = None
    role: RoleType | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    department: str | None
    role: str
    active: bool


class BOMComponentIn(BaseModel):
    child_item_id: int
    quantity: Decimal = Field(gt=0)
    sort_order: int = 0
    line_remark: str | None = None
    alternative_group_id: int | None = None


class ItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    copy_source_id: int | None = None

    item_type: ItemType
    code: str | None = Field(default=None, max_length=120)
    code_rule_id: int | None = None
    auxiliary_code: str | None = None
    name: str = Field(min_length=1, max_length=255)
    specification: str | None = None
    source_type: SourceType | None = None
    unit: str = "pcs"
    remark: str | None = None
    previous_version_name: str | None = None
    invoice_name: str | None = None
    material_attribute: str | None = None
    key_component_code: str | None = None
    machine_model: str | None = None
    is_formally_imported: bool = True
    requires_assembly: bool = False
    status: ItemStatus | None = None
    similarity_confirmed: bool = False
    reason: str = "新建物料"
    components: list[BOMComponentIn] = []


class ItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auxiliary_code: str | None = None
    name: str | None = None
    specification: str | None = None
    source_type: SourceType | None = None
    unit: str | None = None
    remark: str | None = None
    previous_version_name: str | None = None
    invoice_name: str | None = None
    material_attribute: str | None = None
    key_component_code: str | None = None
    machine_model: str | None = None
    requires_assembly: bool | None = None
    status: ItemStatus | None = None
    similarity_confirmed: bool = False
    reason: str = Field(min_length=1)


class PromoteMaterialIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=120)
    code_rule_id: int
    auxiliary_code: str | None = None
    name: str = Field(min_length=1, max_length=255)
    specification: str | None = None
    source_type: SourceType
    unit: str = "pcs"
    remark: str | None = None
    previous_version_name: str | None = None
    invoice_name: str | None = None
    material_attribute: str | None = None
    key_component_code: str | None = None
    similarity_confirmed: bool = False
    reason: str = Field(min_length=1)


class CopyItemIn(BaseModel):
    mode: Literal["new_version", "new_item"]
    code: str | None = None
    reason: str = Field(min_length=1)


class BOMLineCreate(BOMComponentIn):
    reason: str = Field(min_length=1)


class BOMLineUpdate(BaseModel):
    confirm_clear: bool = False
    quantity: Decimal | None = Field(default=None, gt=0)
    sort_order: int | None = None
    line_remark: str | None = None
    child_item_id: int | None = None
    alternative_group_id: int | None = None
    reason: str = Field(min_length=1)


class BOMLineReplaceIn(BaseModel):
    child_item_id: int
    reason: str = Field(min_length=1)
    confirm_clear: bool = False


class ReorderIn(BaseModel):
    line_ids: list[int]
    reason: str = "调整显示顺序"


class CodeRuleIn(BaseModel):
    item_type: ItemType
    large_category: str | None = None
    small_category: str | None = None
    material_attribute: str | None = None
    prefix: str
    pattern: str
    description: str | None = None
    active: bool = True
    sort_order: int = 0


class CodeRuleReplaceIn(BaseModel):
    rules: list[CodeRuleIn]
    reason: str = Field(min_length=1)


class CodeRuleUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_attribute: str | None = None
    description: str | None = None
    reason: str = Field(min_length=1)


class AlternativeGroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    item_type: Literal["material", "semi_finished", "unit"]
    default_item_id: int
    member_item_ids: list[int]
    member_market_shares: dict[int, Decimal] | None = None
    active: bool = True
    reason: str = Field(min_length=1)


class AlternativeSelectionIn(BaseModel):
    item_id: int
    alternative_group_id: int | None = None
    reason: str = Field(min_length=1)


class ImportCommitIn(BaseModel):
    row_ids: list[int]
    similarity_confirmed_row_ids: list[int] = []
    reason: str = "批量导入原材料"


class ImportRowEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cancelled: bool = False
    item_type: ItemType = "material"
    status: ItemStatus | None = None
    machine_model: str | None = None
    code_input: str | None = None
    auto_code: bool = False
    alias_errors: list[str] = []
    code: str | None = None
    code_rule_id: int | None = None
    large_category: str | None = None
    small_category: str | None = None
    auxiliary_code: str | None = None
    historical_item_code: str | None = None
    name: str | None = None
    specification: str | None = None
    source_type: SourceType | None = None
    unit: str = "pcs"
    remark: str | None = None
    previous_version_name: str | None = None
    invoice_name: str | None = None
    material_attribute: str | None = None
    key_component_code: str | None = None
    is_formally_imported: bool = True
    import_status_error: str | None = None


class MaintenancePreviewIn(BaseModel):
    source_item_id: int | None = None
    target_item_id: int | None = None
    operation: Literal["replace", "adjust", "add", "delete"]
    parent_item_ids: list[int]
    quantity: Decimal | None = Field(default=None, gt=0)


class MaintenanceApplyIn(MaintenancePreviewIn):
    reason: str = Field(min_length=1)
    confirm_clear: bool = False


class BackupIn(BaseModel):
    label: str | None = None
