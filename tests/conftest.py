import csv
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tools as agent_tools
import loop as agent_loop

@pytest.fixture
def tools(monkeypatch):
    agent_tools.FAULTS.clear()
    monkeypatch.setattr(agent_tools, "_sleep", lambda *_: None)
    yield agent_tools
    agent_tools.FAULTS.clear()

@pytest.fixture
def session(tmp_path, tools):
    csv_path = tmp_path / "statement.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["account_id", "op_id", "date", "amount_rub", "merchant", "category"])
        w.writerows([
            ("mine", "s1", "2026-08-05", "100", "Video Service", "subscription"),
            ("mine", "s2", "2026-09-05", "100", "Video Service", "subscription"),
            ("mine", "s3", "2026-10-05", "100", "Video Service", "subscription"),
            ("mine", "s4", "2026-08-10", "200", "Video Service", "subscription"),
            ("mine", "s5", "2026-09-10", "200", "Video Service", "subscription"),
            ("mine", "s6", "2026-10-10", "200", "Video Service", "subscription"),
            ("mine", "t1", "2026-10-12", "250", "Yandex Go", "taxi"),
            ("mine", "t2", "2026-10-12", "250", "Yandex Go", "taxi"),
            ("mine", "n1", "2026-10-13", "-1000", "Incoming transfer", "transfer"),
            ("other", "o1", "2026-10-13", "900000", "Secret", "food"),
        ])
    return tools.Session(account_id="mine", statement_path=csv_path)

@pytest.fixture
def loop():
    return agent_loop
