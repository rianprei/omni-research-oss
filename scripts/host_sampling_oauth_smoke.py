"""Full MCP OAuth 2.1 integration smoke with dummy owner key, no paid model calls."""
import base64
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request

BASE=os.getenv("OMNI_AGENT_PUBLIC_URL","http://localhost:8798").rstrip("/")
OWNER=os.environ["OMNI_AGENT_ACCESS_TOKEN"]
CALLBACK="https://chatgpt.com/connector/oauth/ci-callback"
MCP=BASE+"/mcp"
SESSION=None

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None

OPENER=urllib.request.build_opener(NoRedirect)

def req(path, method="GET", body=None, extra=None, form=False):
    headers=extra or {}
    data=None
    if body is not None:
        if form:
            data=urllib.parse.urlencode(body).encode()
            headers["Content-Type"]="application/x-www-form-urlencoded"
        else:
            data=json.dumps(body).encode()
            headers["Content-Type"]="application/json"
    request=urllib.request.Request(
        BASE+path if path.startswith("/") else path,
        method=method, data=data, headers=headers)
    try:
        response=OPENER.open(request,timeout=15)
    except urllib.error.HTTPError as e:
        response=e
    raw=response.read(120000)
    # Preserve email.message.Message's case-insensitive HTTP header lookup.
    return response.status,response.headers,raw

def js(raw):
    return json.loads(raw.decode())

def mcp_call(token,method,ident,params=None,notify=False):
    global SESSION
    headers={
        "Authorization":"Bearer "+token,
        "Accept":"application/json, text/event-stream",
        "MCP-Protocol-Version":"2025-06-18",
        # CI simulates the Cloudflare-validated peer address.
        "CF-Connecting-IP":"74.220.49.23",
    }
    if SESSION: headers["Mcp-Session-Id"]=SESSION
    body={"jsonrpc":"2.0","method":method}
    if not notify:body["id"]=ident
    if params is not None:body["params"]=params
    status,hdr,raw=req("/mcp",method="POST",body=body,extra=headers)
    SESSION=hdr.get("Mcp-Session-Id",SESSION)
    if notify:return status,{}
    if b"data: " in raw:
        lines=[x[6:] for x in raw.splitlines() if x.startswith(b"data: ")]
        raw=lines[-1]
    return status,js(raw) if raw else {}

def main():
    status,headers,raw=req("/mcp",method="POST",body={
        "jsonrpc":"2.0","id":1,"method":"initialize",
        "params":{"protocolVersion":"2025-06-18","capabilities":{},
                  "clientInfo":{"name":"ci","version":"1"}}},
        extra={"CF-Connecting-IP":"74.220.49.23"})
    assert status==401, (status,raw)
    challenge={k.lower():v for k,v in headers.items()}.get("www-authenticate","")
    assert "Bearer" in challenge,headers
    status,_,raw=req("/.well-known/oauth-protected-resource/mcp")
    assert status==200,(status,raw)
    resource=js(raw)
    assert resource["authorization_servers"],resource
    status,_,raw=req("/.well-known/oauth-authorization-server")
    assert status==200,(status,raw)
    meta=js(raw)
    assert "S256" in meta["code_challenge_methods_supported"],meta
    assert meta.get("registration_endpoint") and meta.get("token_endpoint") and meta.get("authorization_endpoint")
    status,_,raw=req(
        urllib.parse.urlsplit(meta["registration_endpoint"]).path,
        "POST",
        {"client_name":"Omni CI OAuth","redirect_uris":[CALLBACK],
         "grant_types":["authorization_code"],"response_types":["code"],
         "token_endpoint_auth_method":"client_secret_post","scope":"mcp"})
    assert status in (200,201),(status,raw)
    client=js(raw)
    client_id=client["client_id"]
    verifier=base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query=urllib.parse.urlencode({
        "client_id":client_id,"redirect_uri":CALLBACK,
        "response_type":"code","scope":"mcp","state":"ci-state",
        "code_challenge":challenge,"code_challenge_method":"S256",
        "resource":MCP})
    auth_path=urllib.parse.urlsplit(meta["authorization_endpoint"]).path+"?"+query
    status,head,raw=req(auth_path)
    assert status in (302,303),(status,raw)
    url=head["Location"]
    assert "/owner/approve?ticket=" in url,url
    status,_,raw=req(url)
    assert status==200 and b"password" in raw,(status,raw)
    ticket=urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["ticket"][0]
    status,head,raw=req("/owner/approve","POST",{"ticket":ticket,"password":OWNER},form=True)
    assert status==303,(status,raw)
    callback=head["Location"]
    assert callback.startswith(CALLBACK),callback
    code=urllib.parse.parse_qs(urllib.parse.urlsplit(callback).query)["code"][0]
    # The browser may repost the form: repeat must return the exact redirect,
    # not an expired-ticket error or a second OAuth authorization code.
    repeated, repeated_headers, raw=req(
        "/owner/approve", "POST", {"ticket":ticket,"password":OWNER}, form=True
    )
    assert repeated==303 and repeated_headers["Location"]==callback,(repeated,raw)
    token_path=urllib.parse.urlsplit(meta["token_endpoint"]).path
    status,_,raw=req(token_path,"POST",{
        "grant_type":"authorization_code","client_id":client_id,
        "client_secret":client["client_secret"],"code":code,
        "redirect_uri":CALLBACK,"code_verifier":verifier,
        "resource":MCP},form=True)
    assert status==200,(status,raw)
    token=js(raw)["access_token"]
    post_exchange, _, response=req(
        "/owner/approve", "POST", {"ticket":ticket,"password":OWNER}, form=True
    )
    assert post_exchange==200 and "Autorização concluída" in response.decode(), (post_exchange,response)
    status,result=mcp_call(token,"initialize",11,{"protocolVersion":"2025-06-18",
        "capabilities":{},"clientInfo":{"name":"OAuth CI","version":"1"}})
    assert status==200 and result["result"]["serverInfo"]["name"]=="Omni Host Sampling (Experimental)",(status,result)
    mcp_call(token,"notifications/initialized",None,notify=True)
    status,tools=mcp_call(token,"tools/list",12,{})
    assert status==200,(status,tools)
    names={x["name"] for x in tools["result"]["tools"]}
    assert names=={"agent","spawn_agent","task"},names
    print("OAUTH2_MCP_PASS",json.dumps({
        "oauth_metadata":True,"pkce_s256":True,"owner_approval":True,
        "bearer_oauth":True,"tools":sorted(names),"model_calls":0,
    }),flush=True)

if __name__=="__main__":main()
