import hashlib
import html
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAMS = {
    "fbclid", "gclid", "ref", "ref_src", "ref_url", "mc_cid", "mc_eid",
    "cmpid", "icid", "ito", "taid", "partner", "src",
}


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    kept_params = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
        and not any(k.lower().startswith(p) for p in TRACKING_PARAM_PREFIXES)
    ]
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(kept_params), ""))


_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_headline(headline: str) -> str:
    text = html.unescape(headline or "")
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = _PUNCT_RE.sub(" ", text.lower())
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_hashes(canonical_url: str, normalized_headline: str, description: str | None):
    url_hash = sha256(canonical_url)
    headline_hash = sha256(normalized_headline)
    content_hash = sha256(normalized_headline + "|" + (description or "").strip().lower())
    return url_hash, headline_hash, content_hash


def headline_tokens(normalized_headline: str) -> set[str]:
    return set(normalized_headline.split())
