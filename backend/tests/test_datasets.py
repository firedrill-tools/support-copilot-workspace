from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil

from fastapi.testclient import TestClient
import pytest
from support_workspace.api import create_app,main
from support_workspace.datasets import fixture_root,initialize_case,load_cases
from support_workspace.store import Workspace,Conflict


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):monkeypatch.delenv("OPENAI_API_KEY",raising=False)


def test_generator_and_model_free_cli_reproduce_every_qualified_byte(tmp_path,capsys):
    spec=importlib.util.spec_from_file_location("generator",Path(__file__).parents[2]/"scripts/build_fixtures.py")
    generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator);generator.build(tmp_path)
    for path in fixture_root().glob("*.json"):assert path.read_bytes()==(tmp_path/path.name).read_bytes()
    assert main(["--list-cases"])==0
    listed=json.loads(capsys.readouterr().out)
    assert listed["version"]=="1.0.0" and listed["case_count"]==8
    assert {entry["profile"] for entry in listed["cases"]}=={"starter","busy","ambiguous","boundary"}


@pytest.mark.parametrize("case",load_cases(),ids=lambda entry:entry["case_id"])
def test_all_initialized_profiles_have_coherent_readable_state_and_approval_boundaries(tmp_path,case):
    path=tmp_path/"workspace.json";result=initialize_case(case["case_id"],path)
    assert path.read_bytes()==case["bytes"] and path.stat().st_mode & 0o777==0o600
    assert result["model_called"] is False and result["reset_coverage"]=="local_json_only"
    workspace=Workspace(path);original=json.loads(path.read_text())
    with TestClient(create_app(path,include_agent=False)) as client:
        selected=client.get(f"/cases/{case['selected_case']}").json()
        assert selected["case"]["id"]==case["selected_case"]
        assert len(client.get("/cases").json())==len(original["cases"])
        if case["case_id"]=="investigate-charge":
            assert "investigate" in selected["case"]["message"].lower() and path.read_bytes()==case["bytes"]
        elif case["case_id"] in {"already-refunded","exhausted-balance"}:
            with pytest.raises((Conflict,ValueError)):workspace.propose("case-104",2999,"Controlled offline proposal")
            assert path.read_bytes()==case["bytes"]
        else:
            if case["case_id"]=="changed-currency":proposal=selected["case"]
            else:proposal=workspace.propose("case-104",2999,"Controlled offline proposal")
            response=client.post("/cases/case-104/decision",json={"revision":proposal["revision"],"decision":"approve"})
            if case["case_id"] in {"identity-conflict","changed-currency"}:
                assert response.status_code==409 and workspace.case("case-104")["refunds"]==[]
            else:
                assert response.status_code==200
                assert workspace.case("case-104")["order"]["refunded_cents"]==2999
                final=json.loads(path.read_text())
                assert final["refunds"][:-1]==original["refunds"]
                assert final["cases"][1:]==original["cases"][1:] and final["orders"][1:]==original["orders"][1:]
        assert workspace.evidence("any-thread")["provider_observations"]==[]


@pytest.mark.parametrize("fault",["drift","escape","duplicate","relationship"])
def test_drift_escape_or_broken_identity_prevents_any_reset_output(tmp_path,fault):
    root=tmp_path/"fixtures";shutil.copytree(fixture_root(),root)
    manifest=json.loads((root/"manifest.json").read_text());entry=manifest["cases"][0];path=root/entry["workspace"]
    if fault=="drift":path.write_text("{}")
    elif fault=="escape":
        outside=tmp_path/"outside.json";outside.write_bytes(path.read_bytes());path.unlink();path.symlink_to(outside)
    elif fault=="duplicate":manifest["cases"][1]["case_id"]=entry["case_id"]
    else:
        data=json.loads(path.read_text());data["cases"][0]["order_id"]="unknown-order"
        raw=json.dumps(data).encode();path.write_bytes(raw);entry["sha256"]=sha256(raw).hexdigest()
    (root/"manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):initialize_case("starter",tmp_path/"output.json",root=root)
    assert not (tmp_path/"output.json").exists()


def test_cli_initialization_is_exclusive_and_requires_an_explicit_new_path(tmp_path,capsys):
    path=tmp_path/"state.json"
    assert main(["--init-case","busy","--workspace",str(path)])==0
    assert json.loads(capsys.readouterr().out)["case_id"]=="busy"
    before=path.read_bytes()
    with pytest.raises(FileExistsError):initialize_case("starter",path)
    assert path.read_bytes()==before
    with pytest.raises(SystemExit) as error:main(["--init-case","starter"])
    assert error.value.code==2
