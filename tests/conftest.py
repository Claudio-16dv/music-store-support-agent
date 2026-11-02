from datetime import date

import pytest

from emporio import config
from emporio.data import StoreData
from emporio.tools import Toolbox

TODAY = date(2026, 3, 25)


@pytest.fixture(scope="session")
def store():
    return StoreData()


@pytest.fixture
def toolbox(store, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(config, "TICKETS_FILE", tmp_path / "tickets.jsonl")
    return Toolbox(store, clock=lambda: TODAY)
