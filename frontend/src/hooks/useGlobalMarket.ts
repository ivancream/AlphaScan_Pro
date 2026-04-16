import { useQuery, useMutation } from '@tanstack/react-query';
import axios from 'axios';

import { API_V1_BASE } from '@/lib/apiBase';

// --- API Services ---
const api = axios.create({ baseURL: API_V1_BASE });

export const useMacroData = () => {
    return useQuery({
        queryKey: ['macroData'],
        queryFn: async () => {
            const { data } = await api.get('/global/macro-data');
            return data;
        },
        staleTime: 1000 * 60 * 60, // 1 hour 
    });
};

export const useRegionalMetrics = (marketName: string, enabled: boolean) => {
    return useQuery({
        queryKey: ['regionalMetrics', marketName],
        queryFn: async () => {
            const { data } = await api.get(`/global/market-metrics/${marketName}`);
            return data;
        },
        enabled: enabled,
        staleTime: 1000 * 60 * 5, // 5 min
    });
};

export const useMarketNews = (marketName: string) => {
    return useQuery({
        queryKey: ['marketNews', marketName],
        queryFn: async () => {
            const { data } = await api.get(`/global/market-news/${encodeURIComponent(marketName)}`);
            return data;
        },
        enabled: !!marketName,
        staleTime: 1000 * 60 * 10, // 10 min
    });
};

// --- Streaming Helpers ---
export const streamAIReport = async (
    marketName: string,
    onChunk: (text: string) => void,
    onFinish: () => void
) => {
    try {
        const response = await fetch(`${API_V1_BASE}/global/stream-report`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ market_name: marketName })
        });

        if (!response.body) throw new Error('ReadableStream not supported');

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            // SSE format is: data: [content]\n\n
            const lines = chunk.split('\n\n');
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    // 換回原本的換行符號
                    const content = line.substring(6).replace(/<br>/g, '\n');
                    onChunk(content);
                }
            }
        }
        onFinish();
    } catch (error) {
        console.error('Stream error:', error);
        onChunk('\n[連線異常，串流中斷]');
        onFinish();
    }
};
