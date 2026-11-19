import base64
import io
import json
import os
import time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
import httpx

app = Flask(__name__)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "chat_data")
CHAT_HISTORY_DIR = os.path.join(DATA_DIR, "conversations")
STATS_FILE = os.path.join(DATA_DIR, "usage_stats.json")
os.makedirs(CHAT_HISTORY_DIR, exist_ok=True)

THINKING_LEVELS = {
    "auto": "🤖 Tự động",
    "low": "⚡ Nhanh",
    "medium": "⚖️ Trung bình",
    "high": "🧠 High",
    "xhigh": "🔬 xHigh",
    "max": "🌌 MAX",
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

_http_client = None


def get_http_client() -> httpx.Client:
    global _http_client
    if _http_client is None:
        limits = httpx.Limits(max_keepalive_connections=10, max_connections=20, keepalive_expiry=120.0)
        timeout = httpx.Timeout(read=180.0, write=60.0, connect=22.0, pool=10.0)
        _http_client = httpx.Client(timeout=timeout, limits=limits, http2=False, trust_env=True)
    return _http_client


def reset_http_client():
    global _http_client
    if _http_client is not None:
        try:
            _http_client.close()
        except Exception:
            pass
    _http_client = None


def load_usage_stats() -> dict:
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"total_tokens": 0, "total_cost": 0.0, "total_messages": 0, "daily": {}}


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


def get_conversation_file(conv_id: str) -> str:
    safe_id = "".join(c for c in conv_id if c.isalnum() or c in ("_", "-"))
    return os.path.join(CHAT_HISTORY_DIR, f"{safe_id}.json")


def _auto_title(messages: list) -> str:
    for m in messages:
        if m.get("role") == "user":
            text = m.get("display_text", m.get("full_text", ""))
            if text:
                return text[:60] + ("..." if len(text) > 60 else "")
    return f"Chat {datetime.now().strftime('%d/%m %H:%M')}"


def save_conversation(conv_id: str, messages: list, title: str = ""):
    data = {
        "id": conv_id,
        "title": title or _auto_title(messages),
        "updated_at": datetime.now().isoformat(),
        "messages": messages,
    }
    with open(get_conversation_file(conv_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_conversation(conv_id: str):
    path = get_conversation_file(conv_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def list_conversations() -> list:
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


def resolve_thinking_effort(effort: str, user_text: str, has_files: bool) -> str:
    if effort != "auto":
        return effort
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


def calculate_cost(model_name: str, usage: dict, multiplier: float):
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


def parse_file_storage(file_storage):
    name = file_storage.filename
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    raw_bytes = file_storage.read()
    if ext in {"png", "jpg", "jpeg", "webp", "gif"}:
        mime = file_storage.mimetype or f"image/{'jpeg' if ext == 'jpg' else ext}"
        return "", compress_image_to_data_url(raw_bytes, mime)
    if ext == "pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw_bytes))
            text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
            return f"--- Nội dung tệp PDF: {name} ---\n{text}", None
        except ImportError:
            return f"[Thiếu pypdf để đọc {name}]", None
    if ext == "docx":
        try:
            import docx
            doc = docx.Document(io.BytesIO(raw_bytes))
            text = "\n".join(p.text for p in doc.paragraphs).strip()
            return f"--- Nội dung tệp Word: {name} ---\n{text}", None
        except ImportError:
            return f"[Thiếu python-docx để đọc {name}]", None
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1", errors="ignore")
    return f"--- Nội dung tệp: {name} ---\n```\n{text}\n```", None


def make_headers(api_key: str, mode_name: str) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream, application/json",
        "Connection": "keep-alive",
    }
    headers.update(CLIENT_MODES[mode_name]["headers"])
    return headers


def build_chat_payload(messages: list, model: str, reasoning_effort: str, stream: bool = True) -> dict:
    formatted = []
    for m in messages:
        imgs = m.get("image_urls") or []
        txt = m.get("full_text", m.get("display_text", ""))
        if imgs and m["role"] == "user":
            content = [{"type": "text", "text": txt}] + [{"type": "image_url", "image_url": {"url": u}} for u in imgs]
        else:
            content = txt
        formatted.append({"role": m["role"], "content": content})
    payload = {
        "model": model,
        "messages": formatted,
        "reasoning_effort": reasoning_effort,
        "stream": stream,
    }
    if stream:
        payload["stream_options"] = {"include_usage": True}
    return payload


def build_responses_payload(messages: list, model: str, reasoning_effort: str, stream: bool = True) -> dict:
    input_items = []
    for m in messages:
        imgs = m.get("image_urls") or []
        txt = m.get("full_text", m.get("display_text", ""))
        if m["role"] == "user":
            content = [{"type": "input_text", "text": txt}] + [{"type": "input_image", "image_url": u} for u in imgs]
            input_items.append({"role": "user", "content": content})
        else:
            input_items.append({"role": "assistant", "content": [{"type": "output_text", "text": txt}]})
    return {
        "model": model,
        "instructions": "You are a helpful AI assistant. Respond clearly and completely in the user's language.",
        "input": input_items,
        "reasoning": {"effort": reasoning_effort, "summary": "auto"},
        "store": False,
        "stream": stream,
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/conversations", methods=["GET"])
def api_list_conversations():
    return jsonify(list_conversations())


@app.route("/api/conversations/<conv_id>", methods=["GET"])
def api_get_conversation(conv_id):
    data = load_conversation(conv_id)
    if not data:
        return jsonify({"id": conv_id, "messages": []})
    return jsonify(data)


@app.route("/api/conversations/<conv_id>", methods=["DELETE"])
def api_delete_conversation(conv_id):
    path = get_conversation_file(conv_id)
    if os.path.exists(path):
        os.remove(path)
    return jsonify({"ok": True})


@app.route("/api/stats", methods=["GET"])
def api_stats():
    return jsonify(load_usage_stats())


@app.route("/api/models", methods=["POST"])
def api_models():
    data = request.json or {}
    base_url = data.get("base_url", "https://api.xingchiapi.com/v1").rstrip("/")
    api_key = data.get("api_key", "")
    mode_name = data.get("mode", "Codex CLI (/v1/responses)")
    default_models = ["gpt-6.1-sol", "gpt-6-astra"]
    try:
        r = get_http_client().get(f"{base_url}/models", headers=make_headers(api_key, mode_name), timeout=10.0)
        if r.status_code == 200:
            fetched = [m["id"] for m in r.json().get("data", []) if "id" in m]
            if fetched:
                return jsonify({"models": sorted(fetched)})
    except Exception:
        pass
    return jsonify({"models": default_models})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    conv_id = request.form.get("conv_id") or datetime.now().strftime("%Y%m%d_%H%M%S")
    user_text = (request.form.get("message") or "").strip()
    api_key = request.form.get("api_key", "")
    base_url = request.form.get("base_url", "https://api.xingchiapi.com/v1").rstrip("/")
    selected_mode = request.form.get("mode", "Codex CLI (/v1/responses)")
    model = request.form.get("model", "gpt-6.1-sol")
    effort_choice = request.form.get("effort", "auto")
    multiplier = float(request.form.get("multiplier", "0.25"))
    auto_fallback = request.form.get("auto_fallback", "true") == "true"
    files = request.files.getlist("files")

    if not user_text and files:
        user_text = "Hãy phân tích và tóm tắt chi tiết nội dung các tệp đính kèm này."

    doc_texts, image_urls, attached_names = [], [], []
    for f in files:
        if f.filename:
            attached_names.append(f.filename)
            t_part, img_url = parse_file_storage(f)
            if t_part:
                doc_texts.append(t_part)
            if img_url:
                image_urls.append(img_url)

    full_text = user_text if not doc_texts else f"{user_text}\n\n" + "\n\n".join(doc_texts)
    conv_data = load_conversation(conv_id)
    messages = conv_data.get("messages", []) if conv_data else []
    messages.append({
        "role": "user",
        "display_text": user_text,
        "full_text": full_text,
        "image_urls": image_urls,
        "attached_names": attached_names,
    })

    effective_effort = resolve_thinking_effort(effort_choice, user_text, bool(files))

    def generate():
        active_model = model
        active_mode = selected_mode
        emitted_answer = ""
        emitted_reasoning = ""
        usage_data = None
        start_ts = time.time()
        last_err = None
        effort = effective_effort

        for attempt in range(1, 6):
            mode_cfg = CLIENT_MODES[active_mode]
            endpoint_url = f"{base_url}{mode_cfg['endpoint']}"
            req_headers = make_headers(api_key, active_mode)
            req_payload = (
                build_responses_payload(messages, active_model, effort, stream=True)
                if mode_cfg["endpoint"] == "/responses"
                else build_chat_payload(messages, active_model, effort, stream=True)
            )
            try:
                client = get_http_client()
                with client.stream("POST", endpoint_url, headers=req_headers, json=req_payload) as resp:
                    if resp.status_code != 200:
                        raise RuntimeError(f"HTTP {resp.status_code} - {resp.read().decode('utf-8', errors='ignore')}")
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            obj = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        if obj.get("usage"):
                            usage_data = obj["usage"]
                        choices = obj.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta") or {}
                            r_piece = delta.get("reasoning_content") or delta.get("reasoning")
                            if isinstance(r_piece, str) and r_piece:
                                emitted_reasoning += r_piece
                                yield f"data: {json.dumps({'type': 'reasoning', 'delta': r_piece})}\n\n"
                            c_piece = delta.get("content")
                            if c_piece:
                                emitted_answer += c_piece
                                yield f"data: {json.dumps({'type': 'content', 'delta': c_piece})}\n\n"

                        etype = obj.get("type", "")
                        if etype in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
                            r_piece = obj.get("delta")
                            if isinstance(r_piece, str) and r_piece:
                                emitted_reasoning += r_piece
                                yield f"data: {json.dumps({'type': 'reasoning', 'delta': r_piece})}\n\n"
                        elif etype in ("response.output_text.delta", "response.content_part.delta"):
                            piece = obj.get("delta")
                            if isinstance(piece, str) and piece:
                                emitted_answer += piece
                                yield f"data: {json.dumps({'type': 'content', 'delta': piece})}\n\n"
                        elif etype == "response.completed":
                            resp_obj = obj.get("response") or {}
                            if resp_obj.get("usage"):
                                usage_data = resp_obj["usage"]
                last_err = None
                break
            except Exception as ex:
                last_err = ex
                err_str = str(ex).lower()
                is_503 = "http 503" in err_str
                if not emitted_answer and attempt < 5:
                    if effort in ("max", "xhigh") and (is_503 or "http 400" in err_str):
                        effort = "high"
                    if auto_fallback and is_503 and attempt == 2 and active_mode == "Codex CLI (/v1/responses)":
                        active_mode = "OpenCode (/v1/chat/completions)"
                        yield f"data: {json.dumps({'type': 'notice', 'text': f'Chuyển sang {active_mode}'})}\n\n"
                    elif auto_fallback and is_503 and attempt >= 3 and active_model != "gpt-6.1-sol":
                        active_model = "gpt-6.1-sol"
                        active_mode = selected_mode
                        yield f"data: {json.dumps({'type': 'notice', 'text': 'Tự chuyển sang gpt-6.1-sol'})}\n\n"
                    reset_http_client()
                    time.sleep(0.6)
                    continue
                break

        if last_err and not emitted_answer:
            yield f"data: {json.dumps({'type': 'error', 'text': str(last_err)})}\n\n"
            return

        total_sec = time.time() - start_ts
        if usage_data:
            cost, in_tok, cache_tok, out_tok = calculate_cost(active_model, usage_data, multiplier)
            record_usage(in_tok + out_tok, cost, in_tok, out_tok)
            meta = f"{active_model} ({effort} · {total_sec:.1f}s) | In: {in_tok:,} · Out: {out_tok:,} | ${cost:.6f}"
        else:
            meta = f"{active_model} ({effort} · {total_sec:.1f}s)"

        messages.append({
            "role": "assistant",
            "display_text": emitted_answer,
            "full_text": emitted_answer,
            "reasoning_text": emitted_reasoning.strip(),
            "meta": meta,
        })
        save_conversation(conv_id, messages)
        yield f"data: {json.dumps({'type': 'done', 'meta': meta, 'conv_id': conv_id})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
