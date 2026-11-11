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


def arg(name, description, typ='string', default=None, enum=None):
    p={'type':typ,'description':description}
    if enum: p['enum']=enum
    if default is not None: p['default']=default
    if typ=='array':p['items']={'type':'string'}
    return p


def tool(name, description, props, required=()):
    return {'name':name,'description':description,'inputSchema':{'type':'object','properties':props,'required':list(required),'additionalProperties':False},'annotations':{'readOnlyHint':name!='memory_save','destructiveHint':False,'openWorldHint':name in {'web_search','academic_search','code_search','social_search','news_search','dataset_search','fetch_source','map_website','compare_evidence','research_bundle','citation_lookup'}}}

TOOLS=[
    tool('web_search','Multi-engine public web search with reciprocal-rank fusion, dedup, provenance and failure reporting; no paid API key.',{'query':arg('q','Search terms'),'engines':arg('e','Optional engine names: duckduckgo, bing, mojeek, wikipedia, searxng','array'),'limit':arg('l','Maximum results 1-30','integer',12)},['query']),
    tool('academic_search','Find scholarly works across OpenAlex, Crossref, arXiv and PubMed, including identifiers and available metadata.',{'query':arg('q','Research question'),'sources':arg('s','Optional: openalex, crossref, arxiv, pubmed','array'),'limit':arg('l','Results per source 1-25','integer',8)},['query']),
    tool('code_search','Search public GitHub repositories, issues or users. Code-search endpoint requires optional GitHub token.',{'query':arg('q','GitHub search syntax'),'mode':arg('m','GitHub index','string','repositories',['repositories','issues','users','code']),'limit':arg('l','Maximum items','integer',10)},['query']),
    tool('social_search','Search Hacker News, Stack Overflow and publicly accessible Reddit discussions; opinions are not verified facts.',{'query':arg('q','Search terms'),'sources':arg('s','hackernews, stackoverflow, reddit','array'),'limit':arg('l','Per-source maximum','integer',8)},['query']),
    tool('news_search','Read Google News public RSS search. Returns publisher, date and source URLs; published dates need original-page verification.',{'query':arg('q','Search terms'),'limit':arg('l','Maximum results','integer',12),'locale':arg('locale','Language-region for Google News feed','string','en-US')},['query']),
    tool('dataset_search','Discover openly indexed datasets on Hugging Face or Zenodo without credentials.',{'query':arg('q','Search terms'),'source':arg('s','Dataset catalog','string','huggingface',['huggingface','zenodo']),'limit':arg('l','Maximum items','integer',10)},['query']),
    tool('fetch_source','Fetch and clean an HTTP(S) document; SSRF guard blocks private/localhost addresses, 2MB response cap. PDF requires optional pypdf.',{'url':arg('u','Public URL'),'max_chars':arg('max','Maximum returned text characters','integer',16000)},['url']),
    tool('map_website','Bounded crawl of same-host public pages, respecting robots.txt when available; no browser rendering.',{'url':arg('u','Public site URL'),'max_pages':arg('n','Pages to retrieve, maximum 15','integer',6)},['url']),
    tool('read_document','Read local .txt/.md/.csv/.json/.html/.docx/.pptx/.xlsx and optional .pdf. Restrict to OMNI_ALLOWED_DIRS.',{'path':arg('p','Absolute or relative local file path'),'max_chars':arg('c','Maximum characters','integer',16000)},['path']),
    tool('compare_evidence','Collect relevant passages and numerical/date signals from 1-8 URLs for a claim, without asserting a verdict.',{'claim':arg('c','Atomic testable claim'),'urls':arg('urls','Public source URLs','array')},['claim','urls']),
    tool('research_bundle','Multi-source parallel evidence collection with stable citation IDs and adversarial research protocol. Final report synthesis is done by the caller model.',{'topic':arg('t','Research topic'),'mode':arg('m','Research emphasis','string','general',['general','academic','technical','trends','news']),'max_results':arg('n','Maximum returned items','integer',16)},['topic']),
    tool('citation_lookup','Resolve a DOI via Crossref and return bibliographic metadata plus an approximate APA reference.',{'doi':arg('doi','A valid DOI, e.g. 10.1038/xxxxx')},['doi']),
    tool('memory_save','Save a user-provided research note in a local SQLite database under OMNI_STATE_DIR. No cloud upload.',{'topic':arg('t','Note topic'),'body':arg('b','Note text')},['topic','body']),
    tool('memory_search','Query locally saved research notes using SQLite FTS5 where available.',{'query':arg('q','Terms or FTS5 query'),'limit':arg('l','Maximum notes','integer',10)},['query']),
    tool('health_check','Show available providers, optional credentials, configuration and public service limitations.',{}),
]


def bounds(v,lo,hi):
    if not isinstance(v,int) or isinstance(v,bool): raise ValueError('Expected integer')
    return min(hi,max(lo,v))


def dispatch(name,a):
    if name=='web_search':return e.web_search(a['query'],a.get('engines'),bounds(a.get('limit',12),1,30))
    if name=='academic_search':return e.academic_search(a['query'],a.get('sources'),bounds(a.get('limit',8),1,25))
    if name=='code_search':return e.code_search(a['query'],a.get('mode','repositories'),bounds(a.get('limit',10),1,30))
    if name=='social_search':return e.social_search(a['query'],a.get('sources'),bounds(a.get('limit',8),1,30))
    if name=='news_search':return e.news_search(a['query'],bounds(a.get('limit',12),1,30),a.get('locale','en-US'))
    if name=='dataset_search':return e.dataset_search(a['query'],a.get('source','huggingface'),bounds(a.get('limit',10),1,25))
    if name=='fetch_source':return e.extract_url(a['url'],bounds(a.get('max_chars',16000),100,60000))
    if name=='map_website':return e.crawl_site(a['url'],bounds(a.get('max_pages',6),1,15))
    if name=='read_document':return e.document_read(a['path'],bounds(a.get('max_chars',16000),100,60000))
    if name=='compare_evidence':return e.evidence_compare(a['claim'],a['urls'])
    if name=='research_bundle':return e.deep_research(a['topic'],a.get('mode','general'),bounds(a.get('max_results',16),1,30))
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
        return {'protocolVersion':proto,'capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'omni-research-oss','version':'1.3.0'}}
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
