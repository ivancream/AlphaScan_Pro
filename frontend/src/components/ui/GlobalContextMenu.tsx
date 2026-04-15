import React, { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAppStore } from '@/store/useAppStore';
import { useAddToWatchlist } from '@/hooks/useWatchlist';
import { LineChart, Star } from 'lucide-react';
import { cleanStockSymbol, toStockDetailPath } from '@/lib/stocks';

export const GlobalContextMenu = () => {
    const { contextMenu, closeContextMenu } = useAppStore();
    const menuRef = useRef<HTMLDivElement>(null);
    const { mutate: addToWatchlist } = useAddToWatchlist();
    const navigate = useNavigate();

    useEffect(() => {
        const handleClickOutside = (e: MouseEvent) => {
            if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
                closeContextMenu();
            }
        };

        const handleScroll = () => {
            if (contextMenu.isOpen) closeContextMenu();
        };

        // click anyway to close if it's not the menu itself
        const handleDocumentClick = (e: MouseEvent) => {
            if (contextMenu.isOpen && menuRef.current && !menuRef.current.contains(e.target as Node)) {
                closeContextMenu();
            }
        };


        if (contextMenu.isOpen) {
            document.addEventListener('mousedown', handleClickOutside);
            document.addEventListener('click', handleDocumentClick);
            window.addEventListener('scroll', handleScroll, { passive: true });
        }
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
            document.removeEventListener('click', handleDocumentClick);
            window.addEventListener('scroll', handleScroll);
        };
    }, [contextMenu.isOpen, closeContextMenu]);

    if (!contextMenu.isOpen || !contextMenu.symbol) return null;

    return (
        <div
            ref={menuRef}
            className="fixed z-[100] bg-[#161B22] border border-gray-700/80 rounded-lg shadow-2xl py-1.5 min-w-[200px] overflow-hidden"
            style={{ 
                top: contextMenu.y, 
                left: contextMenu.x,
                boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.3)'
            }}
        >
            <div className="px-3 py-1.5 border-b border-gray-800/80 mb-1">
                <span className="text-xs font-bold text-gray-500 uppercase tracking-wider">{contextMenu.symbol} 標的整理</span>
            </div>
            <button
                type="button"
                onClick={() => {
                    const sym = cleanStockSymbol(contextMenu.symbol as string);
                    useAppStore.getState().setSymbol(sym);
                    navigate(toStockDetailPath(sym));
                    closeContextMenu();
                }}
                className="w-full text-left px-3 py-2 text-sm text-gray-300 hover:bg-[#1E293B] hover:text-cyan-400 flex items-center gap-2.5 transition-colors"
            >
                <LineChart size={16} className="text-cyan-400" />
                <span className="font-medium">開啟個股情報</span>
            </button>
            <button
                onClick={() => {
                    addToWatchlist(contextMenu.symbol as string);
                    closeContextMenu();
                }}
                className="w-full text-left px-3 py-2 text-sm text-gray-300 hover:bg-[#1E293B] hover:text-[#EAB308] flex items-center gap-2.5 transition-colors"
            >
                <Star size={16} className="text-[#EAB308]" />
                <span className="font-medium">加入自選股</span>
            </button>
        </div>
    );
};
