import React from 'react';

export const LoadingState: React.FC<{ text?: string }> = ({ text = "正在載入海量歷史數據..." }) => {
    return (
        <div className="flex flex-col items-center justify-center h-full w-full bg-[#0E1117] space-y-6 pt-20">
            <div className="w-80 h-1.5 bg-gray-800 rounded-full overflow-hidden relative">
                <div className="absolute top-0 left-0 h-full bg-[#EAB308] animate-pulse w-full origin-left scale-x-0 transition-transform duration-1000 ease-out"
                    style={{ animation: 'progress 2s ease-in-out infinite' }}></div>
            </div>
            <p className="text-gray-400 text-sm animate-pulse tracking-wide">{text}</p>
        </div>
    );
};
