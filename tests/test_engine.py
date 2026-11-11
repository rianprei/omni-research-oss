import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE/'server'))
import engine as e

class EngineTest(unittest.TestCase):
    def test_url_security(self):
        for url in ('file:///etc/passwd','ftp://example.org/a','http://127.0.0.1/x','http://192.168.0.1/','http://[::1]/','http://localhost','https://user:pass@example.com'):
            with self.subTest(url=url),self.assertRaises(ValueError):e.safe_url(url,check_dns=False)
        self.assertEqual(e.safe_url('https://example.org/a#b',check_dns=False),'https://example.org/a')

    def test_clean_html_and_url(self):
        text,links=e.clean_html('<main><h1>Header</h1><script>evil</script><p>Usable text</p><a href="https://x.org/a">A link</a></main>')
        self.assertIn('Usable text',text)
        self.assertNotIn('evil',text)
        self.assertEqual(links[0]['title'],'A link')
        self.assertEqual(e.clean_url('https://x.org/a/?utm_source=x&y=1#h'),'https://x.org/a?y=1')

    def test_ddg_search_html(self):
        h='<div><a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpaper">Research paper title</a></div>'
        items=e.items_from_html(h,'duckduckgo')
        self.assertEqual(items[0]['url'],'https://example.com/paper')

    def test_normalize_preserves_provenance(self):
        a=e.normalize([{'url':'https://a.org/?utm_source=x','title':'Item','source':'web'},{'url':'https://a.org/','title':'Duplicate','source':'arxiv'}])
        self.assertEqual(len(a),1)
        self.assertEqual(a[0]['sources'],['web','arxiv'])

    def test_rank_fusion_determinism(self):
        with patch.object(e,'web_engine',side_effect=lambda q,s,n:[{'url':'https://z.org','title':'Z article text','source':s},{'url':'https://a.org','title':'A article text','source':s}] if s=='bing' else [{'url':'https://a.org','title':'A article text','source':s}]):
            with patch.object(e,'_cache_get',return_value=None),patch.object(e,'_cache_put'):
                r=e.web_search('test',['bing','wikipedia'],5)
        self.assertEqual(r['results'][0]['url'],'https://a.org/')
        self.assertEqual(len(r['results'][0]['engines']),2)

    def test_deep_bundle_failures_visible(self):
        with patch.object(e,'web_search',return_value={'results':[{'title':'A','url':'https://a.org/','source':'web'}]}),patch.object(e,'academic_search',side_effect=RuntimeError('mock unavailable')),patch.object(e,'code_search',return_value={'results':[]}),patch.object(e,'social_search',return_value={'results':[]}),patch.object(e,'news_search',return_value={'results':[]}):
            r=e.deep_research('test','general')
        self.assertEqual(r['sources'][0]['citation_id'],'S1')
        self.assertIn('papers',r['provider_errors'])

    def test_doc_and_memory(self):
        with tempfile.TemporaryDirectory() as td:
            p=pathlib.Path(td)/'doc.md'; p.write_text('Research test text',encoding='utf-8')
            with patch.dict(os.environ,{'OMNI_ALLOWED_DIRS':td}):
                self.assertIn('Research test',e.document_read(str(p))['text'])
                with self.assertRaises(ValueError): e.document_read('/etc/passwd')
            with patch.object(e,'DB_PATH',pathlib.Path(td)/'test.sqlite'):
                e.save_note('FTS test topic','A research note about fusion')
                self.assertEqual(len(e.search_notes('fusion')['results']),1)

    def test_citation_comparison_never_asserts_proof(self):
        with patch.object(e,'extract_url',return_value={'text':'In 2024, a study included 120 participants.'}):
            result=e.evidence_compare('The study has 120 participants',['https://example.org/x'])
        self.assertEqual(result['verdict'],'UNVERIFIED')

class ProtocolTest(unittest.TestCase):
    def test_mcp_protocol(self):
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}},{'jsonrpc':'2.0','id':2,'method':'tools/list'},{'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'health_check','arguments':{}}}]
        p=subprocess.run([sys.executable,str(HERE/'server/main.py')],input='\n'.join(json.dumps(m) for m in messages)+'\n',capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        data=[json.loads(x) for x in p.stdout.splitlines()]
        self.assertEqual(len(data),3)
        self.assertGreaterEqual(len(data[1]['result']['tools']),15)
        self.assertIn('structuredContent',data[2]['result'])

if __name__=='__main__': unittest.main()
