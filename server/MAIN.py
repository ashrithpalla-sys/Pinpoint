import os
import re
import json
import httpx
import base64
import hashlib
import asyncio
import cloudinary
import cloudinary.uploader
import google.generativeai as genai
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import logging
from contextlib import asynccontextmanager

import db

logging.basicConfig(level=logging.INFO)
load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
)

SERPAPI_KEY = os.getenv("SERPAPI_KEY")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

AI_BATCH_SIZE = 8          # candidates per Gemini vision call
MAX_AI_CANDIDATES = 30     # cap how many of the (up to 60) candidates get AI-scored
GEMINI_MODEL = "gemini-1.5-flash"

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Blocked domains ───────────────────────────────────────────────────────────

BLOCKED_DOMAINS = {
    "instagram.com", "pinterest.com", "tiktok.com", "facebook.com",
    "twitter.com", "x.com", "reddit.com", "tumblr.com", "youtube.com",
    "snapchat.com", "threads.net", "linkedin.com", "wikimedia.org",
    "wikipedia.org", "imgur.com", "flickr.com",
}

# ── Country config ────────────────────────────────────────────────────────────

# Maps ISO country code → (SerpApi country param, hl language, currency symbols to KEEP)
COUNTRY_CONFIG = {
    "in": ("in",  "en", ["₹", "INR", "Rs"]),
    "gb": ("gb",  "en", ["£", "GBP"]),
    "au": ("au",  "en", ["A$", "AUD"]),
    "ca": ("ca",  "en", ["C$", "CAD"]),
    "de": ("de",  "de", ["€", "EUR"]),
    "fr": ("fr",  "fr", ["€", "EUR"]),
    "it": ("it",  "it", ["€", "EUR"]),
    "es": ("es",  "es", ["€", "EUR"]),
    "jp": ("jp",  "ja", ["¥", "JPY"]),
    "sg": ("sg",  "en", ["S$", "SGD"]),
    "ae": ("ae",  "ar", ["AED", "د.إ"]),
    "us": ("us",  "en", ["$", "USD"]),
}

DEFAULT_CONFIG = ("us", "en", ["$", "USD"])

# ── Models ────────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    image: str
    country: str = "us"

class Product(BaseModel):
    title: str
    link: str
    thumbnail: str
    source: str
    price: str | None = None
    price_value: float | None = None
    similarity_score: float
    in_stock: bool = True

# ── Helpers ───────────────────────────────────────────────────────────────────

def is_blocked(link: str) -> bool:
    try:
        from urllib.parse import urlparse
        host = urlparse(link).netloc.lower().removeprefix("www.")
        return any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAINS)
    except Exception:
        return False


def price_matches_region(price_str: str, allowed_symbols: list[str]) -> bool:
    """Return True if price string contains one of the allowed currency symbols.

    Symbols are matched only when not immediately preceded by a letter, so a
    bare "$" (US) doesn't false-positive match inside a compound symbol like
    "A$" (AUD), "C$" (CAD), or "S$" (SGD).
    """
    if not price_str:
        return False
    for sym in allowed_symbols:
        if re.search(rf'(?<![A-Za-z]){re.escape(sym)}', price_str):
            return True
    return False


def classify_serpapi_error(status_code: int | None, body: str) -> str:
    """Turn a SerpApi failure into a specific, actionable message instead of a
    raw exception string. Shapes verified against SerpApi's documented error
    codes (https://serpapi.com/api-status-and-error-codes)."""
    lower_body = (body or "").lower()
    if status_code == 429 or "run out of searches" in lower_body:
        return "SerpApi's search quota is used up for this billing period. Try again next month or upgrade your plan."
    if status_code == 401 or "invalid api key" in lower_body:
        return "SerpApi credentials are invalid. Check SERPAPI_KEY in server/.env."
    if status_code == 503:
        return "SerpApi is temporarily unavailable. Please try again in a moment."
    return "Visual search service failed. Please try again."


def classify_cloudinary_error(message: str) -> str:
    """Turn a Cloudinary upload failure into a specific, actionable message."""
    lower_message = (message or "").lower()
    if "permission" in lower_message or "forbidden" in lower_message:
        return "Cloudinary key lacks upload permission. Check the API key's role in the Cloudinary dashboard."
    if "invalid" in lower_message or "credential" in lower_message or "authenticat" in lower_message:
        return "Cloudinary credentials are invalid. Check CLOUDINARY_* values in server/.env."
    return "Image upload service failed. Please try again."


def upload_to_cloudinary(data_url: str) -> str:
    result = cloudinary.uploader.upload(
        data_url, folder="pinpoint", resource_type="image"
    )
    return result["secure_url"]


class SerpApiError(Exception):
    def __init__(self, status_code: int | None, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"SerpApi error {status_code}: {body[:200]}")


async def search_serpapi(image_url: str, serpapi_country: str, hl: str) -> list[dict]:
    params = {
        "engine":  "google_lens",
        "url":     image_url,
        "api_key": SERPAPI_KEY,
        "hl":      hl,
        "country": serpapi_country,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get("https://serpapi.com/search", params=params)
        if resp.status_code != 200:
            raise SerpApiError(resp.status_code, resp.text)
        data = resp.json()

    # Log full raw response so we can see what SerpApi actually returns
    logging.info(f"SerpApi raw keys: {list(data.keys())}")
    matches = data.get("visual_matches") or data.get("shopping_results") or []
    logging.info(f"SerpApi raw sample (first 3): {json.dumps(matches[:3], indent=2)}")
    return matches[:60]


def extract_price_from_html(html: str, allowed_symbols: list[str]) -> str | None:
    """Given a product page's raw HTML, find a price matching the user's region
    currency: first via JSON-LD structured data, then a regex fallback that
    walks every distinct currency-shaped match until one looks plausible."""
    soup = BeautifulSoup(html, "html.parser")

    # 1. JSON-LD
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                offers = item.get("offers") or item.get("Offers")
                if isinstance(offers, dict):
                    price = str(offers.get("price") or offers.get("lowPrice") or "")
                    currency = offers.get("priceCurrency", "")
                    if price and price_matches_region(f"{currency} {price}", allowed_symbols):
                        return f"{currency} {price}".strip()
                elif isinstance(offers, list) and offers:
                    price = str(offers[0].get("price") or "")
                    currency = offers[0].get("priceCurrency", "")
                    if price and price_matches_region(f"{currency} {price}", allowed_symbols):
                        return f"{currency} {price}".strip()
        except Exception:
            continue

    # 2. Regex — only match currency symbols for this region. Walk each
    # distinct match (not just the first one, repeatedly) until one looks
    # like a plausible price.
    sym_pattern = "|".join(re.escape(s) for s in allowed_symbols)
    price_pattern = re.compile(
        rf'({sym_pattern})\s*[\d,]+(?:\.\d{{1,2}})?',
        re.IGNORECASE
    )
    for match in list(price_pattern.finditer(html))[:10]:
        candidate = match.group(0).strip()
        digits = re.sub(r'[^\d.]', '', candidate)
        try:
            if 1 < float(digits) < 500000:
                return candidate
        except Exception:
            continue

    return None


async def scrape_price(
    url: str, client: httpx.AsyncClient, allowed_symbols: list[str]
) -> tuple[str | None, bool]:
    """Scrape product page for a price matching the user's region currency.

    Returns (price_or_None, page_reachable). page_reachable is False when the
    request itself failed (bad status, timeout, connection error) as opposed
    to the page loading fine but simply not containing a parseable price --
    callers use this to distinguish "no price found" from "this link is dead".
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = await client.get(url, headers=headers, timeout=8, follow_redirects=True)
        if resp.status_code != 200:
            return None, False

        return extract_price_from_html(resp.text, allowed_symbols), True
    except Exception as e:
        logging.debug(f"Price scrape failed for {url}: {e}")
        return None, False


def parse_price_value(price_str: str | None) -> float | None:
    if not price_str:
        return None
    digits = re.sub(r'[^\d.]', '', price_str.replace(',', ''))
    try:
        v = float(digits)
        return v if v > 0 else None
    except Exception:
        return None


async def enrich_prices(products: list[dict], allowed_symbols: list[str]) -> list[dict]:
    """Scrape prices for products missing them, concurrently."""
    sem = asyncio.Semaphore(6)

    async def fetch_one(p: dict) -> dict:
        if p.get("price") or not p.get("link"):
            return p
        async with sem:
            async with httpx.AsyncClient() as client:
                scraped, reachable = await scrape_price(p["link"], client, allowed_symbols)
                if scraped:
                    p["price"] = scraped
                    logging.info(f"✅ Scraped price for {p['source']}: {scraped}")
                elif not reachable:
                    p["_unreachable"] = True
                    logging.info(f"🚫 Dropping unreachable link for {p['source']} — {p['link'][:60]}")
                else:
                    logging.info(f"⚠️  No price found for {p['source']} — {p['link'][:60]}")
        return p

    return list(await asyncio.gather(*[fetch_one(p) for p in products]))


def parse_data_url(data_url: str) -> tuple[str, bytes]:
    header, _, encoded = data_url.partition(",")
    mime = header.split(":")[1].split(";")[0] if ":" in header else "image/png"
    return mime, base64.b64decode(encoded)


async def fetch_image_bytes(url: str, client: httpx.AsyncClient) -> tuple[str, bytes] | None:
    try:
        resp = await client.get(url, timeout=8, follow_redirects=True)
        if resp.status_code != 200:
            return None
        mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
        if not mime.startswith("image"):
            mime = "image/jpeg"
        return mime, resp.content
    except Exception:
        return None


SIMILARITY_PROMPT = (
    "You are comparing a QUERY clothing image to several CANDIDATE product images. "
    "For each candidate, rate visual similarity to the query image from 0.0 (not similar) "
    "to 1.0 (nearly identical), based on garment type, color, pattern, and cut. "
    'Respond ONLY with JSON in this exact shape: '
    '{"scores": [{"index": <candidate index>, "score": <0.0-1.0>}, ...]}'
)


async def score_batch(query_part: dict, batch: list[dict], client: httpx.AsyncClient) -> None:
    """Score one batch of products in place. On any failure, leaves the existing
    rank-based fallback score untouched rather than failing the request."""
    try:
        fetched = await asyncio.gather(*[fetch_image_bytes(p["thumbnail"], client) for p in batch])

        parts = [SIMILARITY_PROMPT, "QUERY image:", query_part]

        indexed_batch = []
        for i, (p, fetched_img) in enumerate(zip(batch, fetched), start=1):
            if fetched_img is None:
                continue
            mime, data = fetched_img
            parts.append(f"CANDIDATE {i}:")
            parts.append({"mime_type": mime, "data": data})
            indexed_batch.append((i, p))

        if not indexed_batch:
            return

        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = await model.generate_content_async(
            parts, generation_config={"response_mime_type": "application/json"}
        )
        parsed = json.loads(resp.text)
        score_by_index = {int(s["index"]): float(s["score"]) for s in parsed.get("scores", [])}

        for i, p in indexed_batch:
            if i in score_by_index:
                p["similarity_score"] = max(0.0, min(1.0, score_by_index[i]))
    except Exception as e:
        logging.warning(f"⚠️  Gemini similarity batch failed, keeping fallback scores: {e}")


async def score_similarity_with_gemini(query_image: str, products: list[dict]) -> None:
    """AI-score the top MAX_AI_CANDIDATES products in place using Gemini Vision.
    Remaining products, and any that fail, keep their rank-based fallback score."""
    if not GEMINI_API_KEY or not products:
        return

    scoreable = products[:MAX_AI_CANDIDATES]
    logging.info(f"🤖 AI-scoring {len(scoreable)} of {len(products)} candidates")

    query_mime, query_bytes = parse_data_url(query_image)
    query_part = {"mime_type": query_mime, "data": query_bytes}

    sem = asyncio.Semaphore(3)

    async def run_batch(batch: list[dict], client: httpx.AsyncClient):
        async with sem:
            await score_batch(query_part, batch, client)

    async with httpx.AsyncClient() as client:
        batches = [scoreable[i:i + AI_BATCH_SIZE] for i in range(0, len(scoreable), AI_BATCH_SIZE)]
        await asyncio.gather(*[run_batch(b, client) for b in batches])


# ── Routes ────────────────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Safety net so nothing unhandled ever reaches the client as a raw or
    empty response — the real error is still logged server-side."""
    logging.error(f"Unhandled error on {request.method} {request.url.path}", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our end. Please try again."},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/history")
async def get_history(limit: int = 50):
    return await db.list_history(limit)


@app.get("/history/{item_id}")
async def get_history_item(item_id: int):
    item = await db.get_history_item(item_id)
    if item is None:
        raise HTTPException(404, "History item not found")
    return item


@app.post("/search", response_model=list[Product])
async def search(req: SearchRequest):
    if not req.image.startswith("data:image"):
        raise HTTPException(400, "image must be a base64 data-URL")

    country = (req.country or "us").lower().strip()
    serpapi_country, hl, allowed_symbols = COUNTRY_CONFIG.get(country, DEFAULT_CONFIG)
    logging.info(f"Country: {country} → SerpApi country={serpapi_country}, hl={hl}, symbols={allowed_symbols}")

    # 0. Cache lookup — an identical crop searched again in the last hour skips
    #    Cloudinary/SerpApi/scraping/Gemini entirely
    image_hash = hashlib.sha256(req.image.encode()).hexdigest()
    cached = await db.get_cached_search(image_hash, country)
    if cached is not None:
        logging.info(f"✅ Cache hit for {image_hash[:12]}… ({country})")
        await db.log_search_history(
            image_hash, country, cached["query_image_url"], cached["products"], cache_hit=True
        )
        return cached["products"]

    # 1. Cloudinary
    try:
        public_url = upload_to_cloudinary(req.image)
        logging.info(f"✅ Cloudinary: {public_url}")
    except Exception as e:
        logging.exception("Cloudinary upload failed")
        raise HTTPException(500, classify_cloudinary_error(str(e)))

    # 2. SerpApi
    try:
        candidates = await search_serpapi(public_url, serpapi_country, hl)
        logging.info(f"✅ SerpApi: {len(candidates)} raw candidates")
    except SerpApiError as e:
        logging.exception("SerpApi search failed")
        raise HTTPException(502, classify_serpapi_error(e.status_code, e.body))
    except Exception as e:
        logging.exception("SerpApi search failed")
        raise HTTPException(502, classify_serpapi_error(None, str(e)))

    if not candidates:
        return []

    # 3. Filter blocked domains
    filtered = [c for c in candidates if not is_blocked(c.get("link", ""))]
    logging.info(f"✅ After domain filter: {len(filtered)}")

    # 4. Build product list — normalise price, keep only region-matching prices
    products = []
    for i, c in enumerate(filtered):
        raw_price = c.get("price")
        price_str = None

        if isinstance(raw_price, dict):
            # SerpApi price dict: {"value": "$34*", "extracted_value": 34.0, "currency": "$"}
            price_str = raw_price.get("value") or ""
            # Strip trailing asterisk
            price_str = price_str.rstrip("*").strip() or None
        elif isinstance(raw_price, str):
            price_str = raw_price.rstrip("*").strip() or None

        # Only keep price if it matches user's region currency
        if price_str and not price_matches_region(price_str, allowed_symbols):
            logging.info(f"⚠️  Dropping foreign price '{price_str}' for {c.get('source')}")
            price_str = None

        in_stock = str(c.get("stock_information", "")).lower() not in ("out of stock",)

        products.append({
            "title":            c.get("title", "Unknown"),
            "link":             c.get("link", ""),
            "thumbnail":        c.get("thumbnail", ""),
            "source":           c.get("source", ""),
            "price":            price_str,
            "similarity_score": round(1.0 - i * 0.01, 3),
            "in_stock":         in_stock,
        })

    # 5. Scrape prices + AI-score similarity concurrently — independent I/O passes
    #    over the same product dicts, touching different keys, so safe to run together
    products, _ = await asyncio.gather(
        enrich_prices(products, allowed_symbols),
        score_similarity_with_gemini(req.image, products),
    )

    # 5b. Drop products whose link was confirmed dead during price scraping —
    #     a result that fails to load isn't useful regardless of match score
    dropped = sum(1 for p in products if p.get("_unreachable"))
    products = [p for p in products if not p.pop("_unreachable", False)]
    if dropped:
        logging.info(f"🚫 Dropped {dropped} unreachable-link product(s)")

    # 6. Add numeric price_value for frontend sorting
    for p in products:
        p["price_value"] = parse_price_value(p.get("price"))

    # 7. AI scores aren't guaranteed to follow SerpApi's original order — sort
    #    explicitly so the popup's "Best match" sort (which trusts server order) holds
    products.sort(key=lambda p: p["similarity_score"], reverse=True)

    with_price    = [p for p in products if p["price_value"] is not None]
    without_price = [p for p in products if p["price_value"] is None]
    logging.info(f"✅ {len(with_price)} with price, {len(without_price)} without")

    # 8. Cache this result and log it to search history
    await db.save_search_cache(image_hash, country, public_url, products)
    await db.log_search_history(image_hash, country, public_url, products, cache_hit=False)

    return products