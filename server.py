#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「职途探照灯」Web 服务：本地起一个可点击、可对话的主线 Agent 页面。
运行：python server.py   （默认 http://127.0.0.1:8787/）
API Key：优先读环境变量 DEEPSEEK_API_KEY，否则读同目录 config.json 的 api_key 字段。
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import agent

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(HERE, "index.html")
CONFIG_PATH = os.path.join(HERE, "config.json")
PORT = int(os.environ.get("ZHITU_PORT", "8787"))
HOST = os.environ.get("ZHITU_HOST", "0.0.0.0")


def load_api_key():
    """每次请求都重新读取，方便你把 Key 填进 config.json 后直接刷新页面即可生效。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            k = (cfg.get("api_key") or "").strip()
            if k:
                return k
        except Exception:
            pass
    return ""


class Session:
    def __init__(self):
        self.messages = [{"role": "system", "content": agent.SYSTEM_PROMPT}]
        self.state = {
            "current": "S0",
            "portrait": {"self_portrait_maturity": "低", "career_interest_direction": "模糊", "exploration_depth": "未体验"},
            "evidence": [],
            "s0_rounds": 0,
        }


SESSIONS = {}


def get_session(sid):
    sid = sid or "default"
    if sid not in SESSIONS:
        SESSIONS[sid] = Session()
    return SESSIONS[sid]


def run_chat(session, text):
    api_key = load_api_key()
    if not api_key:
        return {
            "error": "尚未配置 DeepSeek API Key：请打开 zhitu-agent/config.json，把你的 Key 填进 api_key 字段（本机文件，不会上传），然后刷新页面重试。"
        }

    text = text or "（这是开场，请从 S0 破冰开始）"
    session.messages.append({"role": "user", "content": agent.build_user_message(text, session.state)})

    pre_reply = None
    tools_used = []
    reply = None
    kb = agent.load_kb()

    for _ in range(agent.MAX_TOOL_CALLS_PER_TURN):
        parsed = agent.run_one_turn(api_key, session.messages, session.state)
        session.messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
        if parsed.get("tool_call"):
            tools_used.append(parsed["tool_call"].get("tool"))
            if pre_reply is None:
                pre_reply = parsed.get("reply") or ""
            result = agent.execute_tool(kb, parsed["tool_call"])
            session.messages.append(agent.tool_result_message(result, session.state))
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
            "state": session.state["current"],
            "portrait": session.state["portrait"],
            "evidence_count": len(session.state["evidence"]),
            "evidence": session.state["evidence"],
        },
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                with open(INDEX_PATH, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except Exception as e:
                self._send(500, f"读取 index.html 失败: {e}", "text/plain; charset=utf-8")
        else:
            self._send(404, "Not Found", "text/plain; charset=utf-8")

    def do_POST(self):
        if self.path == "/api/chat":
            body = self._read_json()
            sess = get_session(body.get("session_id"))
            try:
                result = run_chat(sess, body.get("message"))
            except Exception as e:
                result = {"error": f"服务端出错：{e}"}
            self._send(200, json.dumps(result, ensure_ascii=False))
        elif self.path == "/api/reset":
            body = self._read_json()
            SESSIONS.pop(body.get("session_id") or "default", None)
            self._send(200, json.dumps({"ok": True}, ensure_ascii=False))
        else:
            self._send(404, "Not Found", "text/plain; charset=utf-8")


def main():
    print("=" * 60)
    print("职途探照灯 Web 服务启动")
    print(f"请在浏览器打开：http://{HOST}:{PORT}/")
    print(f"API Key 来源：环境变量 DEEPSEEK_API_KEY，或 {CONFIG_PATH}")
    print("按 Ctrl+C 停止服务")
    print("=" * 60)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止服务")


if __name__ == "__main__":
    main()
