import pytest
from bank_agent.data import seed


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "treasury.sqlite"
    monkeypatch.setenv("BANK_AGENT_DB", str(path))
    monkeypatch.setenv("BANK_AGENT_MODE", "local")
    seed(path)
    return path
