from pathlib import Path
from copy import deepcopy
import json
import pytest
from fastapi.testclient import TestClient
from support_workspace.runtime import AgentRuntime
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
        AgentRuntime(state(tmp_path))


@pytest.mark.parametrize("change",["currency","customer","order"])
def test_changed_proposal_scope_cannot_commit_a_different_refund(tmp_path,change):
    workspace=state(tmp_path)
    proposal=workspace.propose("case-104",2999,"One damaged scanner")
    data=json.loads(workspace.path.read_text())
    if change=="currency":data["orders"][0]["currency"]="CAD"
    elif change=="customer":data["orders"][0]["customer_email"]=data["cases"][0]["email"]="another@harbor.example"
    else:
        other={**data["orders"][0],"id":"order-200"}
        data["orders"].append(other)
        data["cases"][0]["order_id"]="order-200"
    workspace.path.write_text(json.dumps(data))
    before=workspace.path.read_bytes()
    with pytest.raises(Conflict,match="create a fresh proposal"):
        workspace.decide("case-104",proposal["revision"],"approve")
    assert workspace.path.read_bytes()==before and workspace.case("case-104")["refunds"]==[]


@pytest.mark.parametrize("amount",[True,1.5,-1])
def test_invalid_minor_unit_amount_cannot_create_a_proposal(tmp_path,amount):
    workspace=state(tmp_path);before=workspace.path.read_bytes()
    with pytest.raises(ValueError,match="positive integer"):
        workspace.propose("case-104",amount,"Invalid amount")
    assert workspace.path.read_bytes()==before


def test_identical_proposal_replay_preserves_displayed_revision_and_file(tmp_path):
    workspace=state(tmp_path)
    first=workspace.propose("case-104",2999,"One damaged scanner")
    before=workspace.path.read_bytes()
    again=workspace.propose("case-104",2999,"One damaged scanner")
    assert first==again and workspace.path.read_bytes()==before


def test_unknown_legacy_proposal_scope_needs_a_new_proposal_but_can_be_rejected(tmp_path):
    workspace=state(tmp_path)
    proposal=workspace.propose("case-104",2999,"One damaged scanner")
    data=json.loads(workspace.path.read_text());data["cases"][0]["proposal"].pop("binding")
    workspace.path.write_text(json.dumps(data))
    with pytest.raises(Conflict,match="create a fresh proposal"):
        workspace.decide("case-104",proposal["revision"],"approve")
    rejected=workspace.decide("case-104",proposal["revision"],"reject")
    assert rejected["case"]["status"]=="rejected" and workspace.case("case-104")["refunds"]==[]


def test_imported_noncontiguous_refund_id_is_preserved_without_collision(tmp_path):
    workspace=state(tmp_path)
    data=json.loads(workspace.path.read_text())
    refund={"id":"refund-002","case_id":"case-105","order_id":"order-105","amount_cents":12900,"currency":"USD"}
    data["refunds"].append(refund)
    data["orders"][1]["refunded_cents"]=12900
    data["cases"][1].update(status="refunded",resolution=refund)
    prior=deepcopy(data)
    workspace.path.write_text(json.dumps(data))
    proposal=workspace.propose("case-104",2999,"One damaged scanner")
    result=workspace.decide("case-104",proposal["revision"],"approve")
    assert result["case"]["resolution"]["id"]=="refund-003"
    final=json.loads(workspace.path.read_text())
    assert final["refunds"][0]==refund and final["cases"][1]==prior["cases"][1] and final["orders"][1]==prior["orders"][1]


def test_failed_publication_leaves_original_workspace_and_removes_private_stage(tmp_path,monkeypatch):
    workspace=state(tmp_path);before=workspace.path.read_bytes()
    def fail(*args):raise OSError("controlled publication failure")
    monkeypatch.setattr("support_workspace.store.os.replace",fail)
    with pytest.raises(OSError,match="publication failure"):
        workspace.propose("case-104",2999,"One damaged scanner")
    assert workspace.path.read_bytes()==before
    assert list(tmp_path.glob(".workspace.json.*.tmp"))==[]


@pytest.mark.parametrize("body",[{"revision":True,"decision":"approve"},{"revision":1.5,"decision":"approve"},
                                {"revision":2,"decision":"approve","extra":"unexpected"}])
def test_http_decision_rejects_ambiguous_revision_or_extra_input(tmp_path,body):
    workspace=state(tmp_path);workspace.propose("case-104",2999,"One damaged scanner")
    before=workspace.path.read_bytes()
    with TestClient(create_app(workspace.path,include_agent=False)) as client:
        assert client.post("/cases/case-104/decision",json=body).status_code==422
    assert workspace.path.read_bytes()==before
