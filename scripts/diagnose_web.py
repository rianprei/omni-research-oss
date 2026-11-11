#!/usr/bin/env python3
"""Non-sensitive provider reachability diagnostics: summary counts only."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"server"))
import engine as e
import re, urllib.parse, time
samples = {
 "bing":"https://www.bing.com/search?q=African+Union&count=5",
 "duckduckgo_lite":"https://lite.duckduckgo.com/lite/?q=African+Union",
 "brave":"https://search.brave.com/search?q=African+Union",
 "startpage":"https://www.startpage.com/sp/search?query=African+Union",
}
for name,url in samples.items():
 try:
  start=time.monotonic()
  body,typ,final=e.read_text(url)
  links=e.LinksParser();links.feed(body)
  print(name,{"status":"ok","seconds":round(time.monotonic()-start,2),"body_chars":len(body),
     "link_count":len(links.links),"parsed_results":len(e.items_from_html(body,name,5)),
     "has_organic_markup":bool(re.search(r'b_algo|result__a|result-link|result-title|w-gl__result',body,re.I)),
     "has_block_marker":bool(re.search(r'captcha|unusual traffic|verify you are human|access denied',body,re.I)),
     "title_hint":str(re.search(r'<title[^>]*>(.{0,110})</title>',body,re.I|re.S).group(1))[:90] if re.search(r'<title[^>]*>(.{0,110})</title>',body,re.I|re.S) else ""},flush=True)
 except Exception as exc:
  print(name,{"status":"error","error":str(exc)[:160]},flush=True)
