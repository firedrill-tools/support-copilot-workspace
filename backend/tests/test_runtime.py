"""Native transport evidence, interruption, ownership and lifespan recovery."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from threading import Event

import httpx2
from fastapi.testclient import TestClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from openai import OpenAI, AsyncOpenAI
import pytest

from support_workspace import runtime as runtime_module
from support_workspace.agent import build_agent
from support_workspace.api import create_app
from support_workspace.completion import ResponseBoundaryError
from support_workspace.runtime import AgentRuntime
from test_agent import native, Script, choice, FINAL, USAGE, invoke
from test_workspace import state


def request(run_id="agui-run",thread_id="agui-thread"):
    return {"threadId":thread_id,"runId":run_id,"state":{},
        "messages":[{"id":f"user-{run_id}","role":"user","content":"Inspect case-104 and prepare the damaged scanner proposal."}],
        "tools":[],"context":[],"forwardedProps":{}}


def events(response):
    assert response.status_code==200
    return [json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")]


def application(workspace,script):
    return create_app(workspace.path,runtime_factory=lambda workspace:AgentRuntime(workspace,sync_transport=script,async_transport=script))


@pytest.mark.parametrize("stream",[False,True])
@pytest.mark.parametrize("usage,complete",[(None,False),({},False),({"prompt_tokens":20},False),
                                         ({"prompt_tokens":0,"completion_tokens":0,"total_tokens":0},True)])
def test_actual_sdk_keeps_raw_missing_partial_and_zero_usage_distinct(tmp_path,native,stream,usage,complete):
    workspace=state(tmp_path);script=native([FINAL],usage=usage)
    if stream:
        with TestClient(application(workspace,script)) as client:
            types=[item["type"] for item in events(client.post("/agent",json=request()))]
            assert "RUN_FINISHED" in types and "RUN_ERROR" not in types
            evidence=client.get("/evidence/agui-thread",params={"run_id":"agui-run"}).json()
    else:
        invoke(workspace,script)
        evidence=workspace.evidence("synthetic-thread","synthetic-run")
    provider=evidence["provider_observations"][0]
    assert evidence["http_attempts"]==1 and evidence["usage_complete"] is complete,provider
    assert provider["reported_usage"]==usage and provider["stream"] is stream
    assert (evidence["usage"] is not None) is complete and evidence["cost_usd"] is None
    assert evidence["agent_observations"][0]["provider_observation_id"]==provider["id"]


def test_no_done_marker_rejects_valid_tool_output_and_next_turn_recovers(tmp_path,native):
    workspace=state(tmp_path);script=native([choice(),choice(),FINAL],done=False)
    with TestClient(application(workspace,script)) as client:
        types=[item["type"] for item in events(client.post("/agent",json=request("bad-run")))]
        assert "RUN_ERROR" in types and "RUN_FINISHED" not in types
        assert workspace.case("case-104")["case"]["proposal"] is None
        script.done=True
        assert "RUN_FINISHED" in [item["type"] for item in events(client.post("/agent",json=request("retry-run")))]
        bad=client.get("/evidence/agui-thread",params={"run_id":"bad-run"}).json()
        good=client.get("/evidence/agui-thread",params={"run_id":"retry-run"}).json()
    assert len(script.requests)==3 and good["http_attempts"]==2 and bad["http_attempts"]==1
    assert bad["agent_observations"][0]["protocol_error"]=="transport_did_not_complete"
    assert not any(item.get("tool_calls") for item in json.loads(script.requests[1].content)["messages"])
    assert workspace.case("case-104")["refunds"]==[]


class SplitStream(httpx2.SyncByteStream,httpx2.AsyncByteStream):
    def __init__(self,raw,*,fail=False):
        self.parts=[raw[index:index+7] for index in range(0,len(raw),7)]
        self.fail,self.closed=fail,False
    def __iter__(self):
        yield from self.parts
        if self.fail:raise httpx2.ReadError("controlled stream interruption")
    async def __aiter__(self):
        for part in self.parts:yield part
        if self.fail:raise httpx2.ReadError("controlled stream interruption")
    def close(self):self.closed=True
    async def aclose(self):self.closed=True


def test_fragmented_compressed_crlf_sse_reaches_actual_sdk_and_retains_usage(tmp_path,native):
    workspace=state(tmp_path);base=native([FINAL])
    opened=[]
    def handle(request):
        response=base.handle(request)
        raw=response.content.decode().replace("\n","\r\n").encode()
        body=SplitStream(gzip.compress(raw));opened.append(body)
        return httpx2.Response(200,stream=body,headers={"content-type":"text/event-stream","content-encoding":"gzip"})
    transport=httpx2.MockTransport(handle)
    with TestClient(application(workspace,transport)) as client:
        assert "RUN_FINISHED" in [item["type"] for item in events(client.post("/agent",json=request()))],workspace.evidence("agui-thread","agui-run")["provider_observations"]
    provider=workspace.evidence("agui-thread","agui-run")["provider_observations"][0]
    assert provider["done_marker"] and provider["reported_usage"]==USAGE and provider["capture_error"] is None
    assert opened[0].closed


def test_stream_failure_after_reported_usage_keeps_measurement_without_dispatch(tmp_path,native):
    workspace=state(tmp_path);base=native([choice()],done=False);opened=[]
    def handle(request):
        response=base.handle(request)
        body=SplitStream(response.content,fail=True);opened.append(body)
        return httpx2.Response(200,stream=body,headers={"content-type":"text/event-stream"})
    transport=httpx2.MockTransport(handle)
    app=application(workspace,transport)
    with TestClient(app) as client:
        types=[item["type"] for item in events(client.post("/agent",json=request()))]
        assert "RUN_ERROR" in types and "RUN_FINISHED" not in types
        assert workspace.case("case-104")["case"]["proposal"] is None
    provider=workspace.evidence("agui-thread","agui-run")["provider_observations"][0]
    assert provider["error_type"]=="ReadError" and provider["reported_usage"]==USAGE
    assert provider["usage_complete"] and not provider["done_marker"]
    assert len(base.requests)==1 and opened[0].closed and app.state.runtime.closed


@pytest.mark.parametrize("failure",["http","connection"])
def test_provider_failure_is_one_attempt_and_unknown_usage_survives_shutdown(tmp_path,native,failure):
    workspace=state(tmp_path);native([FINAL]);requests=[]
    def handle(request):
        requests.append(request)
        if failure=="connection":raise httpx2.ConnectError("controlled connection failure")
        return httpx2.Response(503,json={"error":{"type":"server_error","message":"controlled outage"}})
    app=application(workspace,httpx2.MockTransport(handle))
    with TestClient(app) as client:
        types=[item["type"] for item in events(client.post("/agent",json=request()))]
        assert "RUN_ERROR" in types and "RUN_FINISHED" not in types
    evidence=workspace.evidence("agui-thread","agui-run")
    assert len(requests)==evidence["http_attempts"]==1 and evidence["usage"] is None
    assert evidence["agent_observations"]==[] and workspace.case("case-104")["refunds"]==[]
    assert app.state.runtime.client.is_closed() and app.state.runtime.async_client.is_closed()
    assert not app.state.runtime.checkpointer.storage and not app.state.runtime.checkpointer.writes and not app.state.runtime.checkpointer.blobs


def test_restart_owns_fresh_clients_and_clears_only_memory_not_durable_evidence(tmp_path,native):
    workspace=state(tmp_path);script=native([FINAL]);app=application(workspace,script)
    runtimes=[]
    for index in range(2):
        with TestClient(app) as client:
            runtime=app.state.runtime;runtimes.append(runtime)
            assert not runtime.client.is_closed() and not runtime.async_client.is_closed()
            assert "RUN_FINISHED" in [item["type"] for item in events(client.post("/agent",json=request(f"run-{index}")))]
            assert runtime.checkpointer.storage
        assert runtime.closed and runtime.client.is_closed() and runtime.async_client.is_closed()
        assert not runtime.checkpointer.storage and not runtime.checkpointer.writes and not runtime.checkpointer.blobs
        assert not any(getattr(route,"path",None)=="/agent" for route in app.router.routes)
    assert runtimes[0].client is not runtimes[1].client
    assert len(workspace.evidence("agui-thread")["provider_observations"])==2


def test_startup_failure_closes_constructed_clients_and_cannot_reenter(tmp_path,native,monkeypatch):
    workspace=state(tmp_path);script=native([FINAL])
    runtime=AgentRuntime(workspace,sync_transport=script,async_transport=script)
    def fail(*args,**kwargs):raise RuntimeError("controlled graph construction failure")
    monkeypatch.setattr(runtime_module,"build_agent",fail)
    async def call():
        with pytest.raises(RuntimeError,match="construction failure"):
            await runtime.__aenter__()
        with pytest.raises(RuntimeError,match="entered twice"):
            await runtime.__aenter__()
    asyncio.run(call())
    assert runtime.closed and runtime.client.is_closed() and runtime.async_client.is_closed()
    assert script.requests==[]


def test_explicit_builder_dependencies_remain_caller_owned(tmp_path,native):
    workspace=state(tmp_path);script=native([FINAL])
    async def call():
        with OpenAI(api_key="synthetic-not-a-secret",http_client=httpx2.Client(transport=script)) as client:
            async with AsyncOpenAI(api_key="synthetic-not-a-secret",http_client=httpx2.AsyncClient(transport=script)) as asynchronous:
                model=ChatOpenAI(model="gpt-6.1-sol",client=client.chat.completions,root_client=client,
                    async_client=asynchronous.chat.completions,root_async_client=asynchronous,use_responses_api=False)
                checkpointer=MemorySaver()
                graph=build_agent(workspace,model=model,checkpointer=checkpointer)
                graph.invoke({"messages":[{"role":"user","content":"Inspect the case."}]},config={"configurable":{"thread_id":"caller-thread"}})
                assert not client.is_closed() and not asynchronous.is_closed() and checkpointer.storage
    asyncio.run(call())
    evidence=workspace.evidence("caller-thread")
    assert evidence["provider_observations"]==[] and evidence["agent_observations"][0]["reported_usage"] is None


@pytest.mark.parametrize("amount",[True,1.5])
def test_actual_langchain_tool_validation_never_coerces_invalid_minor_units(tmp_path,native,amount):
    workspace=state(tmp_path)
    from test_agent import tool_message
    script=native([choice(tool_message(arguments={"case_id":"case-104","amount_cents":amount,"reason":"A malformed amount"})),FINAL])
    invoke(workspace,script)
    assert workspace.case("case-104")["case"]["proposal"] is None
    result=next(item for item in json.loads(script.requests[1].content)["messages"] if item["role"]=="tool")
    assert "valid integer" in result["content"]


def test_concurrent_agui_runs_are_serialized_before_the_model_and_correlated(tmp_path,native):
    workspace=state(tmp_path);script=native([choice(),FINAL,choice(),FINAL])
    first,second,release=Event(),Event(),Event()
    calls=[]
    class Gated(httpx2.AsyncBaseTransport):
        async def handle_async_request(self,request):
            calls.append(request)
            if len(calls)==1:
                first.set()
                assert await asyncio.to_thread(release.wait,5)
            return script.handle(request)
    app=create_app(workspace.path,runtime_factory=lambda workspace:AgentRuntime(workspace,async_transport=Gated()))
    @app.middleware("http")
    async def arrival(request,call_next):
        if request.url.path=="/agent" and (await request.json())["runId"]=="second":second.set()
        return await call_next(request)
    with TestClient(app) as client,ThreadPoolExecutor(max_workers=2) as pool:
        one=pool.submit(client.post,"/agent",json=request("first","thread-one"))
        try:
            assert first.wait(5)
            two=pool.submit(client.post,"/agent",json=request("second","thread-two"))
            assert second.wait(5) and len(calls)==1
        finally:release.set()
        assert "RUN_FINISHED" in [item["type"] for item in events(one.result())]
        assert "RUN_FINISHED" in [item["type"] for item in events(two.result())]
    assert len(calls)==4
    assert workspace.evidence("thread-one","first")["http_attempts"]==2
    assert workspace.evidence("thread-two","second")["http_attempts"]==2


def test_cancelled_native_stream_closes_response_and_keeps_partial_unknown_usage(tmp_path,native):
    from support_workspace.evidence import execution_scope
    workspace=state(tmp_path);native([FINAL]);opened=[]
    async def call():
        waiting=asyncio.Event()
        class Pending(httpx2.AsyncByteStream):
            closed=False
            async def __aiter__(self):
                yield b'data: {"id":"chatcmpl_partial","object":"chat.completion.chunk","created":1792098000,"model":"gpt-6.1-sol","choices":[{"index":0,"delta":{"role":"assistant","content":"Partial answer"},"finish_reason":null}]}\n\n'
                waiting.set()
                await asyncio.Future()
            async def aclose(self):self.closed=True
        class Transport(httpx2.AsyncBaseTransport):
            async def handle_async_request(self,request):
                body=Pending();opened.append(body)
                return httpx2.Response(200,stream=body,headers={"content-type":"text/event-stream"})
        async with AgentRuntime(workspace,async_transport=Transport()) as runtime:
            async def consume():
                with execution_scope("cancel-thread","cancel-run"):
                    async for _ in runtime.graph.astream_events({"messages":[{"role":"user","content":"Inspect the case."}]},
                        config={"configurable":{"thread_id":"cancel-thread"}},version="v2"):
                        pass
            task=asyncio.create_task(consume())
            await asyncio.wait_for(waiting.wait(),5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
            assert opened[0].closed
        assert runtime.closed and runtime.async_client.is_closed()
    asyncio.run(call())
    evidence=workspace.evidence("cancel-thread","cancel-run")
    assert evidence["http_attempts"]==1 and evidence["usage"] is None and evidence["agent_observations"]==[]
    provider=evidence["provider_observations"][0]
    assert provider["error_type"]=="CancelledError" and "Partial answer" in provider["raw_output"]
    assert not provider["done_marker"] and workspace.case("case-104")["case"]["proposal"] is None


def test_capture_limit_is_explicit_and_cannot_accept_unverified_tool_output(tmp_path,native,monkeypatch):
    from support_workspace import evidence
    monkeypatch.setattr(evidence,"CAPTURE_LIMIT",128)
    workspace=state(tmp_path);script=native([choice(),FINAL])
    with pytest.raises(ResponseBoundaryError,match="invalid_http_observation"):invoke(workspace,script)
    provider=workspace.evidence("synthetic-thread","synthetic-run")["provider_observations"][0]
    assert provider["capture_truncated"] and not provider["usage_complete"] and provider["wire_bytes"]>128
    assert workspace.case("case-104")["case"]["proposal"] is None and len(script.requests)==1


def test_busy_native_loop_records_qualified_start_and_preserves_prior_business_history(tmp_path,native):
    from support_workspace.datasets import initialize_case
    from test_agent import tool_message
    from support_workspace.store import Workspace
    path=tmp_path/"busy.json";initialized=initialize_case("busy",path)
    workspace=Workspace(path);before=json.loads(path.read_text())
    script=native([choice(tool_message("inspect_case",{"case_id":"case-104"})),choice(),FINAL])
    invoke(workspace,script)
    after=json.loads(path.read_text())
    assert after["cases"][1:]==before["cases"][1:] and after["orders"]==before["orders"] and after["refunds"]==before["refunds"]
    evidence=workspace.evidence("synthetic-thread","synthetic-run")
    assert evidence["initial_state"]["file_sha256"]==initialized["sha256"]
    assert evidence["initial_state"]["declared_dataset"]["case_id"]=="busy"
    assert evidence["current_state"]["business_state_sha256"]!=evidence["initial_state"]["business_state_sha256"]
    assert evidence["usage"]=={"input_tokens":60,"output_tokens":30,"total_tokens":90}
    assert all("northstar-support-workspace" not in request.content.decode() for request in script.requests)


def test_provider_failure_after_a_committed_proposal_retains_effect_and_prior_usage(tmp_path,native):
    from test_agent import tool_message
    workspace=state(tmp_path);script=native([choice(tool_message("inspect_case",{"case_id":"case-104"})),choice()])
    requests=[]
    def handle(request):
        requests.append(request)
        if len(requests)==3:return httpx2.Response(503,json={"error":{"type":"server_error","message":"Controlled outage after proposal"}})
        return script.handle(request)
    transport=httpx2.MockTransport(handle)
    with pytest.raises(Exception) as error:invoke(workspace,transport)
    assert "503" in str(error.value)
    assert len(requests)==3 and workspace.case("case-104")["case"]["proposal"]["amount_cents"]==2999
    evidence=workspace.evidence("synthetic-thread","synthetic-run")
    assert evidence["usage"] is None and evidence["http_attempts"]==3
    assert [item["reported_usage"] for item in evidence["provider_observations"]]==[USAGE,USAGE,None]
    assert len(evidence["agent_observations"])==2 and workspace.case("case-104")["refunds"]==[]
