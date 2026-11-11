#!/usr/bin/env python3
"""Test authenticated agent MCP via HTTP without incurring model API charges."""
import json
import os
import urllib.request
import urllib.error

BASE=os.environ.get("OMNI_AGENTS_MCP_URL","http://127.0.0.1:8799/mcp")
TOKEN=os.environ["OMNI_AGENT_ACCESS_TOKEN"]
HEADERS={"Authorization":"Bearer "+TOKEN,"Content-Type":"application/json",
         "Accept":"application/json, text/event-stream","MCP-Protocol-Version":"2025-06-18"}


def call(method,ident,params=None,token=None):
    body={"jsonrpc":"2.0","id":ident,"method":method}
    if params is not None:body["params"]=params
    headers=dict(HEADERS)
    if token is not None:headers["Authorization"]=token
    req=urllib.request.Request(BASE,data=json.dumps(body).encode(),headers=headers,method="POST")
    try:
        with urllib.request.urlopen(req,timeout=15) as response:
            raw=response.read().decode()
            kind=response.headers.get("Content-Type","")
    except urllib.error.HTTPError as exc:
        return {"http_error":exc.code}
    if "text/event-stream" in kind:
        raw=[line[6:] for line in raw.splitlines() if line.startswith("data: ")][-1]
    return json.loads(raw)


def data(result):
    if result.get("error"):raise RuntimeError(result["error"])
    r=result["result"]
    if r.get("isError"):raise RuntimeError(r)
    d=r.get("structuredContent")
    if isinstance(d,dict):return d.get("result",d)
    return json.loads(next(c["text"] for c in r["content"] if c["type"]=="text"))


def main():
    assert call("initialize",10,{"protocolVersion":"2025-06-18","capabilities":{},
            "clientInfo":{"name":"omni-agent-ci","version":"0.1"}} , token="Bearer wrong")["http_error"]==401
    init=call("initialize",1,{"protocolVersion":"2025-06-18","capabilities":{},
        "clientInfo":{"name":"omni-agent-ci","version":"0.1"}})
    assert init["result"]["serverInfo"]["name"]=="OmniAgents OSS",init
    tools=call("tools/list",2)
    names={t["name"] for t in tools["result"]["tools"]}
    assert names=={"agent","task","spawn_agent"},names
    status=data(call("tools/call",3,{"name":"agent","arguments":{"action":"status"}}))
    assert status["backend"]["configured"] is False,status
    not_ready=data(call("tools/call",4,{"name":"spawn_agent",
        "arguments":{"prompt":"Analyze this hypothetical topic","count":2}}))
    assert not_ready["error"]=="MODEL_PROVIDER_NOT_CONFIGURED",not_ready
    empty=data(call("tools/call",5,{"name":"task","arguments":{"action":"list"}}))
    assert isinstance(empty["tasks"],list),empty
    print("AUTH_MCP_PASS",json.dumps({"tools":sorted(names),"provider_ready":False,
          "blocked_unauthorized":True, "model_charges":0}),flush=True)


if __name__=="__main__":main()
