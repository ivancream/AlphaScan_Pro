import pandas as pd
from fastapi import APIRouter
from backend.db import queries as _db_queries
from backend.db.symbol_utils import strip_suffix

router = APIRouter()


@router.get("/api/v1/backtest/history")
async def get_simple_backtest(stock_id: str, strategy: str = "core_long"):
    """
    提供個股過去一年，特定策略的歷史勝率與報酬率回報
    目前支援: core_long (猛虎出閘)
    """
    sid = strip_suffix(stock_id)
    df = _db_queries.get_price_df(sid, period="2y")
    if df.empty:
        return {"error": "Database not found"}

    df = df.rename(columns={"date": "date", "open": "open", "high": "high",
                              "low": "low", "close": "close", "volume": "volume"})

    if len(df) < 60:
        return {"error": "Not enough data"}

    # 模擬技術指標 (仿造 core_long 邏輯)
    df['MA5'] = df['close'].rolling(5).mean()
    df['MA20'] = df['close'].rolling(20).mean()
    df['MA60'] = df['close'].rolling(60).mean()
    
    # 布林
    std = df['close'].rolling(20).std()
    df['Bollinger_Up'] = df['MA20'] + 2.1 * std
    df['Bollinger_Down'] = df['MA20'] - 2.1 * std
    df['Bandwidth'] = ((df['Bollinger_Up'] - df['Bollinger_Down']) / df['MA20']) * 100
    df['Bandwidth_1d'] = df['Bandwidth'].shift(1)
    
    # 找訊號點
    signals = []
    
    if strategy == "core_long":
        # 猛虎出閘條件：帶寬擴張，收盤突破上軌或極近，多排
        for i in range(60, len(df)):
            if df.iloc[i]['MA5'] > df.iloc[i]['MA20'] > df.iloc[i]['MA60']: # 均線多排
                if df.iloc[i]['Bandwidth'] > df.iloc[i]['Bandwidth_1d'] * 1.05: # 帶寬擴張
                    if df.iloc[i]['close'] >= df.iloc[i]['Bollinger_Up'] * 0.985: # 觸及上軌
                        signals.append(i)
                        
    elif strategy == "core_short":
        for i in range(60, len(df)):
            if df.iloc[i]['MA5'] < df.iloc[i]['MA20'] < df.iloc[i]['MA60']:
                if df.iloc[i]['close'] <= df.iloc[i]['Bollinger_Down'] * 1.015:
                    signals.append(i)

    if not signals:
        return {
            "signal_count": 0,
            "win_rate_5d": 0,
            "avg_return_5d": 0,
            "best_return_5d": 0,
            "worst_return_5d": 0,
        }

    # 計算持有5日報酬
    returns_5d = []
    # 避免重複訊號 (比如連三天猛虎出閘，只算第一天進場)
    filtered_signals = []
    last_sig = -999
    for s in signals:
        if s - last_sig >= 5: # 至少間隔5天再算新訊號
            filtered_signals.append(s)
            last_sig = s
            
    for s in filtered_signals:
        if s + 5 < len(df):
            entry_price = df.iloc[s]['close']
            exit_price = df.iloc[s+5]['close']
            ret = ((exit_price - entry_price) / entry_price) * 100
            if strategy == "core_short":
                ret = -ret
            returns_5d.append(ret)
            
    if not returns_5d:
         return {"signal_count": len(filtered_signals), "note": "訊號都在最近剛發生，尚無5日後結果"}

    wins = [r for r in returns_5d if r > 0]
    win_rate = (len(wins) / len(returns_5d)) * 100
    avg_return = sum(returns_5d) / len(returns_5d)
    
    return {
        "signal_count": len(returns_5d),
        "win_rate_5d": round(win_rate, 1),
        "avg_return_5d": round(avg_return, 2),
        "best_return_5d": round(max(returns_5d), 2),
        "worst_return_5d": round(min(returns_5d), 2),
    }
