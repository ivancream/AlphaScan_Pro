declare module 'react-plotly.js' {
    import { Component } from 'react';

    interface PlotParams {
        data: any[];
        layout?: any;
        config?: any;
        frames?: any[];
        style?: React.CSSProperties;
        useResizeHandler?: boolean;
        onClick?: (event: any) => void;
        onHover?: (event: any) => void;
        onUnhover?: (event: any) => void;
        onSelected?: (event: any) => void;
        onRelayout?: (event: any) => void;
        onUpdate?: (figure: any) => void;
        revision?: number;
        className?: string;
        divId?: string;
    }

    class Plot extends Component<PlotParams> {}
    export default Plot;
}
