import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  BarChart3,
  CandlestickChart,
  GitMerge,
  Landmark,
  LineChart,
  Menu,
  Radar,
  Search,
  Star,
  Target,
  TrendingDown,
  TrendingUp,
  X,
} from 'lucide-react';
import clsx from 'clsx';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { GlobalContextMenu } from '@/components/ui/GlobalContextMenu';
import { IntradayRefreshBar } from '@/components/ui/IntradayRefreshBar';
import { API_V1_BASE } from '@/lib/apiBase';
import { cleanStockSymbol, toStockDetailPath } from '@/lib/stocks';
import { useAppStore } from '@/store/useAppStore';

type NavItem = {
  href: string;
  icon: React.ReactNode;
  label: string;
  description?: string;
};

type NavGroup = {
  title: string;
  subtitle: string;
  separated?: boolean;
  showStockNav?: boolean;
  items: NavItem[];
};

const NAV_GROUPS: NavGroup[] = [
  {
    title: '盤中戰情',
    subtitle: 'Live',
    items: [
      { href: '/taiex-dynamics', icon: <Activity size={18} />, label: '大盤動態' },
      { href: '/intraday-monitor', icon: <Radar size={18} />, label: '盤中監控' },
      { href: '/all-around', icon: <LineChart size={18} />, label: '全市場 Tape' },
      { href: '/capital-flow', icon: <BarChart3 size={18} />, label: '資金熱區' },
    ],
  },
  {
    title: '交易選股',
    subtitle: 'Scan',
    separated: true,
    showStockNav: true,
    items: [
      { href: '/watchlist', icon: <Star size={18} />, label: '自選股' },
      { href: '/long-selection', icon: <TrendingUp size={18} />, label: '偏多選股' },
      { href: '/short-selection', icon: <TrendingDown size={18} />, label: '偏空選股' },
      { href: '/double-sword', icon: <GitMerge size={18} />, label: '雙劍合璧' },
    ],
  },
  {
    title: '研究工具',
    subtitle: 'Tools',
    separated: true,
    items: [
      { href: '/warrant-selection', icon: <Target size={18} />, label: '權證篩選' },
      { href: '/dividends', icon: <Landmark size={18} />, label: '股利除息' },
      { href: '/cb-bond', icon: <CandlestickChart size={18} />, label: '可轉債 CB' },
    ],
  },
];

const PAGE_TITLES: Record<string, string> = {
  '/technical': '技術分析',
  '/global-market': '全球市場',
  '/fundamental': '基本面分析',
  '/chips': '籌碼分析',
  '/disposition': '處置股分析',
  '/floor-bounce': '跌深反彈',
  '/etf-tracker': 'ETF 持股追蹤',
};

const NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

function isDirectSymbolQuery(input: string): boolean {
  return /^[A-Z0-9]{2,10}$/.test(cleanStockSymbol(input));
}

function getPageTitle(pathname: string): string {
  const matched = NAV_ITEMS.find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`));
  if (matched) return matched.label;
  if (pathname === '/stock' || pathname.startsWith('/stock/')) return '個股中心';
  for (const [path, title] of Object.entries(PAGE_TITLES)) {
    if (pathname === path || pathname.startsWith(`${path}/`)) return title;
  }
  return 'AlphaScan Pro';
}

export function MainLayout({ children }: { children: React.ReactNode }) {
  const [isSidebarOpen, setSidebarOpen] = useState(true);
  const [searchValue, setSearchValue] = useState('');
  const selectedSymbol = useAppStore((state) => state.selectedSymbol);
  const backendStatus = useAppStore((state) => state.backendStatus);
  const backendError = useAppStore((state) => state.backendError);
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const pageTitle = useMemo(() => getPageTitle(pathname), [pathname]);

  const isLoading = backendStatus === 'idle' || backendStatus === 'starting';
  const isError = backendStatus === 'error';

  useEffect(() => {
    setSearchValue(cleanStockSymbol(selectedSymbol));
  }, [selectedSymbol]);

  const handleSubmit = async () => {
    const query = searchValue.trim();
    if (!query) return;
    const normalizedQuery = cleanStockSymbol(query);

    if (normalizedQuery && isDirectSymbolQuery(query)) {
      useAppStore.getState().setSymbol(normalizedQuery);
      setSearchValue(normalizedQuery);
      navigate(toStockDetailPath(normalizedQuery));
      return;
    }

    try {
      const response = await fetch(`${API_V1_BASE}/market-data/resolve/${encodeURIComponent(query)}`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const message =
          typeof (data as { detail?: string }).detail === 'string'
            ? (data as { detail: string }).detail
            : '找不到符合的股票代號或名稱';
        window.alert(message);
        return;
      }
      const resolvedSymbol = cleanStockSymbol((data as { symbol?: string }).symbol ?? normalizedQuery);
      useAppStore.getState().setSymbol(resolvedSymbol);
      setSearchValue(resolvedSymbol);
      navigate(toStockDetailPath(resolvedSymbol));
    } catch (error) {
      console.error('Symbol resolution failed:', error);
      window.alert('查詢失敗，請確認後端 API 已啟動。');
    }
  };

  return (
    <div className="flex h-screen overflow-hidden bg-[#0E1117] font-sans text-gray-200">
      {isLoading && <BackendLoadingOverlay />}
      {isError && <BackendErrorOverlay error={backendError} />}

      <aside
        className={clsx(
          'flex flex-col border-r border-gray-800 bg-[#161B22] transition-all duration-300 ease-in-out',
          isSidebarOpen ? 'relative w-64' : 'absolute z-20 h-full w-16 lg:relative',
        )}
      >
        <div className="flex h-16 shrink-0 items-center justify-between border-b border-gray-800 p-4">
          {isSidebarOpen && (
            <span className="flex items-center text-xl font-bold tracking-widest text-white">
              Alpha<span className="text-[#EAB308]">Scan</span>
            </span>
          )}
          <button
            type="button"
            onClick={() => setSidebarOpen((open) => !open)}
            className="ml-auto rounded p-1 text-gray-400 transition-colors hover:bg-gray-800 hover:text-white"
            aria-label={isSidebarOpen ? '收合選單' : '展開選單'}
          >
            {isSidebarOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>

        <nav className="custom-scrollbar mt-2 flex-1 overflow-y-auto overflow-x-hidden p-2">
          {NAV_GROUPS.map((group) => (
            <div key={group.title} className={clsx('space-y-1', group.separated && 'mt-5 border-t border-gray-800 pt-4')}>
              {isSidebarOpen ? (
                <div className="px-2 pb-2 pt-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-semibold uppercase tracking-[0.24em] text-gray-500">
                      {group.title}
                    </span>
                    <span className="rounded-full border border-gray-700 bg-[#0E1117] px-2 py-0.5 text-[10px] font-medium text-gray-400">
                      {group.subtitle}
                    </span>
                  </div>
                </div>
              ) : group.separated ? (
                <div className="mx-2 my-2 border-t border-gray-800" />
              ) : null}

              {group.items.map((item) => (
                <NavItemRow
                  key={item.href}
                  href={item.href}
                  icon={item.icon}
                  label={item.label}
                  isOpen={isSidebarOpen}
                  active={pathname === item.href || pathname.startsWith(`${item.href}/`)}
                />
              ))}
              {group.showStockNav && <StockNavItem isOpen={isSidebarOpen} pathname={pathname} />}
            </div>
          ))}
        </nav>
      </aside>

      <main className="flex h-full w-full flex-1 flex-col overflow-hidden">
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-gray-800 bg-[#0E1117] px-6">
          <div className="flex items-center gap-6">
            <div>
              <p className="text-[11px] uppercase tracking-[0.35em] text-gray-500">Trading Terminal</p>
              <h1 className="text-lg font-bold tracking-widest text-white">{pageTitle}</h1>
            </div>
            <div className="group relative">
              <Search
                className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 group-focus-within:text-[#EAB308]"
                size={16}
              />
              <input
                type="text"
                placeholder="輸入股票代號或名稱，Enter 查詢"
                value={searchValue}
                onChange={(e) => setSearchValue(e.target.value)}
                className="w-[320px] rounded-lg border border-gray-700 bg-[#161B22] py-2 pl-10 pr-4 text-sm text-white transition-all focus:border-[#EAB308] focus:outline-none focus:ring-1 focus:ring-[#EAB308]"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void handleSubmit();
                }}
              />
            </div>
          </div>
          <div className="flex items-center gap-4">
            <IntradayRefreshBar />
          </div>
        </header>

        <div className="custom-scrollbar relative flex-1 overflow-auto bg-[#0E1117]">{children}</div>
      </main>

      <GlobalContextMenu />
    </div>
  );
}

function BackendLoadingOverlay() {
  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-[#0E1117]">
      <div className="flex flex-col items-center gap-6">
        <div className="text-3xl font-bold tracking-widest text-white">
          Alpha<span className="text-[#EAB308]">Scan</span>
          <span className="ml-2 text-sm font-normal text-gray-500">Pro</span>
        </div>
        <div className="relative h-12 w-12">
          <div className="absolute inset-0 rounded-full border-2 border-gray-800" />
          <div className="absolute inset-0 animate-spin rounded-full border-2 border-t-[#EAB308]" />
        </div>
        <div className="text-center">
          <p className="text-sm text-gray-400">後端啟動中...</p>
          <p className="mt-1 text-xs text-gray-600">第一次啟動可能需要一點時間</p>
        </div>
      </div>
    </div>
  );
}

function BackendErrorOverlay({ error }: { error: string | null }) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-[#0E1117]">
      <div className="flex max-w-md flex-col items-center gap-4 px-6 text-center">
        <div className="text-3xl font-bold tracking-widest text-white">
          Alpha<span className="text-[#EAB308]">Scan</span>
        </div>
        <div className="flex h-12 w-12 items-center justify-center rounded-full border border-red-800 bg-red-900/30">
          <span className="text-xl text-red-400">!</span>
        </div>
        <div>
          <p className="font-medium text-red-400">後端啟動失敗</p>
          <p className="mt-2 break-all font-mono text-xs text-gray-500">{error}</p>
        </div>
        <p className="text-xs text-gray-600">
          請確認 FastAPI 後端或 Tauri sidecar 已正確啟動，並且 8000 port 沒有被其他程序占用。
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-2 rounded-lg bg-[#EAB308] px-4 py-2 text-sm font-medium text-black transition-colors hover:bg-yellow-400"
        >
          重新整理
        </button>
      </div>
    </div>
  );
}

function StockNavItem({ isOpen, pathname }: { isOpen: boolean; pathname: string }) {
  const selectedSymbol = useAppStore((state) => state.selectedSymbol);
  const symbol = cleanStockSymbol(selectedSymbol);
  const href = symbol ? toStockDetailPath(symbol) : '/stock';
  const active = pathname === '/stock' || pathname.startsWith('/stock/');

  return (
    <Link
      to={href}
      className={clsx(
        'flex w-full items-center overflow-hidden whitespace-nowrap rounded-lg p-2.5 transition-colors',
        active
          ? 'border-l-2 border-cyan-400 bg-[#1E293B] text-cyan-400'
          : 'text-gray-400 hover:bg-gray-800 hover:text-white',
      )}
    >
      <span className="shrink-0">
        <LineChart size={18} />
      </span>
      {isOpen && <span className="ml-3 text-sm font-medium">個股中心</span>}
    </Link>
  );
}

function NavItemRow({
  href,
  icon,
  label,
  isOpen,
  active = false,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
  isOpen: boolean;
  active?: boolean;
}) {
  return (
    <Link
      to={href}
      className={clsx(
        'flex w-full items-center overflow-hidden whitespace-nowrap rounded-lg p-2.5 transition-colors',
        active
          ? 'border-l-2 border-[#EAB308] bg-[#1E293B] text-[#EAB308]'
          : 'text-gray-400 hover:bg-gray-800 hover:text-white',
      )}
    >
      <span className="shrink-0">{icon}</span>
      {isOpen && <span className="ml-3 text-sm font-medium">{label}</span>}
    </Link>
  );
}
