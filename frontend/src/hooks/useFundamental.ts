import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

// --- API Services ---
const api = axios.create({ baseURL: 'http://localhost:8000/api/v1' });

export const useFundamentalInfo = (stockCode: string, enabled: boolean) => {
    return useQuery({
        queryKey: ['fundamentalInfo', stockCode],
        queryFn: async () => {
            const { data } = await api.get(`/fundamental/info/${stockCode}`);
            return data;
        },
        enabled: enabled && !!stockCode,
        staleTime: 1000 * 60 * 60, // 1 hour 
    });
};

export const useFundamentalSentiment = (stockCode: string, enabled: boolean) => {
    return useQuery({
        queryKey: ['fundamentalSentiment', stockCode],
        queryFn: async () => {
            const { data } = await api.get(`/fundamental/sentiment/${stockCode}`);
            return data;
        },
        enabled: enabled && !!stockCode,
        staleTime: 1000 * 60 * 60, // 1 hour
    });
};

export const streamFundamentalReport = async (
    stockCode: string,
    dataInfo: any,
    sentimentSummary: any,
    onChunk: (text: string) => void,
    onFinish: () => void
) => {
    try {
        const response = await fetch('http://localhost:8000/api/v1/fundamental/stream-report', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                stock_code: stockCode,
                data_info: dataInfo,
                sentiment_summary: sentimentSummary
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
