"""
Seed a starting set of REAL public sources -- not a hardcoded permanent list.
Per the spec, admins add/edit/enable/disable/prioritize sources later; this is
just enough to prove the collector against live data. Safe to re-run (skips
rows that already exist by URL).
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Source
from app.collectors.google_news import build_google_news_url

RSS_SOURCES = [
    dict(name="NPR News", url="https://feeds.npr.org/1001/rss.xml",
         category="general", credibility_tier=2, polling_tier="priority"),
    dict(name="BBC World News", url="http://feeds.bbci.co.uk/news/world/rss.xml",
         category="world", credibility_tier=2, polling_tier="standard"),
    dict(name="BBC US & Canada", url="http://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",
         category="us", credibility_tier=2, polling_tier="priority"),
    dict(name="CNN Politics", url="http://rss.cnn.com/rss/cnn_allpolitics.rss",
         category="politics", credibility_tier=2, polling_tier="priority"),
    dict(name="Fox News Politics", url="https://moxie.foxnews.com/google-publisher/politics.xml",
         category="politics", credibility_tier=2, polling_tier="priority"),
    dict(name="Politico Picks", url="https://www.politico.com/rss/politicopicks.xml",
         category="politics", credibility_tier=2, polling_tier="standard"),
    dict(name="ABC News (US)", url="https://abcnews.go.com/abcnews/usheadlines",
         category="us", credibility_tier=2, polling_tier="priority"),
    dict(name="CBS News", url="https://www.cbsnews.com/latest/rss/main",
         category="general", credibility_tier=2, polling_tier="priority"),
    dict(name="NBC News", url="http://feeds.nbcnews.com/nbcnews/public/news",
         category="general", credibility_tier=2, polling_tier="priority"),
    dict(name="The Hill", url="https://thehill.com/homenews/feed/",
         category="politics", credibility_tier=2, polling_tier="standard"),
    dict(name="Washington Examiner Politics",
         url="https://www.washingtonexaminer.com/section/news/politics/feed",
         category="politics", credibility_tier=2, polling_tier="standard"),
    dict(name="Washington Times Politics",
         url="https://www.washingtontimes.com/rss/headlines/news/politics/",
         category="politics", credibility_tier=2, polling_tier="standard"),
    dict(name="Al Jazeera", url="https://www.aljazeera.com/xml/rss/all.xml",
         category="world", credibility_tier=2, polling_tier="standard"),
    dict(name="NY Post Politics", url="https://nypost.com/politics/feed/",
         category="politics", credibility_tier=3, polling_tier="standard"),
    dict(name="Newsmax Politics", url="https://www.newsmax.com/rss/Politics/1/",
         category="politics", credibility_tier=3, polling_tier="standard"),
    dict(name="Breitbart", url="http://feeds.feedburner.com/breitbart",
         category="politics", credibility_tier=3, polling_tier="standard"),
    dict(name="FBI National Press Releases",
         url="https://www.fbi.gov/feeds/national-press-releases/rss.xml",
         category="law-enforcement", credibility_tier=1, polling_tier="standard"),
    # America First (movement-branded outlets -- tiered lower than straight-news
    # wire coverage per the credibility rubric, not because of viewpoint)
    dict(name="Daily Wire", url="https://www.dailywire.com/feeds/rss.xml",
         category="america_first", credibility_tier=3, polling_tier="standard"),
    dict(name="Gateway Pundit", url="https://www.thegatewaypundit.com/feed/",
         category="america_first", credibility_tier=4, polling_tier="standard"),
    dict(name="The Federalist", url="https://thefederalist.com/feed/",
         category="america_first", credibility_tier=3, polling_tier="standard"),
    dict(name="RedState", url="https://redstate.com/feed",
         category="america_first", credibility_tier=3, polling_tier="standard"),
    dict(name="The Blaze", url="https://www.theblaze.com/feeds/feed.rss",
         category="america_first", credibility_tier=3, polling_tier="standard"),
    dict(name="PJ Media", url="https://pjmedia.com/feed",
         category="america_first", credibility_tier=3, polling_tier="standard"),
    # Politics (policy-focused conservative, more traditional/wire-style)
    dict(name="National Review", url="https://nationalreview.com/feed",
         category="politics", credibility_tier=2, polling_tier="standard"),
    dict(name="Washington Free Beacon", url="https://freebeacon.com/feed",
         category="politics", credibility_tier=2, polling_tier="standard"),
    dict(name="Daily Signal", url="https://www.dailysignal.com/feed/",
         category="politics", credibility_tier=2, polling_tier="standard"),
    # Business
    dict(name="Yahoo Finance", url="https://finance.yahoo.com/news/rssindex",
         category="business", credibility_tier=2, polling_tier="standard"),
    dict(name="Business Insider", url="https://feeds.businessinsider.com/custom/all",
         category="business", credibility_tier=2, polling_tier="standard"),
    dict(name="CNBC", url="https://www.cnbc.com/id/100003114/device/rss/rss.html",
         category="business", credibility_tier=2, polling_tier="standard"),
    dict(name="MarketWatch", url="https://feeds.content.dowjones.io/public/rss/mw_topstories",
         category="business", credibility_tier=2, polling_tier="standard"),
    dict(name="Forbes Business", url="https://www.forbes.com/business/feed/",
         category="business", credibility_tier=2, polling_tier="standard"),
    # NY Post broader coverage (politics feed already above) + Fox National
    dict(name="NY Post Main", url="https://nypost.com/feed/",
         category="general", credibility_tier=3, polling_tier="standard"),
    dict(name="NY Post Business", url="https://nypost.com/business/feed/",
         category="business", credibility_tier=3, polling_tier="standard"),
    dict(name="NY Post US News", url="https://nypost.com/us-news/feed/",
         category="us", credibility_tier=3, polling_tier="standard"),
    dict(name="Fox News National", url="https://feeds.feedburner.com/foxnews/national",
         category="us", credibility_tier=2, polling_tier="standard"),
]

GOOGLE_NEWS_QUERIES = [
    dict(query="breaking news United States", category="breaking", polling_tier="priority"),
    dict(query="White House", category="government", polling_tier="priority"),
    dict(query="Congress", category="government", polling_tier="standard"),
    dict(query="Supreme Court", category="courts", polling_tier="standard"),
    dict(query="immigration", category="immigration", polling_tier="standard"),
    dict(query="crime", category="crime", polling_tier="standard"),
    dict(query="Trump", category="trump", polling_tier="priority"),
    # Bare "America First" collides with America First Credit Union (a real,
    # unrelated business) -- confirmed live: 6 real clusters were nothing but
    # credit-union press coverage before this query was narrowed. Requires a
    # political co-occurrence term and excludes the credit union explicitly.
    dict(query='"America First" (Trump OR MAGA OR conservative OR agenda OR movement) -"credit union"',
         category="america_first", polling_tier="standard"),
    dict(query="MAGA", category="america_first", polling_tier="standard"),
    dict(query="US economy", category="business", polling_tier="standard"),
    dict(query="stock market", category="business", polling_tier="standard"),
]


def seed():
    session = SessionLocal()
    created = 0
    try:
        for row in RSS_SOURCES:
            exists = session.execute(select(Source).where(Source.url == row["url"])).scalars().first()
            if exists:
                continue
            session.add(Source(type="rss", enabled=True, **row))
            created += 1

        for row in GOOGLE_NEWS_QUERIES:
            url = build_google_news_url(row["query"])
            exists = session.execute(select(Source).where(Source.url == url)).scalars().first()
            if exists:
                continue
            session.add(Source(
                type="google_news",
                name=f"Google News: {row['query']}",
                url=url,
                query=row["query"],
                category=row["category"],
                credibility_tier=2,
                polling_tier=row["polling_tier"],
                enabled=True,
            ))
            created += 1

        session.commit()
        total = session.execute(select(Source)).scalars().all()
        print(f"Seeded {created} new source(s). Total sources in DB: {len(total)}")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
