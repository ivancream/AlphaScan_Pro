import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  BarChart3,
  Bell,
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
    title: '即時盤勢',
    subtitle: 'Live',
    items: [
      { href: '/taiex-dynamics', icon: <Activity size={18} />, label: '大盤動態' },
      { href: '/intraday-monitor', icon: <Radar size={18} />, label: '盤中監控' },
      { href: '/all-around', icon: <LineChart size={18} />, label: '全市場 Tape' },
      { href: '/capital-flow', icon: <BarChart3 size={18} />, label: '資金流向' },
    ],
  },
  {
    title: '選股清單',
    subtitle: 'Scan',
    separated: true,
    showStockNav: true,
    items: [
      { href: '/watchlist', icon: <Star size={18} />, label: '自選股' },
      { href: '/long-selection', icon: <TrendingUp size={18} />, label: '多方選股' },
      { href: '/short-selection', icon: <TrendingDown size={18} />, label: '空方選股' },
      { href: '/double-sword', icon: <GitMerge size={18} />, label: '雙劍策略' },
    ],
  },
  {
    title: '研究工具',
    subtitle: 'Tools',
    separated: true,
    items: [
      { href: '/warrant-selection', icon: <Target size={18} />, label: '權證篩選' },
      { href: '/dividends', icon: <Landmark size={18} />, label: '股利分析' },
      { href: '/cb-bond', icon: <CandlestickChart size={18} />, label: '可轉債 CB' },
    ],
  },
];

const PAGE_TITLES: Record<string, string> = {
  '/technical': '技術分析',
  '/global-market': '國際市場',
  '/fundamental': '基本面',
  '/chips': '籌碼分析',
  '/disposition': '處置股',
  '/floor-bounce': '跌深反彈',
  '/etf-tracker': 'ETF 追蹤',
};

const NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

function isDirectSymbolQuery(input: string): boolean {
  return /^[A-Z0-9]{2,10}$/.test(cleanStockSymbol(input));
}

function getPageTitle(pathname: string): string {
  const matched = NAV_ITEMS.find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`));
  if (matched) return matched.label;
  if (pathname === '/stock' || pathname.startsWith('/stock/')) return '個股看盤';
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
            : '查無股票代號，請確認輸入內容。';
        window.alert(message);
        return;
      }
      const resolvedSymbol = cleanStockSymbol((data as { symbol?: string }).symbol ?? normalizedQuery);
      useAppStore.getState().setSymbol(resolvedSymbol);
      setSearchValue(resolvedSymbol);
      navigate(toStockDetailPath(resolvedSymbol));
    } catch (error) {
      console.error('Symbol resolution failed:', error);
      window.alert('無法連線到股票查詢 API，請確認後端服務狀態。');
    }
  };

  return (
    <div className="app-shell flex h-screen overflow-hidden bg-[var(--as-bg)] font-sans text-[var(--as-text)]">
      {isLoading && <BackendLoadingOverlay />}
      {isError && <BackendErrorOverlay error={backendError} />}

      <aside
        className={clsx(
          'flex flex-col border-r border-[var(--as-border)] bg-[var(--as-sidebar)] transition-all duration-300 ease-in-out',
          isSidebarOpen ? 'relative w-64' : 'absolute z-20 h-full w-16 lg:relative',
        )}
      >
        <div className="flex h-16 shrink-0 items-center justify-between border-b border-[var(--as-border)] px-4">
          {isSidebarOpen && (
            <Link to="/" className="flex items-baseline gap-1 text-xl font-black tracking-wide text-white">
              Alpha<span className="text-[var(--as-yellow)]">Scan</span>
              <span className="ml-1 text-[10px] font-bold uppercase tracking-[0.28em] text-[var(--as-muted)]">Pro</span>
            </Link>
          )}
          <button
            type="button"
            onClick={() => setSidebarOpen((open) => !open)}
            className="ml-auto rounded-md p-2 text-slate-400 transition-colors hover:bg-white/[0.06] hover:text-white"
            aria-label={isSidebarOpen ? '收合側邊欄' : '展開側邊欄'}
          >
            {isSidebarOpen ? <X size={19} /> : <Menu size={19} />}
          </button>
        </div>

        <nav className="custom-scrollbar mt-2 flex-1 overflow-y-auto overflow-x-hidden px-2 pb-3">
          {NAV_GROUPS.map((group) => (
            <div key={group.title} className={clsx('space-y-1', group.separated && 'mt-5 border-t border-[var(--as-border)] pt-4')}>
              {isSidebarOpen ? (
                <div className="px-2 pb-2 pt-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--as-muted)]">
                      {group.title}
                    </span>
                    <span className="rounded-full border border-[var(--as-border)] bg-[var(--as-bg)] px-2 py-0.5 text-[10px] font-medium text-slate-400">
                      {group.subtitle}
                    </span>
                  </div>
                </div>
              ) : group.separated ? (
                <div className="mx-2 my-2 border-t border-[var(--as-border)]" />
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

      <main className="flex h-full min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-[var(--as-border)] bg-[rgba(18,20,27,0.92)] px-5 backdrop-blur">
          <div className="flex min-w-0 items-center gap-5">
            <div className="min-w-[150px]">
              <p className="text-[10px] font-bold uppercase tracking-[0.32em] text-[var(--as-muted)]">Dashboard</p>
              <h1 className="truncate text-lg font-black tracking-wide text-white">{pageTitle}</h1>
            </div>
            <div className="group relative hidden sm:block">
              <Search
                className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-[var(--as-yellow)]"
                size={16}
              />
              <input
                type="text"
                placeholder="輸入股票代號或名稱"
                value={searchValue}
                onChange={(e) => setSearchValue(e.target.value)}
                className="h-10 w-[320px] rounded-md border border-[var(--as-border)] bg-[var(--as-card)] py-2 pl-10 pr-4 text-sm font-semibold text-white outline-none transition-all placeholder:text-slate-600 focus:border-[var(--as-yellow)] focus:ring-1 focus:ring-[var(--as-yellow)]"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void handleSubmit();
                }}
              />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="hidden h-10 w-10 items-center justify-center rounded-md border border-[var(--as-border)] bg-[var(--as-card)] text-slate-400 transition-colors hover:border-[var(--as-yellow)] hover:text-white md:flex"
              aria-label="通知"
            >
              <Bell size={16} />
            </button>
            <IntradayRefreshBar />
          </div>
        </header>

        <div className="custom-scrollbar relative min-h-0 flex-1 overflow-auto bg-[var(--as-bg)]">{children}</div>
      </main>

      <GlobalContextMenu />
    </div>
  );
}

function BackendLoadingOverlay() {
  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-[var(--as-bg)]">
      <div className="flex flex-col items-center gap-6">
        <div className="text-3xl font-black tracking-wide text-white">
          Alpha<span className="text-[var(--as-yellow)]">Scan</span>
          <span className="ml-2 text-sm font-semibold text-[var(--as-muted)]">Pro</span>
        </div>
        <div className="relative h-12 w-12">
          <div className="absolute inset-0 rounded-full border-2 border-[var(--as-border)]" />
          <div className="absolute inset-0 animate-spin rounded-full border-2 border-t-[var(--as-yellow)]" />
        </div>
        <div className="text-center">
          <p className="text-sm text-slate-400">正在啟動後端服務...</p>
          <p className="mt-1 text-xs text-slate-600">載入市場資料與即時連線</p>
        </div>
      </div>
    </div>
  );
}

function BackendErrorOverlay({ error }: { error: string | null }) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-[var(--as-bg)]">
      <div className="flex max-w-md flex-col items-center gap-4 px-6 text-center">
        <div className="text-3xl font-black tracking-wide text-white">
          Alpha<span className="text-[var(--as-yellow)]">Scan</span>
        </div>
        <div className="flex h-12 w-12 items-center justify-center rounded-full border border-red-500/30 bg-red-500/10">
          <span className="text-xl text-red-300">!</span>
        </div>
        <div>
          <p className="font-semibold text-red-300">後端服務啟動失敗</p>
          <p className="mt-2 break-all font-mono text-xs text-slate-500">{error}</p>
        </div>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-2 rounded-md bg-[var(--as-yellow)] px-4 py-2 text-sm font-black text-black transition-colors hover:bg-yellow-300"
        >
          重新載入
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
        'group flex w-full items-center overflow-hidden whitespace-nowrap rounded-md px-3 py-2.5 transition-colors',
        active
          ? 'bg-[rgba(234,179,8,0.12)] text-[var(--as-yellow)] shadow-[inset_3px_0_0_var(--as-yellow)]'
          : 'text-slate-400 hover:bg-white/[0.055] hover:text-white',
      )}
    >
      <span className="shrink-0">
        <LineChart size={18} />
      </span>
      {isOpen && <span className="ml-3 text-sm font-semibold">個股看盤</span>}
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
        'group flex w-full items-center overflow-hidden whitespace-nowrap rounded-md px-3 py-2.5 transition-colors',
        active
          ? 'bg-[rgba(234,179,8,0.12)] text-[var(--as-yellow)] shadow-[inset_3px_0_0_var(--as-yellow)]'
          : 'text-slate-400 hover:bg-white/[0.055] hover:text-white',
      )}
      title={isOpen ? undefined : label}
    >
      <span className="shrink-0">{icon}</span>
      {isOpen && <span className="ml-3 text-sm font-semibold">{label}</span>}
    </Link>
  );
}
