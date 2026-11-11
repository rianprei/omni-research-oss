#!/usr/bin/env python3
"""Minimal MCP stdio JSON-RPC server; no pip dependencies.

Protocol: newline-delimited UTF-8 JSON-RPC, stdout reserved for protocol.
"""
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
import engine as e
import unified


def arg(name, description, typ='string', default=None, enum=None):
    p={'type':typ,'description':description}
    if enum: p['enum']=enum
    if default is not None: p['default']=default
    if typ=='array':p['items']={'type':'string'}
    return p


def tool(name, description, props, required=()):
    return {'name':name,'description':description,'inputSchema':{'type':'object','properties':props,'required':list(required),'additionalProperties':False},'annotations':{'readOnlyHint':name!='memory_save','destructiveHint':False,'openWorldHint':name in {'omni_research-deep','fetch_source','map_website','compare_evidence','research_bundle','citation_lookup'}}}

TOOLS=[
    tool('omni_research-deep','Search all six source categories via one MCP tool; modes deep, web, academic, code, social, news, datasets, technical and trends.',
         {'query':arg('query','Research question'),
          'mode':arg('mode','Research scope','string','deep',['deep','web','academic','code','social','news','datasets','technical','trends']),
          'providers':arg('providers','Subset: web, academic, code, social, news, datasets','array'),
          'limit':arg('limit','Maximum merged results','integer',16),
          'locale':arg('locale','Locale for news','string','en-US'),
          'code_mode':arg('code_mode','GitHub search type','string','repositories',['repositories','issues','users','code']),
          'dataset_source':arg('dataset_source','Dataset catalog','string','both',['both','huggingface','zenodo']),
          'web_engines':arg('web_engines','Specific web engines','array'),
          'academic_sources':arg('academic_sources','Specific scholarly providers','array'),
          'social_sources':arg('social_sources','Specific communities','array')},['query']),
    tool('fetch_source','Extract public HTTP(S) documents and PDFs.',
         {'url':arg('url','Public URL'),'max_chars':arg('max_chars','Returned text characters','integer',16000)},['url']),
    tool('map_website','Crawl a bounded number of public pages on one host.',
         {'url':arg('url','Public URL'),'max_pages':arg('max_pages','Pages','integer',6)},['url']),
    tool('read_document','Read local research documents within OMNI_ALLOWED_DIRS.',
         {'path':arg('path','Local path'),'max_chars':arg('max_chars','Returned characters','integer',16000)},['path']),
    tool('compare_evidence','Collect relevant passages from public URLs.',
         {'claim':arg('claim','Atomic claim'),'urls':arg('urls','Source URLs','array')},['claim','urls']),
    tool('citation_lookup','Resolve DOI metadata with Crossref.',{'doi':arg('doi','DOI')},['doi']),
    tool('memory_save','Store local research note.',{'topic':arg('topic','Topic'),'body':arg('body','Body')},['topic','body']),
    tool('memory_search','Search local notes.',{'query':arg('query','Terms'),'limit':arg('limit','Results','integer',10)},['query']),
    tool('health_check','Local provider configuration and status.',{}),
]



def bounds(v,lo,hi):
    if not isinstance(v,int) or isinstance(v,bool): raise ValueError('Expected integer')
    return min(hi,max(lo,v))


def dispatch(name,a):
    if name=='omni_research-deep':
        return unified.research(query=a['query'], mode=a.get('mode','deep'),
            providers=a.get('providers'), limit=bounds(a.get('limit',16),1,30),
            locale=a.get('locale','en-US'), code_mode=a.get('code_mode','repositories'),
            dataset_source=a.get('dataset_source','both'), web_engines=a.get('web_engines'),
            academic_sources=a.get('academic_sources'), social_sources=a.get('social_sources'))
    if name=='fetch_source':return e.extract_url(a['url'],bounds(a.get('max_chars',16000),100,60000))
    if name=='map_website':return e.crawl_site(a['url'],bounds(a.get('max_pages',6),1,15))
    if name=='read_document':return e.document_read(a['path'],bounds(a.get('max_chars',16000),100,60000))
    if name=='compare_evidence':return e.evidence_compare(a['claim'],a['urls'])
    if name=='citation_lookup':return e.citation_lookup(a['doi'])
    if name=='memory_save':return e.save_note(a['topic'],a['body'])
    if name=='memory_search':return e.search_notes(a['query'],bounds(a.get('limit',10),1,50))
    if name=='health_check':return e.health()
    raise ValueError('Unknown tool '+name)


def handle(req):
    method=req.get('method','')
    if method=='initialize':
        offered=req.get('params',{}).get('protocolVersion','2025-06-18')
        proto=offered if offered in ('2024-11-05','2025-03-26','2025-06-18','2025-11-25') else '2025-06-18'
        return {'protocolVersion':proto,'capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'omni-research-oss','version':'1.4.0'}}
    if method=='ping':return {}
    if method=='tools/list':return {'tools':TOOLS}
    if method=='tools/call':
        params=req.get('params',{}); name=params.get('name','');a=params.get('arguments') or {}
        try:
            if name not in {x['name'] for x in TOOLS}: raise ValueError('Tool not found')
            required=next(x for x in TOOLS if x['name']==name)['inputSchema']['required']
            for k in required:
                if k not in a: raise ValueError('Missing argument '+k)
            out=dispatch(name,a)
            # structuredContent preserves typing; text provides broad MCP-client compatibility
            return {'content':[{'type':'text','text':json.dumps(out,ensure_ascii=False,default=str)}], 'structuredContent':out}
        except Exception as exc:
            return {'content':[{'type':'text','text':f'{type(exc).__name__}: {str(exc)[:500]}'}], 'isError':True}
    if method.startswith('notifications/'):
        return None
    raise ValueError('Unsupported method '+method)


def main():
    for line in sys.stdin.buffer:
        if not line.strip(): continue
        ident=None
        try:
            req=json.loads(line)
            ident=req.get('id')
            result=handle(req)
            if ident is None or result is None: continue
            response={'jsonrpc':'2.0','id':ident,'result':result}
        except Exception as exc:
            response={'jsonrpc':'2.0','id':ident,'error':{'code':-32603,'message':str(exc)[:500]}}
        sys.stdout.write(json.dumps(response,ensure_ascii=False,separators=(',',':'))+'\n')
        sys.stdout.flush()

if __name__=='__main__':main()
