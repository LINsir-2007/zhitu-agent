#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「职途探照灯」Flask 版 —— 用于云部署（Render / Railway 等）。
本地开发：python app.py
云上启动：gunicorn app:app（见 Procfile）

环境变量：
  - DEEPSEEK_API_KEY：DeepSeek API Key（云上必填）
  - ACCESS_CODE：可选访问码；设置后，评委访问需带 ?code=访问码 或在前端输入（防止陌生人消耗额度）
  - PORT：监听端口（云平台自动注入，本地默认 8787）
"""

import json
import os

from flask import Flask, request, jsonify, send_from_directory

import agent

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
ACCESS_CODE = os.environ.get("ACCESS_CODE", "2026").strip()

SESSIONS = {}


def load_api_key():
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    cfg_path = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            k = (cfg.get("api_key") or "").strip()
            if k:
                return k
        except Exception:
            pass
    return ""


def get_session(sid):
    sid = sid or "default"
    if sid not in SESSIONS:
        SESSIONS[sid] = {
            "messages": [{"role": "system", "content": agent.SYSTEM_PROMPT}],
            "state": {
                "current": "S0",
                "portrait": {"self_portrait_maturity": "低", "career_interest_direction": "模糊", "exploration_depth": "未体验"},
                "evidence": [],
                "s0_rounds": 0,
            },
        }
    return SESSIONS[sid]


def run_chat(session, text):
    api_key = load_api_key()
    if not api_key:
        return {"error": "服务端未配置 DEEPSEEK_API_KEY。"}

    text = text or "（这是开场，请从 S0 破冰开始）"
    session["messages"].append({"role": "user", "content": agent.build_user_message(text, session["state"])})

    pre_reply = None
    tools_used = []
    reply = None
    kb = agent.load_kb()

    for _ in range(agent.MAX_TOOL_CALLS_PER_TURN):
        parsed = agent.run_one_turn(api_key, session["messages"], session["state"])
        session["messages"].append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
        if parsed.get("tool_call"):
            tools_used.append(parsed["tool_call"].get("tool"))
            if pre_reply is None:
                pre_reply = parsed.get("reply") or ""
            result = agent.execute_tool(kb, parsed["tool_call"])
            session["messages"].append(agent.tool_result_message(result, session["state"]))
            continue
        reply = parsed.get("reply") or ""
        break
    else:
        reply = "（本轮工具调用次数过多，请重新描述一下你的想法。）"

    return {
        "reply": reply,
        "pre_reply": pre_reply,
        "tools_used": tools_used,
        "status": {
            "state": session["state"]["current"],
            "portrait": session["state"]["portrait"],
            "evidence_count": len(session["state"]["evidence"]),
            "evidence": session["state"]["evidence"],
        },
    }


def _check_access(body):
    if ACCESS_CODE and (body or {}).get("access_code") != ACCESS_CODE:
        return jsonify({"error": "此链接需要访问码。", "code": "auth_required"}), 401
    return None


@app.route("/")
@app.route("/index.html")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    body = request.get_json(silent=True) or {}
    denied = _check_access(body)
    if denied:
        return denied
    sess = get_session(body.get("session_id"))
    try:
        result = run_chat(sess, body.get("message"))
    except Exception as e:
        result = {"error": f"服务端出错：{e}"}
    return jsonify(result)


@app.route("/api/reset", methods=["POST"])
def api_reset():
    body = request.get_json(silent=True) or {}
    denied = _check_access(body)
    if denied:
        return denied
    SESSIONS.pop(body.get("session_id") or "default", None)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8787")), threaded=True)
