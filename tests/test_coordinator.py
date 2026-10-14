"""When the mower counts as away from the dock (GPS tracking runs only then)."""
from __future__ import annotations

import pytest

from custom_components.imow_v2.coordinator import ImowCoordinator


@pytest.mark.parametrize(
    ("activity", "docked", "away"),
    [
        ("error", True, False),     # wire fault on the dock: no tracking
        ("error", False, True),     # stuck on the lawn: track it
        ("locked", True, False),
        ("locked", False, True),
        ("mowing", True, True),     # isDocked can lag during a job; activity wins
        ("returning", False, True),
        ("paused", False, True),
        ("docked", True, False),
        ("charging", True, False),
        ("busy", False, True),
        ("busy", True, False),
        ("offline", False, False),
    ],
)
def test_is_away(activity: str, docked: bool, away: bool) -> None:
    mower = {"_activity": activity, "device": {"isDocked": docked}}
    assert ImowCoordinator._is_away(None, mower) is away
