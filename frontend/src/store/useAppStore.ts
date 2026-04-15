import { create } from 'zustand';

interface AppState {
    selectedSymbol: string;
    dateRange: [string, string] | null;
    activeIndicators: string[];
    setSymbol: (symbol: string) => void;
    setDateRange: (range: [string, string]) => void;
    toggleIndicator: (indicator: string) => void;
    contextMenu: { isOpen: boolean; x: number; y: number; symbol: string | null };
    openContextMenu: (x: number, y: number, symbol: string) => void;
    closeContextMenu: () => void;
    // 記憶已執行的掃描狀態
    scannedStrategies: string[];
    setScanned: (strategyId: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
    selectedSymbol: '',
    dateRange: null,
    activeIndicators: ['MA20', 'Volume'],
    setSymbol: (symbol) => set({ selectedSymbol: symbol }),
    setDateRange: (range) => set({ dateRange: range }),
    toggleIndicator: (indicator) => set((state) => ({
        activeIndicators: state.activeIndicators.includes(indicator)
            ? state.activeIndicators.filter((i) => i !== indicator)
            : [...state.activeIndicators, indicator]
    })),
    contextMenu: { isOpen: false, x: 0, y: 0, symbol: null },
    openContextMenu: (x, y, symbol) => set({ contextMenu: { isOpen: true, x, y, symbol } }),
    closeContextMenu: () => set((state) => ({ contextMenu: { ...state.contextMenu, isOpen: false } })),
    scannedStrategies: [],
    setScanned: (id) => set((state) => ({
        scannedStrategies: state.scannedStrategies.includes(id) ? state.scannedStrategies : [...state.scannedStrategies, id]
    }))
}));
