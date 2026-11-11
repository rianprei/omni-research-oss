#!/usr/bin/env python3
"""Authenticated MCP smoke: no model credentials and no sampling client."""
import json, os, urllib.request, urllib.error

BASE=os.getenv("OMNI_SAMPLING_URL","http://localhost:8798/mcp")
TOKEN=os.environ["OMNI_AGENT_ACCESS_TOKEN"]
headers={
    "authorization":"Bearer "+TOKEN,
    "content-type":"application/json",
    "accept":"application/json, text/event-stream",
    "mcp-protocol-version":"2025-06-18",
}
session=None
def rpc(method, id, params=None, authorized=True, notification=False):
    global session
    data={"jsonrpc":"2.0","method":method}
    if not notification: data["id"]=id
    if params is not None:data["params"]=params
    h=dict(headers)
    if not authorized:h.pop("authorization",None)
    if session:h["mcp-session-id"]=session
    req=urllib.request.Request(BASE,data=json.dumps(data).encode(),headers=h,method="POST")
    try:
        with urllib.request.urlopen(req,timeout=15) as rsp:
            status=rsp.status
            session=rsp.headers.get("mcp-session-id",session)
            body=rsp.read().decode()
            typ=rsp.headers.get("content-type","")
    except urllib.error.HTTPError as exc:
        return {"http_error":exc.code}
    if notification:return {"status":status}
    if "text/event-stream" in typ:
        data_lines=[x[6:] for x in body.splitlines() if x.startswith("data: ")]
        assert data_lines,"Empty SSE response"
        body=data_lines[-1]
    return json.loads(body)

def result_data(response):
    assert "error" not in response,response
    value=response["result"]
    assert not value.get("isError"),value
    if isinstance(value.get("structuredContent"),dict):
        r=value["structuredContent"]
        return r.get("result",r)
    for part in value.get("content",[]):
        if part.get("type")=="text":
            return json.loads(part["text"])
    return {}

def main():
    unauth=rpc("initialize",777,{"protocolVersion":"2025-06-18","capabilities":{},
       "clientInfo":{"name":"offline","version":"0.1"}},authorized=False)
    assert unauth=={"http_error":401},unauth
    initialized=rpc("initialize",1,{"protocolVersion":"2025-06-18","capabilities":{},
        "clientInfo":{"name":"sampling-unsupported-test","version":"0.1"}})
    assert initialized.get("result",{}).get("serverInfo",{}).get("name")=="Omni Host Sampling (Experimental)",initialized
    rpc("notifications/initialized",None,notification=True)
    listed=rpc("tools/list",2,{})
    names={x["name"] for x in listed["result"]["tools"]}
    assert names=={"agent","spawn_agent","task"},names
    provider=result_data(rpc("tools/call",3,{"name":"agent","arguments":{}}))
    assert provider["client_sampling_declared"] is False,provider
    spawned=result_data(rpc("tools/call",4,{"name":"spawn_agent",
        "arguments":{"prompt":"Research African history","roles":["researcher","critic"],"model_hint":"gpt-6"}}))
    assert spawned["error"]=="HOST_SAMPLING_UNSUPPORTED" and spawned["agents_started"]==0,spawned
    missing=result_data(rpc("tools/call",5,{"name":"task","arguments":{"task_id":"missing"}}))
    assert missing["error"]=="TASK_NOT_FOUND_OR_RESTARTED",missing
    print("HOST_SAMPLING_MCP_PASS",json.dumps({"tools":sorted(names),"unauthorized":401,
        "sampling_advertised":False,"spawned":0,"model_calls":0}),flush=True)

if __name__=="__main__":
    main()
