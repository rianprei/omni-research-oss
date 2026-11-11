"""OmniResearch OSS: dependency-free research engine (Python 3.10+).

No provider credentials are required. Public endpoints can rate limit or fail.
This implementation does not use an in-server LLM, and never certifies a claim.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import html
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import time
from typing import Any
import urllib.error
import urllib.parse as up
import urllib.request as ur
import urllib.robotparser
import xml.etree.ElementTree as ET
import zipfile

USER_AGENT = "OmniResearchOSS/1.0 (+local research client; contact: user)"
TIMEOUT = int(os.getenv("OMNI_TIMEOUT", "12"))
MAX_BODY = 2_000_000
STATE_DIR = Path(os.getenv("OMNI_STATE_DIR", str(Path.home() / ".local/share/omni-research-oss"))).expanduser()
STATE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = STATE_DIR / "cache.sqlite3"


def _db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, expiry REAL, payload TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, topic TEXT, body TEXT, created TEXT)")
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(topic,body,content='notes',content_rowid='id')")
        con.executescript("""CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
            INSERT INTO notes_fts(rowid,topic,body) VALUES (new.id,new.topic,new.body); END;""")
    except sqlite3.OperationalError:
        pass
    return con


def _cache_get(key):
    with _db() as con:
        row = con.execute("SELECT payload,expiry FROM cache WHERE key=?", (key,)).fetchone()
    if row and row[1] > time.time():
        return json.loads(row[0])
    return None


def _cache_put(key, value, ttl=900):
    try:
        with _db() as con:
            con.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (key, time.time()+ttl, json.dumps(value,ensure_ascii=False)))
    except (sqlite3.Error, OSError):
        pass


def safe_url(url: str, check_dns=True) -> str:
    parsed = up.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only public HTTP(S) URLs without credentials are allowed")
    host = parsed.hostname.rstrip('.').lower()
    if host in ("localhost", "localhost.localdomain") or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Private network access denied")
    try:
        ip = ipaddress.ip_address(host.strip('[]'))
        if not ip.is_global:
            raise ValueError("Private/reserved IP denied")
    except ValueError as err:
        if "denied" in str(err):
            raise
        if check_dns:
            addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                raise ValueError("DNS contains a private/reserved address")
    return up.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/', parsed.query, ''))


class GuardedRedirect(ur.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = ur.build_opener(GuardedRedirect())


def download(url: str, *, max_bytes=MAX_BODY, accept='text/html,application/json,application/xml,text/xml,text/plain,*/*') -> tuple[bytes, str, str]:
    safe_url(url)
    req = ur.Request(url, headers={"User-Agent":USER_AGENT,"Accept":accept})
    with OPENER.open(req, timeout=TIMEOUT) as resp:
        typ = resp.headers.get('Content-Type', 'application/octet-stream')
        size = resp.headers.get('Content-Length')
        if size and int(size) > max_bytes:
            raise ValueError("Response exceeds byte limit")
        data = resp.read(max_bytes+1)
        if len(data) > max_bytes:
            raise ValueError("Response exceeds byte limit")
        return data, typ, resp.geturl()


def read_text(url: str, *, max_bytes=MAX_BODY):
    raw, typ, final = download(url, max_bytes=max_bytes)
    enc = re.search(r'charset=([\w-]+)', typ, re.I)
    return raw.decode(enc.group(1) if enc else 'utf-8', errors='replace'), typ, final


def jget(url):
    data, _, _ = download(url, max_bytes=MAX_BODY, accept='application/json')
    return json.loads(data)


class LinksParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links=[]; self._link=None; self._text=[]
        self._skip=0; self.body=[]; self.in_main=0
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag in ('script','style','noscript','svg','nav','footer','header'):
            self._skip+=1
        if tag in ('main','article'):
            self.in_main+=1
        if tag=='a' and self._skip==0 and a.get('href'):
            self._link=a; self._text=[]
        if tag in ('p','h1','h2','h3','li','blockquote','tr','br') and self._skip==0:
            self.body.append('\n')
    def handle_data(self, data):
        if self._skip==0:
            self.body.append(data)
            if self._link is not None: self._text.append(data)
    def handle_endtag(self, tag):
        if tag=='a' and self._link is not None:
            title=' '.join(' '.join(self._text).split())
            if title:
                self.links.append({'href':self._link.get('href',''),'title':title,'class':self._link.get('class','')})
            self._link=None; self._text=[]
        if tag in ('script','style','noscript','svg','nav','footer','header') and self._skip: self._skip-=1
        if tag in ('main','article') and self.in_main: self.in_main-=1


def clean_html(source: str) -> tuple[str,list]:
    p=LinksParser(); p.feed(source)
    text=' '.join(''.join(p.body).replace('\xa0',' ').split())
    return text, p.links


def clean_url(url: str):
    p=up.urlsplit(url)
    if p.hostname in ('duckduckgo.com','www.duckduckgo.com'):
        args=up.parse_qs(p.query)
        if args.get('uddg'): url=args['uddg'][0]; p=up.urlsplit(url)
    args=up.parse_qsl(p.query,keep_blank_values=True)
    args=[(k,v) for k,v in args if not (k.startswith('utm_') or k in ('fbclid','gclid','ref'))]
    return up.urlunsplit((p.scheme,p.netloc.lower(),p.path.rstrip('/') or '/',up.urlencode(args),''))


def items_from_html(body: str, engine: str, limit=12):
    parser=LinksParser(); parser.feed(body)
    out=[]
    for link in parser.links:
        href=html.unescape(link['href'])
        if href.startswith('//'): href='https:'+href
        if href.startswith('/'): continue
        if not href.startswith(('https://','http://')): continue
        href=clean_url(href)
        host=up.urlsplit(href).hostname or ''
        if host.endswith(('duckduckgo.com','bing.com','google.com')): continue
        # DuckDuckGo's results use result__a; Bing uses organic result headings,
        # other engines have no guaranteed markup. Treat results as unverified.
        if engine=='duckduckgo' and not any(mark in link['class'] for mark in ('result__a','result-link')): continue
        if len(link['title'])<9: continue
        out.append({'title':link['title'][:200], 'url':href,'snippet':'', 'source':engine})
        if len(out)>=limit: break
    return out


def web_engine(query, engine, limit=10):
    q=up.quote_plus(query)
    if engine=='duckduckgo':
        url=f'https://lite.duckduckgo.com/lite/?q={q}'
    elif engine=='bing':
        url=f'https://www.bing.com/search?q={q}&count={min(limit,30)}'
    elif engine=='mojeek':
        url=f'https://www.mojeek.com/search?q={q}'
    elif engine=='searxng':
        base=os.getenv('OMNI_SEARXNG_URL','').rstrip('/')
        if not base: raise ValueError('OMNI_SEARXNG_URL not configured')
        # Only permit loopback HTTP as an explicit local opt-in; all other instances
        # go through the public HTTP(S) fetch guard.
        host=up.urlsplit(base).hostname
        endpoint=f'{base}/search?q={q}&format=json'
        if base.startswith('http://') and host in ('localhost','127.0.0.1','::1'):
            req=ur.Request(endpoint,headers={'User-Agent':USER_AGENT,'Accept':'application/json'})
            with OPENER.open(req,timeout=TIMEOUT) as resp:
                data=json.loads(resp.read(MAX_BODY))
        elif base.startswith('https://'):
            data=jget(endpoint)
        else:
            raise ValueError('SearXNG requires public HTTPS or explicitly configured loopback HTTP')
        return [dict(title=r.get('title',''),url=r.get('url',''),snippet=r.get('content',''),source='searxng') for r in data.get('results',[])[:limit]]
    elif engine=='google-news':
        # Public RSS is reliable on cloud hosting; articles are time-sensitive
        # news discovery, not a general-purpose web index.
        return news_search(query,limit=limit)['results']
    elif engine=='wikipedia':
        data=jget('https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srsearch='+q+'&srlimit='+str(limit))
        return [dict(title=x['title'],url='https://en.wikipedia.org/wiki/'+up.quote(x['title'].replace(' ','_')),snippet=clean_html(x.get('snippet',''))[0],source='wikipedia') for x in data.get('query',{}).get('search',[])]
    else: raise ValueError('Unknown engine '+engine)
    body,_,_=read_text(url)
    return items_from_html(body,engine,limit)


def normalize(items):
    out=[]; seen={}
    for row in items:
        if not isinstance(row,dict): continue
        url=row.get('url','')
        try:
            u=clean_url(url)
            if up.urlsplit(u).scheme not in ('https','http'): continue
        except Exception: continue
        if u in seen:
            old=out[seen[u]]
            sources=old.setdefault('sources',[old.get('source','unknown')])
            if row.get('source') not in sources: sources.append(row.get('source','unknown'))
            continue
        item={k:v for k,v in row.items() if v is not None}
        item['url']=u
        seen[u]=len(out); out.append(item)
    return out


def web_search(query, engines=None, limit=12):
    engines=engines or ['wikipedia','google-news']
    engines=[x for x in engines if x in ('duckduckgo','bing','mojeek','wikipedia','google-news','searxng')]
    if not engines: raise ValueError('No valid search engines')
    key=json.dumps(['web',query,engines,limit]); cached=_cache_get(key)
    if cached is not None: return cached
    errors={}; batches={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(5,len(engines))) as pool:
        fs={pool.submit(web_engine,query,e,limit):e for e in engines}
        for f in concurrent.futures.as_completed(fs):
            e=fs[f]
            try: batches[e]=f.result()
            except Exception as exc: errors[e]=str(exc)[:200]
    # Reciprocal rank fusion, deterministic tie break
    scores={}; entries={}; providers={}
    for e in engines:
        for rank,item in enumerate(normalize(batches.get(e,[]))):
            url=item['url']; scores[url]=scores.get(url,0)+1/(60+rank+1)
            entries.setdefault(url,item)
            providers.setdefault(url,[])
            if e not in providers[url]: providers[url].append(e)
    results=[]
    for url in sorted(scores,key=lambda u:(-scores[u],u))[:limit]:
        x=dict(entries[url]); x['engines']=providers[url]; x['rrf_score']=round(scores[url],6); results.append(x)
    answer={'query':query,'results':results,'errors':errors,'engines_attempted':engines,'note':'Rank is relevance heuristic; empty/blocked engines do not imply absence.'}
    if results: _cache_put(key,answer)
    return answer


def _parse_date(value):
    if not value: return None
    try:
        if isinstance(value,list): return '-'.join(str(z).zfill(2) for z in value[0][:3])
        return str(value)[:30]
    except Exception: return None


def academic_search(query, sources=None, limit=8):
    sources=sources or ['openalex','crossref','arxiv','pubmed']
    sources=[x for x in sources if x in ('openalex','crossref','arxiv','pubmed')]
    errors={}; batches={}; q=up.quote_plus(query)
    def go(src):
        if src=='openalex':
            d=jget(f'https://api.openalex.org/works?search={q}&per-page={min(limit,25)}')
            results=[]
            for x in d.get('results',[]):
                doi=x.get('doi') or x.get('id')
                results.append({'title':x.get('title',''),'url':doi,'source':'openalex','year':x.get('publication_year'),'cited_by_count':x.get('cited_by_count'),'doi':x.get('doi'),'published_at':x.get('publication_date'),'authors':[a.get('author',{}).get('display_name') for a in x.get('authorships',[])[:6]]})
            return results
        if src=='crossref':
            d=jget(f'https://api.crossref.org/works?query={q}&rows={min(limit,25)}')
            return [{'title':(x.get('title') or [''])[0], 'url':x.get('DOI') and 'https://doi.org/'+x['DOI'] or x.get('URL',''), 'source':'crossref', 'doi':x.get('DOI'), 'published_at':_parse_date(x.get('published',{}).get('date-parts')), 'authors':[(a.get('given','')+' '+a.get('family','')).strip() for a in x.get('author',[])[:6]]} for x in d.get('message',{}).get('items',[])]
        if src=='arxiv':
            body,_,_=read_text(f'https://export.arxiv.org/api/query?search_query=all:{up.quote(query)}&start=0&max_results={min(limit,25)}')
            root=ET.fromstring(body); ns={'a':'http://www.w3.org/2005/Atom'}
            return [{'title':' '.join((x.findtext('a:title','',ns)).split()),'url':x.findtext('a:id','',ns),'snippet':' '.join(x.findtext('a:summary','',ns).split())[:500],'published_at':x.findtext('a:published','',ns)[:10],'authors':[a.findtext('a:name','',ns) for a in x.findall('a:author',ns)],'source':'arxiv'} for x in root.findall('a:entry',ns)]
        if src=='pubmed':
            d=jget(f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={q}&retmode=json&retmax={min(limit,25)}')
            ids=d.get('esearchresult',{}).get('idlist',[])
            if not ids: return []
            d=jget('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id='+','.join(ids))
            return [{'title':d['result'][x].get('title',''),'url':'https://pubmed.ncbi.nlm.nih.gov/'+x+'/','source':'pubmed','published_at':d['result'][x].get('pubdate'),'authors':[a.get('name') for a in d['result'][x].get('authors',[])[:6]]} for x in ids if x in d.get('result',{})]
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(sources) or 1) as pool:
        fs={pool.submit(go,s):s for s in sources}
        for f in concurrent.futures.as_completed(fs):
            try: batches[fs[f]]=f.result()
            except Exception as e: errors[fs[f]]=str(e)[:200]
    combined=normalize([item for source in sources for item in batches.get(source,[])])
    return {'query':query,'results':combined[:limit*2],'errors':errors,'sources_attempted':sources,'note':'Citation counts are provider metadata, not evidence of factual correctness.'}


def code_search(query, mode='repositories',limit=10):
    if mode not in ('repositories','issues','users','code'):
        raise ValueError('mode must be repositories, issues, users, or code')
    if mode=='code' and not os.getenv('GITHUB_TOKEN'):
        return {'results':[],'error':'GitHub code search requires a GitHub token; repo/issue search remains free without one.'}
    url=f'https://api.github.com/search/{mode}?q={up.quote_plus(query)}&per_page={min(limit,30)}'
    token=os.getenv('GITHUB_TOKEN')
    if token:
        req=ur.Request(url,headers={'Accept':'application/vnd.github+json','Authorization':'Bearer '+token,'User-Agent':USER_AGENT})
        safe_url(url)
        with OPENER.open(req,timeout=TIMEOUT) as resp: d=json.loads(resp.read(MAX_BODY))
    else: d=jget(url)
    items=[]
    for x in d.get('items',[]):
        items.append({'title':x.get('full_name') or x.get('title') or x.get('login') or x.get('name',''), 'url':x.get('html_url') or x.get('url'), 'snippet':(x.get('description') or x.get('body') or '')[:400] or '', 'source':'github', 'stars':x.get('stargazers_count'), 'updated_at':x.get('updated_at'), 'license':(x.get('license') or {}).get('spdx_id') if isinstance(x.get('license'),dict) else None})
    return {'query':query,'mode':mode,'results':normalize(items),'incomplete_results':d.get('incomplete_results',False)}


def social_search(query, sources=None,limit=10):
    sources=sources or ['hackernews','stackoverflow']
    sources=[x for x in sources if x in ('hackernews','stackoverflow','reddit')]
    errors={}; batches={}; q=up.quote_plus(query)
    def go(src):
        if src=='hackernews':
            d=jget(f'https://hn.algolia.com/api/v1/search?query={q}&hitsPerPage={min(limit,30)}')
            return [{'title':x.get('title') or x.get('story_title') or '', 'url':x.get('url') or ('https://news.ycombinator.com/item?id='+str(x.get('objectID',''))), 'snippet':(x.get('comment_text') or '')[:400],'source':'hackernews','score':x.get('points'),'published_at':x.get('created_at')} for x in d.get('hits',[])]
        if src=='stackoverflow':
            d=jget(f'https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=relevance&q={q}&site=stackoverflow&pagesize={min(limit,30)}')
            return [{'title':html.unescape(x.get('title','')),'url':x.get('link',''),'source':'stackoverflow','score':x.get('score'),'answered':x.get('is_answered'),'published_at':dt.datetime.fromtimestamp(x['creation_date'],dt.timezone.utc).isoformat() if x.get('creation_date') else None} for x in d.get('items',[])]
        if src=='reddit':
            d=jget(f'https://www.reddit.com/search.json?q={q}&sort=relevance&limit={min(limit,30)}&raw_json=1')
            return [{'title':x['data'].get('title',''),'url':'https://www.reddit.com'+x['data'].get('permalink',''),'snippet':x['data'].get('selftext','')[:400],'source':'reddit','score':x['data'].get('score'),'subreddit':x['data'].get('subreddit')} for x in d.get('data',{}).get('children',[])]
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(sources) or 1) as pool:
        fs={pool.submit(go,s):s for s in sources}
        for f in concurrent.futures.as_completed(fs):
            try: batches[fs[f]]=f.result()
            except Exception as e: errors[fs[f]]=str(e)[:200]
    return {'query':query,'results':normalize([i for s in sources for i in batches.get(s,[])])[:limit*len(sources)],'errors':errors,'sources_attempted':sources}


def news_search(query,limit=15,locale='en-US'):
    if not isinstance(locale,str) or not re.fullmatch(r'[a-zA-Z]{2,3}-[a-zA-Z]{2}',locale):
        raise ValueError('locale must be a language-region such as pt-BR or en-US')
    lang,region=locale.split('-')
    lang,region=lang.lower(),region.upper()
    url=f'https://news.google.com/rss/search?q={up.quote_plus(query)}&hl={up.quote(lang+"-"+region)}&gl={region}&ceid={region}:{lang}'
    body,_,_=read_text(url)
    root=ET.fromstring(body)
    items=[]
    for x in root.findall('.//item')[:limit]:
        items.append({'title':x.findtext('title',''), 'url':x.findtext('link',''), 'published_at':x.findtext('pubDate',''), 'source':'google-news-rss','publisher':x.findtext('source','')})
    return {'query':query,'results':normalize(items),'note':'Publication dates are feed metadata; verify at the original publisher.'}


def extract_url(url, max_chars=16000):
    data,typ,final=download(url,max_bytes=MAX_BODY)
    if 'pdf' in typ.lower() or final.lower().endswith('.pdf'):
        try:
            from pypdf import PdfReader
            from io import BytesIO
            text='\n'.join(p.extract_text() or '' for p in PdfReader(BytesIO(data)).pages[:30])
        except ImportError:
            return {'url':final,'media_type':'pdf','error':'PDF parsing optional: pip install pypdf','bytes':len(data)}
    else:
        plain=data.decode('utf-8',errors='replace')
        text=clean_html(plain)[0] if 'html' in typ.lower() else plain
    return {'url':final,'media_type':typ,'text':text[:max_chars],'chars_total':len(text),'truncated':len(text)>max_chars}


def crawl_site(url,max_pages=6):
    safe_url(url); host=up.urlsplit(url).hostname
    rp=urllib.robotparser.RobotFileParser(); rp.set_url(f'{up.urlsplit(url).scheme}://{host}/robots.txt')
    robots_loaded=False
    try:
        robots,_,_=read_text(rp.url)
        rp.parse(robots.splitlines()); robots_loaded=True
    except Exception: pass
    queue=[url]; seen=set(); docs=[]; errors=[]
    while queue and len(docs)<min(max_pages,15):
        current=queue.pop(0); canonical=clean_url(current)
        if canonical in seen: continue
        seen.add(canonical)
        if robots_loaded and not rp.can_fetch(USER_AGENT,current): continue
        try:
            body,typ,final=read_text(current)
            if 'html' not in typ.lower(): continue
            text,links=clean_html(body)
            docs.append({'url':final,'title':(re.search(r'<title[^>]*>(.*?)</title>',body,re.I|re.S).group(1) if re.search(r'<title[^>]*>(.*?)</title>',body,re.I|re.S) else final)[:180], 'text':text[:3000]})
            for x in links:
                nexturl=up.urljoin(final,x['href'])
                if up.urlsplit(nexturl).hostname==host and clean_url(nexturl) not in seen and nexturl not in queue:
                    if not re.search(r'\.(?:jpg|gif|png|zip|exe|mp4|pdf)(?:\?|$)',nexturl,re.I): queue.append(nexturl)
        except Exception as e: errors.append({'url':current,'error':str(e)[:140]})
    return {'pages':docs,'errors':errors,'pages_visited':len(seen),'note':'Polite bounded crawl; respects robots.txt if retrieved.'}


def document_read(path, max_chars=16000):
    p=Path(path).expanduser().resolve()
    allowed=[Path(x).expanduser().resolve() for x in os.getenv('OMNI_ALLOWED_DIRS',str(Path.cwd())).split(os.pathsep) if x]
    if not any(p.is_relative_to(root) for root in allowed):
        raise ValueError('Path outside OMNI_ALLOWED_DIRS (default: current working directory)')
    if not p.is_file() or p.stat().st_size>20_000_000:
        raise ValueError('Missing file or file exceeds 20 MB')
    ext=p.suffix.lower(); text=''
    if ext in ('.txt','.md','.csv','.json','.yaml','.yml','.xml','.html','.htm','.log','.rst'):
        text=p.read_text(encoding='utf-8',errors='replace')
        if ext in ('.html','.htm'): text=clean_html(text)[0]
    elif ext in ('.docx','.pptx','.xlsx'):
        names={'docx':re.compile(r'word/document.xml'),'pptx':re.compile(r'ppt/slides/slide\d+\.xml'),'xlsx':re.compile(r'xl/sharedStrings.xml|xl/worksheets/sheet\d+\.xml')}
        pattern=names[ext[1:]]
        with zipfile.ZipFile(p) as z:
            for item in z.infolist():
                if item.file_size>5_000_000: continue
                if pattern.fullmatch(item.filename):
                    root=ET.fromstring(z.read(item)); text+='\n'+' '.join(x.text or '' for x in root.iter() if x.tag.rsplit('}',1)[-1] in ('t','v'))
    elif ext=='.pdf':
        try:
            from pypdf import PdfReader
            text='\n'.join(page.extract_text() or '' for page in PdfReader(str(p)).pages[:100])
        except ImportError: raise ValueError('Install optional pypdf to read PDFs: python -m pip install pypdf')
    else: raise ValueError('Unsupported file format')
    return {'path':str(p),'type':ext,'text':text[:max_chars],'chars_total':len(text),'truncated':len(text)>max_chars}


def evidence_compare(claim, urls, max_chars=5000):
    if not urls or len(urls)>8: raise ValueError('Provide 1-8 URLs')
    words=set(re.findall(r'\b[\w-]{4,}\b',claim.lower()))
    out=[]
    def go(url):
        page=extract_url(url,max_chars=20000)
        body=page.get('text','')
        sentences=re.split(r'(?<=[.!?])\s+',body)
        ranked=sorted(sentences,key=lambda s:len(words & set(re.findall(r'\b[\w-]{4,}\b',s.lower()))),reverse=True)
        snippets=[s[:350] for s in ranked[:3] if s.strip()]
        return {'url':url,'snippets':snippets,'dates':re.findall(r'\b(?:20\d\d|19\d\d)[-/](?:0?[1-9]|1[0-2])(?:[-/](?:[0-2]?\d|3[01]))?\b',body[:max_chars])[:8], 'numbers':re.findall(r'(?<!\w)\d+(?:[.,]\d+)?%?(?!\w)',body[:max_chars])[:15]}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6,len(urls))) as pool:
        fs={pool.submit(go,url):url for url in urls}
        for f in concurrent.futures.as_completed(fs):
            try: out.append(f.result())
            except Exception as e: out.append({'url':fs[f],'error':str(e)[:150]})
    order={u:i for i,u in enumerate(urls)}; out.sort(key=lambda x:order[x['url']])
    return {'claim':claim,'evidence':out,'verdict':'UNVERIFIED','note':'Snippets and dates support manual/LLM citation audit; matches are not proof. Conflicting figures require context, units and date comparison.'}


def deep_research(topic, mode='general', max_results=16):
    if mode not in ('general','academic','technical','trends','news'):
        raise ValueError('mode must be general/academic/technical/trends/news')
    tasks={'web':lambda:web_search(topic,limit=10)}
    if mode in ('general','academic','technical'): tasks['papers']=lambda:academic_search(topic,limit=5)
    if mode in ('general','technical'): tasks['code']=lambda:code_search(topic,limit=6)
    if mode in ('general','trends'): tasks['social']=lambda:social_search(topic,limit=5)
    if mode in ('general','trends','news'): tasks['news']=lambda:news_search(topic,limit=8)
    result={}; errors={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        fs={pool.submit(f):k for k,f in tasks.items()}
        for f in concurrent.futures.as_completed(fs):
            try: result[fs[f]]=f.result()
            except Exception as e: errors[fs[f]]=str(e)[:200]
    source_errors={k:v.get('errors',{}) for k,v in result.items() if isinstance(v,dict) and v.get('errors')}
    items=normalize([item for k in tasks for item in result.get(k,{}).get('results',[])])[:max_results]
    for idx,x in enumerate(items,1): x['citation_id']=f'S{idx}'
    return {'topic':topic,'mode':mode,'searched':list(tasks),'sources':items,'provider_errors':errors,'source_errors':source_errors,'research_protocol':[
      'Decompose the question into testable subquestions and competing hypotheses',
      'Fetch primary documents for material claims; distinguish snippet from full text',
      'Triangulate disputed points using independent sources and matching dates',
      'Run a critic pass that identifies omitted perspectives and numeric discrepancies',
      'Perform URL/citation audit; do not cite unvisited or irrelevant documents',
      'Produce a cited report with explicit uncertainty and scope limitations'],
      'limitations':'Evidence collection only. Final synthesis and claim verification require an agent/analyst; no LLM runs inside this MCP server.'}


def dataset_search(query, source='huggingface',limit=10):
    if source=='huggingface':
        rows=jget('https://huggingface.co/api/datasets?search='+up.quote_plus(query)+'&limit='+str(min(limit,30)))
        return {'results':[{'title':x.get('id',''),'url':'https://huggingface.co/datasets/'+x.get('id',''),'source':'huggingface','downloads':x.get('downloads'),'likes':x.get('likes')} for x in rows]}
    if source=='zenodo':
        d=jget('https://zenodo.org/api/records?q='+up.quote_plus(query)+'&size='+str(min(limit,25)))
        return {'results':[{'title':x.get('metadata',{}).get('title',''),'url':x.get('links',{}).get('html') or 'https://zenodo.org/records/'+str(x.get('id')),'source':'zenodo','doi':x.get('doi')} for x in d.get('hits',{}).get('hits',[])]}
    raise ValueError('source must be huggingface or zenodo')


def citation_lookup(doi):
    doi=doi.strip().removeprefix('https://doi.org/').removeprefix('doi:')
    if not re.match(r'^10\.\d{4,9}/\S+$',doi,re.I): raise ValueError('Invalid DOI')
    d=jget('https://api.crossref.org/works/'+up.quote(doi,safe='/'))['message']
    authors=[(a.get('given','')+' '+a.get('family','')).strip() for a in d.get('author',[])]; year=_parse_date(d.get('published',{}).get('date-parts'))
    return {'doi':doi,'title':(d.get('title') or [''])[0],'authors':authors,'date':year,'publisher':d.get('publisher'), 'journal':(d.get('container-title') or [''])[0], 'url':'https://doi.org/'+doi,'apa_approx':f"{', '.join(authors[:5])} ({year or 'n.d.'}). {(d.get('title') or [''])[0]}. {d.get('publisher','')}. https://doi.org/{doi}", 'note':'APA is an approximate draft, not a standards-certified formatted reference.'}


def save_note(topic, body):
    if len(body)>200_000: raise ValueError('Note exceeds 200k chars')
    created=dt.datetime.now(dt.timezone.utc).isoformat()
    with _db() as con:
        row=con.execute('INSERT INTO notes(topic,body,created) VALUES (?,?,?)',(topic,body,created))
    return {'id':row.lastrowid,'created_at':created,'stored_in':str(DB_PATH)}


def search_notes(query,limit=10):
    with _db() as con:
        try:
            rows=con.execute('SELECT n.id,n.topic,substr(n.body,1,2000),n.created FROM notes_fts JOIN notes n ON n.id=notes_fts.rowid WHERE notes_fts MATCH ? ORDER BY bm25(notes_fts) LIMIT ?', (query,limit)).fetchall()
        except sqlite3.OperationalError:
            rows=con.execute('SELECT id,topic,substr(body,1,2000),created FROM notes WHERE topic LIKE ? OR body LIKE ? LIMIT ?',('%'+query+'%','%'+query+'%',limit)).fetchall()
    return {'results':[dict(id=r[0],topic=r[1],excerpt=r[2],created_at=r[3]) for r in rows]}


def health():
    return {'name':'OmniResearch OSS','version':'1.4.0','python':'stdlib only (optional pypdf for PDF)','state_dir':str(STATE_DIR),'web_engines':['wikipedia','google-news','duckduckgo','bing','mojeek']+(['searxng'] if os.getenv('OMNI_SEARXNG_URL') else []),'free_sources':['OpenAlex','Crossref','arXiv','PubMed','GitHub repositories/issues','HN Algolia','Stack Exchange','Reddit public','Google News RSS','Hugging Face','Zenodo'],'github_token_configured':bool(os.getenv('GITHUB_TOKEN')),'searxng_configured':bool(os.getenv('OMNI_SEARXNG_URL')),'disclaimer':'Public providers impose rate limits, can block bots, and may change APIs.'}
