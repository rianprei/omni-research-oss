#!/usr/bin/env python3
"""Remote end-to-end audit for the unified OmniResearch Cloud MCP server."""
import concurrent.futures
import json
import os
import time
import urllib.error
import urllib.request

BASE=os.environ.get("OMNI_MCP_URL","https://omni-research-oss-mcp.onrender.com/mcp")
HEADERS={"Content-Type":"application/json","Accept":"application/json, text/event-stream",
         "MCP-Protocol-Version":"2025-06-18","User-Agent":"OmniResearchOSS-E2E/1.4.0"}
PUBLIC={"omni_research-deep","fetch_source","map_website",
        "compare_evidence","citation_lookup","health_check"}

def rpc(method,ident,params=None,timeout=95):
    payload={"jsonrpc":"2.0","id":ident,"method":method}
    if params is not None:
        payload["params"]=params
    req=urllib.request.Request(BASE,data=json.dumps(payload).encode(),headers=HEADERS,method="POST")
    with urllib.request.urlopen(req,timeout=timeout) as response:
        raw=response.read(2_500_000).decode("utf-8","replace")
        mime=response.headers.get("Content-Type","")
    if "text/event-stream" in mime:
        lines=[s[6:] for s in raw.splitlines() if s.startswith("data: ")]
        if not lines:raise RuntimeError("empty SSE stream")
        raw=lines[-1]
    answer=json.loads(raw)
    if answer.get("error"):raise RuntimeError(str(answer["error"])[:250])
    return answer.get("result",{})

def decode(result):
    data=result.get("structuredContent")
    if isinstance(data,dict):
        if len(data)==1 and "result" in data:return data["result"]
        return data
    for block in result.get("content",[]):
        if block.get("type")=="text":
            try:return json.loads(block["text"])
            except Exception:return {"text":block["text"]}
    return {}

TASKS=[
 ("health_check",{}),
 ("omni_research-deep",{"query":"African Union","mode":"deep","limit":12}),
 ("omni_research-deep/web",{"query":"African Union","mode":"web","limit":3}),
 ("omni_research-deep/academic",{"query":"Africa climate change","mode":"academic","limit":3}),
 ("omni_research-deep/code",{"query":"africa language:python","mode":"code","limit":2}),
 ("omni_research-deep/social",{"query":"open source research","mode":"social","limit":2}),
 ("omni_research-deep/news-ptBR",{"query":"África","mode":"news","locale":"pt-BR","limit":2}),
 ("omni_research-deep/datasets",{"query":"africa","mode":"datasets","limit":3}),
 ("omni_research-deep/technical",{"query":"python async","mode":"technical","limit":4}),
 ("omni_research-deep/trends",{"query":"African Union","mode":"trends","limit":4}),
 ("omni_research-deep/code-issues",{"query":"is:issue repo:python/cpython","mode":"code","code_mode":"issues","limit":2}),
 ("omni_research-deep/data-zenodo",{"query":"africa","mode":"datasets","dataset_source":"zenodo","limit":2}),
 ("omni_research-deep/provider-subset",{"query":"African Union","providers":["news","web"],"limit":4}),
 ("fetch_source",{"url":"https://example.org/","max_chars":1000}),
 ("fetch_source/pdf",{"url":"https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf","max_chars":400}),
 ("map_website",{"url":"https://example.org/","max_pages":1}),
 ("compare_evidence",{"claim":"Example Domain for use in documentation","urls":["https://example.org/"]}),
 ("citation_lookup",{"doi":"10.1038/nature12373"}),
]
NEGATIVE=[
 ("fetch_source/private","fetch_source",{"url":"http://127.0.0.1/latest/meta-data"}),
 ("fetch_source/file","fetch_source",{"url":"file:///etc/passwd"}),
 ("citation_lookup/invalid","citation_lookup",{"doi":"invalid"}),
 ("compare_evidence/no_urls","compare_evidence",{"claim":"x","urls":[]}),
 ("omni/invalid_mode","omni_research-deep",{"query":"Africa","mode":"invalid"}),
 ("omni/invalid_sources","omni_research-deep",{"query":"Africa","providers":["supersecret"]}),
 ("omni/invalid_limit","omni_research-deep",{"query":"Africa","limit":True}),
 ("legacy/web_search","web_search",{"query":"Africa"}),
 ("legacy/research_bundle","research_bundle",{"topic":"Africa"}),
]

def measure(i, label, args):
    actual=label.split("/")[0]
    start=time.monotonic()
    try:
        result=rpc("tools/call",i+100,{"name":actual,"arguments":args},timeout=95)
        if result.get("isError"):
            return {"tool":label,"status":"ERROR","reason":str(decode(result))[:180]}
        data=decode(result)
        if not isinstance(data,dict):data={}
        if actual=="omni_research-deep":
            valid=data.get("providers_attempted") and isinstance(data.get("results"),list)
            count=len(data.get("results",[]))
            status="PASS" if valid and count else "DEGRADED"
            errors=data.get("errors") or data.get("source_errors") or {}
        elif actual=="health_check":
            valid=data.get("public_tools")==6 and data.get("search_tool")=="omni_research-deep"
            count=1 if valid else 0
            status="PASS" if valid else "ERROR"
            errors={}
        elif actual=="fetch_source":
            count=1 if data.get("text") and data.get("url") else 0
            status="PASS" if count else "DEGRADED"
            errors={}
        elif actual=="map_website":
            count=len(data.get("pages",[]))
            status="PASS" if count else "DEGRADED"
            errors=data.get("errors")
        elif actual=="compare_evidence":
            count=len(data.get("evidence",[]))
            status="PASS" if count and data.get("verdict")=="UNVERIFIED" else "DEGRADED"
            errors={}
        else:
            count=1 if data.get("doi") and data.get("title") else 0
            status="PASS" if count else "DEGRADED"
            errors={}
        return {"tool":label,"status":status,"results":count,
                "upstream_errors":str(errors)[:200] if errors else None,
                "elapsed":round(time.monotonic()-start,2)}
    except Exception as exc:
        return {"tool":label,"status":"ERROR","reason":str(exc)[:240],
                "elapsed":round(time.monotonic()-start,2)}

def main():
    init=rpc("initialize",1,{"protocolVersion":"2025-06-18","capabilities":{},
                            "clientInfo":{"name":"omni-e2e","version":"1.4.0"}})
    names=rpc("tools/list",2,{})["tools"]
    observed={x["name"] for x in names}
    assert observed==PUBLIC,(sorted(observed),sorted(PUBLIC))
    for tool in names:
        ann=tool.get("annotations") or {}
        assert ann.get("readOnlyHint") is True and ann.get("destructiveHint") is False,tool
    print("MCP_INVENTORY_PASS",json.dumps({"count":len(names),"names":sorted(observed),"server":init.get("serverInfo")}),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        tasks=[pool.submit(measure,i,name,args) for i,(name,args) in enumerate(TASKS)]
        results=[]
        for future in concurrent.futures.as_completed(tasks):
            entry=future.result()
            results.append(entry)
            print("CASE",json.dumps(entry,ensure_ascii=False),flush=True)
    # The public input guard rejects large POSTs without consuming provider budget.
    payload=json.dumps({"jsonrpc":"2.0","id":701,"method":"ping","params":{"padding":"x"*34000}}).encode()
    req=urllib.request.Request(BASE,data=payload,headers=HEADERS,method="POST")
    try:
        with urllib.request.urlopen(req,timeout=20) as resp:status=resp.status
    except urllib.error.HTTPError as exc:status=exc.code
    print("LARGE_INPUT",status,flush=True)
    assert status==413
    negatives=[]
    for i,(label,name,args) in enumerate(NEGATIVE):
        try:
            r=rpc("tools/call",900+i,{"name":name,"arguments":args},timeout=25)
            good=r.get("isError") is True
        except Exception:
            good=False
        negatives.append({"name":label,"passed":good})
        print("NEGATIVE",json.dumps(negatives[-1]),flush=True)
    states={x["tool"]:x["status"] for x in results}
    mandatory=("health_check","omni_research-deep",
               "omni_research-deep/web","fetch_source","fetch_source/pdf",
               "compare_evidence","citation_lookup")
    failed=[x for x in mandatory if states.get(x)!="PASS"]
    summary={"total_positive":len(results),"pass":sum(x["status"]=="PASS" for x in results),
             "degraded":sum(x["status"]=="DEGRADED" for x in results),
             "error":sum(x["status"]=="ERROR" for x in results),
             "negative_pass":sum(x["passed"] for x in negatives),
             "mandatory_failures":failed}
    print("SUMMARY",json.dumps(summary),flush=True)
    assert not failed,"Core MCP feature failed"
    assert all(x["passed"] for x in negatives),"Input validation or legacy removal failed"

if __name__=="__main__":
    main()
