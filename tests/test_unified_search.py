"""Regression tests for one unified search across six internal provider categories."""
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"server"))
import unified
import engine as e
import main


class UnifiedSearchTest(unittest.TestCase):
    def mocks(self):
        common=lambda category,link:{"results":[{"title":category,"url":link,"source":category}]}
        return {
            "web_search":common("web","https://example.org/shared"),
            "academic_search":common("academic","https://example.org/shared"),
            "code_search":common("code","https://example.org/code"),
            "social_search":common("social","https://example.org/social"),
            "news_search":common("news","https://example.org/news"),
            "dataset_search":common("datasets","https://example.org/data")
        }

    def test_deep_all_categories_dedup_and_citations(self):
        with patch.object(e,"_cache_get",return_value=None), patch.object(e,"_cache_put") as put:
            with patch.object(e,"web_search",return_value=self.mocks()["web_search"]), \
                 patch.object(e,"academic_search",return_value=self.mocks()["academic_search"]), \
                 patch.object(e,"code_search",return_value=self.mocks()["code_search"]), \
                 patch.object(e,"social_search",return_value=self.mocks()["social_search"]), \
                 patch.object(e,"news_search",return_value=self.mocks()["news_search"]), \
                 patch.object(e,"dataset_search",side_effect=lambda q,source,limit:self.mocks()["dataset_search"]):
                result=unified.research("African history",mode="deep",limit=12)
        self.assertEqual(result["providers_attempted"],list(unified.SEARCH_PROVIDERS))
        self.assertEqual(len(result["results"]),5)  # same URL across academic and web
        self.assertEqual(result["results"][0]["search_categories"],["web","academic"])
        self.assertEqual([v["citation_id"] for v in result["results"]],[f"S{i}" for i in range(1,6)])
        self.assertEqual(result["errors"],{})
        put.assert_called_once()

    def test_targeted_mode_calls_one_provider(self):
        with patch.object(e,"_cache_get",return_value=None), \
             patch.object(e,"_cache_put"), \
             patch.object(e,"academic_search",return_value=self.mocks()["academic_search"]) as academy, \
             patch.object(e,"web_search",side_effect=AssertionError("web must not run")):
            result=unified.research("climate change Africa",mode="academic",academic_sources=["crossref"],limit=2)
        self.assertEqual(result["providers_attempted"],["academic"])
        self.assertEqual(len(result["results"]),1)
        academy.assert_called_once_with("climate change Africa",["crossref"],3)

    def test_partial_provider_error_is_reported(self):
        with patch.object(e,"_cache_get",return_value=None),patch.object(e,"_cache_put"), \
             patch.object(e,"web_search",return_value=self.mocks()["web_search"]), \
             patch.object(e,"news_search",side_effect=TimeoutError("news blocked")):
            r=unified.research("African Union",providers=["web","news"],limit=5)
        self.assertEqual(len(r["results"]),1)
        self.assertIn("news",r["errors"])
        self.assertEqual(r["provider_counts"]["news"],0)

    def test_options_validation(self):
        bad=[
            dict(query="a"),dict(query="research",mode="anything"),
            dict(query="research",providers=["web","unknown"]),
            dict(query="research",providers=[]),
            dict(query="research",limit=True),
            dict(query="research",web_engines=["impossible"]),
            dict(query="research",code_mode="other"),
            dict(query="research",dataset_source="invalid"),
            dict(query="research",locale="xyz"),
        ]
        for opts in bad:
            with self.subTest(opts=opts),self.assertRaises(ValueError):
                unified.research(**opts)

    def test_mode_provider_list_and_cache(self):
        cached={"query":"Africa","results":[],"providers_attempted":["news"]}
        with patch.object(e,"_cache_get",return_value=cached),patch.object(e,"_cache_put"):
            r=unified.research("Africa",mode="news")
        self.assertTrue(r["cached"])

    def test_local_stdio_exposes_one_search(self):
        names=[item["name"] for item in main.TOOLS]
        self.assertEqual(len(names),9)
        self.assertIn("omni_research-deep",names)
        for legacy in ("web_search","academic_search","code_search","social_search","news_search","dataset_search","research_bundle"):
            self.assertNotIn(legacy,names)

    def test_local_stdio_dispatch_with_mock(self):
        with patch.object(unified,"research",return_value={"results":[{"title":"ok"}]}) as runner:
            result=main.dispatch("omni_research-deep",{"query":"Africa","mode":"news"})
        self.assertEqual(result["results"][0]["title"],"ok")
        runner.assert_called_once()

if __name__=="__main__":
    unittest.main()
