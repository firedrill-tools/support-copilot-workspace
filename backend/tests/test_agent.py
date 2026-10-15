"""Actual LangChain/OpenAI and AG-UI paths over controlled JSON/SSE HTTP."""
import asyncio
from copy import deepcopy
import json

import httpx2
from fastapi.testclient import TestClient
import pytest

from support_workspace.runtime import AgentRuntime
from support_workspace.api import create_app
from support_workspace.completion import ResponseBoundaryError
from test_workspace import state

USAGE={"prompt_tokens":20,"completion_tokens":10,"total_tokens":30}


def tool_message(name="propose_refund",arguments=None):
    return {"role":"assistant","content":None,"tool_calls":[{"id":"call_synthetic","type":"function",
        "function":{"name":name,"arguments":json.dumps(arguments if arguments is not None else {"case_id":"case-104","amount_cents":2999,"reason":"One damaged scanner"})}}]}


class Script(httpx2.MockTransport):
    def __init__(self,choices,*,usage=USAGE,done=True):
        self.choices,self.requests=choices,[]
        self.usage,self.done=usage,done
        super().__init__(self.handle)
    def handle(self,request):
        self.requests.append(request)
        choice=deepcopy(self.choices[min(len(self.requests)-1,len(self.choices)-1)])
        body=json.loads(request.content)
        assert request.url.path=="/v1/chat/completions"
        if not body.get("stream"):
            return httpx2.Response(200,json={"id":"chatcmpl_synthetic","object":"chat.completion","created":1792098000,
                "model":"gpt-6.1-sol","choices":[{"index":0,**choice}],"usage":self.usage})
        assert body["stream_options"]["include_usage"] is True
        delta={**choice["message"]}
        if "tool_calls" in delta:
            delta["tool_calls"]=[{"index":index,**call} for index,call in enumerate(delta["tool_calls"])]
        base={"id":"chatcmpl_synthetic","object":"chat.completion.chunk","created":1792098000,"model":"gpt-6.1-sol"}
        chunks=[{**base,"choices":[{"index":0,"delta":delta,"finish_reason":None}]},
            {**base,"choices":[{"index":0,"delta":{},"finish_reason":choice["finish_reason"]}]},
            {**base,"choices":[],"usage":self.usage}]
        stream="".join("data: "+json.dumps(chunk)+"\n\n" for chunk in chunks)+("data: [DONE]\n\n" if self.done else "")
        return httpx2.Response(200,content=stream,headers={"content-type":"text/event-stream"})


def choice(message=None,finish="tool_calls"):
    return {"finish_reason":finish,"message":message or tool_message()}


FINAL=choice({"role":"assistant","content":"A proposal is saved for operator review; no refund has been issued."},"stop")


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","synthetic-not-a-secret")
    monkeypatch.setenv("OPENAI_MODEL","gpt-6.1-sol")
    monkeypatch.setenv("LANGSMITH_TRACING","false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2","false")
    for name in ("OPENAI_BASE_URL","OPENAI_API_BASE"):
        monkeypatch.delenv(name,raising=False)
    def make(choices,**kwargs):
        return Script(choices,**kwargs)
    return make


def invoke(workspace,script):
    async def call():
        async with AgentRuntime(workspace,sync_transport=script,async_transport=script) as runtime:
            return runtime.invoke({"messages":[{"role":"user","content":"Inspect case-104 and propose a refund for the damaged scanner."}]},
                                  thread_id="synthetic-thread",run_id="synthetic-run")
    return asyncio.run(call())


def test_native_tool_loop_creates_only_a_proposal_and_saves_sdk_evidence(tmp_path,native):
    workspace=state(tmp_path)
    script=native([choice(),FINAL])
    result=invoke(workspace,script)
    assert len(script.requests)==2 and "operator review" in result["messages"][-1].text
    assert workspace.case("case-104")["case"]["proposal"]["amount_cents"]==2999
    assert workspace.case("case-104")["refunds"]==[]
    body=json.loads(script.requests[0].content)
    assert body["max_completion_tokens"]==4096 and body["store"] is False and body["parallel_tool_calls"] is False
    tool_result=next(item for item in json.loads(script.requests[1].content)["messages"] if item["role"]=="tool")
    assert json.loads(tool_result["content"])["proposal"]["binding"]["order_id"]=="order-104"
    observations=json.loads(workspace.path.read_text())["agent_observations"]
    assert len(observations)==2 and all(item["accepted"] for item in observations)
    assert all(item["thread_id"]=="synthetic-thread" and item["reported_usage"] == USAGE and item["cost_usd"] is None for item in observations)
    assert observations[0]["sdk_usage"]["total_tokens"]==30


@pytest.mark.parametrize("finish",["length","content_filter",None])
def test_nonfinal_native_tool_call_cannot_mutate_pending_proposal(tmp_path,native,finish):
    workspace=state(tmp_path);script=native([choice(finish=finish),FINAL])
    with pytest.raises(ResponseBoundaryError) as error:invoke(workspace,script)
    assert len(script.requests)==1 and workspace.case("case-104")["case"]["proposal"] is None
    observation=json.loads(workspace.path.read_text())["agent_observations"][0]
    assert not observation["accepted"] and observation["protocol_error"]=="tool_response_not_completed"
    assert observation["sdk_message"]["response_metadata"]["finish_reason"]==finish
    assert error.value.observation["sdk_usage"]["total_tokens"]==30


def test_parallel_native_tools_and_blank_final_answer_are_rejected(tmp_path,native):
    workspace=state(tmp_path)
    message=tool_message();message["tool_calls"].append({**message["tool_calls"][0],"id":"second_call"})
    script=native([choice(message)])
    with pytest.raises(ResponseBoundaryError,match="parallel"):invoke(workspace,script)
    assert workspace.case("case-104")["case"]["proposal"] is None and len(script.requests)==1
    script=native([choice({"role":"assistant","content":" "},"stop")])
    with pytest.raises(ResponseBoundaryError,match="answer_not_completed"):invoke(workspace,script)
    assert len(script.requests)==1


def test_repeated_native_reads_stop_at_eight_model_calls_without_refunds(tmp_path,native):
    workspace=state(tmp_path);script=native([choice(tool_message("list_cases",{}))])
    with pytest.raises(Exception) as error:invoke(workspace,script)
    assert "limit" in str(error.value).lower()
    assert len(script.requests)==8 and workspace.case("case-104")["refunds"]==[]
    assert len(json.loads(workspace.path.read_text())["agent_observations"])==8


def test_later_user_turn_removes_rejected_unanswered_call_but_keeps_original_evidence(tmp_path,native):
    workspace=state(tmp_path);script=native([choice(finish="length"),choice(),FINAL])
    async def call():
        async with AgentRuntime(workspace,sync_transport=script,async_transport=script) as runtime:
            with pytest.raises(ResponseBoundaryError):
                runtime.invoke({"messages":[{"role":"user","content":"Propose the damaged scanner refund."}]},thread_id="recovery-thread",run_id="failed-run")
            runtime.invoke({"messages":[{"role":"user","content":"Try again with a completed response."}]},thread_id="recovery-thread",run_id="retry-run")
    asyncio.run(call())
    retried=json.loads(script.requests[1].content)
    assert not any(message.get("tool_calls") for message in retried["messages"])
    assert len(script.requests)==3 and workspace.case("case-104")["case"]["proposal"]["amount_cents"]==2999
    observations=json.loads(workspace.path.read_text())["agent_observations"]
    assert [item["accepted"] for item in observations]==[False,True,True]
    assert observations[0]["sdk_message"]["response_metadata"]["finish_reason"]=="length"


@pytest.mark.parametrize("finish",["tool_calls","length"])
def test_real_agui_endpoint_streams_sdk_loop_or_error_before_proposal_dispatch(tmp_path,native,finish):
    workspace=state(tmp_path);script=native([choice(finish=finish),FINAL])
    body={"threadId":"agui-synthetic-thread","runId":"agui-synthetic-run","state":{},
        "messages":[{"id":"user-synthetic","role":"user","content":"Inspect case-104 and propose the damaged scanner refund."}],
        "tools":[],"context":[],"forwardedProps":{}}
    with TestClient(create_app(workspace.path,runtime_factory=lambda workspace:AgentRuntime(workspace,sync_transport=script,async_transport=script))) as client:
        response=client.post("/agent",json=body,headers={"accept":"text/event-stream"})
    assert response.status_code==200
    events=[json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")]
    types=[event["type"] for event in events]
    assert "RUN_STARTED" in types
    if finish=="length":
        assert "RUN_ERROR" in types and len(script.requests)==1
        assert "RUN_FINISHED" not in types
        assert workspace.case("case-104")["case"]["proposal"] is None
    else:
        assert "RUN_FINISHED" in types and "RUN_ERROR" not in types and len(script.requests)==2
        assert workspace.case("case-104")["case"]["proposal"]["amount_cents"]==2999
    assert workspace.case("case-104")["refunds"]==[]
    observations=json.loads(workspace.path.read_text())["agent_observations"]
    assert observations[0]["thread_id"]=="agui-synthetic-thread"
