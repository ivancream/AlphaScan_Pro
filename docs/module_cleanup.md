# AlphaScan Pro 模組整理紀錄

更新日：2026-06-09

## 系統定位

AlphaScan Pro 目前比較適合定位成「台股交易工作台」，主線應該聚焦在盤中戰情、資金流、選股掃描、個股 drill-down，以及需要日資料支撐的研究工具。舊的 Next.js 時期模組仍保留在路由中，但不應該全部放進主選單，否則使用者會以為每個入口都已經完成。

## 主選單保留模組

| 群組 | 模組 | 路由 | 判斷 |
| --- | --- | --- | --- |
| 盤中戰情 | 大盤動態 | `/taiex-dynamics` | 有 `/api/v1/market/taiex-overview` 與盤中元件支撐 |
| 盤中戰情 | 盤中監控 | `/intraday-monitor` | 有 REST replay 與 `/ws/intraday-monitor` |
| 盤中戰情 | 全市場 Tape | `/all-around` | 有 all-around WebSocket engine |
| 盤中戰情 | 資金熱區 | `/capital-flow` | 有 `/api/v1/heatmap/data` |
| 交易選股 | 自選股 | `/watchlist` | 有 user DB 與 watchlist API |
| 交易選股 | 偏多選股 | `/long-selection` | 有 scanner fast path 與 swing fallback |
| 交易選股 | 偏空選股 | `/short-selection` | 有 scanner fast path 與 swing fallback |
| 交易選股 | 雙劍合璧 | `/double-sword` | 有 correlation API |
| 研究工具 | 權證篩選 | `/warrant-selection` | 有 warrant master 與 Shioaji snapshot 流程 |
| 研究工具 | 股利除息 | `/dividends` | 有 dividend API |
| 研究工具 | 可轉債 CB | `/cb-bond` | 有 CB scanner/stats/history/reverse API |

## 保留但不放主選單

這些模組有後端 controller 或仍可能從個股頁被串起來，先保留直接路由：

| 模組 | 路由 |
| --- | --- |
| 技術分析 | `/technical` |
| 全球市場 | `/global-market` |
| 基本面分析 | `/fundamental` |
| 籌碼分析 | `/chips` |
| 處置股分析 | `/disposition` |
| 跌深反彈 | `/floor-bounce` |
| 個股中心 | `/stock`, `/stock/:symbol` |

## 已停用模組

| 模組 | 路由 | 原因 |
| --- | --- | --- |
| ETF 持股追蹤 | `/etf-tracker` | 前端期待 `/api/v1/etfs/*`，但目前後端沒有 `etfs.py` router，DuckDB schema 也沒有 ETF holdings table。現在改成明確的停用頁，避免使用者進入後看到一串 API 失敗。 |

## 後續要恢復 ETF 時需要補的契約

1. DuckDB schema：`etf_holdings(etf_code, holding_date, stock_id, stock_name, shares, weight_pct)`，以及 ETF metadata table。
2. 後端 router：`backend/api/v1/etfs.py`，至少提供 `/list`、`/{etfCode}/dates`、`/{etfCode}/holdings`、`/all/dates`、`/cross-analysis`。
3. 資料更新腳本：建立可重跑、可審計的 ETF holdings ingest，而不是只在前端提供 trigger button。
4. API 完成後，再把 `/etf-tracker` 從停用頁切回 `EtfTrackerPage` 並放回主選單。
