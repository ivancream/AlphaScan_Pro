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

import datetime
import hashlib
import json
import os
import threading
import time
import zoneinfo
from typing import Any, Dict, List, Mapping, Optional

_TZ_TW = zoneinfo.ZoneInfo("Asia/Taipei")

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


class IntradayAlertCounter:
    """
    盤中即時警報「防洗版」計數器（進程內記憶體，鍵格式：「代號_策略」如 2330_long）。

    - 每個交易日獨立計數；跨日讀寫時自動依台北日期歸零。
    - 亦可由 scheduler 於 14:00 呼叫 clear_all() 強制清空。
    """

    _lock = threading.Lock()
    _counts: dict[str, int] = {}
    _date: str = ""

    @classmethod
    def _today_iso(cls) -> str:
        return datetime.datetime.now(_TZ_TW).date().isoformat()

    @classmethod
    def _roll_date_if_needed_unlocked(cls) -> None:
        t = cls._today_iso()
        if cls._date != t:
            cls._date = t
            cls._counts.clear()

    @classmethod
    def max_per_strategy_per_day(cls) -> int:
        try:
            return max(1, int(os.getenv("INTRADAY_ALERT_MAX_PER_DAY", "2")))
        except ValueError:
            return 2

    @classmethod
    def get_count(cls, stock_id: str, strategy: str) -> int:
        sid = str(stock_id).strip()
        st = str(strategy).strip().lower()
        if not sid or not st:
            return 0
        key = f"{sid}_{st}"
        with cls._lock:
            cls._roll_date_if_needed_unlocked()
            return int(cls._counts.get(key, 0))

    @classmethod
    def filter_rows_under_cap(
        cls,
        rows: List[dict],
        strategy: str,
        max_per_day: Optional[int] = None,
    ) -> List[dict]:
        """回傳今日該策略尚未達發送次數上限的列（不修改計數）。"""
        cap = max_per_day if max_per_day is not None else cls.max_per_strategy_per_day()
        st = str(strategy).strip().lower()
        out: list[dict] = []
        with cls._lock:
            cls._roll_date_if_needed_unlocked()
            for r in rows:
                sid = str(r.get("代號") or r.get("stock_id") or "").strip()
                if not sid:
                    continue
                key = f"{sid}_{st}"
                if int(cls._counts.get(key, 0)) < cap:
                    out.append(r)
        return out

    @classmethod
    def record_sent_for_rows(cls, rows: List[dict], strategy: str) -> None:
        """每成功推送一輪後，對該批每檔 +1（依代號與策略）。"""
        st = str(strategy).strip().lower()
        if not st:
            return
        with cls._lock:
            cls._roll_date_if_needed_unlocked()
            for r in rows:
                sid = str(r.get("代號") or r.get("stock_id") or "").strip()
                if not sid:
                    continue
                key = f"{sid}_{st}"
                cls._counts[key] = int(cls._counts.get(key, 0)) + 1

    @classmethod
    def clear_all(cls) -> None:
        """清空計數（排程收盤後呼叫）。"""
        with cls._lock:
            cls._counts.clear()
            cls._date = ""

    @classmethod
    def snapshot_stats(cls) -> Dict[str, Any]:
        """除錯用：目前日期鍵與筆數（不含明細）。"""
        with cls._lock:
            cls._roll_date_if_needed_unlocked()
            return {"date": cls._date, "keys": len(cls._counts)}

    @classmethod
    def apply_after_discord_notify(
        cls,
        notify_summary: Mapping[str, Any],
        pending: Mapping[str, Any],
    ) -> None:
        """
        在 notify_scan_results 成功送出後，依各策略 payload 成對累加今日次數。
        notify_summary 需含 'long'/'short'/'wanderer' 各為 requests 結果 list。
        """
        if notify_summary.get("skipped"):
            return

        def _all_ok(outs: Any) -> bool:
            if not outs:
                return False
            return all(isinstance(x, dict) and x.get("ok") for x in outs)

        if _all_ok(notify_summary.get("long")):
            cls.record_sent_for_rows(list(pending.get("long") or []), "long")
        if _all_ok(notify_summary.get("short")):
            cls.record_sent_for_rows(list(pending.get("short") or []), "short")
        if _all_ok(notify_summary.get("wanderer")):
            cls.record_sent_for_rows(list(pending.get("wanderer") or []), "wanderer")
