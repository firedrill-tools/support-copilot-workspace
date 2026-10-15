"""Verify wheel and source archive inputs/CLI outside the checkout, without keys."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from zipfile import ZipFile

wheel,=Path("dist").glob("*.whl")
source,=Path("dist").glob("*.tar.gz")
environment={key:value for key,value in os.environ.items() if not key.startswith(("OPENAI_","SUPPORT_"))}


def exercise(import_root,destination):
    script='''
from pathlib import Path
import sys
sys.path.insert(0,sys.argv[1])
from support_workspace import api
assert Path(api.__file__).is_relative_to(Path(sys.argv[1]))
assert api.main(["--list-cases"])==0
raise SystemExit(api.main(["--init-case","busy","--workspace",sys.argv[2]]))
'''
    checked=subprocess.run([sys.executable,"-c",script,str(import_root),str(destination)],cwd=import_root,
        env=environment,text=True,capture_output=True,check=True)
    listed,initialized=[json.loads(line) for line in checked.stdout.splitlines()]
    assert listed["case_count"]==8 and initialized["model_called"] is False
    state=json.loads(destination.read_text())
    assert len(state["cases"])==len(state["orders"])==18 and len(state["refunds"])==2


with TemporaryDirectory(prefix="support-package-") as directory:
    root=Path(directory)
    with ZipFile(wheel) as archive:
        assert "support_workspace/sample_data/manifest.json" in archive.namelist()
        assert len([name for name in archive.namelist() if name.startswith("support_workspace/sample_data/") and name.endswith(".json")])==9
        archive.extractall(root/"wheel")
    exercise(root/"wheel",root/"wheel-state.json")
    with tarfile.open(source) as archive:archive.extractall(root/"source",filter="data")
    project,=(root/"source").iterdir()
    assert (project/"hatch_build.py").is_file() and (project/"fixtures/manifest.json").is_file()
    exercise(project/"src",root/"source-state.json")
print("Wheel and source archive validate all eight cases and initialize busy state outside the checkout; no model called.")
