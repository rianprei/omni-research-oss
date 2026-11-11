"""Regression tests for the public Cloud edition; no external HTTP required."""
import asyncio
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
import engine as e
from request_limits import RateLimitedApp


class ProviderRegressionTests(unittest.TestCase):
    def test_github_issue_without_description_or_body(self):
        with patch.object(e, "jget", return_value={"items":[{
            "title":"Issue title", "body":None, "description":None,
            "html_url":"https://github.com/example/repo/issues/1"
        }]}):
            result=e.code_search("issue",mode="issues",limit=1)
        self.assertEqual(result["results"][0]["title"], "Issue title")
        self.assertEqual(result["results"][0]["snippet"], "")

    def test_search_defaults_skip_blocked_optional_engines(self):
        def fake(q, provider, limit): return [{"url":"https://example.org/","source":provider,"title":"Example"}]
        with patch.object(e, "web_engine",side_effect=fake) as call,patch.object(e,"_cache_get",return_value=None),patch.object(e,"_cache_put"):
            result=e.web_search("audit query",limit=1)
        self.assertEqual(result["engines_attempted"],["duckduckgo","wikipedia"])
        self.assertEqual(call.call_count, 2)

    def test_duckduckgo_lite_organic_result_parser(self):
        html='<a class="result-link" href="https://example.org/paper">An example research source</a>'
        with patch.object(e,"read_text",return_value=(html,"text/html","https://lite.duckduckgo.com/lite/")) as fetch:
            results=e.web_engine("africa","duckduckgo",limit=2)
        self.assertEqual(len(results),1)
        self.assertIn("lite.duckduckgo.com",fetch.call_args.args[0])

    def test_social_defaults_do_not_require_reddit(self):
        def fake(url):
            if "hn.algolia.com" in url: return {"hits":[]}
            if "stackexchange.com" in url: return {"items":[]}
            self.fail(f"unexpected source: {url}")
        with patch.object(e,"jget",side_effect=fake):
            result=e.social_search("research",limit=1)
        self.assertEqual(result["sources_attempted"],["hackernews","stackoverflow"])

    def test_news_locale_is_honored(self):
        seen=[]
        def fake(url):
            seen.append(url)
            return ("<rss><channel></channel></rss>", "application/rss+xml", url)
        with patch.object(e,"read_text",side_effect=fake):
            e.news_search("africa",limit=1,locale="pt-BR")
        self.assertIn("&gl=BR&ceid=BR:pt", seen[0])
        with self.assertRaises(ValueError):
            e.news_search("africa",locale="not-a-real-region")

class PublicLimitTests(unittest.TestCase):
    def test_rate_limit_and_body_size_and_health_bypass(self):
        async def test():
            calls=[]
            async def downstream(scope,receive,send):
                calls.append(scope["path"])
                await send({"type":"http.response.start","status":200,"headers":[]})
                await send({"type":"http.response.body","body":b"ok"})
            app=RateLimitedApp(downstream,requests_per_minute=2,concurrency=1,max_bytes=10)
            async def invoke(path="/mcp",size=b"2"):
                messages=[]
                async def send(message):messages.append(message)
                scope={"type":"http","path":path,"method":"POST","headers":[(b"content-length",size)]}
                await app(scope,None,send)
                return next(x["status"] for x in messages if x["type"]=="http.response.start")
            self.assertEqual(await invoke(),200)
            self.assertEqual(await invoke(),200)
            self.assertEqual(await invoke(),429)
            self.assertEqual(await invoke("/healthz"),200)
            other=RateLimitedApp(downstream,max_bytes=10)
            async def invalid(size):
                messages=[]
                async def send(m):messages.append(m)
                await other({"type":"http","path":"/mcp","method":"POST","headers":[(b"content-length",size)]},None,send)
                return next(x["status"] for x in messages if x["type"]=="http.response.start")
            self.assertEqual(await invalid(b"11"),413)
            self.assertEqual(await invalid(b"foo"),400)
            self.assertEqual(calls.count("/mcp"),2)
        asyncio.run(test())

if __name__ == "__main__":
    unittest.main()
