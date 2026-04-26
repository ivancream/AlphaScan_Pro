"""
Ingest 5y historical ML data into DuckDB.

Data-source strategy (stability-first):
1) Adjusted daily bars: local daily_prices (fallback yfinance TW/OTC).
2) Institutional chips: FinMind API (requires FINMIND_API_TOKEN in .env).
3) Macro indicators: yfinance (^TWII, ^VIX).

Writes to:
- historical_kbars_adj
- historical_chips
- macro_indicators
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Set

import duckdb
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

# Allow "python backend/scripts/ingest_historical_ml_data.py" execution
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.db.connection import DUCKDB_PATH, init_duckdb  # noqa: E402
from backend.db.user_db import get_watchlist  # noqa: E402
from backend.engines.data_providers.finmind_client import FinMindClient  # noqa: E402


def get_symbol_universe(conn: duckdb.DuckDBPyConnection, limit: Optional[int]) -> List[str]:
    q = """
        SELECT stock_id
        FROM stock_info si
        WHERE si.is_active = TRUE
          AND si.market IN ('TSE', 'OTC')
          AND regexp_full_match(si.stock_id, '^[0-9]{4}$')
          AND EXISTS (
              SELECT 1
              FROM daily_prices dp
              WHERE dp.stock_id = si.stock_id
                AND dp.date >= (CURRENT_DATE - INTERVAL 120 DAY)
          )
        ORDER BY stock_id
    """
    if limit and limit > 0:
        q += f" LIMIT {int(limit)}"
    rows = conn.execute(q).fetchall()
    return [str(r[0]).strip() for r in rows if r and str(r[0]).strip()]


def get_watchlist_symbols_best_effort() -> List[str]:
    try:
        return [str(s).strip() for s in get_watchlist() if str(s).strip()]
    except Exception:
        return []


def get_symbols_by_avg_volume(
    conn: duckdb.DuckDBPyConnection,
    start_date: str,
    *,
    limit: Optional[int] = None,
) -> List[str]:
    """依 historical_kbars_adj 區間內平均成交量排序（大到小）。"""
    q = """
        SELECT symbol
        FROM (
            SELECT symbol, AVG(volume) AS avol
            FROM historical_kbars_adj
            WHERE date >= ?::DATE
              AND volume IS NOT NULL
            GROUP BY symbol
        ) t
        ORDER BY avol DESC NULLS LAST
    """
    if limit and int(limit) > 0:
        q += f" LIMIT {int(limit)}"
    try:
        rows = conn.execute(q, [start_date]).fetchall()
    except Exception:
        return []
    return [str(r[0]).strip() for r in rows if r and r[0]]


def parse_symbols_csv(s: str) -> List[str]:
    out: List[str] = []
    for part in (s or "").split(","):
        p = str(part).strip()
        if p:
            out.append(p)
    return out


def read_symbols_file(path: Path) -> List[str]:
    out: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        p = line.split("#", 1)[0].strip()
        if p:
            out.append(p)
    return out


def build_chip_symbol_order(
    conn: duckdb.DuckDBPyConnection,
    start_date: str,
    *,
    explicit: Optional[List[str]] = None,
    prioritize_watchlist: bool = True,
    volume_limit: Optional[int] = None,
    fallback_universe_limit: Optional[int] = None,
) -> List[str]:
    """
    回補籌碼用的 symbol 順序：
    1) explicit（--symbols / --symbols-file）
    2) 自選股（watchlist）
    3) historical_kbars_adj 平均成交量大者
    4) stock_info 活躍股（fallback）
    """
    if explicit:
        uniq = list(dict.fromkeys([str(x).strip() for x in explicit if str(x).strip()]))
        if uniq:
            return uniq

    ordered: List[str] = []
    seen: Set[str] = set()

    def add_many(ids: Iterable[str]) -> None:
        for raw in ids:
            sid = str(raw).strip()
            if not sid or sid in seen:
                continue
            seen.add(sid)
            ordered.append(sid)

    if prioritize_watchlist:
        add_many(get_watchlist_symbols_best_effort())

    add_many(get_symbols_by_avg_volume(conn, start_date, limit=volume_limit))

    if not ordered:
        add_many(get_symbol_universe(conn, fallback_universe_limit))

    return ordered


def _normalize_yf_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.reset_index().copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.droplevel(1)
    out.columns = [str(c).strip().lower() for c in out.columns]
    return out


def fetch_adj_kbars(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    tickers = [f"{symbol}.TW", f"{symbol}.TWO"]
    for ticker in tickers:
        raw = yf.download(
            ticker,
            start=start_date,
            end=end_date,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        if raw is None or raw.empty:
            continue
        df = _normalize_yf_columns(raw)
        if "date" not in df.columns:
            continue
        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                df[col] = None
        df["amount"] = pd.to_numeric(df["close"], errors="coerce") * pd.to_numeric(
            df["volume"], errors="coerce"
        )
        df["symbol"] = symbol
        df = df[["symbol", "date", "open", "high", "low", "close", "volume", "amount"]]
        return df
    return pd.DataFrame()


def fetch_kbars_from_local_duckdb(
    conn: duckdb.DuckDBPyConnection, symbol: str, start_date: str, end_date: str
) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT
            stock_id AS symbol,
            date,
            open,
            high,
            low,
            close,
            volume,
            (close * volume) AS amount
        FROM daily_prices
        WHERE stock_id = ?
          AND date >= ?::DATE
          AND date <= ?::DATE
        ORDER BY date ASC
        """,
        [symbol, start_date, end_date],
    ).df()
    if rows is None or rows.empty:
        return pd.DataFrame()
    return rows


def fetch_macro_indicators(start_date: str, end_date: str) -> pd.DataFrame:
    twii = yf.download(
        "^TWII",
        start=start_date,
        end=end_date,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    vix = yf.download(
        "^VIX",
        start=start_date,
        end=end_date,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if twii is None or twii.empty:
        return pd.DataFrame()

    twii_df = _normalize_yf_columns(twii)
    vix_df = _normalize_yf_columns(vix) if vix is not None and not vix.empty else pd.DataFrame()

    macro = pd.DataFrame()
    macro["date"] = twii_df["date"]
    macro["taiex_close"] = pd.to_numeric(twii_df.get("close"), errors="coerce")
    macro["taiex_volume"] = pd.to_numeric(twii_df.get("volume"), errors="coerce")
    if not vix_df.empty and "date" in vix_df.columns:
        vv = vix_df[["date", "close"]].rename(columns={"close": "vix"})
        macro = macro.merge(vv, on="date", how="left")
    else:
        macro["vix"] = None
    return macro


def upsert_dataframe(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    df: pd.DataFrame,
    columns: Iterable[str],
    pk_columns: Iterable[str],
) -> int:
    if df.empty:
        return 0
    cols = list(columns)
    pks = list(pk_columns)
    updates = [c for c in cols if c not in pks]

    conn.register("tmp_df", df[cols])
    sql = f"""
        INSERT INTO {table_name} ({", ".join(cols)})
        SELECT {", ".join(cols)} FROM tmp_df
        ON CONFLICT ({", ".join(pks)}) DO UPDATE SET
            {", ".join([f"{c}=excluded.{c}" for c in updates])}
    """
    conn.execute(sql)
    conn.unregister("tmp_df")
    return len(df)


def chunked(items: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


CHIPS_COLS = [
    "symbol",
    "date",
    "foreign_buy",
    "foreign_sell",
    "investment_trust_buy",
    "investment_trust_sell",
    "dealer_buy",
    "dealer_sell",
    "total_shares_outstanding",
]


def ingest_historical_chips(
    conn: duckdb.DuckDBPyConnection,
    client: FinMindClient,
    symbols: List[str],
    start_s: str,
    end_s: str,
) -> int:
    """逐檔抓取 FinMind 籌碼並 upsert；每檔 commit 一次。"""
    total = 0
    n = len(symbols)
    for i, symbol in enumerate(symbols, start=1):
        print(f"[{i}/{n}] 正在抓取 {symbol} 的籌碼資料...")
        try:
            rows = client.fetch_institutional_investors(symbol, start_s, end_s)
            cdf = FinMindClient.institutional_rows_to_chips_dataframe(symbol, rows)
            if cdf.empty:
                print(f"    -> 無資料或轉換為空，略過")
                continue
            total += upsert_dataframe(
                conn=conn,
                table_name="historical_chips",
                df=cdf,
                columns=CHIPS_COLS,
                pk_columns=["symbol", "date"],
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            print(f"    -> 失敗: {exc}")
            try:
                conn.rollback()
            except Exception:
                pass
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest historical ML dataset into DuckDB")
    parser.add_argument("--years", type=int, default=5, help="Lookback years (default: 5)")
    parser.add_argument("--limit", type=int, default=0, help="Limit symbols for kbars universe smoke test")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size for kbar insert loop")
    parser.add_argument(
        "--chips-only",
        action="store_true",
        help="只回補 historical_chips（不寫入 kbars / macro）",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="只處理指定股票，逗號分隔，例如 2330,2317（優先於自動排序）",
    )
    parser.add_argument(
        "--symbols-file",
        type=Path,
        default=None,
        help="從檔案讀取代號清單（一行一檔，可含 # 註解）",
    )
    parser.add_argument(
        "--no-watchlist-first",
        action="store_true",
        help="不要將自選股置於籌碼回補順序最前",
    )
    parser.add_argument(
        "--volume-rank-limit",
        type=int,
        default=0,
        help="僅取 historical_kbars_adj 平均成交量前 N 檔（0=不限制）",
    )
    parser.add_argument(
        "--max-chips-symbols",
        type=int,
        default=0,
        help="最多處理幾檔籌碼（0=不限制；用於試跑）",
    )
    parser.add_argument(
        "--finmind-max-per-hour",
        type=int,
        default=600,
        help="FinMind 每小時最多請求數（滑動視窗）",
    )
    parser.add_argument(
        "--finmind-min-interval",
        type=float,
        default=0.05,
        help="兩次 FinMind 請求之間最少間隔秒數（額外節流）",
    )
    args = parser.parse_args()
    load_dotenv(PROJECT_ROOT / ".env")

    end_date = date.today()
    start_date = end_date - timedelta(days=max(args.years, 1) * 365)
    start_s = start_date.isoformat()
    end_s = end_date.isoformat()
    token = os.getenv("FINMIND_API_TOKEN")

    print(f"[ML Ingest] DB path: {DUCKDB_PATH}")
    print(f"[ML Ingest] range: {start_s} ~ {end_s}")

    init_duckdb()
    conn = duckdb.connect(str(DUCKDB_PATH))
    try:
        explicit_syms: Optional[List[str]] = None
        if args.symbols_file and args.symbols_file.exists():
            raw = read_symbols_file(args.symbols_file)
            explicit_syms = raw or None
        elif (args.symbols or "").strip():
            raw = parse_symbols_csv(args.symbols)
            explicit_syms = raw or None

        chip_symbols = build_chip_symbol_order(
            conn,
            start_s,
            explicit=explicit_syms,
            prioritize_watchlist=not args.no_watchlist_first,
            volume_limit=int(args.volume_rank_limit) if args.volume_rank_limit > 0 else None,
            fallback_universe_limit=args.limit if args.limit > 0 else None,
        )
        if args.max_chips_symbols and args.max_chips_symbols > 0:
            chip_symbols = chip_symbols[: int(args.max_chips_symbols)]

        if args.chips_only:
            if not token:
                print("[ML Ingest] FINMIND_API_TOKEN 未設定，無法回補籌碼。")
                return
            print(f"[ML Ingest] chips-only 模式，標的數: {len(chip_symbols)}")
            client = FinMindClient(
                token,
                max_requests_per_hour=int(args.finmind_max_per_hour),
                min_interval_seconds=float(args.finmind_min_interval),
            )
            total_chips = ingest_historical_chips(conn, client, chip_symbols, start_s, end_s)
            print(f"[ML Ingest] done: historical_chips rows upserted ~= {total_chips}")
            return

        symbols = get_symbol_universe(conn, args.limit if args.limit > 0 else None)
        if not symbols:
            print("[ML Ingest] no symbols found in stock_info.")
            return
        print(f"[ML Ingest] kbar symbols: {len(symbols)}")

        total_kbars = 0
        for s_chunk in chunked(symbols, max(1, args.batch_size)):
            k_frames: List[pd.DataFrame] = []
            for symbol in s_chunk:
                kdf = fetch_kbars_from_local_duckdb(conn, symbol, start_s, end_s)
                if kdf.empty:
                    kdf = fetch_adj_kbars(symbol, start_s, end_s)
                if not kdf.empty:
                    k_frames.append(kdf)

            if k_frames:
                k_all = pd.concat(k_frames, ignore_index=True)
                total_kbars += upsert_dataframe(
                    conn=conn,
                    table_name="historical_kbars_adj",
                    df=k_all,
                    columns=[
                        "symbol",
                        "date",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "amount",
                    ],
                    pk_columns=["symbol", "date"],
                )

        total_chips = 0
        if token:
            print(f"[ML Ingest] 籌碼回補標的數: {len(chip_symbols)}（FinMind）")
            client = FinMindClient(
                token,
                max_requests_per_hour=int(args.finmind_max_per_hour),
                min_interval_seconds=float(args.finmind_min_interval),
            )
            total_chips = ingest_historical_chips(conn, client, chip_symbols, start_s, end_s)
        else:
            print("[ML Ingest] FINMIND_API_TOKEN 未設定，略過 historical_chips。")

        macro_df = fetch_macro_indicators(start_s, end_s)
        total_macro = upsert_dataframe(
            conn=conn,
            table_name="macro_indicators",
            df=macro_df,
            columns=["date", "taiex_close", "taiex_volume", "vix"],
            pk_columns=["date"],
        )
        conn.commit()
        print(
            "[ML Ingest] done: "
            f"historical_kbars_adj={total_kbars}, "
            f"historical_chips={total_chips}, "
            f"macro_indicators={total_macro}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
