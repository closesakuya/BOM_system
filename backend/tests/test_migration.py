from __future__ import annotations

from backend.app.migration import preflight


def test_legacy_preflight_reconciles_source():
    report = preflight()
    assert report["fatal"] is False
    assert report["unique_items"] == 4845
    assert report["unique_bom_lines"] == 17799
    assert report["resolved_material_machine_collisions"] == 56
    assert report["duplicate_bom_rows_to_merge"] == 9
    assert report["code_rules"] == 81
