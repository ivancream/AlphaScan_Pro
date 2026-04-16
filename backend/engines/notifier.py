"""
Discord Webhook 警報模組 (AlphaScan Pro Notifier)

架構設計：
─────────────────────────────────────────────────────────────────────────────
• send_discord_alert()   — 底層送出單一 Embed 訊息（非同步，requests 在 executor 中執行）
• build_scan_embeds()    — 將掃描結果轉為 Discord Embed 清單（含分頁，每批 ≤ 10 檔）
• notify_scan_results()  — 多方 / 空方 掃描完成後呼叫此函式
• notify_watchlist()     — 自選清單開收盤彙報 / 條件觸發時呼叫此函式

環境變數（設定於專案根目錄 .env）：
  DISCORD_WEBHOOK_LONG       多方選股 Webhook URL
  DISCORD_WEBHOOK_SHORT      空方選股 Webhook URL
  DISCORD_WEBHOOK_WATCHLIST  自選清單 Webhook URL
  DISCORD_NOTIFY_ON_SCAN          掃描完成後是否自動推送 (true/false，預設 false)
  DISCORD_NOTIFY_ONLY_NEW_TRIGGERS 僅推送「與上一輪掃描相比新進榜」標的 (true/false，預設 true)
  DISCORD_MAX_STOCKS               每則訊息最多顯示幾檔（預設 10）
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import zoneinfo
from typing import Any, Dict, List, Optional

# 使用 requests（後端 codebase 已有引用）
import requests

_TZ = zoneinfo.ZoneInfo("Asia/Taipei")

# ─── 顏色常數（Discord Embed 用 int） ────────────────────────────────────────
COLOR_LONG       = 0x22C55E   # 綠：多方
COLOR_SHORT      = 0xEF4444   # 紅：空方
COLOR_WATCHLIST  = 0xEAB308   # 金：自選
COLOR_INFO       = 0x3B82F6   # 藍：一般訊息
COLOR_SUCCESS    = 0x10B981   # 青綠：成功
COLOR_WARNING    = 0xF59E0B   # 橘：警告
COLOR_ERROR      = 0xFF6B35   # 橘紅：錯誤


# ─── 設定讀取 ─────────────────────────────────────────────────────────────────

def _get_env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def get_webhook_config() -> Dict[str, str]:
    """回傳目前所有 Discord Webhook 設定（URL 僅顯示前 40 字元供除錯）。"""
    urls = {
        "long":      _get_env("DISCORD_WEBHOOK_LONG"),
        "short":     _get_env("DISCORD_WEBHOOK_SHORT"),
        "watchlist": _get_env("DISCORD_WEBHOOK_WATCHLIST"),
    }
    return {
        k: (v[:40] + "…" if len(v) > 40 else v) if v else "(未設定)"
        for k, v in urls.items()
    }


def is_notify_enabled() -> bool:
    """DISCORD_NOTIFY_ON_SCAN=true 時才自動推送。"""
    return _get_env("DISCORD_NOTIFY_ON_SCAN", "false").lower() in ("1", "true", "yes")


def _max_stocks() -> int:
    try:
        return max(1, int(_get_env("DISCORD_MAX_STOCKS", "10")))
    except ValueError:
        return 10


# ─── 底層 HTTP 傳送（同步，供 executor 使用） ─────────────────────────────────

def _post_to_discord(webhook_url: str, payload: Dict) -> Dict:
    """
    向 Discord Webhook 發送 POST 請求。
    回傳 {"ok": True} 或 {"ok": False, "status": int, "body": str}。
    """
    try:
        resp = requests.post(
            webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=10,
        )
        if resp.status_code in (200, 204):
            return {"ok": True, "status": resp.status_code}
        return {"ok": False, "status": resp.status_code, "body": resp.text[:300]}
    except Exception as exc:
        return {"ok": False, "status": 0, "body": str(exc)}


# ─── 非同步公開介面 ───────────────────────────────────────────────────────────

async def send_discord_alert(
    webhook_url: str,
    title: str,
    message: str,
    color: int = COLOR_INFO,
    fields: Optional[List[Dict[str, Any]]] = None,
    footer: Optional[str] = None,
) -> Dict:
    """
    傳送單一 Discord Embed 通知。

    Args:
        webhook_url: Discord Webhook URL。
        title:       Embed 標題（< 256 字元）。
        message:     Embed description（< 4096 字元）。
        color:       Embed 左側色條（整數 RGB）。
        fields:      Embed fields 清單，每筆格式 {"name": str, "value": str, "inline": bool}。
        footer:      Embed footer 文字。

    Returns:
        {"ok": True} 或 {"ok": False, "status": int, "body": str}
    """
    if not webhook_url or not webhook_url.startswith("http"):
        return {"ok": False, "status": 0, "body": "Webhook URL 未設定或格式錯誤"}

    now_str = datetime.datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")
    embed: Dict[str, Any] = {
        "title":       title[:256],
        "description": message[:4096],
        "color":       color,
        "timestamp":   datetime.datetime.utcnow().isoformat() + "Z",
    }
    if fields:
        embed["fields"] = fields[:25]          # Discord 限 25 個 fields
    if footer:
        embed["footer"] = {"text": f"{footer} • {now_str}"}
    else:
        embed["footer"] = {"text": f"AlphaScan Pro • {now_str}"}

    payload = {"embeds": [embed]}
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _post_to_discord, webhook_url, payload)
    return result


# ─── Embed 建構工具 ───────────────────────────────────────────────────────────

def _fmt_change(pct: Any) -> str:
    """將漲跌幅格式化為帶顏色符號的字串（Discord 不支援顏色，只用符號）。"""
    try:
        v = float(pct)
        symbol = "▲" if v >= 0 else "▼"
        return f"{symbol} {abs(v):.2f}%"
    except (TypeError, ValueError):
        return "—"


def build_scan_embeds(
    strategy: str,
    results: List[Dict],
    scan_id: str,
    scan_time: str,
    *,
    variant: str = "full",
) -> List[Dict]:
    """
    將掃描結果拆成多組 Embed payload（每組最多 10 檔），避免超過 Discord 字數上限。

    Args:
        strategy:  'long' | 'short' | 'wanderer'
        results:   掃描結果清單
        scan_id:   掃描批次 ID
        scan_time: ISO 時間字串

    Returns:
        List of Discord payload dict（每項可直接傳給 webhook）
    """
    strategy_meta = {
        "long":     ("📈 多方選股", COLOR_LONG,  "布林突破多方候選"),
        "short":    ("📉 空方選股", COLOR_SHORT, "布林跌破空方候選"),
        "wanderer": ("🔄 浪子回頭", COLOR_INFO,  "布林回歸均值候選"),
    }
    label, color, subtitle = strategy_meta.get(strategy, ("🔔 選股訊號", COLOR_INFO, ""))
    is_new_only = variant == "new_triggers"
    title_action = "新觸發" if is_new_only else "掃描完成"
    subtitle_line = "本輪新進榜標的" if is_new_only else subtitle

    max_n = _max_stocks()
    chunks = [results[i : i + max_n] for i in range(0, max(len(results), 1), max_n)]
    payloads = []

    for page_idx, chunk in enumerate(chunks):
        total_pages = len(chunks)
        page_tag = f"（第 {page_idx + 1}/{total_pages} 頁）" if total_pages > 1 else ""

        description = (
            f"**{subtitle_line}** {page_tag}\n"
            f"本次共 **{len(results)}** 檔{'新觸發' if is_new_only else '符合條件'}\n"
            f"掃描批次：`{scan_id}` ｜ 時間：`{scan_time[:19]}`"
        )

        fields = []
        for item in chunk:
            sid   = item.get("代號", "?")
            name  = item.get("名稱", "")
            close = item.get("收盤價", "—")
            chg   = item.get("今日漲跌幅(%)", 0)
            vol   = item.get("成交量(張)", "—")

            # 策略特定欄位
            extra_parts = []
            if strategy == "long":
                bw  = item.get("帶寬增長(%)", "—")
                vr  = item.get("量比", "—")
                extra_parts = [f"帶寬增長 {bw}%", f"量比 {vr}"]
            elif strategy == "short":
                bp  = item.get("布林位置", "—")
                sl  = item.get("月線斜率", "—")
                extra_parts = [f"布林位置 {bp}", f"月線斜率 {sl}"]
            elif strategy == "wanderer":
                bp  = item.get("布林位階", "—")
                disp = item.get("處置狀態", "-")
                extra_parts = [f"位階 {bp}", f"處置: {disp}"]

            extra_str = " ｜ ".join(str(p) for p in extra_parts) if extra_parts else ""
            value_lines = [
                f"收盤 **{close}** ｜ {_fmt_change(chg)} ｜ 量 {vol} 張",
            ]
            if extra_str:
                value_lines.append(extra_str)

            fields.append({
                "name":   f"**{sid}** {name}",
                "value":  "\n".join(value_lines),
                "inline": False,
            })

        embed: Dict[str, Any] = {
            "title":       f"{label}{title_action}",
            "description": description,
            "color":       color,
            "fields":      fields,
            "footer":      {
                "text": f"AlphaScan Pro • {datetime.datetime.now(_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
            },
            "timestamp":   datetime.datetime.utcnow().isoformat() + "Z",
        }
        payloads.append({"embeds": [embed]})

    return payloads


# ─── 高階業務通知函式 ─────────────────────────────────────────────────────────

async def notify_scan_results(
    results_long: List[Dict],
    results_short: List[Dict],
    scan_id: str,
    scan_time: str,
    *,
    only_new_triggers: bool = False,
) -> Dict[str, Any]:
    """
    掃描完成後推送多方 / 空方結果至各自的 Discord Webhook。
    若 DISCORD_NOTIFY_ON_SCAN != true 則直接跳過。
    only_new_triggers=True 時 Embed 標題與說明改為「新觸發」（payload 應已由掃描器做差集）。

    Returns:
        {"long": [...結果], "short": [...結果]}
    """
    if not is_notify_enabled():
        return {"skipped": True, "reason": "DISCORD_NOTIFY_ON_SCAN 未啟用"}

    embed_variant = "new_triggers" if only_new_triggers else "full"
    if not results_long and not results_short:
        return {"skipped": True, "reason": "無待推送標的"}

    url_long  = _get_env("DISCORD_WEBHOOK_LONG")
    url_short = _get_env("DISCORD_WEBHOOK_SHORT")
    summary: Dict[str, Any] = {}

    async def _send_strategy(url: str, strategy: str, results: List[Dict]) -> List[Dict]:
        if not url or not results:
            return []
        payloads = build_scan_embeds(
            strategy, results, scan_id, scan_time, variant=embed_variant
        )
        outcomes = []
        for payload in payloads:
            r = await _async_post(url, payload)
            outcomes.append(r)
            if not r.get("ok"):
                print(f"[Notifier] {strategy} 推送失敗: {r}")
        return outcomes

    # 多方
    if url_long and results_long:
        summary["long"] = await _send_strategy(url_long, "long", results_long)
    else:
        summary["long"] = []

    # 空方
    if url_short and results_short:
        summary["short"] = await _send_strategy(url_short, "short", results_short)
    else:
        summary["short"] = []

    return summary


async def notify_watchlist(
    stocks: List[Dict],
    event: str = "market_open",
    custom_title: Optional[str] = None,
    custom_message: Optional[str] = None,
) -> Dict:
    """
    自選清單通知。

    Args:
        stocks:         自選股清單，格式同 watchlist API 回傳結果。
        event:          'market_open' | 'market_close' | 'condition_hit' | 'custom'
        custom_title:   event='custom' 時可自訂標題
        custom_message: event='custom' 時可自訂說明
    """
    url = _get_env("DISCORD_WEBHOOK_WATCHLIST")
    if not url:
        return {"ok": False, "body": "DISCORD_WEBHOOK_WATCHLIST 未設定"}

    event_meta = {
        "market_open":   ("🔔 自選股開盤彙報",   "今日盤中開始，以下為持有標的概況："),
        "market_close":  ("📊 自選股收盤彙報",   "今日收盤，自選股表現彙整："),
        "condition_hit": ("⚡ 自選股條件觸發",   "以下標的達到預設進出場條件："),
        "custom":        (custom_title or "🔔 自選股通知", custom_message or ""),
    }
    title, description_prefix = event_meta.get(event, event_meta["custom"])

    now_str = datetime.datetime.now(_TZ).strftime("%Y-%m-%d %H:%M")
    description = f"{description_prefix}\n共 **{len(stocks)}** 檔標的 ｜ `{now_str}`"

    fields = []
    for item in stocks[:_max_stocks()]:
        sid   = item.get("代號", item.get("stock_id", "?"))
        name  = item.get("名稱", item.get("name", ""))
        close = item.get("收盤價", "—")
        chg   = item.get("今日漲跌幅(%)", 0)
        vol   = item.get("成交量(張)", "—")

        fields.append({
            "name":   f"**{sid}** {name}",
            "value":  f"收盤 **{close}** ｜ {_fmt_change(chg)} ｜ 量 {vol} 張",
            "inline": True,
        })

    return await send_discord_alert(
        webhook_url=url,
        title=title,
        message=description,
        color=COLOR_WATCHLIST,
        fields=fields if fields else None,
    )


# ─── 測試用工具 ───────────────────────────────────────────────────────────────

async def send_test_alert(webhook_url: str, alert_type: str = "info") -> Dict:
    """
    傳送一則測試訊息，驗證 Webhook URL 是否正確。

    Args:
        webhook_url: 要測試的 Discord Webhook URL。
        alert_type:  'long' | 'short' | 'watchlist' | 'info'
    """
    type_meta = {
        "long":      ("📈 多方選股 — 測試通知", COLOR_LONG),
        "short":     ("📉 空方選股 — 測試通知", COLOR_SHORT),
        "watchlist": ("🔔 自選清單 — 測試通知", COLOR_WATCHLIST),
        "info":      ("✅ AlphaScan 通知測試",  COLOR_SUCCESS),
    }
    title, color = type_meta.get(alert_type, type_meta["info"])
    now_str = datetime.datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")

    mock_fields = [
        {"name": "股票代號", "value": "2330 台積電",           "inline": True},
        {"name": "觸發時間", "value": now_str,                "inline": True},
        {"name": "收盤價",   "value": "▲ 950.00 (+2.15%)",   "inline": True},
        {"name": "成交量",   "value": "45,000 張",            "inline": True},
        {"name": "觸發條件", "value": "布林通道擴張 + 爆量",   "inline": False},
    ]

    return await send_discord_alert(
        webhook_url=webhook_url,
        title=title,
        message=(
            f"這是一則來自 **AlphaScan Pro** 的測試通知。\n"
            f"若您看到此訊息，代表 Webhook 設定正確！\n\n"
            f"類型：`{alert_type}` ｜ 發送時間：`{now_str}`"
        ),
        color=color,
        fields=mock_fields,
        footer="AlphaScan Pro 測試訊息",
    )


# ─── 內部輔助：直接 POST payload（不包裝 embed，供 build_scan_embeds 回傳的 payload 使用）

async def _async_post(webhook_url: str, payload: Dict) -> Dict:
    """直接非同步傳送已建構好的 payload dict。"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _post_to_discord, webhook_url, payload)
