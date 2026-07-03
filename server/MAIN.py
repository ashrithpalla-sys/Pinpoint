import os
import re
import json
import httpx
import base64
import asyncio
import cloudinary
import cloudinary.uploader
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO)
load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
)

SERPAPI_KEY = os.getenv("SERPAPI_KEY")

app = FastAPI()
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
        host = urlparse(link).netloc.lower().lstrip("www.")
        return any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAINS)
    except Exception:
        return False


def price_matches_region(price_str: str, allowed_symbols: list[str]) -> bool:
    """Return True if price string contains one of the allowed currency symbols."""
    if not price_str:
        return False
    for sym in allowed_symbols:
        if sym in price_str:
            return True
    return False


def upload_to_cloudinary(data_url: str) -> str:
    result = cloudinary.uploader.upload(
        data_url, folder="pinpoint", resource_type="image"
    )
    return result["secure_url"]


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
        resp.raise_for_status()
        data = resp.json()

    # Log full raw response so we can see what SerpApi actually returns
    logging.info(f"SerpApi raw keys: {list(data.keys())}")
    matches = data.get("visual_matches") or data.get("shopping_results") or []
    logging.info(f"SerpApi raw sample (first 3): {json.dumps(matches[:3], indent=2)}")
    return matches[:60]


async def scrape_price(url: str, client: httpx.AsyncClient, allowed_symbols: list[str]) -> str | None:
    """Scrape product page for a price matching the user's region currency."""
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
            return None

        html = resp.text
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

        # 2. Regex — only match currency symbols for this region
        sym_pattern = "|".join(re.escape(s) for s in allowed_symbols)
        price_pattern = re.compile(
            rf'({sym_pattern})\s*[\d,]+(?:\.\d{{1,2}})?',
            re.IGNORECASE
        )
        matches_found = price_pattern.findall(html)
        for m in matches_found[:10]:
            full = price_pattern.search(html)
            if full:
                candidate = full.group(0).strip()
                digits = re.sub(r'[^\d.]', '', candidate)
                try:
                    if 1 < float(digits) < 500000:
                        return candidate
                except Exception:
                    continue

        return None
    except Exception as e:
        logging.debug(f"Price scrape failed for {url}: {e}")
        return None


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
                scraped = await scrape_price(p["link"], client, allowed_symbols)
                if scraped:
                    p["price"] = scraped
                    logging.info(f"✅ Scraped price for {p['source']}: {scraped}")
                else:
                    logging.info(f"⚠️  No price found for {p['source']} — {p['link'][:60]}")
        return p

    return list(await asyncio.gather(*[fetch_one(p) for p in products]))


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/search", response_model=list[Product])
async def search(req: SearchRequest):
    if not req.image.startswith("data:image"):
        raise HTTPException(400, "image must be a base64 data-URL")

    country = (req.country or "us").lower().strip()
    serpapi_country, hl, allowed_symbols = COUNTRY_CONFIG.get(country, DEFAULT_CONFIG)
    logging.info(f"Country: {country} → SerpApi country={serpapi_country}, hl={hl}, symbols={allowed_symbols}")

    # 1. Cloudinary
    try:
        public_url = upload_to_cloudinary(req.image)
        logging.info(f"✅ Cloudinary: {public_url}")
    except Exception as e:
        raise HTTPException(500, f"Cloudinary upload failed: {e}")

    # 2. SerpApi
    try:
        candidates = await search_serpapi(public_url, serpapi_country, hl)
        logging.info(f"✅ SerpApi: {len(candidates)} raw candidates")
    except Exception as e:
        raise HTTPException(502, f"SerpApi search failed: {e}")

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

    # 5. Scrape prices for products missing them (region-aware)
    products = await enrich_prices(products, allowed_symbols)

    # 6. Add numeric price_value for frontend sorting
    for p in products:
        p["price_value"] = parse_price_value(p.get("price"))

    with_price    = [p for p in products if p["price_value"] is not None]
    without_price = [p for p in products if p["price_value"] is None]
    logging.info(f"✅ {len(with_price)} with price, {len(without_price)} without")

    return products