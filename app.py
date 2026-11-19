import base64
import io
import json
import math
import os
import re
import time
from datetime import datetime, timedelta
from collections import defaultdict
import httpx
import streamlit as st

st.set_page_config(page_title="Chat sex premium", page_icon="✨", layout="wide")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ĐƯỜNG DẪN LƯU TRỮ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "chat_data")
CHAT_HISTORY_DIR = os.path.join(DATA_DIR, "conversations")
STATS_FILE = os.path.join(DATA_DIR, "usage_stats.json")
AVATAR_FILE = os.path.join(APP_DIR, "user_avatar.jpg")

os.makedirs(CHAT_HISTORY_DIR, exist_ok=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HỆ THỐNG LƯU TRỮ THỐNG KÊ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def load_usage_stats() -> dict:
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "total_tokens": 0,
        "total_cost": 0.0,
        "total_messages": 0,
        "daily": {},  # "2026-11-19": {"tokens": X, "cost": Y, "messages": Z, "input_tokens": A, "output_tokens": B}
    }


def save_usage_stats(stats: dict):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


def record_usage(tokens: int, cost: float, input_tok: int, output_tok: int):
    stats = load_usage_stats()
    today = datetime.now().strftime("%Y-%m-%d")
    stats["total_tokens"] += tokens
    stats["total_cost"] += cost
    stats["total_messages"] += 1
    if today not in stats["daily"]:
        stats["daily"][today] = {"tokens": 0, "cost": 0.0, "messages": 0, "input_tokens": 0, "output_tokens": 0}
    stats["daily"][today]["tokens"] += tokens
    stats["daily"][today]["cost"] += cost
    stats["daily"][today]["messages"] += 1
    stats["daily"][today]["input_tokens"] += input_tok
    stats["daily"][today]["output_tokens"] += output_tok
    save_usage_stats(stats)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HỆ THỐNG LƯU TRỮ CUỘC HỘI THOẠI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_conversation_file(conv_id: str) -> str:
    return os.path.join(CHAT_HISTORY_DIR, f"{conv_id}.json")


def save_conversation(conv_id: str, messages: list, title: str = ""):
    data = {
        "id": conv_id,
        "title": title or _auto_title(messages),
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "messages": _serialize_messages(messages),
    }
    with open(get_conversation_file(conv_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_conversation(conv_id: str) -> dict | None:
    path = get_conversation_file(conv_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def list_conversations() -> list[dict]:
    convs = []
    for fname in os.listdir(CHAT_HISTORY_DIR):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(CHAT_HISTORY_DIR, fname), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    convs.append({
                        "id": data.get("id", fname[:-5]),
                        "title": data.get("title", "Untitled"),
                        "updated_at": data.get("updated_at", ""),
                        "msg_count": len(data.get("messages", [])),
                    })
            except Exception:
                pass
    convs.sort(key=lambda x: x["updated_at"], reverse=True)
    return convs


def delete_conversation(conv_id: str):
    path = get_conversation_file(conv_id)
    if os.path.exists(path):
        os.remove(path)


def _auto_title(messages: list) -> str:
    for m in messages:
        if m.get("role") == "user":
            text = m.get("display_text", m.get("full_text", ""))
            if text:
                return text[:60] + ("..." if len(text) > 60 else "")
    return f"Chat {datetime.now().strftime('%d/%m %H:%M')}"


def _serialize_messages(messages: list) -> list:
    """Serialize messages for JSON storage, excluding binary preview_images."""
    serialized = []
    for m in messages:
        entry = {
            "role": m["role"],
            "display_text": m.get("display_text", ""),
            "full_text": m.get("full_text", ""),
        }
        if m.get("image_urls"):
            entry["image_urls"] = m["image_urls"]
        if m.get("attached_names"):
            entry["attached_names"] = m["attached_names"]
        if m.get("reasoning_text"):
            entry["reasoning_text"] = m["reasoning_text"]
        if m.get("meta"):
            entry["meta"] = m["meta"]
        serialized.append(entry)
    return serialized


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CSS + JAVASCRIPT HIỆU ỨNG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.markdown(
    """
    <style>
    /* ═══ CHAT BUBBLES ═══ */
    [data-testid="stChatMessage"]:has(.user-msg-hook) {
        flex-direction: row-reverse !important;
        justify-content: flex-start !important;
        margin-left: auto !important;
        margin-right: 0 !important;
        width: fit-content !important;
        max-width: 80% !important;
        background: linear-gradient(135deg, rgba(14, 116, 234, 0.12) 0%, rgba(99, 60, 255, 0.10) 100%) !important;
        border: 1px solid rgba(14, 116, 234, 0.24) !important;
        border-radius: 18px 18px 4px 18px !important;
        padding: 10px 14px !important;
        gap: 10px !important;
        animation: slideInRight 0.4s cubic-bezier(0.16, 1, 0.3, 1) !important;
    }
    [data-testid="stChatMessage"]:has(.user-msg-hook) [data-testid="stChatMessageContent"] {
        text-align: right !important;
    }
    [data-testid="stChatMessage"]:has(.user-msg-hook) pre,
    [data-testid="stChatMessage"]:has(.user-msg-hook) code {
        text-align: left !important;
    }
    [data-testid="stChatMessage"]:has(.user-msg-hook) [data-testid="stChatMessageAvatarCustom"],
    [data-testid="stChatMessage"]:has(.user-msg-hook) [data-testid="stChatMessageAvatarUser"],
    [data-testid="stChatMessage"]:has(.user-msg-hook) > div:first-child img {
        border-radius: 50% !important;
        object-fit: cover !important;
        width: 38px !important;
        height: 38px !important;
    }

    /* AI message */
    [data-testid="stChatMessage"]:not(:has(.user-msg-hook)) {
        flex-direction: row !important;
        justify-content: flex-start !important;
        margin-right: auto !important;
        margin-left: 0 !important;
        max-width: 86% !important;
        background: linear-gradient(135deg, rgba(128, 128, 128, 0.07) 0%, rgba(16, 163, 127, 0.05) 100%) !important;
        border: 1px solid rgba(128, 128, 128, 0.16) !important;
        border-radius: 18px 18px 18px 4px !important;
        padding: 12px 16px !important;
        gap: 12px !important;
        animation: slideInLeft 0.4s cubic-bezier(0.16, 1, 0.3, 1) !important;
    }
    [data-testid="stChatMessage"]:not(:has(.user-msg-hook)) [data-testid="stChatMessageAvatarCustom"],
    [data-testid="stChatMessage"]:not(:has(.user-msg-hook)) [data-testid="stChatMessageAvatarAssistant"],
    [data-testid="stChatMessage"]:not(:has(.user-msg-hook)) > div:first-child,
    [data-testid="stChatMessage"]:not(:has(.user-msg-hook)) > div:first-child img {
        background: transparent !important;
        background-color: transparent !important;
        box-shadow: none !important;
        border: none !important;
        border-radius: 0 !important;
        width: 34px !important;
        height: 34px !important;
        object-fit: contain !important;
    }

    @media (prefers-color-scheme: dark) {
        [data-testid="stChatMessage"]:not(:has(.user-msg-hook)) > div:first-child img {
            filter: invert(1) brightness(1.15);
        }
    }
    [data-theme="dark"] [data-testid="stChatMessage"]:not(:has(.user-msg-hook)) > div:first-child img {
        filter: invert(1) brightness(1.15);
    }

    /* ═══ ANIMATIONS ═══ */
    @keyframes slideInRight {
        from { opacity: 0; transform: translateX(30px) scale(0.95); }
        to   { opacity: 1; transform: translateX(0) scale(1); }
    }
    @keyframes slideInLeft {
        from { opacity: 0; transform: translateX(-30px) scale(0.95); }
        to   { opacity: 1; transform: translateX(0) scale(1); }
    }
    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(12px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes pulseGlow {
        0%, 100% { box-shadow: 0 0 5px rgba(16, 163, 127, 0.3); }
        50%      { box-shadow: 0 0 20px rgba(16, 163, 127, 0.6); }
    }
    @keyframes gradientShift {
        0%   { background-position: 0% 50%; }
        50%  { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }

    /* ═══ COPY BUTTONS ═══ */
    .copy-btn-container {
        display: flex;
        gap: 6px;
        margin-top: 8px;
        animation: fadeInUp 0.3s ease;
    }
    .copy-btn {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 4px 12px;
        border-radius: 8px;
        border: 1px solid rgba(128, 128, 128, 0.25);
        background: rgba(128, 128, 128, 0.08);
        color: inherit;
        font-size: 12px;
        cursor: pointer;
        transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
        user-select: none;
        backdrop-filter: blur(8px);
    }
    .copy-btn:hover {
        background: rgba(16, 163, 127, 0.15);
        border-color: rgba(16, 163, 127, 0.4);
        transform: translateY(-1px);
        box-shadow: 0 2px 8px rgba(16, 163, 127, 0.2);
    }
    .copy-btn:active {
        transform: scale(0.95);
    }
    .copy-btn.copied {
        background: rgba(16, 163, 127, 0.2) !important;
        border-color: #10a37f !important;
        color: #10a37f !important;
    }
    .copy-btn svg {
        width: 14px;
        height: 14px;
        fill: currentColor;
        opacity: 0.7;
    }

    /* ═══ CODE BLOCK COPY ═══ */
    .code-block-wrapper {
        position: relative;
        margin: 8px 0;
    }
    .code-copy-btn {
        position: absolute;
        top: 8px;
        right: 8px;
        padding: 4px 8px;
        border-radius: 6px;
        border: 1px solid rgba(128, 128, 128, 0.3);
        background: rgba(0, 0, 0, 0.6);
        color: #e0e0e0;
        font-size: 11px;
        cursor: pointer;
        opacity: 0;
        transition: all 0.2s ease;
        z-index: 10;
        backdrop-filter: blur(4px);
    }
    .code-block-wrapper:hover .code-copy-btn {
        opacity: 1;
    }
    .code-copy-btn:hover {
        background: rgba(16, 163, 127, 0.8);
        color: white;
    }
    .code-copy-btn.copied {
        background: rgba(16, 163, 127, 0.9) !important;
        color: white !important;
        opacity: 1 !important;
    }

    /* ═══ CONVERSATION LIST ═══ */
    .conv-item {
        padding: 8px 12px;
        border-radius: 10px;
        margin: 3px 0;
        cursor: pointer;
        transition: all 0.2s ease;
        border: 1px solid transparent;
    }
    .conv-item:hover {
        background: rgba(16, 163, 127, 0.1);
        border-color: rgba(16, 163, 127, 0.3);
    }
    .conv-item.active {
        background: rgba(16, 163, 127, 0.15);
        border-color: rgba(16, 163, 127, 0.4);
    }
    .conv-title {
        font-size: 13px;
        font-weight: 500;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .conv-meta {
        font-size: 11px;
        opacity: 0.6;
    }

    /* ═══ STATS TABLE ═══ */
    .stats-card {
        background: linear-gradient(135deg, rgba(16, 163, 127, 0.08), rgba(99, 60, 255, 0.06));
        border: 1px solid rgba(16, 163, 127, 0.2);
        border-radius: 12px;
        padding: 14px;
        margin: 6px 0;
        animation: fadeInUp 0.4s ease;
    }
    .stats-card h4 {
        margin: 0 0 8px 0;
        font-size: 14px;
        color: #10a37f;
    }
    .stats-table {
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        font-size: 12px;
    }
    .stats-table th {
        background: rgba(16, 163, 127, 0.12);
        padding: 6px 8px;
        text-align: left;
        font-weight: 600;
        border-bottom: 2px solid rgba(16, 163, 127, 0.3);
    }
    .stats-table th:first-child { border-radius: 8px 0 0 0; }
    .stats-table th:last-child { border-radius: 0 8px 0 0; }
    .stats-table td {
        padding: 5px 8px;
        border-bottom: 1px solid rgba(128, 128, 128, 0.1);
    }
    .stats-table tr:hover td {
        background: rgba(16, 163, 127, 0.05);
    }
    .stats-table tr:last-child td:first-child { border-radius: 0 0 0 8px; }
    .stats-table tr:last-child td:last-child { border-radius: 0 0 8px 0; }

    /* ═══ BALANCE DISPLAY ═══ */
    .balance-card {
        background: linear-gradient(135deg, #10a37f 0%, #0e8a6b 50%, #0d7a5f 100%);
        background-size: 200% 200%;
        animation: gradientShift 4s ease infinite;
        border-radius: 14px;
        padding: 16px;
        color: white;
        text-align: center;
        margin: 8px 0;
    }
    .balance-amount {
        font-size: 28px;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    .balance-label {
        font-size: 12px;
        opacity: 0.85;
        margin-top: 4px;
    }

    /* ═══ THINKING ANIMATION ═══ */
    @keyframes gptSpinPulse {
        0%   { transform: rotate(0deg) scale(0.95); opacity: 0.85; }
        50%  { transform: rotate(180deg) scale(1.06); opacity: 1; }
        100% { transform: rotate(360deg) scale(0.95); opacity: 0.85; }
    }
    @keyframes shimmerSlide {
        0%   { background-position: -220% 0; }
        100% { background-position: 220% 0; }
    }
    @keyframes dotBounce {
        0%, 80%, 100% { transform: translateY(0); opacity: 0.35; }
        40%           { transform: translateY(-4px); opacity: 1; }
    }
    .thinking-card {
        display: inline-flex;
        align-items: center;
        gap: 11px;
        padding: 10px 16px;
        border-radius: 14px;
        background: linear-gradient(
            110deg,
            rgba(16, 163, 127, 0.08) 25%,
            rgba(16, 163, 127, 0.20) 50%,
            rgba(16, 163, 127, 0.08) 75%
        );
        background-size: 220% 100%;
        animation: shimmerSlide 2.1s linear infinite;
        border: 1px solid rgba(16, 163, 127, 0.28);
        margin: 2px 0 6px 0;
    }
    .thinking-logo {
        width: 22px;
        height: 22px;
        animation: gptSpinPulse 2.4s cubic-bezier(0.45, 0.05, 0.55, 0.95) infinite;
        flex-shrink: 0;
    }
    .thinking-label {
        font-size: 14px;
        font-weight: 600;
        color: #0e8a6b;
    }
    .thinking-sub {
        font-size: 12px;
        opacity: 0.78;
        margin-left: 4px;
    }
    .thinking-dots span {
        display: inline-block;
        width: 5px;
        height: 5px;
        margin-left: 3px;
        border-radius: 50%;
        background-color: #10a37f;
        animation: dotBounce 1.3s infinite ease-in-out both;
    }
    .thinking-dots span:nth-child(1) { animation-delay: -0.32s; }
    .thinking-dots span:nth-child(2) { animation-delay: -0.16s; }

    /* ═══ SIDEBAR STYLING ═══ */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(16, 163, 127, 0.03) 0%, transparent 30%);
    }

    /* ═══ PARTICLE BACKGROUND ═══ */
    #particles-bg {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        pointer-events: none;
        z-index: 0;
        overflow: hidden;
    }
    .particle {
        position: absolute;
        width: 3px;
        height: 3px;
        border-radius: 50%;
        background: rgba(16, 163, 127, 0.15);
        animation: floatUp linear infinite;
    }
    @keyframes floatUp {
        0%   { transform: translateY(100vh) rotate(0deg); opacity: 0; }
        10%  { opacity: 0.6; }
        90%  { opacity: 0.3; }
        100% { transform: translateY(-10vh) rotate(360deg); opacity: 0; }
    }

    /* ═══ TAB STYLING ═══ */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        padding: 6px 16px;
        font-size: 13px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# JAVASCRIPT: NÚT SAO CHÉP + HIỆU ỨNG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COPY_JS = """
<script>
// ═══ COPY FUNCTION ═══
function copyToClipboard(text, btnEl) {
    navigator.clipboard.writeText(text).then(() => {
        const origHTML = btnEl.innerHTML;
        btnEl.classList.add('copied');
        btnEl.innerHTML = '<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg> Đã sao chép!';
        setTimeout(() => {
            btnEl.classList.remove('copied');
            btnEl.innerHTML = origHTML;
        }, 2000);
    }).catch(() => {
        // Fallback for older browsers
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.cssText = 'position:fixed;left:-9999px';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        const origHTML = btnEl.innerHTML;
        btnEl.classList.add('copied');
        btnEl.innerHTML = '✓ Đã sao chép!';
        setTimeout(() => { btnEl.classList.remove('copied'); btnEl.innerHTML = origHTML; }, 2000);
    });
}

// ═══ AUTO-ADD CODE COPY BUTTONS ═══
function addCodeCopyButtons() {
    document.querySelectorAll('[data-testid="stChatMessage"] pre').forEach(pre => {
        if (pre.dataset.copyAdded) return;
        pre.dataset.copyAdded = 'true';
        const wrapper = document.createElement('div');
        wrapper.className = 'code-block-wrapper';
        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(pre);
        const btn = document.createElement('button');
        btn.className = 'code-copy-btn';
        btn.innerHTML = '📋 Copy';
        btn.onclick = function(e) {
            e.stopPropagation();
            const code = pre.innerText || pre.textContent;
            copyToClipboard(code, btn);
        };
        wrapper.appendChild(btn);
    });
}

// ═══ PARTICLE BACKGROUND ═══
function createParticles() {
    if (document.getElementById('particles-bg')) return;
    const container = document.createElement('div');
    container.id = 'particles-bg';
    document.body.appendChild(container);
    for (let i = 0; i < 15; i++) {
        const p = document.createElement('div');
        p.className = 'particle';
        p.style.left = Math.random() * 100 + '%';
        p.style.width = p.style.height = (2 + Math.random() * 3) + 'px';
        p.style.animationDuration = (12 + Math.random() * 20) + 's';
        p.style.animationDelay = Math.random() * 15 + 's';
        container.appendChild(p);
    }
}

// ═══ SMOOTH SCROLL ═══
function smoothScrollToBottom() {
    const chatContainer = document.querySelector('[data-testid="stChatMessageContainer"]');
    if (chatContainer) {
        chatContainer.scrollTo({ top: chatContainer.scrollHeight, behavior: 'smooth' });
    }
}

// ═══ INIT ═══
function initEffects() {
    addCodeCopyButtons();
    createParticles();
    smoothScrollToBottom();
}

// Run on load and observe DOM changes
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initEffects);
} else {
    initEffects();
}

const observer = new MutationObserver((mutations) => {
    let shouldUpdate = false;
    for (const m of mutations) {
        if (m.addedNodes.length > 0) { shouldUpdate = true; break; }
    }
    if (shouldUpdate) {
        setTimeout(addCodeCopyButtons, 100);
    }
});
observer.observe(document.body, { childList: true, subtree: true });
</script>
"""

st.markdown(COPY_JS, unsafe_allow_html=True)

st.title("✨ Chat sex premium")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CÁC HẰNG SỐ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

OPENAI_SVG_PATH = (
    "M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818"
    "a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001"
    "A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001"
    "a6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582"
    "a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944z"
    "m-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324"
    "a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464z"
    "M2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685"
    "a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1192 7.2"
    "a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231"
    "l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866"
    "a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742"
    "a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654"
    "l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z"
)

THINKING_LEVELS = {
    "🤖 Tự động": {
        "effort": "auto",
        "desc": "Khuyên dùng — câu hỏi thường trả lời ngay (2-4s), bài khó/ảnh mới suy luận sâu.",
    },
    "⚡ Tức thì": {
        "effort": "low",
        "desc": "Phản hồi siêu nhanh, ít suy nghĩ ngầm nhất — hợp câu hỏi đơn giản.",
    },
    "🚀 Nhanh": {
        "effort": "low",
        "desc": "Tốc độ cao, tiết kiệm token — hợp tra cứu nhanh và hội thoại thường.",
    },
    "⚖️ Trung bình": {
        "effort": "medium",
        "desc": "Cân đối hài hòa giữa tốc độ phản hồi và độ sâu logic.",
    },
    "🧠 high": {
        "effort": "high",
        "desc": "Suy luận kỹ nhiều bước — ổn định nhất cho viết code, giải toán và phân tích.",
    },
    "🔬 xhigh": {
        "effort": "xhigh",
        "desc": "Tư duy chuyên sâu cường độ cao — hợp bài toán hóc búa, kiến trúc hệ thống.",
    },
    "🌌 MAX": {
        "effort": "max",
        "desc": "Mức cao nhất (nếu kênh server báo 503 sẽ tự hạ về high để chạy tiếp).",
    },
}

MODEL_PRICING = {
    "gpt-6.1-sol": {"input": 2.00, "cached": 0.10, "output": 10.00},
    "gpt-6-astra": {"input": 10.00, "cached": 1.00, "output": 50.00},
}

CLIENT_MODES = {
    "Codex CLI (/v1/responses)": {
        "endpoint": "/responses",
        "headers": {
            "User-Agent": "codex_cli_rs/0.114.0 (Windows 10.0.22631; x86_64)",
            "originator": "codex_cli_rs",
            "OpenAI-Beta": "responses=experimental",
        },
    },
    "OpenCode (/v1/chat/completions)": {
        "endpoint": "/chat/completions",
        "headers": {
            "User-Agent": "opencode/1.2.15",
            "X-Title": "OpenCode",
        },
    },
    "ZCode (/v1/chat/completions)": {
        "endpoint": "/chat/completions",
        "headers": {
            "User-Agent": "ZCode/1.0.0",
            "X-Title": "ZCode",
        },
    },
    "Hermes Agent (/v1/chat/completions)": {
        "endpoint": "/chat/completions",
        "headers": {
            "User-Agent": "Hermes-Agent/1.0.0",
            "X-Title": "Hermes Agent",
        },
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UTILITY FUNCTIONS (giữ nguyên từ bản gốc)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@st.cache_resource
def get_shared_http_client() -> httpx.Client:
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=20, keepalive_expiry=120.0)
    timeout = httpx.Timeout(read=180.0, write=60.0, connect=22.0, pool=10.0)
    try:
        transport = httpx.HTTPTransport(local_address="0.0.0.0", limits=limits, retries=1)
        return httpx.Client(transport=transport, timeout=timeout, http2=False, trust_env=True)
    except Exception:
        return httpx.Client(timeout=timeout, limits=limits, http2=False, trust_env=True)


def reset_shared_http_client():
    get_shared_http_client.clear()


@st.cache_data(ttl=300, show_spinner=False)
def fetch_models_cached(base_url: str, api_key: str, mode_name: str) -> list[str]:
    default_models = ["gpt-6.1-sol", "gpt-6-astra"]
    if not api_key.startswith("sk-"):
        return default_models
    try:
        client = get_shared_http_client()
        r = client.get(
            f"{base_url}/models",
            headers=make_headers(api_key, mode_name),
            timeout=10.0,
        )
        if r.status_code == 200:
            fetched = [m["id"] for m in r.json().get("data", []) if "id" in m]
            if fetched:
                return sorted(fetched)
    except Exception:
        pass
    return default_models


def resolve_thinking_effort(level_label: str, user_text: str, has_files: bool) -> str:
    cfg = THINKING_LEVELS.get(level_label, THINKING_LEVELS["🤖 Tự động"])
    if cfg["effort"] != "auto":
        return cfg["effort"]
    text_lower = user_text.lower().strip()
    hard_keywords = (
        "code", "python", "javascript", "lập trình", "sửa lỗi", "debug", "thuật toán",
        "chứng minh", "toán", "tích phân", "xác suất", "kiến trúc", "hệ thống",
        "phân tích sâu", "so sánh chi tiết", "tối ưu", "sql", "api", "contract",
        "ielts", "essay", "viết bài", "dịch thuật",
    )
    if has_files or len(text_lower) > 300 or any(k in text_lower for k in hard_keywords):
        return "high"
    if len(text_lower) < 60:
        return "low"
    return "medium"


def get_chatgpt_svg_data_uri(color_hex: str = "#10a37f") -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{color_hex}">'
        f'<path d="{OPENAI_SVG_PATH}"/></svg>'
    )
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def _svg_arc_to_cubic(x1, y1, rx, ry, phi, fA, fS, x2, y2):
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    rx, ry = abs(rx), abs(ry)
    phi_rad = math.radians(phi % 360)
    cos_p, sin_p = math.cos(phi_rad), math.sin(phi_rad)
    dx2, dy2 = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = cos_p * dx2 + sin_p * dy2
    y1p = -sin_p * dx2 + cos_p * dy2
    lam = (x1p ** 2) / (rx ** 2) + (y1p ** 2) / (ry ** 2)
    if lam > 1:
        s = math.sqrt(lam)
        rx *= s
        ry *= s
    num = max(0.0, (rx ** 2) * (ry ** 2) - (rx ** 2) * (y1p ** 2) - (ry ** 2) * (x1p ** 2))
    den = (rx ** 2) * (y1p ** 2) + (ry ** 2) * (x1p ** 2)
    coef = math.sqrt(num / den) if den != 0 else 0.0
    if fA == fS:
        coef = -coef
    cxp = coef * (rx * y1p) / ry
    cyp = coef * -(ry * x1p) / rx
    cx = cos_p * cxp - sin_p * cyp + (x1 + x2) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (y1 + y2) / 2.0

    def angle(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        len_prod = math.hypot(ux, uy) * math.hypot(vx, vy)
        c = max(-1.0, min(1.0, dot / len_prod)) if len_prod != 0 else 1.0
        ang = math.acos(c)
        return -ang if (ux * vy - uy * vx < 0) else ang

    vx1, vy1 = (x1p - cxp) / rx, (y1p - cyp) / ry
    vx2, vy2 = (-x1p - cxp) / rx, (-y1p - cyp) / ry
    theta1 = angle(1, 0, vx1, vy1)
    dtheta = angle(vx1, vy1, vx2, vy2)
    if not fS and dtheta > 0:
        dtheta -= 2 * math.pi
    elif fS and dtheta < 0:
        dtheta += 2 * math.pi

    segs = max(1, int(math.ceil(abs(dtheta) / (math.pi / 2.0))))
    delta = dtheta / segs
    t = (8.0 / 3.0) * math.sin(delta / 4.0) ** 2 / math.sin(delta / 2.0)

    curves = []
    ang = theta1
    for _ in range(segs):
        ang_next = ang + delta
        c1, s1 = math.cos(ang), math.sin(ang)
        c2, s2 = math.cos(ang_next), math.sin(ang_next)
        p1x, p1y = rx * (c1 - t * s1), ry * (s1 + t * c1)
        p2x, p2y = rx * (c2 + t * s2), ry * (s2 - t * c2)
        ex, ey = rx * c2, ry * s2

        def xform(px, py):
            return (cos_p * px - sin_p * py + cx, sin_p * px + cos_p * py + cy)

        curves.append((xform(p1x, p1y), xform(p2x, p2y), xform(ex, ey)))
        ang = ang_next
    return curves


@st.cache_resource
def build_official_chatgpt_avatar(color_hex: str = "#111111"):
    try:
        import matplotlib.pyplot as plt
        from matplotlib.path import Path
        from matplotlib.patches import PathPatch
        from PIL import Image

        tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", OPENAI_SVG_PATH)
        verts, codes = [], []
        idx, cmd = 0, None
        cx = cy = sx = sy = 0.0

        def next_float():
            nonlocal idx
            val = float(tokens[idx])
            idx += 1
            return val

        while idx < len(tokens):
            if tokens[idx].isalpha():
                cmd = tokens[idx]
                idx += 1
            if cmd in ("M", "m"):
                x, y = next_float(), next_float()
                if cmd == "m":
                    x += cx
                    y += cy
                verts.append((x, y))
                codes.append(Path.MOVETO)
                cx = sx = x
                cy = sy = y
                cmd = "L" if cmd == "M" else "l"
            elif cmd in ("L", "l"):
                x, y = next_float(), next_float()
                if cmd == "l":
                    x += cx
                    y += cy
                verts.append((x, y))
                codes.append(Path.LINETO)
                cx, cy = x, y
            elif cmd in ("H", "h"):
                x = next_float()
                if cmd == "h":
                    x += cx
                verts.append((x, cy))
                codes.append(Path.LINETO)
                cx = x
            elif cmd in ("V", "v"):
                y = next_float()
                if cmd == "v":
                    y += cy
                verts.append((cx, y))
                codes.append(Path.LINETO)
                cy = y
            elif cmd in ("C", "c"):
                x1, y1, x2, y2, x, y = [next_float() for _ in range(6)]
                if cmd == "c":
                    x1 += cx; y1 += cy; x2 += cx; y2 += cy; x += cx; y += cy
                verts.extend([(x1, y1), (x2, y2), (x, y)])
                codes.extend([Path.CURVE4, Path.CURVE4, Path.CURVE4])
                cx, cy = x, y
            elif cmd in ("A", "a"):
                rx, ry, phi, fA, fS, x, y = [next_float() for _ in range(7)]
                if cmd == "a":
                    x += cx; y += cy
                for p1, p2, ep in _svg_arc_to_cubic(cx, cy, rx, ry, phi, int(fA), int(fS), x, y):
                    verts.extend([p1, p2, ep])
                    codes.extend([Path.CURVE4, Path.CURVE4, Path.CURVE4])
                cx, cy = x, y
            elif cmd in ("Z", "z"):
                verts.append((sx, sy))
                codes.append(Path.CLOSEPOLY)
                cx, cy = sx, sy

        fig, ax = plt.subplots(figsize=(1.6, 1.6), dpi=100)
        fig.patch.set_alpha(0.0)
        ax.set_facecolor("none")
        ax.add_patch(PathPatch(Path(verts, codes), facecolor=color_hex, edgecolor="none"))
        ax.set_xlim(-0.5, 24.5)
        ax.set_ylim(24.5, -0.5)
        ax.set_aspect("equal")
        ax.axis("off")
        plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", transparent=True, dpi=100)
        plt.close(fig)
        buf.seek(0)
        return Image.open(buf).convert("RGBA")
    except Exception:
        return "✨"


def save_square_avatar(image_bytes: bytes) -> None:
    try:
        from PIL import Image, ImageOps

        img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = max(0, int((h - side) * 0.25))
        if top + side > h:
            top = (h - side) // 2
        cropped = img.crop((left, top, left + side, top + side)).resize((200, 200), Image.Resampling.LANCZOS)
        cropped.save(AVATAR_FILE, format="JPEG", quality=90)
    except ImportError:
        with open(AVATAR_FILE, "wb") as f:
            f.write(image_bytes)


def get_user_avatar():
    if os.path.exists(AVATAR_FILE):
        return AVATAR_FILE
    return "🧑"


def calculate_cost(model_name: str, usage: dict, multiplier: float) -> tuple[float, int, int, int]:
    rates = MODEL_PRICING["gpt-6.1-sol"]
    for key, val in MODEL_PRICING.items():
        if key in model_name.lower():
            rates = val
            break

    prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
    completion_tokens = usage.get("completion_tokens") or usage.get("output_tokens") or 0

    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    cached_tokens = details.get("cached_tokens", 0) or 0

    regular_input = max(0, prompt_tokens - cached_tokens)
    raw_usd = (
        regular_input * rates["input"]
        + cached_tokens * rates["cached"]
        + completion_tokens * rates["output"]
    ) / 1_000_000

    return raw_usd * multiplier, prompt_tokens, cached_tokens, completion_tokens


def compress_image_to_data_url(raw_bytes: bytes, fallback_mime: str, max_side: int = 1280) -> str:
    try:
        from PIL import Image, ImageOps

        img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw_bytes)))
        if img.mode in ("RGBA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        w, h = img.size
        if max(w, h) > max_side:
            scale = max_side / float(max(w, h))
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85, optimize=True)
        b64 = base64.b64encode(out.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        b64 = base64.b64encode(raw_bytes).decode("utf-8")
        return f"data:{fallback_mime};base64,{b64}"


def parse_uploaded_file(uploaded_file) -> tuple[str, str | None, bytes | None]:
    name = uploaded_file.name
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    raw_bytes = uploaded_file.getvalue()

    if ext in {"png", "jpg", "jpeg", "webp", "gif"}:
        mime = uploaded_file.type or f"image/{'jpeg' if ext == 'jpg' else ext}"
        data_url = compress_image_to_data_url(raw_bytes, mime, max_side=1280)
        return "", data_url, raw_bytes

    if ext == "pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw_bytes))
            text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
            return f"--- Nội dung tệp PDF: {name} ---\n{text}", None, None
        except ImportError:
            return f"[Thiếu thư viện pypdf: chạy `pip install pypdf` để đọc file {name}]", None, None

    if ext == "docx":
        try:
            import docx
            doc = docx.Document(io.BytesIO(raw_bytes))
            text = "\n".join(p.text for p in doc.paragraphs).strip()
            return f"--- Nội dung tệp Word: {name} ---\n{text}", None, None
        except ImportError:
            return f"[Thiếu thư viện python-docx: chạy `pip install python-docx` để đọc file {name}]", None, None

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1", errors="ignore")
    return f"--- Nội dung tệp: {name} ---\n```\n{text}\n```", None, None


def build_chat_payload(
    messages: list, model: str, reasoning_effort: str, stream: bool = True, max_tokens: int | None = None
) -> dict:
    formatted = []
    for m in messages:
        imgs = m.get("image_urls") or []
        txt = m.get("full_text", m.get("display_text", ""))
        if imgs and m["role"] == "user":
            content = [{"type": "text", "text": txt}] + [
                {"type": "image_url", "image_url": {"url": u}} for u in imgs
            ]
        else:
            content = txt
        formatted.append({"role": m["role"], "content": content})

    payload = {
        "model": model,
        "messages": formatted,
        "reasoning_effort": reasoning_effort,
        "stream": stream,
    }
    if max_tokens is not None:
        payload["max_completion_tokens"] = max_tokens
    if stream:
        payload["stream_options"] = {"include_usage": True}
    return payload


def build_responses_payload(
    messages: list, model: str, reasoning_effort: str, stream: bool = True, max_tokens: int | None = None
) -> dict:
    input_items = []
    for m in messages:
        imgs = m.get("image_urls") or []
        txt = m.get("full_text", m.get("display_text", ""))
        if m["role"] == "user":
            content = [{"type": "input_text", "text": txt}] + [
                {"type": "input_image", "image_url": u} for u in imgs
            ]
            input_items.append({"role": "user", "content": content})
        else:
            input_items.append({"role": "assistant", "content": [{"type": "output_text", "text": txt}]})

    payload = {
        "model": model,
        "instructions": "You are a helpful AI assistant. Respond clearly and completely in the user's language.",
        "input": input_items,
        "reasoning": {"effort": reasoning_effort, "summary": "auto"},
        "store": False,
        "stream": stream,
    }
    if max_tokens is not None:
        payload["max_output_tokens"] = max_tokens
    return payload


def make_headers(api_key: str, mode_name: str) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream, application/json",
        "Connection": "keep-alive",
    }
    headers.update(CLIENT_MODES[mode_name]["headers"])
    return headers


def fetch_api_balance(base_url: str, api_key: str) -> dict | None:
    """Lấy số dư tài khoản từ API (nếu hỗ trợ endpoint /dashboard/billing/credit_grants hoặc tương tự)."""
    endpoints_to_try = [
        "/dashboard/billing/credit_grants",
        "/dashboard/billing/subscription",
        "/billing/credit_grants",
    ]
    try:
        client = get_shared_http_client()
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
        }
        for ep in endpoints_to_try:
            try:
                r = client.get(f"{base_url.rstrip('/v1')}{ep}", headers=headers, timeout=8.0)
                if r.status_code == 200:
                    return r.json()
            except Exception:
                continue
    except Exception:
        pass
    return None


def render_copy_buttons(text: str, msg_index: int):
    """Render nút sao chép văn bản và code cho tin nhắn AI."""
    # Extract code blocks
    code_blocks = re.findall(r'```[\w]*\n(.*?)```', text, re.DOTALL)

    escaped_text = text.replace('\\', '\\\\').replace('`', '\\`').replace("'", "\\'").replace('\n', '\\n').replace('\r', '')

    buttons_html = f'''<div class="copy-btn-container">
        <button class="copy-btn" onclick="copyToClipboard(`{escaped_text}`, this)">
            <svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>
            Sao chép văn bản
        </button>'''

    if code_blocks:
        for i, code in enumerate(code_blocks):
            escaped_code = code.strip().replace('\\', '\\\\').replace('`', '\\`').replace("'", "\\'").replace('\n', '\\n').replace('\r', '')
            buttons_html += f'''
        <button class="copy-btn" onclick="copyToClipboard(`{escaped_code}`, this)">
            <svg viewBox="0 0 24 24"><path d="M9.4 16.6L4.8 12l4.6-4.6L8 6l-6 6 6 6 1.4-1.4zm5.2 0l4.6-4.6-4.6-4.6L16 6l6 6-6 6-1.4-1.4z"/></svg>
            Code #{i+1}
        </button>'''

    buttons_html += '</div>'

    st.markdown(buttons_html, unsafe_allow_html=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BẢNG THỐNG KÊ HELPER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_stats_summary(stats: dict) -> dict:
    """Tính tổng hợp thống kê theo tuần, tháng, năm."""
    today = datetime.now()
    daily = stats.get("daily", {})

    # Tuần này (thứ 2 -> CN)
    start_of_week = today - timedelta(days=today.weekday())
    week_tokens = 0
    week_cost = 0.0
    week_messages = 0

    # Tháng này
    start_of_month = today.replace(day=1)
    month_tokens = 0
    month_cost = 0.0
    month_messages = 0

    # Năm này
    start_of_year = today.replace(month=1, day=1)
    year_tokens = 0
    year_cost = 0.0
    year_messages = 0

    for date_str, data in daily.items():
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        tok = data.get("tokens", 0)
        cost = data.get("cost", 0.0)
        msgs = data.get("messages", 0)

        if date >= start_of_week:
            week_tokens += tok
            week_cost += cost
            week_messages += msgs
        if date >= start_of_month:
            month_tokens += tok
            month_cost += cost
            month_messages += msgs
        if date >= start_of_year:
            year_tokens += tok
            year_cost += cost
            year_messages += msgs

    return {
        "week": {"tokens": week_tokens, "cost": week_cost, "messages": week_messages},
        "month": {"tokens": month_tokens, "cost": month_cost, "messages": month_messages},
        "year": {"tokens": year_tokens, "cost": year_cost, "messages": year_messages},
    }


def render_stats_table(stats: dict, period_days: int = 7):
    """Render bảng chi tiết ngày nào dùng bao nhiêu token."""
    daily = stats.get("daily", {})
    today = datetime.now()

    rows = []
    for i in range(period_days):
        date = today - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        data = daily.get(date_str, {})
        rows.append({
            "date": date.strftime("%d/%m/%Y"),
            "day_name": ["T2", "T3", "T4", "T5", "T6", "T7", "CN"][date.weekday()],
            "tokens": data.get("tokens", 0),
            "input": data.get("input_tokens", 0),
            "output": data.get("output_tokens", 0),
            "cost": data.get("cost", 0.0),
            "messages": data.get("messages", 0),
        })

    table_html = '''<div class="stats-card"><table class="stats-table">
        <tr>
            <th>📅 Ngày</th>
            <th>Thứ</th>
            <th>💬</th>
            <th>📥 Input</th>
            <th>📤 Output</th>
            <th>🔢 Tổng Token</th>
            <th>💰 Chi phí</th>
        </tr>'''

    for r in rows:
        highlight = ' style="background:rgba(16,163,127,0.08)"' if r["tokens"] > 0 else ""
        table_html += f'''
        <tr{highlight}>
            <td><strong>{r["date"]}</strong></td>
            <td>{r["day_name"]}</td>
            <td>{r["messages"]}</td>
            <td>{r["input"]:,}</td>
            <td>{r["output"]:,}</td>
            <td><strong>{r["tokens"]:,}</strong></td>
            <td>${r["cost"]:.4f}</td>
        </tr>'''

    table_html += '</table></div>'
    return table_html


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# KHỞI TẠO BỘ NHỚ PHIÊN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_cost" not in st.session_state:
    st.session_state.session_cost = 0.0
if "session_tokens" not in st.session_state:
    st.session_state.session_tokens = 0
if "selected_mode" not in st.session_state:
    st.session_state.selected_mode = "Codex CLI (/v1/responses)"
if "thinking_label" not in st.session_state:
    st.session_state.thinking_label = "🤖 Tự động"
if "current_conv_id" not in st.session_state:
    st.session_state.current_conv_id = datetime.now().strftime("%Y%m%d_%H%M%S")
if "api_balance" not in st.session_state:
    st.session_state.api_balance = None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SIDEBAR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with st.sidebar:
    # ═══ CONVERSATION MANAGEMENT ═══
    st.header("💬 Cuộc hội thoại")

    col_new, col_refresh = st.columns(2)
    with col_new:
        if st.button("➕ Mới", use_container_width=True):
            # Lưu cuộc hội thoại hiện tại trước
            if st.session_state.messages:
                save_conversation(st.session_state.current_conv_id, st.session_state.messages)
            # Tạo cuộc mới
            st.session_state.current_conv_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.session_state.messages = []
            st.session_state.session_cost = 0.0
            st.session_state.session_tokens = 0
            st.rerun()
    with col_refresh:
        if st.button("🔄 Làm mới", use_container_width=True):
            st.rerun()

    # List conversations
    conversations = list_conversations()
    if conversations:
        with st.expander(f"📂 Lịch sử ({len(conversations)} cuộc)", expanded=False):
            for conv in conversations[:20]:
                col_title, col_del = st.columns([4, 1])
                with col_title:
                    is_active = conv["id"] == st.session_state.current_conv_id
                    label = f"{'▶ ' if is_active else ''}{conv['title']}"
                    if st.button(label, key=f"conv_{conv['id']}", use_container_width=True):
                        # Save current first
                        if st.session_state.messages:
                            save_conversation(st.session_state.current_conv_id, st.session_state.messages)
                        # Load selected
                        loaded = load_conversation(conv["id"])
                        if loaded:
                            st.session_state.current_conv_id = conv["id"]
                            st.session_state.messages = loaded.get("messages", [])
                            st.session_state.session_cost = 0.0
                            st.session_state.session_tokens = 0
                            st.rerun()
                with col_del:
                    if st.button("🗑️", key=f"del_{conv['id']}"):
                        delete_conversation(conv["id"])
                        if conv["id"] == st.session_state.current_conv_id:
                            st.session_state.messages = []
                            st.session_state.current_conv_id = datetime.now().strftime("%Y%m%d_%H%M%S")
                        st.rerun()

    st.divider()

    # ═══ AVATAR ═══
    st.header("🖼️ Ảnh đại diện & Logo")
    new_avatar = st.file_uploader(
        "Ảnh đại diện của bạn (tự lưu vĩnh viễn)",
        type=["png", "jpg", "jpeg", "webp"],
        key="avatar_uploader",
    )
    if new_avatar is not None:
        save_square_avatar(new_avatar.getvalue())
        st.success("Đã lưu ảnh đại diện!")

    ai_avatar_choice = st.selectbox(
        "Logo bên ChatGPT (nền trong suốt)",
        options=[
            "ChatGPT Đen chuẩn (Xóa nền)",
            "ChatGPT Xanh ngọc (Xóa nền)",
            "Dùng ảnh của tôi",
        ],
        index=0,
    )

    st.divider()

    # ═══ API CONFIG ═══
    st.header("⚙️ Cấu hình API")
    api_key = st.text_input(
        "API Key",
        value="sk-c2c32ff6b89bb397afe8fae4073a19f9ede34b13c521ad3bf7e1e0dd3612f92c",
        type="password",
    )
    base_url = st.text_input("Base URL", value="https://api.xingchiapi.com/v1").rstrip("/")

    mode_options = list(CLIENT_MODES.keys())
    mode_idx = mode_options.index(st.session_state.selected_mode) if st.session_state.selected_mode in mode_options else 0
    selected_mode = st.selectbox("Chế độ kết nối", options=mode_options, index=mode_idx)
    st.session_state.selected_mode = selected_mode

    available_models = fetch_models_cached(base_url, api_key, selected_mode)
    default_idx = available_models.index("gpt-6.1-sol") if "gpt-6.1-sol" in available_models else 0
    model = st.selectbox("Model", options=available_models, index=default_idx)

    auto_fallback_503 = st.checkbox(
        "🔄 Tự động đổi kênh/model dự phòng khi lỗi 503",
        value=True,
        help="Nếu gpt-6-astra báo 503 (hết slot/bảo trì), tự động chuyển sang cổng khác hoặc gpt-6.1-sol để chạy tiếp.",
    )

    if st.button("⚡ Kiểm tra kết nối nhanh", use_container_width=True):
        found_mode = None
        logs = []
        reset_shared_http_client()
        with st.spinner("Đang kiểm tra kết nối tới server..."):
            client = get_shared_http_client()
            for m_name, cfg in CLIENT_MODES.items():
                url = f"{base_url}{cfg['endpoint']}"
                test_msg = [{"role": "user", "full_text": "Say OK", "display_text": "Say OK"}]
                payload = (
                    build_responses_payload(test_msg, model, "low", stream=False, max_tokens=16)
                    if cfg["endpoint"] == "/responses"
                    else build_chat_payload(test_msg, model, "low", stream=False, max_tokens=16)
                )
                try:
                    resp = client.post(url, headers=make_headers(api_key, m_name), json=payload, timeout=22.0)
                    if resp.status_code == 200:
                        found_mode = m_name
                        logs.append(f"✅ {m_name}: Kết nối thành công!")
                        break
                    else:
                        logs.append(f"❌ {m_name}: HTTP {resp.status_code}")
                except Exception as ex:
                    logs.append(f"⚠️ {m_name}: {ex}")

        if found_mode:
            st.session_state.selected_mode = found_mode
            st.success(f"Đang dùng chế độ tốt nhất: **{found_mode}**")
        else:
            st.error("Không kết nối được:")
            for line in logs:
                st.caption(line)

    level_keys = list(THINKING_LEVELS.keys())
    level_idx = level_keys.index(st.session_state.thinking_label) if st.session_state.thinking_label in level_keys else 0
    chosen_level = st.selectbox(
        "🧠 Cấp độ tư duy (Reasoning)",
        options=level_keys,
        index=level_idx,
        help=THINKING_LEVELS[st.session_state.thinking_label]["desc"],
    )
    st.session_state.thinking_label = chosen_level
    active_level_label = chosen_level
    st.caption(THINKING_LEVELS[active_level_label]["desc"])

    multiplier = st.number_input(
        "Hệ số nhóm giá (Group Multiplier)",
        min_value=0.01,
        max_value=5.0,
        value=0.25,
        step=0.05,
    )

    st.divider()

    # ═══ THỐNG KÊ ═══
    st.header("📊 Thống kê sử dụng")

    # Phiên hiện tại
    st.subheader("💰 Phiên hiện tại")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Chi phí", f"${st.session_state.session_cost:.6f}")
    with col2:
        st.metric("Token", f"{st.session_state.session_tokens:,}")

    # Số dư API
    if st.button("💳 Kiểm tra số dư API", use_container_width=True):
        with st.spinner("Đang kiểm tra..."):
            balance_data = fetch_api_balance(base_url, api_key)
            st.session_state.api_balance = balance_data

    if st.session_state.api_balance:
        bal = st.session_state.api_balance
        total_granted = bal.get("total_granted", bal.get("hard_limit_usd", 0))
        total_used = bal.get("total_used", bal.get("total_usage", 0))
        # Some APIs return in cents
        if isinstance(total_used, (int, float)) and total_used > 1000:
            total_used = total_used / 100.0
        remaining = total_granted - total_used if total_granted else 0
        st.markdown(
            f'''<div class="balance-card">
                <div class="balance-label">💳 Số dư còn lại</div>
                <div class="balance-amount">${remaining:.2f}</div>
                <div class="balance-label">Đã dùng: ${total_used:.2f} / ${total_granted:.2f}</div>
            </div>''',
            unsafe_allow_html=True,
        )

    # Thống kê tổng hợp
    usage_stats = load_usage_stats()

    if usage_stats["total_tokens"] > 0:
        summary = get_stats_summary(usage_stats)

        st.subheader("📈 Tổng hợp")
        st.markdown(
            f'''<div class="stats-card">
                <h4>🌐 Tổng cộng (All time)</h4>
                <p>🔢 <strong>{usage_stats["total_tokens"]:,}</strong> tokens &nbsp;|&nbsp;
                💰 <strong>${usage_stats["total_cost"]:.4f}</strong> &nbsp;|&nbsp;
                💬 <strong>{usage_stats["total_messages"]:,}</strong> tin nhắn</p>
            </div>''',
            unsafe_allow_html=True,
        )

        # Tabs: Tuần / Tháng / Năm
        tab_week, tab_month, tab_year, tab_detail = st.tabs(["📅 Tuần", "📆 Tháng", "📆 Năm", "📋 Chi tiết"])

        with tab_week:
            w = summary["week"]
            st.markdown(
                f'''<div class="stats-card">
                    <h4>📅 Tuần này</h4>
                    <p>🔢 <strong>{w["tokens"]:,}</strong> tokens &nbsp;|&nbsp;
                    💰 <strong>${w["cost"]:.4f}</strong> &nbsp;|&nbsp;
                    💬 <strong>{w["messages"]}</strong> tin nhắn</p>
                </div>''',
                unsafe_allow_html=True,
            )
            st.markdown(render_stats_table(usage_stats, 7), unsafe_allow_html=True)

        with tab_month:
            m = summary["month"]
            st.markdown(
                f'''<div class="stats-card">
                    <h4>📆 Tháng này</h4>
                    <p>🔢 <strong>{m["tokens"]:,}</strong> tokens &nbsp;|&nbsp;
                    💰 <strong>${m["cost"]:.4f}</strong> &nbsp;|&nbsp;
                    💬 <strong>{m["messages"]}</strong> tin nhắn</p>
                </div>''',
                unsafe_allow_html=True,
            )
            st.markdown(render_stats_table(usage_stats, 30), unsafe_allow_html=True)

        with tab_year:
            y = summary["year"]
            st.markdown(
                f'''<div class="stats-card">
                    <h4>📆 Năm {datetime.now().year}</h4>
                    <p>🔢 <strong>{y["tokens"]:,}</strong> tokens &nbsp;|&nbsp;
                    💰 <strong>${y["cost"]:.4f}</strong> &nbsp;|&nbsp;
                    💬 <strong>{y["messages"]}</strong> tin nhắn</p>
                </div>''',
                unsafe_allow_html=True,
            )
            st.markdown(render_stats_table(usage_stats, 90), unsafe_allow_html=True)

        with tab_detail:
            st.markdown("**Chi tiết tất cả ngày có sử dụng:**")
            daily = usage_stats.get("daily", {})
            sorted_days = sorted(daily.keys(), reverse=True)
            detail_html = '''<div class="stats-card"><table class="stats-table">
                <tr>
                    <th>📅 Ngày</th>
                    <th>💬 Tin nhắn</th>
                    <th>📥 Input</th>
                    <th>📤 Output</th>
                    <th>🔢 Tổng</th>
                    <th>💰 Chi phí</th>
                </tr>'''
            for d in sorted_days:
                data = daily[d]
                try:
                    formatted_date = datetime.strptime(d, "%Y-%m-%d").strftime("%d/%m/%Y")
                except ValueError:
                    formatted_date = d
                detail_html += f'''
                <tr>
                    <td><strong>{formatted_date}</strong></td>
                    <td>{data.get("messages", 0)}</td>
                    <td>{data.get("input_tokens", 0):,}</td>
                    <td>{data.get("output_tokens", 0):,}</td>
                    <td><strong>{data.get("tokens", 0):,}</strong></td>
                    <td>${data.get("cost", 0.0):.4f}</td>
                </tr>'''
            detail_html += '</table></div>'
            st.markdown(detail_html, unsafe_allow_html=True)

    st.divider()
    if st.button("🗑️ Xóa lịch sử & Đặt lại bộ đếm", use_container_width=True):
        st.session_state.messages = []
        st.session_state.session_cost = 0.0
        st.session_state.session_tokens = 0
        st.rerun()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHỌN AVATAR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
user_avatar = get_user_avatar()
if ai_avatar_choice == "Dùng ảnh của tôi":
    bot_avatar = user_avatar
elif ai_avatar_choice == "ChatGPT Xanh ngọc (Xóa nền)":
    bot_avatar = build_official_chatgpt_avatar("#10A37F")
else:
    bot_avatar = build_official_chatgpt_avatar("#111111")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HIỂN THỊ LỊCH SỬ CHAT + NÚT SAO CHÉP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
for idx, msg in enumerate(st.session_state.messages):
    role = msg["role"]
    avatar = user_avatar if role == "user" else bot_avatar
    with st.chat_message(role, avatar=avatar):
        if role == "user":
            st.markdown('<span class="user-msg-hook" style="display:none"></span>', unsafe_allow_html=True)
        if msg.get("attached_names"):
            st.caption("📎 Đã đính kèm: " + ", ".join(msg["attached_names"]))
        for img_bytes in msg.get("preview_images", []):
            st.image(img_bytes, width=260)
        if msg.get("reasoning_text"):
            with st.expander("💭 Quá trình tư duy của AI", expanded=False):
                st.markdown(msg["reasoning_text"])
        st.markdown(msg.get("display_text", msg.get("content", "")))

        # ═══ NÚT SAO CHÉP cho tin nhắn AI ═══
        if role == "assistant":
            display_text = msg.get("display_text", msg.get("content", ""))
            if display_text.strip():
                render_copy_buttons(display_text, idx)

        if msg.get("meta"):
            st.caption(msg["meta"])

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Ô NHẬP TIN NHẮN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
user_text = ""
uploaded_files = []
submitted = False

try:
    chat_val = st.chat_input(
        "Nhập câu hỏi hoặc bấm đính kèm file...",
        accept_file="multiple",
    )
    if chat_val and (chat_val.text or chat_val.files):
        submitted = True
        user_text = (chat_val.text or "").strip()
        uploaded_files = list(chat_val.files or [])
except TypeError:
    with st.sidebar:
        uploaded_files = st.file_uploader("📎 Đính kèm file", accept_multiple_files=True) or []
    raw_prompt = st.chat_input("Nhập câu hỏi của bạn...")
    if raw_prompt:
        submitted = True
        user_text = raw_prompt.strip()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# XỬ LÝ GỬI TIN NHẮN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if submitted:
    if not user_text and uploaded_files:
        user_text = "Hãy phân tích và tóm tắt chi tiết nội dung các tệp đính kèm này."

    doc_texts = []
    image_urls = []
    preview_images = []
    attached_names = []

    for f in uploaded_files:
        attached_names.append(f.name)
        text_part, img_url, img_bytes = parse_uploaded_file(f)
        if text_part:
            doc_texts.append(text_part)
        if img_url:
            image_urls.append(img_url)
        if img_bytes:
            preview_images.append(img_bytes)

    full_text = user_text
    if doc_texts:
        full_text = f"{user_text}\n\n" + "\n\n".join(doc_texts)

    st.session_state.messages.append(
        {
            "role": "user",
            "display_text": user_text,
            "full_text": full_text,
            "image_urls": image_urls,
            "attached_names": attached_names,
            "preview_images": preview_images,
        }
    )

    with st.chat_message("user", avatar=user_avatar):
        st.markdown('<span class="user-msg-hook" style="display:none"></span>', unsafe_allow_html=True)
        if attached_names:
            st.caption("📎 Đã đính kèm: " + ", ".join(attached_names))
        for img_bytes in preview_images:
            st.image(img_bytes, width=260)
        st.markdown(user_text)

    effective_effort = resolve_thinking_effort(active_level_label, user_text, bool(uploaded_files))
    active_model = model
    active_mode = selected_mode
    fallback_notice = ""

    thinking_logo_uri = get_chatgpt_svg_data_uri("#10a37f")

    with st.chat_message("assistant", avatar=bot_avatar):
        notice_box = st.empty()
        thinking_box = st.empty()
        reasoning_box = st.empty()
        answer_box = st.empty()
        copy_box = st.empty()

        def render_thinking_banner(elapsed_sec: float, phase: str = "Đang suy nghĩ"):
            thinking_box.markdown(
                f"""
                <div class="thinking-card">
                    <img class="thinking-logo" src="{thinking_logo_uri}" alt="thinking" />
                    <div>
                        <span class="thinking-label">{phase}</span>
                        <span class="thinking-dots"><span></span><span></span><span></span></span>
                        <span class="thinking-sub">({active_model} · {effective_effort} · {elapsed_sec:.1f}s)</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        start_ts = time.time()
        render_thinking_banner(0.0, "Đang gửi & suy nghĩ")

        emitted_answer = ""
        emitted_reasoning = ""
        usage_data = None

        max_attempts = 5
        last_err = None

        for attempt in range(1, max_attempts + 1):
            mode_cfg = CLIENT_MODES[active_mode]
            endpoint_url = f"{base_url}{mode_cfg['endpoint']}"
            req_headers = make_headers(api_key, active_mode)

            if mode_cfg["endpoint"] == "/responses":
                req_payload = build_responses_payload(
                    st.session_state.messages, active_model, effective_effort, stream=True
                )
            else:
                req_payload = build_chat_payload(
                    st.session_state.messages, active_model, effective_effort, stream=True
                )

            try:
                client = get_shared_http_client()
                with client.stream("POST", endpoint_url, headers=req_headers, json=req_payload) as resp:
                    if resp.status_code != 200:
                        err_body = resp.read().decode("utf-8", errors="ignore")
                        raise RuntimeError(f"HTTP {resp.status_code} - {err_body}")

                    for line in resp.iter_lines():
                        elapsed = time.time() - start_ts
                        if not line or not line.startswith("data: "):
                            if not emitted_answer:
                                render_thinking_banner(elapsed, "Đang phân tích & suy luận")
                            continue

                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            obj = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        # 1. Luồng /v1/chat/completions
                        if obj.get("usage"):
                            usage_data = obj["usage"]
                        choices = obj.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta") or {}
                            r_piece = delta.get("reasoning_content") or delta.get("reasoning")
                            if isinstance(r_piece, str) and r_piece:
                                emitted_reasoning += r_piece
                                render_thinking_banner(elapsed, "Đang tư duy từng bước")
                                with reasoning_box.expander("💭 Quá trình tư duy của AI (đang chạy...)", expanded=True):
                                    st.markdown(emitted_reasoning + " ▌")

                            c_piece = delta.get("content")
                            if c_piece:
                                if not emitted_answer:
                                    thinking_box.empty()
                                emitted_answer += c_piece
                                answer_box.markdown(emitted_answer + " ▌")

                        # 2. Luồng /v1/responses (Codex CLI)
                        etype = obj.get("type", "")
                        if etype in (
                            "response.reasoning_summary_text.delta",
                            "response.reasoning_text.delta",
                        ):
                            r_piece = obj.get("delta")
                            if isinstance(r_piece, str) and r_piece:
                                emitted_reasoning += r_piece
                                render_thinking_banner(elapsed, "Đang tổng hợp mạch suy luận")
                                with reasoning_box.expander("💭 Quá trình tư duy của AI (đang chạy...)", expanded=True):
                                    st.markdown(emitted_reasoning + " ▌")

                        elif etype in ("response.output_text.delta", "response.content_part.delta"):
                            piece = obj.get("delta")
                            if isinstance(piece, str) and piece:
                                if not emitted_answer:
                                    thinking_box.empty()
                                emitted_answer += piece
                                answer_box.markdown(emitted_answer + " ▌")

                        elif etype == "response.output_text.done":
                            full_done = obj.get("text") or ""
                            if len(full_done) > len(emitted_answer):
                                thinking_box.empty()
                                emitted_answer = full_done
                                answer_box.markdown(emitted_answer)

                        elif etype == "response.completed":
                            resp_obj = obj.get("response") or {}
                            if resp_obj.get("usage"):
                                usage_data = resp_obj["usage"]
                            for item in resp_obj.get("output") or []:
                                for part in item.get("content") or []:
                                    full_final = part.get("text") or ""
                                    if len(full_final) > len(emitted_answer):
                                        emitted_answer = full_final

                last_err = None
                break

            except Exception as ex:
                last_err = ex
                err_str = str(ex).lower()
                is_503 = "http 503" in err_str
                is_retryable = isinstance(
                    ex, (httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError)
                ) or any(
                    k in err_str
                    for k in ("handshake", "_ssl", "ssl", "timed out", "http 503", "http 502", "http 504", "http 429")
                )

                if is_retryable and not emitted_answer and attempt < max_attempts:
                    if effective_effort in ("max", "xhigh") and (is_503 or "http 400" in err_str):
                        effective_effort = "high"

                    if auto_fallback_503 and is_503 and attempt == 2 and active_mode == "Codex CLI (/v1/responses)":
                        active_mode = "OpenCode (/v1/chat/completions)"
                        fallback_notice = (
                            f"⚠️ Cổng `/v1/responses` của `{active_model}` báo 503 → Đã tự chuyển sang "
                            f"**{active_mode}**."
                        )
                        notice_box.warning(fallback_notice)

                    elif (
                        auto_fallback_503
                        and is_503
                        and attempt >= 3
                        and active_model != "gpt-6.1-sol"
                        and "gpt-6.1-sol" in available_models
                    ):
                        old_model = active_model
                        active_model = "gpt-6.1-sol"
                        active_mode = selected_mode
                        fallback_notice = (
                            f"⚠️ Kênh **`{old_model}`** đang bảo trì/hết slot trên server (503) → "
                            f"Đã tự động chuyển sang **`gpt-6.1-sol`** để tiếp tục."
                        )
                        notice_box.warning(fallback_notice)

                    reset_shared_http_client()
                    render_thinking_banner(
                        time.time() - start_ts,
                        f"Kênh đang bận, tự thử lại ({attempt + 1}/{max_attempts})",
                    )
                    time.sleep(0.6)
                    continue
                break

        thinking_box.empty()
        if last_err is not None and not emitted_answer:
            st.error(
                f"Lỗi gọi API: {last_err}\n\n"
                "💡 **Gợi ý khắc phục nhanh:** Kênh `gpt-6-astra` trên `xingchiapi.com` hiện đang hết slot upstream. "
                "Hãy đổi **Model** ở thanh bên trái sang **`gpt-6.1-sol`** rồi gửi lại."
            )
        else:
            total_sec = time.time() - start_ts

            if emitted_reasoning.strip():
                with reasoning_box.expander(f"✅ Đã suy nghĩ xong trong {total_sec:.1f}s", expanded=False):
                    st.markdown(emitted_reasoning)
            else:
                reasoning_box.empty()

            answer_box.markdown(emitted_answer)

            # ═══ NÚT SAO CHÉP ═══
            if emitted_answer.strip():
                with copy_box:
                    render_copy_buttons(emitted_answer, len(st.session_state.messages))

            in_tok = out_tok = 0
            if usage_data:
                cost, in_tok, cache_tok, out_tok = calculate_cost(active_model, usage_data, multiplier)
                total_tok = in_tok + out_tok
                st.session_state.session_cost += cost
                st.session_state.session_tokens += total_tok

                # ═══ GHI THỐNG KÊ VĨNH VIỄN ═══
                record_usage(total_tok, cost, in_tok, out_tok)

                cache_note = f" (Cache: {cache_tok:,})" if cache_tok > 0 else ""
                meta_info = (
                    f"📊 `{active_model}` ({active_level_label} → `{effective_effort}` · {total_sec:.1f}s) | "
                    f"Input: **{in_tok:,}**{cache_note} · Output: **{out_tok:,}** tokens | "
                    f"Chi phí: **${cost:.6f}** (hệ số {multiplier}x)"
                )
            else:
                meta_info = f"📊 `{active_model}` ({active_level_label} → `{effective_effort}` · {total_sec:.1f}s)"

            st.caption(meta_info)

            if emitted_answer.strip():
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "display_text": emitted_answer,
                        "full_text": emitted_answer,
                        "reasoning_text": emitted_reasoning.strip(),
                        "meta": meta_info,
                    }
                )

                # ═══ TỰ ĐỘNG LƯU CUỘC HỘI THOẠI ═══
                save_conversation(st.session_state.current_conv_id, st.session_state.messages)

            st.rerun()
