export function cleanStockSymbol(input: string | null | undefined): string {
  return String(input ?? '')
    .trim()
    .toUpperCase()
    .replace(/\.(TW|TWO)$/i, '');
}

export function toStockDetailPath(input: string | null | undefined): string {
  const symbol = cleanStockSymbol(input);
  return `/stock/${encodeURIComponent(symbol)}`;
}
