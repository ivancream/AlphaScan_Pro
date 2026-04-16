# AlphaScan Pro — 量化交易系統架構與開發規範

> **版本**: v1.0 | **最後更新**: 2026-04-15
> 本文件為 AI 輔助開發的唯一真實來源 (Single Source of Truth)，所有開發決策必須以此為準。

---

## 1. 核心技術棧 (Tech Stack)

### 前端 (Frontend)
| 技術 | 用途 | 備註 |
|------|------|------|
| **Next.js 14 (App Router)** | 頁面路由與 SSR | 所有頁面採用 `src/app/` 結構 |
| **React** | UI 元件框架 | — |
| **TailwindCSS** | 樣式系統 | 深色金融終端機風格 |
| **Zustand** | 全域狀態管理 | 唯一 store：`useAppStore.ts` |
| **Lightweight Charts** | K 線 / 走勢圖渲染 | `CandlestickChart.tsx` 封裝 |
| **react-virtuoso** | 高頻虛擬列表 | 全方位監控等高頻推播場景 |

### 後端 (Backend)
| 技術 | 用途 | 備註 |
|------|------|------|
| **FastAPI** | RESTful API 框架 | `backend/main.py` 為入口 |
| **Uvicorn** | ASGI 伺服器 | — |
| **asyncio** | 非同步事件迴圈 | 確保不阻塞 |
| **Pydantic v2** | 資料驗證與序列化 | — |
| **DuckDB** | 主資料庫 (OLAP) | `data/market.duckdb` |
| **yfinance** | 歷史股價抓取 | — |
| **Google Gemini AI** | AI 輔助分析 | 目前已 Mock，可於 `main.py` 恢復 |
| **pandas** | 數據處理 | — |

### 資料來源
| 來源 | 用途 |
|------|------|
| **Shioaji API (WebSocket)** | 盤中即時報價推播 |
| **yfinance** | 個股/ETF 歷史 OHLCV |
| **自建爬蟲** | 籌碼、技術面、相關係數離線資料庫 |

---

## 2. 完整目錄架構 (Actual Structure)

```
AlphaScan_Pro/
├── docs/
│   └── architecture.md          # 本檔案 — 系統架構與開發規範
│
├── frontend/
│   └── src/
│       ├── app/                  # Next.js App Router 頁面
│       │   ├── (archive)/        # 【規劃中】非核心舊版頁面歸檔區
│       │   ├── stock/[symbol]/   # 【規劃中】個股情報中心 (Tab 化架構)
│       │   ├── cb-tracker/       # 可轉債追蹤
│       │   ├── chips/            # 籌碼分析
│       │   ├── correlation/      # 關聯分析 / 相關係數
│       │   ├── disposition/      # 主力處置股
│       │   ├── dividend/         # 除權息分析
│       │   ├── etf-tracker/      # ETF 追蹤器
│       │   ├── floor-bounce/     # 地板反彈選股
│       │   ├── fundamental/      # 基本面分析
│       │   ├── global-market/    # 大盤 / 全球市場
│       │   ├── heatmap/          # 板塊熱力圖
│       │   ├── swing-long/       # 波段多方選股
│       │   ├── swing-short/      # 波段空方選股
│       │   ├── technical/        # 技術面掃描
│       │   ├── watchlist/        # 自選清單
│       │   ├── layout.tsx        # 根 Layout (含 MainLayout)
│       │   ├── page.tsx          # 首頁
│       │   └── providers.tsx     # React Context Providers
│       │
│       ├── components/
│       │   ├── charts/
│       │   │   └── CandlestickChart.tsx    # K 線圖元件 (Lightweight Charts)
│       │   ├── chips/
│       │   │   └── ChipsAnalysisWidget.tsx # 籌碼分析 Widget
│       │   ├── layout/
│       │   │   └── MainLayout.tsx          # 主版型 (側欄導覽 + 內容區)
│       │   └── ui/
│       │       ├── GlobalContextMenu.tsx   # 全域右鍵選單
│       │       ├── IntradayRefreshBar.tsx  # 盤中刷新狀態列
│       │       └── LoadingState.tsx        # 通用 Loading 元件
│       │
│       ├── hooks/               # 各模組 API 串接 Hooks
│       │   ├── useBacktest.ts
│       │   ├── useCbTracker.ts
│       │   ├── useChips.ts
│       │   ├── useDividend.ts
│       │   ├── useEtf.ts
│       │   ├── useFloorBounce.ts
│       │   ├── useFundamental.ts
│       │   ├── useGlobalMarket.ts
│       │   ├── useHeatmap.ts
│       │   ├── useHistoricalData.ts
│       │   ├── useIntraday.ts
│       │   ├── useSwing.ts
│       │   ├── useTechnical.ts
│       │   └── useWatchlist.ts
│       │
│       ├── store/
│       │   └── useAppStore.ts   # ⚠️ 唯一全域狀態 — 禁止隨意修改結構
│       └── types/               # TypeScript 型別定義
│
├── backend/
│   ├── main.py                  # FastAPI 入口、CORS、DuckDB 初始化、路由註冊
│   ├── requirements.txt
│   ├── api/
│   │   └── v1/                  # RESTful API 路由層 (Controller)
│   │       ├── backtest.py       → /backtest
│   │       ├── cb_tracker.py     → /cb-tracker
│   │       ├── chips.py          → /chips
│   │       ├── correlation.py    → /correlation
│   │       ├── disposition.py    → /disposition
│   │       ├── dividend.py       → /dividend
│   │       ├── etfs.py           → /etfs
│   │       ├── floor_bounce.py   → /floor-bounce
│   │       ├── fundamental.py    → /fundamental
│   │       ├── global_market.py  → /global-market
│   │       ├── heatmap.py        → /heatmap
│   │       ├── intraday.py       → /intraday (含盤中排程器)
│   │       ├── market_data.py    → /market-data
│   │       ├── sentiment.py      → /sentiment
│   │       ├── swing.py          → /swing
│   │       ├── technical.py      → /technical
│   │       └── watchlist.py      → /watchlist
│   │
│   └── engines/                 # 商業邏輯運算層 (Service)
│       ├── engine_ai.py          # Gemini AI 分析引擎 (目前 Mock)
│       ├── engine_chips.py       # 籌碼計算
│       ├── engine_disposition.py # 主力/分點處置分析
│       ├── engine_fundamental.py # 基本面計算
│       ├── engine_global.py      # 全球市場指標
│       ├── engine_heatmap.py     # 板塊熱力圖計算
│       ├── engine_technical.py   # 技術指標計算 (最大引擎)
│       ├── cb_crawler.py         # 可轉債爬蟲（SQLite cb.db）
│       └── prompts.py            # Gemini 提示詞模板
│
├── databases/                   # 離線 SQLite 資料庫與爬蟲腳本
│   ├── db_chips_ownership.db    # 籌碼持股資料庫
│   ├── db_correlation.db        # 個股相關係數資料庫
│   ├── db_technical_prices.db   # 技術面歷史價格資料庫
│   ├── build_correlation_db.py  # 相關係數資料庫建置腳本
│   ├── crawler_chips.py         # 籌碼爬蟲
│   ├── crawler_main_force.py    # 主力爬蟲
│   ├── crawler_technical.py     # 技術面爬蟲
│   └── update_correlation.py    # 相關係數更新腳本
│
└── data/
    └── market.duckdb            # 主 DuckDB 資料庫 (OLAP，盤中即時更新)
```

---

## 3. 資料庫架構 (Database Schema)

### 主資料庫：`data/market.duckdb` (DuckDB — OLAP)
| 資料表 | 說明 |
|--------|------|
| `historical_prices` | 個股歷史 OHLCV (PK: symbol + date) |
| `key_branch_trades` | 重點分點交易紀錄 (B/S) |
| `warrant_branch_positions` | 權證分點持倉快照 |
| `insider_transfers` | 內部人申報轉讓 |
| `stock_sector_map` | 個股板塊分類 (macro/meso/micro) |

### 離線資料庫 (SQLite)
| 檔案 | 說明 |
|------|------|
| `db_chips_ownership.db` | 法人籌碼持股明細 |
| `db_correlation.db` | 個股間皮爾森相關係數矩陣 |
| `db_technical_prices.db` | 技術分析用歷史價格快取 |

---

## 4. 全域狀態管理 (Zustand Store)

**檔案**: `frontend/src/store/useAppStore.ts`

> ⚠️ **鐵律**: 任何 UI 重構或功能新增，**絕對不可破壞** 此 store 的現有結構。如需擴充，只能新增欄位，不可刪除或重命名現有欄位。

```typescript
interface AppState {
  // 個股選擇
  selectedSymbol: string;           // 目前選中的股票代號
  setSymbol: (symbol: string) => void;

  // 日期範圍
  dateRange: [string, string] | null;
  setDateRange: (range: [string, string]) => void;

  // 技術指標開關
  activeIndicators: string[];       // 預設: ['MA20', 'Volume']
  toggleIndicator: (indicator: string) => void;

  // 全域右鍵選單
  contextMenu: { isOpen: boolean; x: number; y: number; symbol: string | null };
  openContextMenu: (x: number, y: number, symbol: string) => void;
  closeContextMenu: () => void;

  // 選股策略掃描記憶
  scannedStrategies: string[];
  setScanned: (strategyId: string) => void;
}
```

---

## 5. API 層架構 (Backend API)

- **基底 URL**: `http://localhost:8000`
- **前端 Port**: `http://localhost:3000`
- **CORS**: 已設定允許 `localhost:3000`
- **API 版本**: `v1`（路由前綴依各 router 定義）

### 已登錄路由模組
| 模組 | Tag | 主要功能 |
|------|-----|----------|
| `market_data` | Market Data | 市場報價與概覽 |
| `sentiment` | Qualitative Analysis | 情緒 / 質化分析 |
| `global_market` | Global Market | 全球指數 / 大盤動態 |
| `fundamental` | Fundamental Analysis | 財務基本面 |
| `technical` | Technical Analysis | 技術指標掃描 |
| `swing` | Swing Strategy | 波段多空選股 |
| `etfs` | ETF Tracking | ETF 追蹤器 |
| `floor_bounce` | Floor Bounce | 地板反彈選股 |
| `dividend` | Dividend Analysis | 除權息資訊 |
| `cb_tracker` | CB Tracker | 可轉債追蹤 |
| `chips` | Chips Analysis | 籌碼分析 |
| `correlation` | Correlation Strategy | 個股相關係數 |
| `disposition` | Disposition Analysis | 主力處置股分析 |
| `intraday` | Intraday Refresh | 盤中即時更新排程 |
| `watchlist` | Watchlist | 自選清單管理 |
| `backtest` | Backtesting | 策略回測 |
| `heatmap` | Heatmap | 板塊熱力圖 |

---

## 6. 核心導覽模組 (Navigation — 目標架構)

核心導覽**限縮為 8 大模組**，其餘功能整合至個股情報中心 Tab：

| # | 模組名稱 | 對應路由 | 說明 |
|---|----------|----------|------|
| 1 | 大盤動態 | `/global-market` | 全球指數 + 大盤概覽 |
| 2 | 資金流向 | `/chips` | 法人籌碼 + 資金熱點 |
| 3 | 多方選股 | `/swing-long` | 波段多方策略掃描 |
| 4 | 空方選股 | `/swing-short` | 波段空方策略掃描 |
| 5 | 自選清單 | `/watchlist` | 個人追蹤清單 |
| 6 | 雙刀戰法 | `/floor-bounce` | 地板反彈 + 處置股策略 |
| 7 | 除權息 | `/dividend` | 除息選股與配息追蹤 |
| 8 | 可轉債 | `/cb-tracker` | 可轉債套利追蹤 |

### 個股情報中心（規劃中）
- **路由**: `/stock/[symbol]`
- **Tab 架構**: 即時走勢 → 技術分析 → 籌碼分析 → 相關係數 → 可轉債資訊

---

## 7. 開發鐵律 (Development Rules)

### Rule 1 — 極致效能
- 所有高頻 WebSocket 推播場景（如盤中監控），前端**必須**使用 **Virtual List**（react-virtuoso）。
- **嚴格控制 Re-render 範圍**：使用 `React.memo`、`useCallback`、`useMemo` 隔離非必要更新。
- 後端 async 函式內**絕對不可**呼叫同步阻塞操作（如 `time.sleep`、同步 IO）。

### Rule 2 — 防禦性 UI (三態設計)
所有串接外部 API 的元件**必須**實作完整三態：
```
Loading  → 骨架屏 (Skeleton)，不可只用 spinner
Empty    → 精美無資料提示，附說明文字
Error    → 錯誤訊息 + 重試按鈕
```
參考實作：`src/components/ui/LoadingState.tsx`

### Rule 3 — 無損重構
- 進行任何 UI/UX 調整或目錄搬移時，**不可破壞** `useAppStore.ts` 的現有狀態結構。
- 新增功能只能在 store 中**新增欄位**，不可刪除或重命名現有欄位。
- 路由重構前，必須確認所有 hooks 中的 API endpoint 路徑仍然有效。

### Rule 4 — UI 風格規範
- **主題**: 深色金融終端機 (Dark Financial Terminal)
- **主色調**: 金融藍 (`#2563EB`)、冷光青色 (`#06B6D4`)
- **背景**: 深黑 (`#0A0F1E`) / 深藍灰 (`#111827`)
- **字體**: 數字使用等寬字體 (monospace)，標題字體**醒目清晰**
- **漲跌色**: 上漲 `#22C55E` (綠)、下跌 `#EF4444` (紅)
- **禁止**: 白色背景、圓潤卡通風格元件

### Rule 5 — AI 引擎規範
- Gemini AI 功能目前已在 `backend/main.py` 以 Mock 方式停用。
- 恢復方式：移除 `mocked_generate_content` 的 monkey-patch 段落。
- AI 分析結果**不可**作為交易決策的唯一依據，必須附加免責聲明。

### Rule 6 — 資料層規範
- **DuckDB** (`data/market.duckdb`)：盤中即時更新，使用 OLAP 聚合查詢。
- **SQLite 離線庫** (`databases/`)：定期批次更新，不做即時寫入。
- 所有資料庫操作必須使用 **async context manager**，避免連線洩漏。

---

## 8. 啟動指令 (Dev Commands)

```bash
# 後端 (於專案根目錄執行)
uvicorn backend.main:app --reload --port 8000

# 前端 (於 frontend/ 目錄執行)
npm run dev   # → http://localhost:3000
```

---

## 9. AI 輔助開發協作規範

當 AI (Cursor) 協助開發時，必須遵守以下優先順序：

1. **先讀此文件** → 確認架構與規範再動手
2. **不主動重構** → 除非用戶明確要求，否則不調整目錄結構
3. **最小影響原則** → 只修改必要的檔案，不引入未使用的依賴
4. **型別安全** → 所有新增 TypeScript 程式碼必須有完整型別定義
5. **不破壞 Store** → 任何修改前先確認 `useAppStore.ts` 結構不受影響
