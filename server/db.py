import json
import os

import aiosqlite

DB_PATH = os.path.join(os.path.dirname(__file__), "pinpoint.db")

SEARCH_CACHE_TTL_MINUTES = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS search_cache (
    image_hash      TEXT NOT NULL,
    country         TEXT NOT NULL,
    query_image_url TEXT NOT NULL,
    products_json   TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (image_hash, country)
);

CREATE TABLE IF NOT EXISTS search_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    image_hash      TEXT NOT NULL,
    country         TEXT NOT NULL,
    query_image_url TEXT NOT NULL,
    products_json   TEXT NOT NULL,
    result_count    INTEGER NOT NULL,
    cache_hit       INTEGER NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def get_cached_search(image_hash: str, country: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT query_image_url, products_json FROM search_cache
            WHERE image_hash = ? AND country = ?
              AND created_at > datetime('now', ?)
            """,
            (image_hash, country, f"-{SEARCH_CACHE_TTL_MINUTES} minutes"),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "query_image_url": row["query_image_url"],
            "products": json.loads(row["products_json"]),
        }


async def save_search_cache(image_hash: str, country: str, query_image_url: str, products: list[dict]) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO search_cache (image_hash, country, query_image_url, products_json, created_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (image_hash, country) DO UPDATE SET
                query_image_url = excluded.query_image_url,
                products_json   = excluded.products_json,
                created_at      = excluded.created_at
            """,
            (image_hash, country, query_image_url, json.dumps(products)),
        )
        await db.commit()


async def log_search_history(
    image_hash: str, country: str, query_image_url: str, products: list[dict], cache_hit: bool
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO search_history
                (image_hash, country, query_image_url, products_json, result_count, cache_hit)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (image_hash, country, query_image_url, json.dumps(products), len(products), int(cache_hit)),
        )
        await db.commit()


async def list_history(limit: int = 50) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, query_image_url, country, result_count, created_at
            FROM search_history
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_history_item(item_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, query_image_url, country, result_count, created_at, products_json
            FROM search_history
            WHERE id = ?
            """,
            (item_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        item = dict(row)
        item["products"] = json.loads(item.pop("products_json"))
        return item
