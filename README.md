# 职途探照灯 Agent（DeepSeek 直调版 · 含网页版）

面向高中生的对话式生涯探索智能体。主线 Agent 维护学生画像状态，按需调用职业情报与情境模拟工具，最终收敛为可追踪的行动计划。

## 一、网页版（本机可点击、可对话）

1. 需要 Python 3.8+（`server.py` 只用标准库，无需 pip install）。
2. 打开 PowerShell 进入本目录：
   ```
   cd zhitu-agent
   python server.py
   ```
   （若 `python` 是微软商店空壳，请装 python.org 的 Python，或用内置 Python：）
   ```
   & "C:\Users\zzz\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" server.py
   ```
3. 浏览器打开：http://127.0.0.1:8787/
4. 配置 API Key（二选一，Key 不会出现在前端）：
   - 方式 A（推荐）：编辑 `config.json`，把 Key 填进 `api_key`，保存后刷新页面即生效。
   - 方式 B：环境变量 `$env:DEEPSEEK_API_KEY="sk-xxx"` 后重启服务。

## 二、云部署（给评委的公网链接）

见 `app.py`（Flask 版）+ `requirements.txt` + `Procfile` + `.gitignore`。以 Render 为例：

1. 把本目录推到 GitHub 仓库（`config.json` 已在 `.gitignore`，不会上传 Key）。
2. 注册 render.com → New → Web Service → 连接该 GitHub 仓库。
3. 启动命令用 `Procfile`（或手动填 `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120`）。
4. 添加环境变量：
   - `DEEPSEEK_API_KEY` = sk-你的key
   - `ACCESS_CODE` = 任意访问码（可选；设置后评委链接需带 `?code=访问码`）
5. Deploy，拿到 `https://xxx.onrender.com`。发给评委；若设了访问码，发 `https://xxx.onrender.com/?code=访问码`。

## 三、命令行版（调试用）

```
python agent.py
```
启动后按提示输入 Key（不回显）。对话中 `/state` 查看状态，`/quit` 退出。

## 四、文件说明

- `server.py`：本地 Web 服务（http.server，仅标准库）
- `app.py`：云部署 Web 服务（Flask）
- `index.html`：聊天前端（含状态外显面板 + 访问码支持）
- `agent.py`：主线 Agent（状态机 + 强约束 prompt + 硬钳制 + 工具调度）
- `knowledge_base.json`：知识库（已含「大学教师（文科）」条目）
- `config.json`：本地 API Key（勿上传，已在 .gitignore）
- `requirements.txt` / `Procfile` / `.gitignore`：云部署配置
- `test_state_machine.py`：状态机逻辑自测

## 五、知识库字段

- `interest_cluster` 固定词表：分析机制型 / 表达创造型 / 助人服务型 / 动手实践型 / 商业经营型
- `confidence`：`已验证` | `合成内容待验证`

## 六、说明

- 默认模型 `deepseek-chat`；改 `agent.py` 里 `MODEL` 可换 `deepseek-reasoner`。
- `server.py` 默认监听 `0.0.0.0`（局域网可访问）；仅本机用可设 `$env:ZHITU_HOST="127.0.0.1"`。
- S5 追踪提醒为静态计划 + 节点文案，不含实时定时推送。
