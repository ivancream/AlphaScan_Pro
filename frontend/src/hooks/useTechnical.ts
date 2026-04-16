import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

import { API_V1_BASE } from '@/lib/apiBase';

// --- API Services ---
const api = axios.create({ baseURL: API_V1_BASE });

export const useTechnicalIndicators = (stockCode: string, enabled: boolean) => {
    return useQuery({
        queryKey: ['technicalIndicators', stockCode],
        queryFn: async () => {
            const { data } = await api.get(`/technical/indicators/${stockCode}`);
            return data;
        },
        enabled: enabled && !!stockCode,
        staleTime: 1000 * 60 * 5, // 5 min
    });
};

export const streamTechnicalReport = async (
    stockCode: string,
    onChunk: (text: string) => void,
    onFinish: () => void
) => {
    try {
        const response = await fetch(`${API_V1_BASE}/technical/stream-report`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                stock_code: stockCode,
                period: "12mo"
            })
        });

        if (!response.body) throw new Error('ReadableStream not supported');

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split('\n\n');
            for (const line of lines) {
                if (line.startsWith('data: ')) {
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
