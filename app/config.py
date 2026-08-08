import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./aim_news_desk.db")
APP_URL = os.getenv("APP_URL", "http://localhost:8000")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

POLL_MINUTES_PRIORITY = int(os.getenv("POLL_MINUTES_PRIORITY", "3"))
POLL_MINUTES_STANDARD = int(os.getenv("POLL_MINUTES_STANDARD", "10"))
POLL_MINUTES_LOW = int(os.getenv("POLL_MINUTES_LOW", "30"))

# Supabase Auth (Phase 2: team login)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")

# Phase 3: AI-assisted viral sub-scores
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Near-duplicate thresholds (Level 2 dedup). Tune against real data later;
# these are deliberately conservative (biased toward false negatives per spec).
HEADLINE_JACCARD_THRESHOLD = 0.6
HEADLINE_FUZZ_RATIO_THRESHOLD = 85
NEAR_DUP_LOOKBACK_HOURS = 72

# feedparser.parse(url) has NO built-in network timeout -- one slow or
# unresponsive source can hang the entire sequential scan behind it (found
# live: BBC World News hung long enough to trigger a Windows socket timeout,
# WinError 10060, stalling every other source queued after it in the same
# scan). Fetch with an explicit timeout instead of letting feedparser do its
# own unbounded network call.
FEED_FETCH_TIMEOUT_SECONDS = 15
