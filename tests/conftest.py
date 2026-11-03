from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.harness import LiveSessionHarness


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[LiveSessionHarness]:
    h = LiveSessionHarness(db_path=tmp_path / "test.db")
    yield h
    h.close()
