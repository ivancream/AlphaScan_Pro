# AlphaScan Pro — 桌面版（Tauri + Vite + FastAPI）

台股量化質化分析平台，以 Tauri 打包為原生桌面 App。

---

## 開發環境快速啟動

### 0. 一鍵啟動（建議）

```powershell
start-dev.bat
```

> 根目錄 `start-dev.bat` 為捷徑，實際腳本位於 `scripts/dev/start-dev.bat`。

### 1. 啟動後端 FastAPI

```powershell
# 在專案根目錄
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000
```

### 2. 啟動前端（瀏覽器測試，最常用）

```powershell
cd frontend
npm run dev
# 開啟 http://localhost:1420
```

### 3. 啟動桌面 App（Tauri 視窗）

> 需要先安裝 Visual Studio C++ Build Tools 並確保 Rust 可用。

```powershell
cd frontend
npm run tauri dev
```

---

## 環境設定

```powershell
# 複製環境變數範本
copy .env.example .env
# 填入永豐金 API Key / Secret
```

---

## 打包正式 App

### 步驟 1：打包 FastAPI sidecar（執行一次）

```powershell
# 在專案根目錄
pip install pyinstaller
pyinstaller backend.spec

# 查詢目標 triple（e.g. aarch64-pc-windows-msvc）
rustc -vV

# 將產出的執行檔複製至 Tauri binaries 目錄
# Windows 範例：
copy dist\alphascan-backend.exe frontend\src-tauri\binaries\alphascan-backend-aarch64-pc-windows-msvc.exe
```

### 步驟 2：建置 Tauri App

```powershell
cd frontend
npm run tauri build
# 安裝包產出於 frontend/src-tauri/target/release/bundle/
```

---

## 技術架構

| 層級 | 技術 |
|---|---|
| 桌面殼層 | Tauri v2 (Rust) |
| 前端 | Vite + React 19 + TypeScript + Tailwind v4 |
| 路由 | React Router v7 |
| 狀態管理 | Zustand + TanStack Query |
| 後端 API | FastAPI + DuckDB |
| 行情來源 | 永豐 Shioaji |

---

## 目錄結構

```
AlphaScan_Pro/
├── backend/              # FastAPI 後端
│   ├── api/v1/           # REST 路由
│   ├── engines/          # 業務引擎
│   └── main.py           # 入口
├── frontend/             # Vite + React 前端
│   ├── src/              # React 原始碼
│   ├── src-tauri/        # Tauri 設定與 Rust 程式
│   │   ├── binaries/     # FastAPI sidecar 執行檔（打包後放這裡）
│   │   └── tauri.conf.json
│   ├── index.html        # Vite 入口
│   └── vite.config.ts
├── config/
│   └── theme.json        # 題材分類設定
├── scripts/
│   └── dev/              # 開發啟動/清理腳本
├── backend.spec          # PyInstaller 打包設定
└── .env                  # 本機環境變數（不 commit）
```
