import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from ag_ui_langgraph import add_langgraph_fastapi_endpoint
from copilotkit import LangGraphAGUIAgent
from .agent import build_agent
from .store import Workspace, Conflict


class Decision(BaseModel):
    revision: int
    decision: str


def create_app(workspace_path: Path, include_agent: bool = True) -> FastAPI:
    workspace = Workspace(workspace_path)
    app = FastAPI(title="Support copilot workspace")
    app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("SUPPORT_WEB_ORIGIN", "http://localhost:3000")],
                       allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.get("/cases")
    def cases():
        return workspace.cases()

    @app.get("/cases/{case_id}")
    def case(case_id: str):
        try:
            return workspace.case(case_id)
        except KeyError:
            raise HTTPException(404, "unknown case")

    @app.post("/cases/{case_id}/decision")
    def decide(case_id: str, body: Decision):
        try:
            return workspace.decide(case_id, body.revision, body.decision)
        except KeyError:
            raise HTTPException(404, "unknown case")
        except Conflict as exc:
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    if include_agent:
        agent = build_agent(workspace)
        add_langgraph_fastapi_endpoint(
            app=app,
            agent=LangGraphAGUIAgent(name="support_agent", description="Support case copilot", graph=agent),
            path="/agent",
        )
    return app


def main():
    import uvicorn
    path = Path(os.getenv("SUPPORT_WORKSPACE_FILE", "../workspace.json"))
    uvicorn.run(create_app(path), host="127.0.0.1", port=8123)


if __name__ == "__main__":
    main()
