"""Real application/SDKs with test-only scripted model HTTP; never a live model."""
import json
from pathlib import Path
import shutil

import httpx2
import uvicorn
from support_workspace.api import create_app
from support_workspace.runtime import AgentRuntime

root=Path(__file__).resolve().parents[2]
state=root/"frontend/.e2e/workspace.json"
state.parent.mkdir(exist_ok=True)
shutil.copyfile(root/"fixtures/starter.json",state)
sequence=0


def handle(request):
    global sequence
    sequence+=1
    body=json.loads(request.content)
    assert request.url.path=="/v1/chat/completions"
    # The mock enforces the provider's tool-result relationship instead of
    # accepting a broken conversation after a rejected/failed turn.
    pending=set()
    for message in body["messages"]:
        if message["role"]=="assistant":pending.update(call["id"] for call in message.get("tool_calls",[]))
        if message["role"]=="tool":
            if message["tool_call_id"] not in pending:
                return httpx2.Response(400,json={"error":{"type":"invalid_request_error","message":"Orphan tool result in controlled conversation"}})
            pending.remove(message["tool_call_id"])
        if message["role"]=="user" and pending:
            return httpx2.Response(400,json={"error":{"type":"invalid_request_error","message":"Unanswered tool call in controlled conversation"}})
    if pending:return httpx2.Response(400,json={"error":{"type":"invalid_request_error","message":"Missing tool results in controlled conversation"}})
    start=max(index for index,message in enumerate(body["messages"]) if message["role"]=="user")
    task=str(body["messages"][start]["content"]).lower()
    if "provider outage" in task:
        return httpx2.Response(503,json={"error":{"type":"server_error","message":"Controlled offline provider outage"}})
    tools=[message for message in body["messages"][start+1:] if message["role"]=="tool"]
    if "unfinished response" in task:
        name,args,finish="propose_refund",{"case_id":"case-104","amount_cents":2999,"reason":"Controlled unfinished proposal"},"length"
    elif not tools:
        name,args,finish="inspect_case",{"case_id":"case-104"},"tool_calls"
    elif len(tools)==1:
        name,args,finish="propose_refund",{"case_id":"case-104","amount_cents":2999,"reason":"One damaged scanner; awaiting operator approval"},"tool_calls"
    else:
        name,args,finish=None,None,"stop"
    message=({"role":"assistant","content":None,"tool_calls":[{"id":f"call_synthetic_{sequence}","type":"function","function":{"name":name,"arguments":json.dumps(args)}}]} if name else
        {"role":"assistant","content":'Saved a USD 29.99 refund proposal for case-104. An operator must approve it; no refund has been issued. One damaged unit is this fraction of the shipment:\n\n$$\n\\frac{1}{3}\n$$\n\n<script>window.syntheticUnsafe=1</script><a href="javascript:window.syntheticUnsafe=1">Unsafe link</a>'})
    usage={"prompt_tokens":40,"completion_tokens":15,"total_tokens":55}
    base={"id":f"chatcmpl_synthetic_{sequence}","created":1792098000,"model":"gpt-6.1-sol"}
    if not body.get("stream"):
        return httpx2.Response(200,json={**base,"object":"chat.completion","choices":[{"index":0,"message":message,"finish_reason":finish}],"usage":usage})
    if name:message["tool_calls"][0]["index"]=0
    chunks=[{**base,"object":"chat.completion.chunk","choices":[{"index":0,"delta":message,"finish_reason":None}]},
        {**base,"object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":finish}]},
        {**base,"object":"chat.completion.chunk","choices":[],"usage":usage}]
    data="".join("data: "+json.dumps(chunk)+"\n\n" for chunk in chunks)+"data: [DONE]\n\n"
    return httpx2.Response(200,content=data,headers={"content-type":"text/event-stream"})


app=create_app(state,runtime_factory=lambda workspace:AgentRuntime(workspace,
    sync_transport=httpx2.MockTransport(handle),async_transport=httpx2.MockTransport(handle)))
uvicorn.run(app,host="127.0.0.1",port=38123)
