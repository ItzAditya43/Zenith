"""Source quality cues: page kind, published/updated dates, numbering."""
from __future__ import annotations

from bs4 import BeautifulSoup


def test_classify_source():
    from app.services.web_service import classify_source as c

    assert c("https://github.com/a/b") == "code"
    assert c("https://stackoverflow.com/q/1") == "forum"
    assert c("https://en.wikipedia.org/wiki/X") == "wiki"
    assert c("https://arxiv.org/abs/2401.1") == "paper"
    assert c("https://docs.python.org/3/") == "docs"
    assert c("https://www.reuters.com/x") == "news"
    assert c("https://someone.substack.com/p/x") == "blog"
    assert c("https://example.com/") == "page"


def test_page_dates():
    from app.services.web_service import page_dates

    html = """<html><head>
      <meta property="article:published_time" content="2024-03-05T10:00:00Z">
      <script type="application/ld+json">{"dateModified": "2025-01-20T08:00:00+00:00"}</script>
    </head><body><time datetime="2020-01-01">old</time></body></html>"""
    assert page_dates(BeautifulSoup(html, "lxml")) == {"published": "2024-03-05", "updated": "2025-01-20"}
    bare = BeautifulSoup("<html><body>x</body></html>", "lxml")
    assert page_dates(bare, "Wed, 21 Oct 2015 07:28:00 GMT") == {"published": None, "updated": "2015-10-21"}
