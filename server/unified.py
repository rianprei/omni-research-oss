"""Single search entrypoint; individual providers remain internal engine methods.

No LLM, web-browser automation or autonomous subagents run on the MCP host.
"""
from __future__ import annotations

import concurrent.futures
import json
from typing import Any
import engine as e

SEARCH_PROVIDERS = ("web", "academic", "code", "social", "news", "datasets")
MODES = {
    "deep": SEARCH_PROVIDERS,
    "web": ("web",), "academic": ("academic",), "code": ("code",),
    "social": ("social",), "news": ("news",), "datasets": ("datasets",),
    "technical": ("web", "academic", "code"),
    "trends": ("web", "social", "news"),
}
VALID_WEB = ("wikipedia", "google-news", "bing", "duckduckgo", "mojeek", "searxng")
VALID_ACADEMIC = ("openalex", "crossref", "arxiv", "pubmed")
VALID_SOCIAL = ("hackernews", "stackoverflow", "reddit")
VALID_DATASETS = ("both", "huggingface", "zenodo")
VALID_CODE = ("repositories", "issues", "users", "code")


def _choices(value, allowed, name):
    if value is None:
        return None
    if not isinstance(value, list) or not value or len(value) > len(allowed):
        raise ValueError(f"{name} must be a nonempty list of allowed names")
    if any(not isinstance(v, str) or v not in allowed for v in value):
        raise ValueError(f"{name} values must be among: {', '.join(allowed)}")
    return list(dict.fromkeys(value))


def research(
    query: str,
    mode: str = "deep",
    providers: list[str] | None = None,
    limit: int = 16,
    locale: str = "en-US",
    code_mode: str = "repositories",
    dataset_source: str = "both",
    web_engines: list[str] | None = None,
    academic_sources: list[str] | None = None,
    social_sources: list[str] | None = None,
) -> dict[str, Any]:
    """Query all six source categories in deep mode, or a selected subset.

    The provider list overrides the mode. Results have stable citation IDs, and
    source-level errors remain visible; this function performs no LLM synthesis.
    """
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 500:
        raise ValueError("query must contain between 2 and 500 characters")
    query = query.strip()
    if mode not in MODES:
        raise ValueError("Invalid mode")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 30:
        raise ValueError("limit must be an integer from 1 to 30")
    if code_mode not in VALID_CODE:
        raise ValueError("code_mode must be repositories, issues, users or code")
    if dataset_source not in VALID_DATASETS:
        raise ValueError("dataset_source must be both, huggingface or zenodo")
    if not isinstance(locale, str) or not e.re.fullmatch(r"[A-Za-z]{2,3}-[A-Za-z]{2}", locale):
        raise ValueError("locale must look like pt-BR or en-US")
    web_engines = _choices(web_engines, VALID_WEB, "web_engines")
    academic_sources = _choices(academic_sources, VALID_ACADEMIC, "academic_sources")
    social_sources = _choices(social_sources, VALID_SOCIAL, "social_sources")
    selected = list(MODES[mode]) if providers is None else _choices(providers, SEARCH_PROVIDERS, "providers")
    if not selected:
        raise ValueError("Select at least one search provider")

    per = min(8, max(2, (limit + len(selected) - 1) // len(selected) + 1))
    config = (query, mode, selected, limit, locale, code_mode, dataset_source,
              web_engines, academic_sources, social_sources)
    key = "omni_research-deep:" + json.dumps(config, ensure_ascii=False)
    cached = e._cache_get(key)
    if cached is not None:
        return dict(cached, cached=True)

    def datasets():
        catalogs = ("huggingface", "zenodo") if dataset_source == "both" else (dataset_source,)
        entries, errors = [], {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(catalogs)) as pool:
            futures = {pool.submit(e.dataset_search, query, src, per): src for src in catalogs}
            for f in concurrent.futures.as_completed(futures):
                src = futures[f]
                try:
                    entries.extend(f.result().get("results", []))
                except Exception as exc:
                    errors[src] = str(exc)[:250]
        return {"results": entries, "errors": errors}

    calls = {
        "web": lambda: e.web_search(query, web_engines, per),
        "academic": lambda: e.academic_search(query, academic_sources, per),
        "code": lambda: e.code_search(query, code_mode, per),
        "social": lambda: e.social_search(query, social_sources, per),
        "news": lambda: e.news_search(query, per, locale),
        "datasets": datasets,
    }
    batches: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}
    source_errors: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(selected), 6)) as pool:
        futures = {pool.submit(calls[name]): name for name in selected}
        for f in concurrent.futures.as_completed(futures):
            name = futures[f]
            try:
                data = f.result()
                if not isinstance(data, dict):
                    raise ValueError("provider returned invalid results")
                rows = data.get("results", [])
                if not isinstance(rows, list):
                    raise ValueError("provider results must be a list")
                batches[name] = e.normalize(rows)
                provider_err = data.get("errors") or data.get("source_errors") or {}
                if provider_err:
                    source_errors[name] = provider_err
                if data.get("error"):
                    errors[name] = str(data["error"])[:250]
            except Exception as exc:
                batches[name] = []
                errors[name] = str(exc)[:250]

    seen: dict[str, int] = {}
    results: list[dict[str, Any]] = []
    for rank in range(max(map(len, batches.values()), default=0)):
        for category in selected:
            rows = batches.get(category, [])
            if rank >= len(rows):
                continue
            item = rows[rank]
            url = item.get("url", "")
            if not isinstance(url, str) or not url:
                continue
            if url in seen:
                existing = results[seen[url]]
                categories = existing["search_categories"]
                if category not in categories:
                    categories.append(category)
                continue
            fields = ("title", "url", "snippet", "source", "sources", "doi",
                      "published_at", "year", "authors", "stars", "score",
                      "downloads", "likes", "publisher", "updated_at")
            entry = {k: item[k] for k in fields if item.get(k) is not None}
            if "snippet" in entry and isinstance(entry["snippet"], str):
                entry["snippet"] = entry["snippet"][:600]
            entry["search_categories"] = [category]
            seen[url] = len(results)
            results.append(entry)

    results = results[:limit]
    for idx, item in enumerate(results, 1):
        item["citation_id"] = f"S{idx}"
    answer = {
        "query": query,
        "mode": mode,
        "providers_attempted": selected,
        "provider_counts": {name: len(batches.get(name, [])) for name in selected},
        "results": results,
        "errors": errors,
        "source_errors": source_errors,
        "total_unique_before_limit": len(seen),
        "limitations": (
            "Discovery only; no autonomous agents or LLM were launched. "
            "Snippets and citations are not independently verified. "
            "Free providers may block requests; web mode relies on Wikipedia "
            "and news RSS, not a comprehensive internet search index."
        ),
    }
    if results:
        e._cache_put(key, answer, ttl=300)
    return answer
