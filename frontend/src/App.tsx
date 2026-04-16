import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MainLayout } from './components/layout/MainLayout';
import { useBackendSidecar } from './hooks/useBackendSidecar';

// Lazy-load pages
const TaiexDynamicsPage   = lazy(() => import('./app/taiex-dynamics/page'));
const AllAroundFeedPage   = lazy(() => import('./app/all-around/page'));
const CapitalFlowPage     = lazy(() => import('./app/capital-flow/page'));
const LongSelectionPage   = lazy(() => import('./app/long-selection/page'));
const ShortSelectionPage  = lazy(() => import('./app/short-selection/page'));
const WatchlistPage       = lazy(() => import('./app/watchlist/page'));
const DoubleSwordPage     = lazy(() => import('./app/double-sword/page'));
const DividendsPage       = lazy(() => import('./app/dividends/page'));
const CbBondPage          = lazy(() => import('./app/cb-bond/page'));
const TechnicalPage       = lazy(() => import('./app/technical/page'));
const GlobalMarketPage    = lazy(() => import('./app/global-market/page'));
const FundamentalPage     = lazy(() => import('./app/fundamental/page'));
const ChipsPage           = lazy(() => import('./app/chips/page'));
const DispositionPage     = lazy(() => import('./app/disposition/page'));
const FloorBouncePage     = lazy(() => import('./app/floor-bounce/page'));
const EtfTrackerPage      = lazy(() => import('./app/etf-tracker/page'));
const StockHubPage        = lazy(() => import('./app/stock/page'));
const StockDetailPage     = lazy(() => import('./app/stock/[symbol]/page'));

const queryClient = new QueryClient();

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-full text-gray-500 text-sm">
      載入中...
    </div>
  );
}

function AppRoutes() {
  // 在 Tauri 環境中自動啟動 FastAPI sidecar
  useBackendSidecar();

  return (
    <MainLayout>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          {/* 預設首頁重導向 */}
          <Route path="/" element={<Navigate to="/taiex-dynamics" replace />} />

          {/* 主要頁面 */}
          <Route path="/taiex-dynamics"  element={<TaiexDynamicsPage />} />
          <Route path="/all-around"      element={<AllAroundFeedPage />} />
          <Route path="/capital-flow"    element={<CapitalFlowPage />} />
          <Route path="/long-selection"  element={<LongSelectionPage />} />
          <Route path="/short-selection" element={<ShortSelectionPage />} />
          <Route path="/watchlist"       element={<WatchlistPage />} />
          <Route path="/double-sword"    element={<DoubleSwordPage />} />
          <Route path="/dividends"       element={<DividendsPage />} />
          <Route path="/cb-bond"         element={<CbBondPage />} />
          <Route path="/technical"       element={<TechnicalPage />} />
          <Route path="/global-market"   element={<GlobalMarketPage />} />
          <Route path="/fundamental"     element={<FundamentalPage />} />
          <Route path="/chips"           element={<ChipsPage />} />
          <Route path="/disposition"     element={<DispositionPage />} />
          <Route path="/floor-bounce"    element={<FloorBouncePage />} />
          <Route path="/etf-tracker"     element={<EtfTrackerPage />} />

          {/* 個股 */}
          <Route path="/stock"           element={<StockHubPage />} />
          <Route path="/stock/:symbol"   element={<StockDetailPage />} />

          {/* 舊路徑永久重導向（取代 next.config.ts redirects） */}
          <Route path="/heatmap"         element={<Navigate to="/capital-flow"    replace />} />
          <Route path="/swing-long"      element={<Navigate to="/long-selection"  replace />} />
          <Route path="/swing-short"     element={<Navigate to="/short-selection" replace />} />
          <Route path="/correlation"     element={<Navigate to="/double-sword"    replace />} />
          <Route path="/dividend"        element={<Navigate to="/dividends"       replace />} />
          <Route path="/cb-tracker"      element={<Navigate to="/cb-bond"         replace />} />

          {/* 404 fallback */}
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
