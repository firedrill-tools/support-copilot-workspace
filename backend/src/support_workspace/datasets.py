"""Verified fictional starting state; initialization is local and model-free."""
from hashlib import sha256
import json
import os
from pathlib import Path
from .contracts import WorkspaceData

DATASET,VERSION="northstar-support-workspace","1.0.0"
PROFILES={"starter","busy","ambiguous","boundary"}


def fixture_root():
    bundled=Path(__file__).parent/"sample_data"
    if bundled.is_dir():return bundled
    project=Path(__file__).resolve().parents[2]
    return project/"fixtures" if (project/"fixtures"/"manifest.json").is_file() else project.parent/"fixtures"


def bounded(path,limit):
    with path.open("rb") as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError("Dataset file exceeds size limit")
    return raw


def load_cases(root=None):
    root=Path(root or fixture_root()).resolve()
    path=(root/"manifest.json").resolve()
    if not path.is_relative_to(root):raise ValueError("Manifest escapes dataset root")
    manifest=json.loads(bounded(path,128*1024))
    if (manifest.get("dataset"),manifest.get("version"))!=(DATASET,VERSION):raise ValueError("Unqualified dataset identity/version")
    entries=manifest.get("cases")
    if not isinstance(entries,list) or not 1<=len(entries)<=100:raise ValueError("Dataset requires 1–100 cases")
    seen,result=set(),[]
    for entry in entries:
        case_id,profile=entry["case_id"],entry["profile"]
        if not isinstance(case_id,str) or not case_id or case_id in seen or profile not in PROFILES:raise ValueError("Duplicate identity or unknown profile")
        seen.add(case_id)
        relative=Path(entry["workspace"]);path=(root/relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(root):raise ValueError("Workspace escapes dataset root")
        raw=bounded(path,512*1024)
        if sha256(raw).hexdigest()!=entry["sha256"]:raise ValueError("Workspace digest drift")
        data=json.loads(raw);parsed=WorkspaceData.model_validate(data)
        if data.get("dataset")!={"id":DATASET,"version":VERSION,"profile":profile,"case_id":case_id,"history_origin":"synthetic_business_state"}:raise ValueError("Embedded dataset identity differs")
        if not any(case.id==entry["selected_case"] for case in parsed.cases):raise ValueError("Unknown selected case")
        if any(not item.email.endswith(".example") for item in parsed.cases) or any(not item.customer_email.endswith(".example") for item in parsed.orders):raise ValueError("Dataset must use fictional addresses")
        if data.get("agent_observations") or data.get("provider_observations"):raise ValueError("Starting business state cannot claim fresh model observations")
        if profile=="busy" and (len(parsed.cases)<18 or len(parsed.orders)<18 or len(parsed.refunds)<2):raise ValueError("Busy profile requires population and prior work")
        if not isinstance(entry.get("prompt"),str) or not entry["prompt"].strip():raise ValueError("Case needs a prompt")
        result.append({**entry,"bytes":raw})
    if {entry["profile"] for entry in result}!=PROFILES:raise ValueError("All four profiles are required")
    return result


def list_cases(root=None):
    cases=load_cases(root)
    return {"dataset":DATASET,"version":VERSION,"case_count":len(cases),"cases":[{key:value for key,value in entry.items() if key!="bytes"} for entry in cases]}


def initialize_case(case_id,path,*,root=None):
    case=next((entry for entry in load_cases(root) if entry["case_id"]==case_id),None)
    if case is None:raise ValueError(f"Unknown case: {case_id}")
    path=Path(path).absolute();path.parent.mkdir(parents=True,exist_ok=True)
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(descriptor,"wb") as stream:stream.write(case["bytes"])
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"dataset":DATASET,"version":VERSION,"case_id":case_id,"workspace":str(path),"sha256":case["sha256"],
            "selected_case":case["selected_case"],"prompt":case["prompt"],"reset_coverage":"local_json_only","model_called":False}
