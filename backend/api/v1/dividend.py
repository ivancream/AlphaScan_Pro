from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import pandas as pd
import duckdb
import sqlite3
import os

router = APIRouter()

class DividendStatsResponse(BaseModel):
    summary: Dict[str, Dict[str, Any]]
    details: List[Dict[str, Any]]
    yearly: List[Dict[str, Any]]

def get_stock_data(stock_code: str) -> pd.DataFrame:
    try:
        symbol = str(stock_code).strip().upper()
        # 嘗試找出正確的後綴
        symbols_to_try = []
        if symbol.isdigit() and len(symbol) in [4, 5]:
            symbols_to_try = [f"{symbol}.TW", f"{symbol}.TWO"]
        else:
            symbols_to_try = [symbol]
            
        with duckdb.connect('data/market.duckdb') as conn:
            for s in symbols_to_try:
                df = conn.execute(f"""
                    SELECT date, open, high, low, close
                    FROM historical_prices
                    WHERE symbol = ?
                    ORDER BY date ASC
                """, [s]).df()
                if not df.empty:
                    return df
            
        return pd.DataFrame()
            
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        return df
    except Exception as e:
        print(f"Error fetching price data: {e}")
        return pd.DataFrame()

def get_dividends_from_db(stock_code: str) -> pd.DataFrame:
    try:
        with sqlite3.connect("data/taiwan_stock.db") as conn:
            df = pd.read_sql(
                "SELECT date, dividend FROM dividends WHERE stock_id=? ORDER BY date DESC",
                conn, params=(stock_code,)
            )
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
            return df
    except Exception as e:
        print(f"Error fetching dividends: {e}")
        return pd.DataFrame()
        
def backfill_dividends(stock_code: str):
    import yfinance as yf
    try:
        with sqlite3.connect("data/taiwan_stock.db") as conn:
            for suffix in ['.TW', '.TWO']:
                try:
                    t = yf.Ticker(f"{stock_code}{suffix}")
                    divs = t.dividends
                    if divs.empty:
                        continue
                    rows = [(stock_code, d.strftime('%Y-%m-%d'), float(v))
                            for d, v in divs.items()]
                    conn.executemany(
                        "INSERT OR REPLACE INTO dividends (stock_id, date, dividend) VALUES (?,?,?)",
                        rows
                    )
                    conn.commit()
                    return len(rows)
                except Exception as ex:
                    continue
        return 0
    except Exception as e:
        print(f"Backfill error: {e}")
        return 0

def get_dividend_window(price_df, div_date, window=3):
    idx = price_df.index.searchsorted(div_date)
    if idx >= len(price_df):
        return None

    found_date = price_df.index[idx]
    if abs((found_date - div_date).days) > 5:
        return None

    rows = {}
    for offset in range(-(window + 1), window + 1):
        pos = idx + offset
        if 0 <= pos < len(price_df):
            rows[offset] = price_df.iloc[pos]
        else:
            rows[offset] = None
    return rows

@router.get("/api/v1/dividend/{stock_code}/scan")
async def get_dividend_analysis(stock_code: str):
    """取得個股歷年除權息前後漲跌行為統計分析"""
    try:
        div_df = get_dividends_from_db(stock_code)
        
        # If no dividends, try to auto fetch from Yahoo
        if div_df.empty or len(div_df) < 1:
            backfill_dividends(stock_code)
            div_df = get_dividends_from_db(stock_code)
            
        if div_df.empty:
             return {"summary": {}, "details": [], "yearly": [], "message": f"No dividend data found for {stock_code}"}
             
        # Limit to 10 years
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=10)
        div_df = div_df[div_df['date'] >= cutoff].reset_index(drop=True)
        
        price_df = get_stock_data(stock_code)
        if price_df.empty:
            raise HTTPException(status_code=404, detail="Stock price history not found")
            
        # Build Stats
        price_df.index = pd.to_datetime(price_df.index).normalize()

        records = []
        for _, row in div_df.iterrows():
            div_date = pd.Timestamp(row['date']).normalize()
            cash_div = round(float(row['dividend']), 2)
            
            window = get_dividend_window(price_df, div_date, window=3)
            if not window: continue
            
            day0 = window.get(0)
            if day0 is None: continue
            
            prev1 = window.get(-1)
            
            yield_pct = None
            if prev1 is not None and prev1['close'] > 0:
                yield_pct = cash_div / prev1['close'] * 100

            def calc_pct(c, p):
                return (c - p) / p * 100 if pd.notna(c) and pd.notna(p) and p else None

            open_gap = calc_pct(day0['open'] if day0 is not None else None, prev1['close'] if prev1 is not None else None)
            intraday = calc_pct(day0['close'] if day0 is not None else None, day0['open'] if day0 is not None else None)

            rec = {
                'date': div_date.strftime('%Y/%m/%d'),
                'dividend': cash_div,
                'yieldPct': round(yield_pct, 2) if yield_pct is not None else None,
            }

            for offset in range(-3, 4):
                curr = window.get(offset)
                prev = window.get(offset - 1)
                chg = calc_pct(curr['close'] if curr is not None else None, prev['close'] if prev is not None else None)
                label = f"d{offset}" if offset < 0 else (f"d_plus_{offset}" if offset > 0 else "d0")
                rec[label] = round(chg, 2) if chg is not None else None

            rec['intraday'] = round(intraday, 2) if intraday is not None else None
            rec['openGap'] = round(open_gap, 2) if open_gap is not None else None
            records.append(rec)
            
        if not records:
             return {"summary": {}, "details": [], "yearly": [], "message": "Could not map dividend dates to market history"}
             
        detail_df = pd.DataFrame(records)
        
        # Summary grouping
        cols_map = {
            'd-3': '3天前', 'd-2': '2天前', 'd-1': '1天前', 'd0': '當日', 
            'd_plus_1': '1天後', 'd_plus_2': '2天後', 'd_plus_3': '3天後', 
            'intraday': '當日開_閉', 'openGap': '開盤跳空'
        }
        summary_rows = {}
        for k, name in cols_map.items():
            if k not in detail_df.columns: continue
            vals = detail_df[k].dropna()
            if len(vals) == 0:
                summary_rows[name] = {'upProb': None, 'upAvg': None, 'dnAvg': None, 'avg': None}
                continue
            up_vals = vals[vals > 0]
            dn_vals = vals[vals < 0]
            summary_rows[name] = {
                'upProb': round(len(up_vals)/len(vals)*100, 1),
                'upAvg': round(up_vals.mean(), 2) if len(up_vals) > 0 else None,
                'dnAvg': round(dn_vals.mean(), 2) if len(dn_vals) > 0 else None,
                'avg': round(vals.mean(), 2)
            }
            
        # Yearly
        detail_df['year'] = detail_df['date'].str[:4]
        yearly_df = detail_df.groupby('year').agg(
             totalDividend=('dividend', 'sum'),
             avgYield=('yieldPct', 'mean')
        ).reset_index().sort_values('year', ascending=False)
        yearly_df['totalDividend'] = yearly_df['totalDividend'].round(2)
        yearly_df['avgYield'] = yearly_df['avgYield'].round(2)
        
        return {
            "summary": summary_rows,
            "details": records,
            "yearly": yearly_df.to_dict(orient="records"),
            "total_count": len(records)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/v1/dividend/search")
async def search_stock(q: str):
    """查詢股票名稱或代號"""
    try:
        with sqlite3.connect("data/taiwan_stock.db") as conn:
            cursor = conn.execute("SELECT stock_id, name FROM stock_info WHERE stock_id LIKE ? OR name LIKE ? LIMIT 20", (f'%{q}%', f'%{q}%'))
            rows = cursor.fetchall()
            return [{"id": r[0], "name": r[1]} for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
