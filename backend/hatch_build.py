"""Bundle shared repository fixtures in wheels and self-contained source archives."""
from pathlib import Path
from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self,version,build_data):
        root=Path(self.root)
        fixtures=root/"fixtures" if (root/"fixtures"/"manifest.json").is_file() else root.parent/"fixtures"
        if not (fixtures/"manifest.json").is_file():raise RuntimeError("Qualified support fixtures are missing")
        destination="support_workspace/sample_data" if self.target_name=="wheel" else "fixtures"
        build_data["force_include"][str(fixtures)]=destination
        if self.target_name=="sdist":
            integration=root/"firedrill" if (root/"firedrill").is_dir() else root.parent/"firedrill"
            # Include reviewed source files individually; installed Node packages,
            # private workspaces and credentials must never be force-included.
            for name in (".gitignore","README.md","adapter-runtime.mjs","adapter.test.mjs","package.json", "package-lock.json","request.py","scenario.json","simulate.mjs","target.mjs"):
                source=integration/name
                if source.is_file():build_data["force_include"][str(source)]="firedrill/"+name
