#!/usr/bin/env python3
"""Live external MCP integration audit. Never prints API keys or private data."""
import concurrent.futures
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("OMNI_MCP_URL", "https://omni-research-oss-mcp.onrender.com/mcp")
HEADERS = {
    "Content-Type":"application/json",
    "Accept":"application/json, text/event-stream",
    "MCP-Protocol-Version":"2025-06-18",
    "User-Agent":"OmniResearchOSS-E2E/1.0",
}

def rpc(method, ident, params, timeout=75):
    req = urllib.request.Request(BASE, data=json.dumps({"jsonrpc":"2.0","id":ident,"method":method,"params":params}).encode(), headers=HEADERS,method="POST")
    with urllib.request.urlopen(req,timeout=timeout) as response:
        raw=response.read(2_500_000).decode("utf-8","replace")
        mime=response.headers.get("Content-Type","")
    if "text/event-stream" in mime:
        events=[s[6:] for s in raw.splitlines() if s.startswith("data: ")]
        if not events:raise RuntimeError("Empty SSE response")
        raw=events[-1]
    envelope=json.loads(raw)
    if "error" in envelope:raise RuntimeError("JSON-RPC error: "+str(envelope["error"])[:350])
    return envelope.get("result",{})

def decode(result):
    data=result.get("structuredContent")
    if data is not None and isinstance(data,dict):
        if "result" in data and len(data)==1:return data["result"]
        return data
    c=result.get("content") or []
    for item in c:
        if item.get("type")=="text":
            try:return json.loads(item["text"])
            except Exception:return {"text":item["text"][:1000]}
    return {}

TASKS = [
 ("health_check", {}),
 ("web_search", {"query":"African Union headquarters", "engines":["wikipedia"], "limit":2}),
 ("academic_search", {"query":"Africa climate change", "sources":["crossref","openalex"], "limit":2}),
 ("code_search", {"query":"africa language:python", "mode":"repositories", "limit":2}),
 ("social_search", {"query":"open source research", "sources":["hackernews","stackoverflow"], "limit":2}),
 ("news_search", {"query":"African Union", "limit":2}),
 ("dataset_search", {"query":"africa", "source":"huggingface", "limit":2}),
 ("fetch_source", {"url":"https://example.org/", "max_chars":1000}),
 ("map_website", {"url":"https://example.org/", "max_pages":1}),
 ("compare_evidence", {"claim":"Example Domain is for use in documentation", "urls":["https://example.org/"]}),
 ("research_bundle", {"topic":"African Union", "mode":"news", "max_results":3}),
 ("citation_lookup", {"doi":"10.1038/nature12373"}),
 ("dataset_search/zenodo", {"query":"africa","source":"zenodo","limit":1}),
 ("web_search/default", {"query":"African Union","limit":3}),
 ("social_search/reddit", {"query":"Africa geography","sources":["reddit"],"limit":1}),
 ("code_search/tokenless", {"query":"hello", "mode":"code", "limit":1}),
 ("code_search/issues", {"query":"is:issue repo:python/cpython", "mode":"issues", "limit":2}),
 ("code_search/users", {"query":"python", "mode":"users", "limit":1}),
 ("academic_search/all", {"query":"African climate change", "limit":2}),
 ("news_search/pt-BR", {"query":"África", "limit":1, "locale":"pt-BR"}),
 ("social_search/default", {"query":"Python", "limit":2}),
 ("web_search/bing", {"query":"African Union", "engines":["bing"], "limit":2}),
 ("web_search/duckduckgo", {"query":"African Union", "engines":["duckduckgo"], "limit":2}),
 ("fetch_source/pdf", {"url":"https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf", "max_chars":500}),
]
NEGATIVE = [
 ("fetch_source/private", "fetch_source", {"url":"http://127.0.0.1/latest/meta-data"}),
 ("fetch_source/file", "fetch_source", {"url":"file:///etc/passwd"}),
 ("citation_lookup/invalid", "citation_lookup", {"doi":"not_a_doi"}),
 ("compare_evidence/no_urls","compare_evidence", {"claim":"x","urls":[]}),
]

def summarize(name,result,seconds):
    if result.get("isError"):
        return {"tool":name,"status":"ERROR","seconds":round(seconds,2),"reason":str(decode(result))[:350]}
    data=decode(result)
    if not isinstance(data,dict): data={"rawtype":type(data).__name__}
    # Note: upstream providers can be down and the MCP protocol still succeeds.
    data_errors=data.get("errors",{}) or data.get("source_errors",{}) or data.get("provider_errors",{})
    results=data.get("results") or data.get("sources") or data.get("pages") or data.get("evidence") or []
    if isinstance(results,list): count=len(results)
    else: count=None
    # Single-document tools do not return a results list. Check their actual fields.
    if name.startswith("fetch_source"): count=1 if data.get("text") and data.get("url") else 0
    if name=="citation_lookup": count=1 if data.get("doi") and data.get("title") else 0
    if name=="health_check":
        count=1 if data.get("status")=="ok" and data.get("providers",{}).get("web_default")==["duckduckgo","wikipedia"] else 0
    status="PASS" if count is None or count>0 else "DEGRADED"
    if data_errors and count==0: status="DEGRADED"
    if name=="code_search/tokenless" and data.get("error"):status="EXPECTED_LIMIT"
    return {"tool":name,"status":status,"seconds":round(seconds,2),"items":count,"provider_errors":str(data_errors)[:300] if data_errors else None,"message":str(data.get("error") or data.get("note") or "")[:110]}

def call_task(idx,name,args):
    method=name.split("/")[0]
    start=time.monotonic()
    try:
        result=rpc("tools/call",100+idx,{"name":method,"arguments":args},timeout=85)
        return summarize(name,result,time.monotonic()-start)
    except Exception as exc:
        return {"tool":name,"status":"ERROR","seconds":round(time.monotonic()-start,2),"reason":str(exc)[:320]}

def main():
    init=rpc("initialize",1,{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"omni-e2e-audit","version":"1.0"}})
    tools=rpc("tools/list",2,{})["tools"]
    names={x["name"] for x in tools}
    expected={x[0] for x in TASKS if "/" not in x[0]}
    assert names==expected,(sorted(names),sorted(expected))
    assert len(tools)==12
    print("PROTOCOL_PASS",json.dumps({"init":init.get("protocolVersion"),"server":init.get("serverInfo"),"tools":sorted(names)}),flush=True)
    for x in tools:
        ann=x.get("annotations") or {}
        assert ann.get("readOnlyHint") is True,(x["name"],ann)
        assert ann.get("destructiveHint") is False,(x["name"],ann)
        assert isinstance(ann.get("openWorldHint"),bool),(x["name"],ann)
    print("ANNOTATIONS_PASS",flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        work=[pool.submit(call_task,i,name,args) for i,(name,args) in enumerate(TASKS)]
        results=[]
        for task in concurrent.futures.as_completed(work):
            result=task.result()
            results.append(result)
            print("TOOL",json.dumps(result,ensure_ascii=False),flush=True)
    # The public endpoint must reject oversized JSON before parsing it.
    too_large=json.dumps({"jsonrpc":"2.0","id":901,"method":"ping","params":{"padding":"x"*33000}}).encode()
    request=urllib.request.Request(BASE,data=too_large,headers=HEADERS,method="POST")
    try:
        with urllib.request.urlopen(request,timeout=20) as response:
            code=response.status
    except urllib.error.HTTPError as error:
        code=error.code
    print("REQUEST_LIMIT",json.dumps({"oversized_status":code,"expected":413}),flush=True)
    assert code==413,"POST max-size guard missing or not deployed"
    neg=[]
    for i,(name,method,args) in enumerate(NEGATIVE):
        start=time.monotonic()
        try:
            result=rpc("tools/call",201+i,{"name":method,"arguments":args},timeout=25)
            outcome={"name":name,"status":"PASS" if result.get("isError") else "FAIL","duration":round(time.monotonic()-start,2),"message":str(decode(result))[:130]}
        except Exception as exc:
            outcome={"name":name,"status":"ERROR","reason":str(exc)[:140]}
        neg.append(outcome)
        print("NEGATIVE",json.dumps(outcome,ensure_ascii=False),flush=True)
    problems=[x for x in results if x["status"] in ("ERROR","DEGRADED")]+[x for x in neg if x["status"]!="PASS"]
    print("SUMMARY",json.dumps({"tested":len(results),"successful":sum(x["status"]=="PASS" for x in results),"degraded":sum(x["status"]=="DEGRADED" for x in results),"errors":sum(x["status"]=="ERROR" for x in results),"negative_pass":sum(x["status"]=="PASS" for x in neg),"problems":problems},ensure_ascii=False),flush=True)
    assert all(x["status"]=="PASS" for x in neg),"Negative security regression!"
    assert not any(x["status"]=="ERROR" and x["tool"] in ("health_check","fetch_source","map_website","compare_evidence") for x in results),"Basic MCP tools failed!"
    assert any(x["status"]=="PASS" for x in results if x["tool"] not in ("health_check","code_search/tokenless")),"All providers failed!"
if __name__=="__main__":
    main()
