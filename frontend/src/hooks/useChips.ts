import { useState } from 'react';

import { API_V1_BASE } from '@/lib/apiBase';

export const useChipsAnalysis = () => {
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [reportStream, setReportStream] = useState('');

    const analyzeChips = async (
        symbol: string,
        files: File[],
        isShort: boolean = false,
        techData?: any
    ) => {
        setIsAnalyzing(true);
        setReportStream('');

        const formData = new FormData();
        formData.append('symbol', symbol);
        formData.append('is_short', String(isShort));
        if (techData) {
            formData.append('tech_data', JSON.stringify(techData));
        }
        files.forEach((file) => {
            formData.append('files', file);
        });

        try {
            const response = await fetch(`${API_V1_BASE}/chips/analyze`, {
                method: 'POST',
                body: formData,
            });

            if (!response.ok) {
                throw new Error('Analysis failed');
            }

            const reader = response.body?.getReader();
            if (!reader) return;

            const decoder = new TextDecoder();
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value);
                const lines = chunk.split('\n');

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const dataStr = line.replace('data: ', '');
                        if (dataStr === '[DONE]') break;

                        try {
                            const parsed = JSON.parse(dataStr);
                            if (parsed.text) {
                                setReportStream((prev) => prev + parsed.text);
                            } else if (parsed.error) {
                                setReportStream((prev) => prev + `\n\n[Error: ${parsed.error}]`);
                            }
                        } catch (e) {
                            // Ignore partial JSON or malformed rows during stream
                        }
                    }
                }
            }
        } catch (error: any) {
            setReportStream((prev) => prev + `\n\n[系統錯誤: ${error.message}]`);
        } finally {
            setIsAnalyzing(false);
        }
    };

    const ingestWarrants = async (files: File[], targetDate?: string) => {
        setIsAnalyzing(true);
        const formData = new FormData();
        files.forEach((file) => formData.append('files', file));
        if (targetDate) {
            formData.append('target_date', targetDate);
        }

        try {
            const response = await fetch(`${API_V1_BASE}/chips/ingest`, {
                method: 'POST',
                body: formData,
            });
            if (!response.ok) throw new Error('Ingestion failed');
            return await response.json();
        } catch (error: any) {
            console.error('Ingestion error:', error);
            throw error;
        } finally {
            setIsAnalyzing(false);
        }
    };

    return {
        analyzeChips,
        ingestWarrants,
        isAnalyzing,
        reportStream,
        setReportStream
    };
};

export const useWarrantPositions = () => {
    const [positions, setPositions] = useState<any[]>([]);
    const [isLoading, setIsLoading] = useState(false);

    const fetchPositions = async (symbol?: string) => {
        setIsLoading(true);
        try {
            const url = symbol
                ? `${API_V1_BASE}/chips/warrants?symbol=${symbol}`
                : `${API_V1_BASE}/chips/warrants`;
            const response = await fetch(url);
            if (!response.ok) throw new Error('Failed to fetch warrant positions');
            const data = await response.json();
            setPositions(data);
        } catch (error) {
            console.error('Error fetching warrant positions:', error);
        } finally {
            setIsLoading(false);
        }
    };

    return {
        positions,
        isLoading,
        fetchPositions
    };
};

export const useBranchTrading = () => {
    const [trades, setTrades] = useState<any[]>([]);
    const [isLoading, setIsLoading] = useState(false);

    const fetchTrades = async (symbol?: string) => {
        setIsLoading(true);
        try {
            const url = symbol
                ? `${API_V1_BASE}/chips/branch-trading?symbol=${symbol}`
                : `${API_V1_BASE}/chips/branch-trading`;
            const response = await fetch(url);
            if (!response.ok) throw new Error('Failed to fetch branch trading data');
            const data = await response.json();
            setTrades(data);
        } catch (error) {
            console.error('Error fetching branch trades:', error);
        } finally {
            setIsLoading(false);
        }
    };

    return {
        trades,
        isLoading,
        fetchTrades
    };
};
