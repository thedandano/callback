"""Crawl4AI wrapper for fetching job descriptions as markdown."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

logger = logging.getLogger("callback.jd_fetcher")

DEFAULT_PAGE_TIMEOUT_MS = 30_000
DEFAULT_WAIT_UNTIL = "networkidle"
DEFAULT_OUTER_TIMEOUT_S = 35
DEFAULT_MAGIC = True
FALSE_ENV_VALUES = {"", "0", "false"}
MIN_MARKDOWN_CHARS = 50


class JDFetchError(Exception):
    """Domain error raised by graph nodes when JD fetch cannot be satisfied."""

    def __init__(self, reason: str, url: str, cause: Exception | None = None) -> None:
        self.reason = reason
        self.url = url
        self.cause = cause
        super().__init__(reason, url, cause)

    def __str__(self) -> str:
        return f"JDFetchError(reason={self.reason}, url={self.url}, cause={self.cause})"


def _page_timeout_ms() -> int:
    return int(os.getenv("CALLBACK_FETCH_PAGE_TIMEOUT_MS", DEFAULT_PAGE_TIMEOUT_MS))


def _wait_until() -> str:
    return os.getenv("CALLBACK_FETCH_WAIT_UNTIL", DEFAULT_WAIT_UNTIL)


def _outer_timeout_s() -> float:
    return float(os.getenv("CALLBACK_FETCH_OUTER_TIMEOUT_S", DEFAULT_OUTER_TIMEOUT_S))


def _magic() -> bool:
    value = os.getenv("CALLBACK_FETCH_MAGIC", str(DEFAULT_MAGIC))
    return value.lower() not in FALSE_ENV_VALUES


def _log(event: str, **fields: object) -> None:
    logger.info(json.dumps({"event": event, **fields}))


async def _fetch_url_to_markdown_unbounded(url: str) -> str:
    config = CrawlerRunConfig(
        markdown_generator=DefaultMarkdownGenerator(content_filter=PruningContentFilter()),
        wait_until=_wait_until(),
        page_timeout=_page_timeout_ms(),
    )

    async with AsyncWebCrawler(headless=True, magic=_magic()) as crawler:
        result: Any = await crawler.arun(url=url, config=config)
    return result.markdown.fit_markdown


async def fetch_url_to_markdown(url: str) -> str:
    """Fetch a URL with Crawl4AI and return pruned fit markdown."""

    return await asyncio.wait_for(
        _fetch_url_to_markdown_unbounded(url),
        timeout=_outer_timeout_s(),
    )
