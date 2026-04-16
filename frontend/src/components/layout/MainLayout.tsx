import React, { useEffect, useMemo, useState } from 'react';
import {
    Menu,
    X,
    Search,
    TrendingUp,
    TrendingDown,
    Activity,
    BarChart3,
    Star,
    GitMerge,
    Landmark,
    CandlestickChart,
    LineChart,
} from 'lucide-react';
import clsx from 'clsx';
import { useAppStore } from '@/store/useAppStore';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { IntradayRefreshBar } from '@/components/ui/IntradayRefreshBar';
import { GlobalContextMenu } from '@/components/ui/GlobalContextMenu';
import { cleanStockSymbol, toStockDetailPath } from '@/lib/stocks';
import { API_V1_BASE } from '@/lib/apiBase';

type NavItem = { href: string; icon: React.ReactNode; label: string };
type NavGroup = { title: string; subtitle: string; separated?: boolean; showStockNav?: boolean; items: NavItem[] };

const NAV_GROUPS: NavGroup[] = [
    {
        title: '市場動態',
        subtitle: '高頻',
        items: [
            { href: '/taiex-dynamics', icon: <Activity size={18} />, label: '大盤氣氛' },
            { href: '/capital-flow', icon: <BarChart3 size={18} />, label: '資金流向' },
        ],
    },
    {
        title: '選股監控',
        subtitle: '高頻',
        separated: true,
        showStockNav: true,
        items: [
            { href: '/watchlist', icon: <Star size={18} />, label: '自選清單' },
            { href: '/long-selection', icon: <TrendingUp size={18} />, label: '多方選股' },
            { href: '/short-selection', icon: <TrendingDown size={18} />, label: '空方選股' },
        ],
    },
    {
        title: '進階數據',
        subtitle: '每日更新',
        separated: true,
        items: [
            { href: '/double-sword', icon: <GitMerge size={18} />, label: '雙刀戰法' },
            { href: '/dividends', icon: <Landmark size={18} />, label: '除權息' },
            { href: '/cb-bond', icon: <CandlestickChart size={18} />, label: '可轉債' },
        ],
    },
];

const NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

function isDirectSymbolQuery(input: string): boolean {
    return /^[A-Z0-9]{2,10}$/.test(cleanStockSymbol(input));
}

function getPageTitle(pathname: string): string {
    const matched = NAV_ITEMS.find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`));
    if (matched) return matched.label;
    if (pathname === '/stock' || pathname.startsWith('/stock/')) return '個股情報中心';
    return 'QuantQual Insight';
}

export const MainLayout = ({ children }: { children: React.ReactNode }) => {
    const [isSidebarOpen, setSidebarOpen] = useState(true);
    const [searchValue, setSearchValue] = useState('');
    const selectedSymbol = useAppStore((state) => state.selectedSymbol);
    const { pathname } = useLocation();
    const navigate = useNavigate();
    const pageTitle = useMemo(() => getPageTitle(pathname), [pathname]);

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
            const response = await fetch(
                `${API_V1_BASE}/market-data/resolve/${encodeURIComponent(query)}`,
            );
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                const msg =
                    typeof (data as { detail?: string }).detail === 'string'
                        ? (data as { detail: string }).detail
                        : '無法解析股票，請確認代號或名稱。';
                window.alert(msg);
                return;
            }
            const resolvedSymbol = cleanStockSymbol((data as { symbol?: string }).symbol ?? normalizedQuery);
            useAppStore.getState().setSymbol(resolvedSymbol);
            setSearchValue(resolvedSymbol);
            navigate(toStockDetailPath(resolvedSymbol));
        } catch (error) {
            console.error('Symbol resolution failed:', error);
            window.alert('無法連線至後端，請確認 API 已啟動 (localhost:8000)。');
        }
    };

    return (
        <div className="flex h-screen bg-[#0E1117] text-gray-200 overflow-hidden font-sans">
            <aside
                className={clsx(
                    "bg-[#161B22] border-r border-gray-800 transition-all duration-300 ease-in-out flex flex-col",
                    isSidebarOpen ? "w-64 relative" : "w-16 absolute lg:relative z-20 h-full"
                )}
            >
                <div className="flex items-center justify-between p-4 border-b border-gray-800 h-16 shrink-0">
                    {isSidebarOpen && <span className="font-bold text-xl text-white tracking-widest flex items-center">AlphaScan</span>}
                    <button
                        onClick={() => setSidebarOpen(!isSidebarOpen)}
                        className="p-1 hover:bg-gray-800 rounded text-gray-400 hover:text-white transition-colors ml-auto"
                    >
                        {isSidebarOpen ? <X size={20} /> : <Menu size={20} />}
                    </button>
                </div>

                <nav className="flex-1 p-2 mt-2 overflow-y-auto overflow-x-hidden custom-scrollbar">
                    {NAV_GROUPS.map((group) => (
                        <div key={group.title} className={clsx('space-y-1', group.separated && 'mt-5 pt-4 border-t border-gray-800')}>
                            {isSidebarOpen ? (
                                <div className="px-2 pt-1 pb-2">
                                    <div className="flex items-center justify-between gap-2">
                                        <span className="text-[11px] font-semibold tracking-[0.24em] text-gray-500 uppercase">
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
                                <NavItem
                                    key={item.href}
                                    href={item.href}
                                    icon={item.icon}
                                    label={item.label}
                                    isOpen={isSidebarOpen}
                                    active={pathname === item.href || pathname.startsWith(`${item.href}/`)}
                                />
                            ))}
                            {group.showStockNav && (
                                <StockNavItem isOpen={isSidebarOpen} pathname={pathname} />
                            )}
                        </div>
                    ))}
                </nav>
            </aside>

            <main className="flex-1 flex flex-col h-full w-full overflow-hidden">
                <header className="h-16 border-b border-gray-800 flex items-center px-6 bg-[#0E1117] justify-between shrink-0">
                    <div className="flex items-center gap-6">
                        <div>
                            <p className="text-[11px] uppercase tracking-[0.35em] text-gray-500">Trading Terminal</p>
                            <h1 className="text-lg font-bold text-white tracking-widest">{pageTitle}</h1>
                        </div>
                        <div className="relative group">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 group-focus-within:text-[#EAB308]" size={16} />
                            <input
                                type="text"
                                placeholder="輸入股票代號，Enter 開啟個股頁"
                                value={searchValue}
                                onChange={(e) => setSearchValue(e.target.value)}
                                className="bg-[#161B22] border border-gray-700 text-white pl-10 pr-4 py-2 rounded-lg text-sm focus:outline-none focus:border-[#EAB308] focus:ring-1 focus:ring-[#EAB308] w-[320px] transition-all"
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                        void handleSubmit();
                                    }
                                }}
                            />
                        </div>
                    </div>
                    <div className="flex items-center gap-4">
                        <IntradayRefreshBar />
                    </div>
                </header>
                <div className="flex-1 overflow-auto relative bg-[#0E1117] custom-scrollbar">
                    {children}
                </div>
            </main>
            <GlobalContextMenu />
        </div>
    );
};

/** 側邊欄「個股情報」：有選標的時直達 /stock/[symbol]，否則為說明頁 /stock */
const StockNavItem = ({ isOpen, pathname }: { isOpen: boolean; pathname: string }) => {
    const selectedSymbol = useAppStore((state) => state.selectedSymbol);
    const sym = cleanStockSymbol(selectedSymbol);
    const href = sym ? toStockDetailPath(sym) : '/stock';
    const active = pathname === '/stock' || pathname.startsWith('/stock/');
    return (
        <Link
            to={href}
            className={clsx(
                'flex items-center w-full p-2.5 rounded-lg transition-colors overflow-hidden whitespace-nowrap',
                active
                    ? 'bg-[#1E293B] text-cyan-400 border-l-2 border-cyan-400'
                    : 'hover:bg-gray-800 text-gray-400 hover:text-white',
            )}
        >
            <span className="shrink-0">
                <LineChart size={18} />
            </span>
            {isOpen && <span className="ml-3 text-sm font-medium">個股情報</span>}
        </Link>
    );
};

const NavItem = ({ href, icon, label, isOpen, active = false }: { href: string, icon: React.ReactNode, label: string, isOpen: boolean, active?: boolean }) => (
    <Link to={href} className={clsx(
        "flex items-center w-full p-2.5 rounded-lg transition-colors overflow-hidden whitespace-nowrap",
        active ? "bg-[#1E293B] text-[#EAB308] border-l-2 border-[#EAB308]" : "hover:bg-gray-800 text-gray-400 hover:text-white"
    )}>
        <span className="shrink-0">{icon}</span>
        {isOpen && <span className="ml-3 text-sm font-medium">{label}</span>}
    </Link>
);
