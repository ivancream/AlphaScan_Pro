import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AlertTriangle } from 'lucide-react';

import { MainLayout } from './components/layout/MainLayout';
import { useBackendSidecar } from './hooks/useBackendSidecar';

const TaiexDynamicsPage = lazy(() => import('./app/taiex-dynamics/page'));
const IntradayMonitorPage = lazy(() => import('./app/intraday-monitor/page'));
const AllAroundFeedPage = lazy(() => import('./app/all-around/page'));
const CapitalFlowPage = lazy(() => import('./app/capital-flow/page'));
const LongSelectionPage = lazy(() => import('./app/long-selection/page'));
const ShortSelectionPage = lazy(() => import('./app/short-selection/page'));
const WatchlistPage = lazy(() => import('./app/watchlist/page'));
const DoubleSwordPage = lazy(() => import('./app/double-sword/page'));
const DividendsPage = lazy(() => import('./app/dividends/page'));
const CbBondPage = lazy(() => import('./app/cb-bond/page'));
const TechnicalPage = lazy(() => import('./app/technical/page'));
const GlobalMarketPage = lazy(() => import('./app/global-market/page'));
const FundamentalPage = lazy(() => import('./app/fundamental/page'));
const ChipsPage = lazy(() => import('./app/chips/page'));
const DispositionPage = lazy(() => import('./app/disposition/page'));
const FloorBouncePage = lazy(() => import('./app/floor-bounce/page'));
const WarrantSelectionPage = lazy(() => import('./app/warrant-selection/page'));
const StockHubPage = lazy(() => import('./app/stock/page'));
const StockDetailPage = lazy(() => import('./app/stock/[symbol]/page'));

const queryClient = new QueryClient();

function PageLoader() {
  return (
    <div className="flex h-full items-center justify-center text-sm text-gray-500">
      載入中...
    </div>
  );
}

function ModuleUnavailablePage({
  title,
  reason,
}: {
  title: string;
  reason: string;
}) {
  return (
    <div className="flex min-h-full items-center justify-center bg-[#0E1117] p-6 text-gray-200">
      <section className="w-full max-w-2xl rounded-xl border border-amber-500/30 bg-[#161B22] p-6 shadow-xl">
        <div className="mb-4 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-amber-500/30 bg-amber-500/10 text-amber-300">
            <AlertTriangle size={20} />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-amber-300/80">
              Module Disabled
            </p>
            <h2 className="mt-1 text-2xl font-bold tracking-wider text-white">{title}</h2>
          </div>
        </div>
        <p className="text-sm leading-7 text-gray-400">{reason}</p>
        <div className="mt-5 text-xs text-gray-500">
          這個入口先保留，避免舊連結變成空白頁；等資料表與後端 controller 補齊後再重新啟用。
        </div>
      </section>
    </div>
  );
}

function AppRoutes() {
  useBackendSidecar();

  return (
    <MainLayout>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/" element={<Navigate to="/taiex-dynamics" replace />} />

          <Route path="/taiex-dynamics" element={<TaiexDynamicsPage />} />
          <Route path="/intraday-monitor" element={<IntradayMonitorPage />} />
          <Route path="/all-around" element={<AllAroundFeedPage />} />
          <Route path="/capital-flow" element={<CapitalFlowPage />} />
          <Route path="/long-selection" element={<LongSelectionPage />} />
          <Route path="/short-selection" element={<ShortSelectionPage />} />
          <Route path="/watchlist" element={<WatchlistPage />} />
          <Route path="/double-sword" element={<DoubleSwordPage />} />
          <Route path="/dividends" element={<DividendsPage />} />
          <Route path="/cb-bond" element={<CbBondPage />} />
          <Route path="/warrant-selection" element={<WarrantSelectionPage />} />

          <Route path="/technical" element={<TechnicalPage />} />
          <Route path="/global-market" element={<GlobalMarketPage />} />
          <Route path="/fundamental" element={<FundamentalPage />} />
          <Route path="/chips" element={<ChipsPage />} />
          <Route path="/disposition" element={<DispositionPage />} />
          <Route path="/floor-bounce" element={<FloorBouncePage />} />

          <Route path="/stock" element={<StockHubPage />} />
          <Route path="/stock/:symbol" element={<StockDetailPage />} />

          <Route
            path="/etf-tracker"
            element={
              <ModuleUnavailablePage
                title="ETF 持股追蹤"
                reason="前端原本期待 /api/v1/etfs/*，但目前後端沒有 ETF router、DuckDB schema 也沒有 ETF 持股表。先停用這個模組，避免進入後所有查詢都失敗。"
              />
            }
          />

          <Route path="/heatmap" element={<Navigate to="/capital-flow" replace />} />
          <Route path="/swing-long" element={<Navigate to="/long-selection" replace />} />
          <Route path="/swing-short" element={<Navigate to="/short-selection" replace />} />
          <Route path="/correlation" element={<Navigate to="/double-sword" replace />} />
          <Route path="/dividend" element={<Navigate to="/dividends" replace />} />
          <Route path="/cb-tracker" element={<Navigate to="/cb-bond" replace />} />

          <Route path="*" element={<Navigate to="/taiex-dynamics" replace />} />
        </Routes>
      </Suspense>
    </MainLayout>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
