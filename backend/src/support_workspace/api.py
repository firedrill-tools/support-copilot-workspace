import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from ag_ui_langgraph import add_langgraph_fastapi_endpoint
from copilotkit import LangGraphAGUIAgent
from .runtime import AgentRuntime
from .evidence import execution_scope
from .store import Workspace, Conflict


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(strict=True,ge=0)
    decision: Literal["approve","reject"]


class RuntimeAgent(LangGraphAGUIAgent):
    """Keep native per-request clones and correlate their model transport events."""
    def __init__(self, *, runtime, name, graph, description=None, config=None):
        self.runtime = runtime
        super().__init__(name=name,graph=graph,description=description,config=config)

    def clone(self):
        return type(self)(runtime=self.runtime,name=self.name,graph=self.graph,description=self.description,
                          config=dict(self.config) if self.config else None)

    async def run(self,input):
        # The in-memory checkpointer has one owning event loop. Serialize whole
        # chat runs; REST decisions still use the workspace's revision checks.
        async with self.runtime.run_lock:
            with execution_scope(input.thread_id,input.run_id):
                async for event in super().run(input):
                    yield event


def create_app(workspace_path: Path, include_agent: bool = True, *, runtime_factory=None) -> FastAPI:
    workspace = Workspace(workspace_path)
    @asynccontextmanager
    async def lifespan(app):
        if not include_agent:
            yield
            return
        async with (runtime_factory or AgentRuntime)(workspace) as runtime:
            app.state.runtime = runtime
            before = {id(route) for route in app.router.routes}
            try:
                add_langgraph_fastapi_endpoint(app=app,
                    agent=RuntimeAgent(runtime=runtime,name="support_agent",description="Support case copilot",graph=runtime.graph),path="/agent")
                app.openapi_schema = None
                yield
            finally:
                # A fresh lifespan must never dispatch through a previous closed
                # model client or retained conversation graph.
                app.router.routes[:] = [route for route in app.router.routes if id(route) in before]
                app.openapi_schema = None

    app = FastAPI(title="Support copilot workspace",lifespan=lifespan)
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

    @app.get("/evidence/{thread_id}")
    def evidence(thread_id: str,run_id: str | None=None):
        return workspace.evidence(thread_id,run_id)
    return app


def main(argv=None):
    import argparse
    import json
    parser=argparse.ArgumentParser(description="Run the local support workspace API")
    selection=parser.add_mutually_exclusive_group()
    selection.add_argument("--list-cases",action="store_true")
    selection.add_argument("--init-case",metavar="CASE")
    parser.add_argument("--workspace",type=Path)
    parser.add_argument("--port",type=int,default=8123)
    args=parser.parse_args(argv)
    if args.list_cases or args.init_case:
        if args.init_case and args.workspace is None:parser.error("--init-case requires --workspace with a fresh path")
        from .datasets import initialize_case,list_cases
        try:result=list_cases() if args.list_cases else initialize_case(args.init_case,args.workspace)
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
        print(json.dumps(result))
        return 0
    import uvicorn
    path = args.workspace or Path(os.getenv("SUPPORT_WORKSPACE_FILE", "../workspace.json"))
    uvicorn.run(create_app(path), host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
