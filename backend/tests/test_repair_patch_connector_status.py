import pytest

from app.missions.repair_patch_connector import (
    MissionRepairPatchConnectorError,
    _validate_request,
)


def _request(status):
    return {
        "status": status,
        "auto_apply": False,
        "patch_applied": False,
        "edits": [
            {
                "operation": "REPLACE_UNIQUE",
                "path": "src/calculator.py",
                "old_text": "return a + b",
                "new_text": "return a * b",
            }
        ],
    }


def test_patch_connector_accepts_edit_connected_status():
    _validate_request(
        _request(
            "AWAITING_REPAIR_PATCH_CHECK"
        )
    )


def test_patch_connector_keeps_requested_compatible():
    _validate_request(
        _request("REQUESTED")
    )


def test_patch_connector_rejects_unrelated_status():
    with pytest.raises(
        MissionRepairPatchConnectorError
    ):
        _validate_request(
            _request("REPAIR_FAILED")
        )
