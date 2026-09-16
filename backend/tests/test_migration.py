from __future__ import annotations

import pytest
from backend.app.migration import preflight, LEGACY_PATH, RULE_PATH


def test_legacy_preflight_reconciles_source():
    if not LEGACY_PATH.is_file() or not RULE_PATH.is_file():
        pytest.skip('原始业务输入通过内部渠道单独提供')
    report = preflight()
    assert report["fatal"] is False
    if '(1)' in LEGACY_PATH.name:
        assert report["unique_items"] == 4845
        assert report["unique_bom_lines"] == 17799
    else:
        assert report["unique_items"] == 4925
        assert report["unique_bom_lines"] == 17949
        assert report["resolved_material_machine_collisions"] == 58
        assert report["duplicate_bom_rows_to_merge"] == 8
    assert report["code_rules"] == 81
