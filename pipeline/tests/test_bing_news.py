import httpx

from umbral_pipeline.ingest import bing_news

BING_RSS = """<?xml version='1.0' encoding='utf-8'?>
<rss version='2.0'><channel><item>
<title>El Canal de Panamá anuncia nuevas medidas - TVN</title>
<link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;url=https%3A%2F%2Fwww.tvn-2.com%2Fnacionales%2Fcanal_1_1.html%3Futm_source%3Dbing</link>
<pubDate>Thu, 08 Oct 2026 17:45:00 GMT</pubDate><source>TVN</source>
</item></channel></rss>"""


def test_original_article_url_unwraps_bing_redirect_without_fetching_article():
    raw = "http://www.bing.com/news/apiclick.aspx?ref=FexRss&url=https%3A%2F%2Fwww.tvn-2.com%2Fstory.html%3Futm_source%3Dbing"
    assert bing_news.original_article_url(raw) == "https://www.tvn-2.com/story.html?utm_source=bing"
    assert bing_news.original_article_url("javascript:alert(1)") is None


def test_parse_rss_keeps_only_title_publisher_date_and_original_url():
    rows = bing_news.parse_rss(
        BING_RSS, query="Canal de Panamá", topic="logistica", extracted_at="2026-10-09T01:00:00Z"
    )

    assert rows == [{
        "title": "El Canal de Panamá anuncia nuevas medidas",
        "url": "https://www.tvn-2.com/nacionales/canal_1_1.html?utm_source=bing",
        "publishedRaw": "Thu, 08 Oct 2026 17:45:00 GMT",
        "language": None,
        "sourceRank": 0,
        "topicHint": "logistica",
        "origin": {"source": "bing_news_rss", "query": "Canal de Panamá",
                   "endpoint": bing_news.BING_NEWS_ENDPOINT, "publisher": "TVN"},
        "extractedAt": "2026-10-09T01:00:00Z",
    }]


def test_fetch_bing_news_returns_independent_query_logs(monkeypatch):
    class NoThrottle:
        def wait(self):
            pass

    class FakeClient:
        def __init__(self):
            self.calls = []

        def get(self, url, params=None):
            self.calls.append((url, params))
            return httpx.Response(200, text=BING_RSS, request=httpx.Request("GET", url))

    monkeypatch.setattr(bing_news, "Throttle", lambda _interval: NoThrottle())
    client = FakeClient()
    records, queries, errors = bing_news.fetch_bing_news(
        client=client, queries={"panama": "Panamá", "economia": "economía Panamá"}, log=lambda *_: None
    )

    assert len(client.calls) == 2
    assert len(records) == 2
    assert [query["topic"] for query in queries] == ["panama", "economia"]
    assert all(query["source"] == "bing_news_rss" and query["returned"] == 1 for query in queries)
    assert errors == []
