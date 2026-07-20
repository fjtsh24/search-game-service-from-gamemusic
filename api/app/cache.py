"""
Upstash Redis REST API を使ったシンプルなキャッシュラッパー。

使い方:
  from app.cache import cache
  await cache.get("key")
  await cache.set("key", "value", ex=300)
  await cache.delete("key")
"""

import json
import httpx
from urllib.parse import quote
from app.config import settings

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.upstash_redis_url,
            headers={"Authorization": f"Bearer {settings.upstash_redis_token}"},
            timeout=5.0,
        )
    return _client


async def get(key: str) -> str | None:
    """キャッシュから値を取得。存在しなければ None を返す。"""
    resp = await _get_client().get(f"/get/{key}")
    result = resp.json().get("result")
    return result


async def set(key: str, value: str | dict | list, ex: int = 300) -> None:
    """キャッシュに値をセット。ex は秒単位の TTL（デフォルト 5 分）。"""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    # JSON や特殊文字が URL パスセグメントに入ると壊れるので URL エンコード
    encoded = quote(value, safe="")
    await _get_client().get(f"/set/{key}/{encoded}/ex/{ex}")


async def delete(key: str) -> None:
    """キャッシュから値を削除。"""
    await _get_client().get(f"/del/{key}")


async def close() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None
