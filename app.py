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


def get_session(sid):
    sid = sid or "default"
    if sid not in SESSIONS:
        SESSIONS[sid] = agent.new_session()
    return SESSIONS[sid]


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
        result = agent.run_chat(sess, body.get("message"))
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
