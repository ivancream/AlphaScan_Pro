# engines/engine_ai.py
"""
統一 AI 對話引擎 (Unified AI Brain)

架構說明：
- 維護以「股票代號」為鍵的跨模組 Context 彙整 (Brain)
- 每個分析模組完成後，將摘要注入 Brain
- 所有對話都帶完整 Brain Context，讓 AI 知道用戶在各模組研究了什麼
- Streamlit 透過 session_state 持久化 Brain 狀態

Brain 結構 (存於 st.session_state.ai_brain)：
{
    "active_ticker": "2330",
    "contexts": {
        "2330": {
            "fundamental": "P/E 15x...",
            "technical":   "RSI=65, MA多排...",
            "chips":       "主力賣超3000張...",
            "band_long":   "猛虎出閘, 上軌斜率 0.35%...",
            "band_short":  "月線下彎, 跌破月線..."
        }
    },
    "chat_history": [
        {"role": "user",      "content": "..."},
        {"role": "assistant", "content": "..."}
    ]
}
"""

import os
from typing import List, Dict, Any, Optional, Tuple
import google.generativeai as genai
from PIL import Image
from . import prompts


# ==========================================
# 模組名稱對應（用於顯示與 Prompt 中）
# ==========================================
MODULE_LABELS: Dict[str, str] = {
    "fundamental": "基本面 / 財報分析",
    "technical":   "技術指標分析",
    "chips":       "籌碼面分析",
    "band_long":   "波段多方策略",
    "band_short":  "波段空方策略",
}


def _get_model() -> genai.GenerativeModel:
    """取得 Gemini 模型實例，並確保 API Key 已正確設定。"""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY 未設定，請檢查 .env 檔案。")
    genai.configure(api_key=api_key)

    model_id = os.getenv("GEMINI_MODEL_ID", "gemini-1.5-flash-latest").strip()
    return genai.GenerativeModel(
        model_id,
        generation_config=genai.types.GenerationConfig(
            temperature=0.7,
        )
    )


# ==========================================
# Brain 操作函數
# ==========================================

def get_empty_brain() -> Dict[str, Any]:
    """回傳一個初始化的空 Brain 結構。"""
    return {
        "active_ticker": None,
        "contexts": {},
        "chat_history": []
    }


def update_context(brain: Dict, ticker: str, module: str, summary: str) -> Dict:
    """
    將某模組的分析摘要注入 Brain。
    每次分析完成後呼叫，讓 AI 在後續對話中能引用。

    Args:
        brain:   現有的 Brain dict (來自 session_state)
        ticker:  股票代號 (e.g. "2330.TW")
        module:  模組名稱 ("fundamental", "technical", etc.)
        summary: 該模組的文字摘要 (可以是 AI 報告或數據字串)

    Returns:
        更新後的 Brain dict
    """
    if ticker not in brain["contexts"]:
        brain["contexts"][ticker] = {}
    brain["contexts"][ticker][module] = summary
    brain["active_ticker"] = ticker
    return brain


def build_context_string(brain: Dict, ticker: str) -> str:
    """
    將 Brain 中某支股票的所有模組 Context 整合成一段 AI 可讀的字串。

    Args:
        brain:  Brain dict
        ticker: 股票代號

    Returns:
        整合後的 Context 字串
    """
    ctx = brain.get("contexts", {}).get(ticker, {})
    if not ctx:
        return "（目前尚無其他模組的分析資料）"

    parts = []
    for module_key, label in MODULE_LABELS.items():
        if module_key in ctx:
            parts.append(f"### [{label}]\n{ctx[module_key]}")

    return "\n\n".join(parts)


# ==========================================
# 核心功能函數
# ==========================================

def initial_report(
    brain: Dict,
    ticker: str,
    module: str,
    new_data: str,
    images: Optional[List[Any]] = None,
    custom_prompt_override: Optional[str] = None
) -> str:
    """
    生成初始分析報告，自動整合 Brain 中所有已知的跨模組 Context。

    Args:
        brain:                 Brain dict (來自 session_state)
        ticker:                股票代號
        module:                當前呼叫的模組名稱
        new_data:              本模組的最新數據字串
        images:                若有圖片 (籌碼圖)，傳入 PIL Image list
        custom_prompt_override: 若指定，直接使用此 Prompt 覆蓋預設 Prompt

    Returns:
        AI 回覆的報告文字
    """
    model = _get_model()
    cross_context = build_context_string(brain, ticker)
    module_label = MODULE_LABELS.get(module, module)

    if custom_prompt_override:
        prompt = custom_prompt_override
    else:
        prompt = prompts.get_unified_initial_prompt(ticker, module_label, cross_context, new_data)

    try:
        if images:
            # Vision 模式（含圖片）
            response = model.generate_content([prompt] + images)
        else:
            response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 分析失敗：{e}"


def chat(
    brain: Dict,
    ticker: str,
    user_input: str,
) -> Tuple[str, Dict]:
    """
    帶完整跨模組記憶的對話回覆。

    Args:
        brain:      Brain dict (來自 session_state)
        ticker:     股票代號
        user_input: 用戶輸入

    Returns:
        (AI 回覆文字, 更新後的 Brain dict)
    """
    model = _get_model()
    cross_context = build_context_string(brain, ticker)

    # 建構對話歷史字串
    history_text = ""
    for msg in brain.get("chat_history", []):
        role = "用戶" if msg["role"] == "user" else "分析師"
        history_text += f"{role}: {msg['content']}\n\n"

    # 使用 prompts.py 中的統一提示詞
    prompt = prompts.get_unified_chat_prompt(ticker, cross_context, history_text, user_input)

    try:
        response = model.generate_content(prompt)
        reply = response.text
    except Exception as e:
        reply = f"回覆失敗：{e}"

    # 更新對話歷史
    brain["chat_history"].append({"role": "user", "content": user_input})
    brain["chat_history"].append({"role": "assistant", "content": reply})

    return reply, brain


def stream_chat(
    brain: Dict,
    ticker: str,
    user_input: str,
) -> Tuple[Any, Dict]:
    """
    Streaming 版本的對話。回傳 (generator, brain_updater_fn)。
    用法：
        stream, update_fn = engine_ai.stream_chat(brain, ticker, q)
        reply = st.write_stream(stream)
        st.session_state.ai_brain = update_fn(reply)
    """
    model = _get_model()
    cross_context = build_context_string(brain, ticker)

    history_text = ""
    for msg in brain.get("chat_history", []):
        role = "用戶" if msg["role"] == "user" else "分析師"
        history_text += f"{role}: {msg['content']}\n\n"

    prompt = prompts.get_unified_chat_prompt(ticker, cross_context, history_text, user_input)

    def _generator():
        try:
            for chunk in model.generate_content(prompt, stream=True):
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            yield f"回覆失敗：{e}"

    def _update_brain(reply: str) -> Dict:
        brain["chat_history"].append({"role": "user", "content": user_input})
        brain["chat_history"].append({"role": "assistant", "content": reply})
        return brain

    return _generator(), _update_brain


def stream_initial_report(
    brain: Dict,
    ticker: str,
    module: str,
    new_data: str,
    images: Optional[List[Any]] = None,
    custom_prompt_override: Optional[str] = None
) -> Any:
    """
    Streaming 版本的初始報告生成。
    用法：reply = st.write_stream(engine_ai.stream_initial_report(...))
    """
    model = _get_model()
    cross_context = build_context_string(brain, ticker)
    module_label = MODULE_LABELS.get(module, module)

    if custom_prompt_override:
        prompt = custom_prompt_override
    else:
        prompt = prompts.get_unified_initial_prompt(ticker, module_label, cross_context, new_data)

    def _generator():
        try:
            content = [prompt]
            if images:
                content += images
            
            # Gemini 1.5 Flash 支援 Vision + Streaming
            response = model.generate_content(content, stream=True)
            for chunk in response:
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            yield f"AI 生成失敗：{e}"

    return _generator()


def clear_chat(brain: Dict) -> Dict:
    """清除對話歷史（但保留 Context）。"""
    brain["chat_history"] = []
    return brain


def clear_ticker_context(brain: Dict, ticker: str) -> Dict:
    """清除某支股票的所有 Context（重新研究時用）。"""
    if ticker in brain.get("contexts", {}):
        del brain["contexts"][ticker]
    brain["chat_history"] = []
    return brain
