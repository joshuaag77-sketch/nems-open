"""Test speed-ups: module markers, and year-level parallelism under pytest-xdist.

Markers (select with -m): comm, resd, tran, ind by file name; `slow` for the heavy files.
Run with `-n auto --dist loadgroup`. Tests of one file stay on one worker (they share module
caches), except in files that set XDIST_BY_YEAR = True: there every year is independent,
so each year is its own group and the 9 test years spread across the workers. Tests that
use the `full_run` fixture (the chained residential year driver, about 3 minutes) get their own group.
"""

import pytest

MODULES = {"commercial": "comm", "residential": "resd", "tran": "tran", "industrial": "ind"}
SLOW_FILES = {"test_commercial_distgen", "test_commercial_technology_choice", "test_residential_chain"}


def pytest_collection_modifyitems(config, items):
    for item in items:
        name = item.module.__name__.rsplit(".", 1)[-1]
        for key, marker in MODULES.items():
            if name.startswith(f"test_{key}"):
                item.add_marker(getattr(pytest.mark, marker))
        if name in SLOW_FILES:
            item.add_marker(pytest.mark.slow)
        year = item.callspec.params.get("y") if hasattr(item, "callspec") else None
        group = f"{name}-{year}" if year is not None and getattr(item.module, "XDIST_BY_YEAR", False) else name
        if "full_run" in item.fixturenames:      # the all-years chain runs once, in sequence, on one worker
            group = f"{name}-full"
        item.add_marker(pytest.mark.xdist_group(group))
