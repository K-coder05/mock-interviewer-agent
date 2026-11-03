from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.harness import LiveSessionHarness
from tests.report_harness import ReportHarness


@pytest.fixture
async def harness(tmp_path: Path) -> AsyncIterator[LiveSessionHarness]:
    h = LiveSessionHarness(db_path=tmp_path / "test.db")
    yield h
    await h.aclose()


@pytest.fixture
async def reports(tmp_path: Path) -> AsyncIterator[ReportHarness]:
    h = ReportHarness(db_path=tmp_path / "reports.db")
    yield h
    await h.aclose()
