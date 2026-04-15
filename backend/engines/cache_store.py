"""
輕量級進程內 TTL 快取 (in-process memory cache)

設計原則：
  • 純 Python 標準庫，不依賴 Redis / Memcached
  • Thread-safe（讀寫皆持鎖）
  • Key 由 prefix + params hash 組成，相同 query params 命中相同快取桶
  • TTL 預設 12 小時（靜態資料：雙刀戰法 / 除權息 / 可轉債）
  • 到期項目在下次讀取時惰性清除；另可呼叫 purge_expired() 主動清理

使用範例：
    from backend.engines.cache_store import StaticCache

    key = StaticCache.make_key("swing:long", req_ma=True, req_vol=True)
    cached = StaticCache.get(key)
    if cached is None:
        result = expensive_computation()
        StaticCache.set(key, result)
    else:
        result = cached
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Optional

# ── 常數 ──────────────────────────────────────────────────────────────────────
TTL_12H = 12 * 3600          # 靜態模組 (雙刀 / 除權息 / 可轉債)
TTL_1H  = 1  * 3600          # 半靜態備用
TTL_30M = 30 * 60            # 盤中短快取備用


class _TTLStore:
    """
    線程安全的 TTL 快取容器。

    結構：_store: dict[str, tuple[Any, float]]
          value = (data, expires_at_unix_timestamp)
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock  = threading.Lock()

    # ── 核心 CRUD ─────────────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[Any]:
        """
        取得快取值。若 key 不存在或已過期則回傳 None。
        過期項目會在此時惰性移除。
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            data, exp = entry
            if time.monotonic() > exp:
                del self._store[key]
                return None
            return data

    def set(self, key: str, data: Any, ttl: int = TTL_12H) -> None:
        """寫入快取，覆寫同 key 舊值。"""
        with self._lock:
            self._store[key] = (data, time.monotonic() + ttl)

    def delete(self, key: str) -> bool:
        """刪除單一 key，回傳是否成功找到並刪除。"""
        with self._lock:
            return self._store.pop(key, None) is not None

    def invalidate_prefix(self, prefix: str) -> int:
        """刪除所有以 prefix 開頭的 key，回傳刪除數量。"""
        with self._lock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]
            return len(keys)

    def purge_expired(self) -> int:
        """主動清除所有已過期項目，回傳清除數量。"""
        with self._lock:
            now = time.monotonic()
            expired = [k for k, (_, exp) in self._store.items() if now > exp]
            for k in expired:
                del self._store[k]
            return len(expired)

    # ── 工具 ──────────────────────────────────────────────────────────────────

    @staticmethod
    def make_key(prefix: str, **params) -> str:
        """
        產生快取 key。

        Args:
            prefix: 模組標識字串，例如 "swing:long", "cb:scan"
            **params: query params，會以 JSON 序列化後 md5 雜湊

        Returns:
            格式為 "{prefix}:{hash8}" 的字串

        Example:
            key = StaticCache.make_key("swing:long", req_ma=True, req_vol=True)
            # → "swing:long:a3f1c8b2"
        """
        raw = json.dumps(params, sort_keys=True, default=str).encode()
        h   = hashlib.md5(raw).hexdigest()[:8]
        return f"{prefix}:{h}" if params else prefix

    def stats(self) -> dict:
        """回傳目前快取統計（不包含資料內容）。"""
        with self._lock:
            now   = time.monotonic()
            total = len(self._store)
            valid = sum(1 for _, (_, exp) in self._store.items() if exp > now)
            return {
                "total":   total,
                "valid":   valid,
                "expired": total - valid,
            }

    def list_keys(self, prefix: str = "") -> list[str]:
        """列出所有（或特定前綴的）key，供除錯使用。"""
        with self._lock:
            now = time.monotonic()
            return [
                k for k, (_, exp) in self._store.items()
                if (not prefix or k.startswith(prefix)) and exp > now
            ]


# ── 進程共享的單例快取實例 ────────────────────────────────────────────────────
StaticCache = _TTLStore()
