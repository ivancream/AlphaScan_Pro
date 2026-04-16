"""
系統資料狀態 API

GET /api/v1/system/data-status
  回傳各資料表的最後更新時間、筆數、狀態，供前端顯示 data-freshness 指示器。
"""

from fastapi import APIRouter
from backend.db import queries

router = APIRouter()


@router.get("/api/v1/system/data-status")
async def get_data_status():
    """
    回傳各資料表的更新狀態。
    若 update_log 為空（首次啟動前尚未執行任何更新），回傳空清單。
    """
    try:
        df = queries.get_update_log()
        if df.empty:
            return {"tables": [], "note": "尚無更新記錄，請先執行資料初始化。"}

        tables = df.to_dict(orient="records")
        return {"tables": tables}
    except Exception as exc:
        return {"tables": [], "error": str(exc)}


@router.get("/api/v1/system/health")
async def health_check():
    """簡易健康檢查，確認 DuckDB 可正常讀取。"""
    try:
        latest = queries.get_latest_price_date()
        from backend.db.connection import duck_read
        with duck_read() as conn:
            stock_count = conn.execute("SELECT COUNT(*) FROM stock_info").fetchone()[0]
            price_count = conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
            date_dist = conn.execute("""
                SELECT date::VARCHAR AS d, COUNT(DISTINCT stock_id) AS n
                FROM daily_prices
                WHERE date >= (SELECT MAX(date) - INTERVAL '7 days' FROM daily_prices)
                GROUP BY d ORDER BY d DESC
            """).fetchall()
        return {
            "status": "ok",
            "latest_price_date": latest,
            "stock_count": stock_count,
            "daily_prices_rows": price_count,
            "recent_dates": [{"date": r[0], "stocks": r[1]} for r in date_dist],
        }
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}
