"""
Discord Webhook 通知管理 API

Endpoints:
  GET  /api/v1/notifications/config
      回傳目前各 Webhook 設定狀態（URL 僅顯示前 40 字元）

  POST /api/v1/notifications/test-discord
      對指定 Webhook URL 發送一則測試訊息

  POST /api/v1/notifications/trigger-scan-alert
      手動將最新掃描結果推送至 Discord（不受 DISCORD_NOTIFY_ON_SCAN 限制）

  POST /api/v1/notifications/trigger-watchlist-alert
      手動推送自選清單至 Discord
"""
from __future__ import annotations

import os
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from backend.engines import notifier as _notifier
from backend.engines.engine_intraday_scanner import (
    get_scan_results,
    get_scan_status,
)
from backend.api.v1.watchlist import get_watchlist

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


# ─── Request / Response schemas ───────────────────────────────────────────────

class TestDiscordRequest(BaseModel):
    webhook_url: str
    alert_type: Literal["long", "short", "watchlist", "info"] = "info"

    @field_validator("webhook_url")
    @classmethod
    def must_be_discord_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("https://discord.com/api/webhooks/") and \
           not v.startswith("https://discordapp.com/api/webhooks/"):
            raise ValueError("必須是合法的 Discord Webhook URL")
        return v


class TriggerScanAlertRequest(BaseModel):
    strategy: Literal["long", "short", "both"] = "both"
    webhook_url_long:  Optional[str] = None
    webhook_url_short: Optional[str] = None


class TriggerWatchlistAlertRequest(BaseModel):
    event: Literal["market_open", "market_close", "condition_hit", "custom"] = "market_open"
    webhook_url: Optional[str] = None
    custom_title:   Optional[str] = None
    custom_message: Optional[str] = None


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/config")
async def get_notification_config():
    """
    回傳目前 Discord Webhook 設定狀態。
    URL 僅顯示前 40 字元，不洩漏完整 token。
    """
    cfg = _notifier.get_webhook_config()
    return {
        "notify_on_scan_enabled": _notifier.is_notify_enabled(),
        "notify_only_new_triggers": os.getenv(
            "DISCORD_NOTIFY_ONLY_NEW_TRIGGERS", "true"
        ).lower() in ("1", "true", "yes"),
        "max_stocks_per_message": int(os.getenv("DISCORD_MAX_STOCKS", "10")),
        "webhooks": {
            "long":      {"label": "多方選股", "url_preview": cfg.get("long")},
            "short":     {"label": "空方選股", "url_preview": cfg.get("short")},
            "watchlist": {"label": "自選清單",  "url_preview": cfg.get("watchlist")},
        },
    }


@router.post("/test-discord")
async def test_discord_webhook(req: TestDiscordRequest):
    """
    對指定的 Discord Webhook URL 發送測試訊息。

    Body example:
    ```json
    {
      "webhook_url": "https://discord.com/api/webhooks/xxx/yyy",
      "alert_type": "long"
    }
    ```
    """
    result = await _notifier.send_test_alert(req.webhook_url, req.alert_type)
    if not result.get("ok"):
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Discord Webhook 傳送失敗",
                "discord_status": result.get("status"),
                "discord_body":   result.get("body"),
            },
        )
    return {
        "success": True,
        "message": f"測試訊息已成功發送（類型：{req.alert_type}）",
        "discord_status": result.get("status"),
    }


@router.post("/trigger-scan-alert")
async def trigger_scan_alert(req: TriggerScanAlertRequest):
    """
    手動將最新的盤中掃描結果推送至 Discord。
    可覆寫 .env 中的 Webhook URL（Body 不填則沿用 .env 設定）。

    Body example:
    ```json
    {
      "strategy": "both",
      "webhook_url_long":  "https://discord.com/api/webhooks/...",
      "webhook_url_short": "https://discord.com/api/webhooks/..."
    }
    ```
    """
    status = get_scan_status()
    scan_id   = status.get("scan_id") or "manual"
    scan_time = status.get("last_run") or ""

    results_long  = get_scan_results("long")  if req.strategy in ("long",  "both") else []
    results_short = get_scan_results("short") if req.strategy in ("short", "both") else []

    if not results_long and not results_short:
        return {
            "success": False,
            "message": "快取中尚無掃描結果，請先執行一次掃描（POST /api/v1/scanner/trigger）",
        }

    # 暫時覆寫環境變數（只在此 request 內有效）
    _orig_long  = os.environ.get("DISCORD_WEBHOOK_LONG", "")
    _orig_short = os.environ.get("DISCORD_WEBHOOK_SHORT", "")
    _orig_flag  = os.environ.get("DISCORD_NOTIFY_ON_SCAN", "false")
    try:
        if req.webhook_url_long:
            os.environ["DISCORD_WEBHOOK_LONG"]  = req.webhook_url_long
        if req.webhook_url_short:
            os.environ["DISCORD_WEBHOOK_SHORT"] = req.webhook_url_short
        os.environ["DISCORD_NOTIFY_ON_SCAN"] = "true"

        summary = await _notifier.notify_scan_results(
            results_long, results_short, scan_id, scan_time
        )
    finally:
        os.environ["DISCORD_WEBHOOK_LONG"]      = _orig_long
        os.environ["DISCORD_WEBHOOK_SHORT"]     = _orig_short
        os.environ["DISCORD_NOTIFY_ON_SCAN"]    = _orig_flag

    sent_long  = len([r for r in summary.get("long",  []) if r.get("ok")])
    sent_short = len([r for r in summary.get("short", []) if r.get("ok")])

    return {
        "success": True,
        "message": f"推送完成：多方 {sent_long} 則、空方 {sent_short} 則訊息",
        "details": {
            "long_stocks":  len(results_long),
            "short_stocks": len(results_short),
            "scan_id":      scan_id,
            "scan_time":    scan_time,
        },
    }


@router.post("/trigger-watchlist-alert")
async def trigger_watchlist_alert(req: TriggerWatchlistAlertRequest):
    """
    手動推送自選清單至 Discord。

    Body example:
    ```json
    {
      "event": "market_open",
      "webhook_url": "https://discord.com/api/webhooks/..."
    }
    ```
    """
    stocks = await get_watchlist()

    if not stocks:
        return {"success": False, "message": "自選清單為空，無資料可推送"}

    _orig_url  = os.environ.get("DISCORD_WEBHOOK_WATCHLIST", "")
    try:
        if req.webhook_url:
            os.environ["DISCORD_WEBHOOK_WATCHLIST"] = req.webhook_url

        result = await _notifier.notify_watchlist(
            stocks=stocks,
            event=req.event,
            custom_title=req.custom_title,
            custom_message=req.custom_message,
        )
    finally:
        os.environ["DISCORD_WEBHOOK_WATCHLIST"] = _orig_url

    if not result.get("ok"):
        raise HTTPException(
            status_code=502,
            detail={
                "message": "自選清單推送失敗",
                "discord_status": result.get("status"),
                "discord_body":   result.get("body"),
            },
        )
    return {
        "success": True,
        "message": f"自選清單已推送（{len(stocks)} 檔）",
        "event":   req.event,
    }
