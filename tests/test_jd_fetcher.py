import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from crawl4ai import CrawlerRunConfig
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

import pi_apply.jd_fetcher as jd_fetcher


def _mock_crawler(monkeypatch, crawler: Mock) -> Mock:
    crawler_cls = Mock()
    context = crawler_cls.return_value
    context.__aenter__ = AsyncMock(return_value=crawler)
    context.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(jd_fetcher, "AsyncWebCrawler", crawler_cls)
    return crawler_cls


def _result(fit_markdown: str) -> SimpleNamespace:
    return SimpleNamespace(
        markdown=SimpleNamespace(
            fit_markdown=fit_markdown,
            raw_markdown="raw markdown should not be returned",
        )
    )


def test_fetch_url_to_markdown_returns_fit_markdown_and_config(monkeypatch):
    monkeypatch.delenv("PI_APPLY_FETCH_PAGE_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("PI_APPLY_FETCH_WAIT_UNTIL", raising=False)
    monkeypatch.delenv("PI_APPLY_FETCH_OUTER_TIMEOUT_S", raising=False)
    monkeypatch.delenv("PI_APPLY_FETCH_MAGIC", raising=False)

    crawler = Mock()
    crawler.arun = AsyncMock(return_value=_result("pruned fit markdown"))
    crawler_cls = _mock_crawler(monkeypatch, crawler)

    markdown = asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))

    assert markdown == "pruned fit markdown"
    crawler_cls.assert_called_once_with(headless=True, magic=True)
    crawler.arun.assert_awaited_once()

    _, kwargs = crawler.arun.await_args
    assert kwargs["url"] == "https://example.com/job"
    config = kwargs["config"]
    assert isinstance(config, CrawlerRunConfig)
    assert config.wait_until == jd_fetcher.DEFAULT_WAIT_UNTIL
    assert config.page_timeout == jd_fetcher.DEFAULT_PAGE_TIMEOUT_MS
    assert isinstance(config.markdown_generator, DefaultMarkdownGenerator)
    assert isinstance(config.markdown_generator.content_filter, PruningContentFilter)


def test_fetch_url_to_markdown_honors_env_overrides(monkeypatch):
    monkeypatch.setenv("PI_APPLY_FETCH_PAGE_TIMEOUT_MS", "15000")
    monkeypatch.setenv("PI_APPLY_FETCH_WAIT_UNTIL", "domcontentloaded")
    monkeypatch.setenv("PI_APPLY_FETCH_OUTER_TIMEOUT_S", "5")
    monkeypatch.setenv("PI_APPLY_FETCH_MAGIC", "false")

    crawler = Mock()
    crawler.arun = AsyncMock(return_value=_result("env markdown"))
    crawler_cls = _mock_crawler(monkeypatch, crawler)

    markdown = asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))

    assert markdown == "env markdown"
    assert jd_fetcher._page_timeout_ms() == 15000
    assert jd_fetcher._wait_until() == "domcontentloaded"
    assert jd_fetcher._outer_timeout_s() == 5
    assert jd_fetcher._magic() is False
    crawler_cls.assert_called_once_with(headless=True, magic=False)
    config = crawler.arun.await_args.kwargs["config"]
    assert config.page_timeout == 15000
    assert config.wait_until == "domcontentloaded"


def test_fetch_url_to_markdown_propagates_crawl4ai_exception(monkeypatch):
    expected = RuntimeError("crawl failed")
    crawler = Mock()
    crawler.arun = AsyncMock(side_effect=expected)
    _mock_crawler(monkeypatch, crawler)

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))

    assert exc_info.value is expected


def test_fetch_url_to_markdown_propagates_outer_timeout(monkeypatch):
    async def slow_arun(*_args, **_kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(jd_fetcher, "_outer_timeout_s", lambda: 0.01)
    crawler = Mock()
    crawler.arun = AsyncMock(side_effect=slow_arun)
    _mock_crawler(monkeypatch, crawler)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))
