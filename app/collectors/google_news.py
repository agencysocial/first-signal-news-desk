"""
Google News RSS is a plain RSS feed served at a search URL -- no separate
parser needed, just build the URL and hand it to the generic RSS collector.
"""
from urllib.parse import quote_plus


def build_google_news_url(query: str, lang: str = "en-US", country: str = "US") -> str:
    ceid = f"{country}:{lang.split('-')[0]}"
    return (
        f"https://news.google.com/rss/search?q={quote_plus(query)}"
        f"&hl={lang}&gl={country}&ceid={ceid}"
    )
