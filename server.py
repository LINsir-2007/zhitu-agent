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


SESSIONS = {}


def get_session(sid):
    sid = sid or "default"
    if sid not in SESSIONS:
        SESSIONS[sid] = agent.new_session()
    return SESSIONS[sid]


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
                result = agent.run_chat(sess, body.get("message"))
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
