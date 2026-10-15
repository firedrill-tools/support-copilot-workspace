from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from support_workspace.agent import build_agent
from support_workspace.api import create_app
from support_workspace.store import Workspace, Conflict

FIXTURE = Path(__file__).parents[2] / "fixtures" / "starter.json"


def state(tmp_path):
    path = tmp_path / "workspace.json"
    path.write_text(FIXTURE.read_text())
    return Workspace(path)


def test_proposal_is_not_a_refund_and_approval_commits_matching_state(tmp_path):
    workspace = state(tmp_path)
    proposed = workspace.propose("case-104", 2999, "One damaged scanner")
    assert proposed["status"] == "open"
    assert workspace.case("case-104")["refunds"] == []
    committed = workspace.decide("case-104", proposed["revision"], "approve")
    assert committed["case"]["status"] == "refunded"
    assert committed["order"]["refunded_cents"] == 2999
    assert len(workspace.case("case-104")["refunds"]) == 1


def test_rejection_and_stale_revision(tmp_path):
    workspace = state(tmp_path)
    proposed = workspace.propose("case-104", 2999, "One damaged scanner")
    with pytest.raises(Conflict, match="changed"):
        workspace.decide("case-104", proposed["revision"] - 1, "approve")
    rejected = workspace.decide("case-104", proposed["revision"], "reject")
    assert rejected["case"]["status"] == "rejected"
    assert rejected["order"]["refunded_cents"] == 0
    with pytest.raises(Conflict):
        workspace.decide("case-104", rejected["case"]["revision"], "approve")


def test_order_rules_and_http_state(tmp_path):
    workspace = state(tmp_path)
    with pytest.raises(ValueError):
        workspace.propose("case-104", 100000, "Too much")
    proposed = workspace.propose("case-106", 1000, "A proposal to inspect")
    client = TestClient(create_app(workspace.path, include_agent=False))
    assert client.get("/cases/case-106").json()["case"]["proposal"]["amount_cents"] == 1000
    result = client.post("/cases/case-106/decision", json={"revision": proposed["revision"], "decision": "approve"})
    assert result.status_code == 409
    assert client.get("/cases/case-106").json()["order"]["refunded_cents"] == 0


def test_agent_key_boundary(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        build_agent(state(tmp_path))
