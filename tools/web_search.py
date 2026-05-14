"""Web search tool with swappable backend.

Uses DuckDuckGo as the default search backend (free, no API key required).
Backend can be swapped by calling set_backend() with a custom SearchBackend.

Requires: ddgs (install with `uv pip install ddgs`)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SearchResult:
    """A single search result entry."""
    title: str
    url: str
    snippet: str


class SearchBackend(ABC):
    """Abstract interface for search backends."""

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        """Execute a search query, returning up to max_results results."""
        ...


class DuckDuckGoBackend(SearchBackend):
    """DuckDuckGo search backend. Free, no API key required."""

    def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        try:
            from ddgs import DDGS
        except ImportError:
            return [SearchResult(
                title="ddgs not installed",
                url="",
                snippet="Install with: uv pip install ddgs",
            )]

        try:
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=max_results))
        except Exception as e:
            return [SearchResult(title=f"Search error: {e}", url="", snippet="")]

        results: List[SearchResult] = []
        for item in raw:
            results.append(SearchResult(
                title=item.get("title", "")[:200],
                url=item.get("href", ""),
                snippet=item.get("body", "")[:300],
            ))

        return results


# Default backend instance
_BACKEND: SearchBackend = DuckDuckGoBackend()


def set_backend(backend: SearchBackend) -> None:
    """Swap the search backend at runtime."""
    global _BACKEND
    _BACKEND = backend


def run_web_search(query: str, max_results: int = 5) -> str:
    """Execute a web search and return formatted results."""
    if not query or not query.strip():
        return "Error: query cannot be empty."

    results = _BACKEND.search(query.strip(), max_results=max_results)

    if not results:
        return "(no results)"

    # Check if the first result is an error report
    if len(results) == 1 and not results[0].url and results[0].title:
        return results[0].title

    lines = [f"Web search results for: {query}"]
    for i, r in enumerate(results, 1):
        lines.append("")
        lines.append(f"{i}. {r.title}")
        lines.append(f"   URL: {r.url}")
        if r.snippet:
            lines.append(f"   {r.snippet}")

    return "\n".join(lines)


def register_web_search_tools(registry) -> None:
    registry.register(
        name="web_search",
        description=(
            "Search the web using DuckDuckGo. Returns a list of results "
            "with titles, URLs, and snippets. Use this when you need "
            "current information from the internet."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query string.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (1-10, default 5).",
                },
            },
            "required": ["query"],
        },
        handler=lambda inp: run_web_search(
            inp["query"], inp.get("max_results", 5)
        ),
    )
