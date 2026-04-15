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

const NAV_ITEMS = [
    { href: '/taiex-dynamics', icon: <Activity size={18} />, label: '大盤動態' },
    { href: '/capital-flow', icon: <BarChart3 size={18} />, label: '資金流向' },
    { href: '/long-selection', icon: <TrendingUp size={18} />, label: '多方選股' },
    { href: '/short-selection', icon: <TrendingDown size={18} />, label: '空方選股' },
    { href: '/watchlist', icon: <Star size={18} />, label: '自選清單' },
    { href: '/double-sword', icon: <GitMerge size={18} />, label: '雙刀戰法' },
    { href: '/dividends', icon: <Landmark size={18} />, label: '除權息' },
    { href: '/cb-bond', icon: <CandlestickChart size={18} />, label: '可轉債' },
] as const;

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

        try {
            const response = await fetch(
                `http://localhost:8000/api/v1/market-data/resolve/${encodeURIComponent(query)}`,
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
            const resolvedSymbol = cleanStockSymbol((data as { symbol?: string }).symbol ?? query);
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

                <nav className="flex-1 p-2 space-y-1 mt-2 overflow-y-auto overflow-x-hidden custom-scrollbar">
                    {NAV_ITEMS.map((item) => (
                        <NavItem
                            key={item.href}
                            href={item.href}
                            icon={item.icon}
                            label={item.label}
                            isOpen={isSidebarOpen}
                            active={pathname === item.href || pathname.startsWith(`${item.href}/`)}
                        />
                    ))}
                    <StockNavItem isOpen={isSidebarOpen} pathname={pathname} />
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
                                placeholder="輸入股票代號或名稱，Enter 開啟"
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
                        <div className="flex items-center text-sm">
                            <span className="text-gray-400 mr-2 underline decoration-gray-700 underline-offset-4">當前標的：</span>
                            {cleanStockSymbol(selectedSymbol) ? (
                <Link
                    to={toStockDetailPath(selectedSymbol)}
                    className="bg-[#1E293B] text-[#EAB308] border border-gray-700 px-3 py-1 rounded-md font-black tracking-widest min-w-[80px] text-center hover:border-[#EAB308]/50 hover:bg-[#243044] transition-colors"
                    title="開啟個股情報中心"
                >
                                    {cleanStockSymbol(selectedSymbol)}
                                </Link>
                            ) : (
                                <span className="bg-[#1E293B] text-gray-500 border border-gray-700 px-3 py-1 rounded-md font-mono min-w-[80px] text-center">
                                    未指定
                                </span>
                            )}
                        </div>
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
