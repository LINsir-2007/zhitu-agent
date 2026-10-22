#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「职途探照灯」主线 Agent —— 直调 DeepSeek API 可运行版
========================================================
依赖：仅 Python 标准库（urllib / json），无需 pip install。
运行：python agent.py

API Key（二选一，程序不保存任何 Key）：
  1) 环境变量：PowerShell 执行  $env:DEEPSEEK_API_KEY="sk-xxx"
  2) 运行时输入：启动后按提示键入（输入不回显）

知识库：同目录 knowledge_base.json，一日日志/剧本暂为空，填入后工具即返回真实内容。
模型：默认 deepseek-chat，可在下方 MODEL 常量改为 deepseek-reasoner。
"""

import json
import os
import sys
import getpass
import urllib.request
import urllib.error

# 让 Windows 控制台尽量按 UTF-8 处理中文（失败则忽略）
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

DEEPSEEK_BASE = "https://api.deepseek.com"
MODEL = "deepseek-chat"          # 如需推理模型改为 deepseek-reasoner
TEMPERATURE = 0.4
MAX_TOOL_CALLS_PER_TURN = 3

# ---------------------------------------------------------------------------
# 状态机定义
# ---------------------------------------------------------------------------
LEGAL_EDGES = {
    "S0": {"S0", "S1"},
    "S1": {"S1", "S2"},
    "S2": {"S2", "S1", "S3"},    # S2→S1：扫描后仍不聚焦，回退追问
    "S3": {"S3", "S4"},          # S3→S4：跑完剧本，或学生中途明确退出
    "S4": {"S4", "S3", "S5"},    # S4→S3：学生想再体验一次；S4→S5：确认计划，进入任务派发
    "S5": {"S5", "S6"},          # S5 任务派发：逐任务循环；全部完成/学生要求收尾 → S6
    "S6": {"S6", "S2", "S3", "S5"},  # S6 追踪提醒：可回退继续探索或继续实战任务
}

# 工具与目标状态 / 允许来源状态的双向一致性约束
TOOL_TARGET_STATE = {"career_scan": "S2", "scenario": "S3", "dispatch_task": "S5"}
TOOL_ALLOWED_FROM = {
    "career_scan": {"S1", "S2"},
    "scenario": {"S2", "S3"},
    "dispatch_task": {"S4", "S5"},
}

PORTRAIT_FIELDS = {
    "self_portrait_maturity": {"低", "中", "高"},
    "career_interest_direction": {"模糊", "簇状", "聚焦"},
    "exploration_depth": {"未体验", "体验中", "已收敛"},
}
EVIDENCE_DIMENSIONS = {"兴趣", "能力", "价值观"}

SYSTEM_PROMPT = """# 角色
你是「职途探照灯」的主线智能体，一个面向高中生（高一~高二）的对话式生涯探索向导。
你的使命：不急于给学生一个"标准答案"，而是通过有判断的追问，把学生模糊的自我感知逐步转化为可操作的方向；在合适的时机调用工具（职业情报扫描、情境模拟），最终收敛为一份可追踪、可溯源的行动探索计划。

# 人格与语气（知心大姐姐）
你是一位温暖、懂学生、有耐心的"知心大姐姐"。说话方式如下：
- 语气柔和亲切，先共情、再引导：学生说完后，先接住他的感受（如"姐姐懂你""这很正常哦"），再自然地过渡到下一步。
- 多用"呀、哦、呢、啦、哈"等语气词，避免生硬、书面、命令式的表达。
- 可以自称"姐姐"，例如"跟姐姐说说""姐姐先问你一个小问题"。
- 用鼓励代替说教，用"我们一起看看"代替"你应该这样做"。
- 共情与温柔是"调味"，不能冲淡内容：该追问、该判断、该调用工具时依然要照常执行，不能因为温柔就退化成空洞的安慰。

# 硬性约束（违反任何一条都算失败，输出前逐条自检）
1.【禁跳步】画像成熟度未达"中"之前，禁止推荐任何具体职业、禁止罗列职业清单；只能继续追问或呈现"方向簇"。
2.【禁空转】每一轮都必须有明确判断（追问 / 调用扫描 / 进入剧本 / 生成计划），禁止复读学生原话，禁止"好的我明白了"这类无推进的回复。
3.【禁编造】职业信息只能来自工具返回的知识库内容。知识库未提供的细节（薪资、录取分数、就业率、具体公司等）一律禁止编造；确需提及的，必须标注"（合成内容，待从业者验证）"。
4.【禁评价】情境模拟的反馈禁止使用"对/错/好/坏/正确/错误"；只能映射为"你刚才的选择说明你更偏向 X 型工作方式"。
5.【禁失忆】①画像判断必须引用学生原话作为证据；②行动计划的每一条建议必须能追溯到某条对话证据或某次剧本选择。
6.【禁越权】工具只能在指定状态调用：career_scan 只能在 S1 或 S2 调用；scenario 只能在 S2 或 S3 调用；S3 之前禁止输出完整行动计划。
7.【禁代入】永远用"你"称呼学生，保持知心大姐姐的温暖语气：不评判、不贴标签、不说教、不贩卖焦虑。
8.【禁重复追问】连续追问时必须换角度，不得连续两次问同一类问题。

# 状态机
## 状态变量（每轮都要维护最新值）
1. self_portrait_maturity（画像成熟度）：低 / 中 / 高
2. career_interest_direction（兴趣指向）：模糊 / 簇状 / 聚焦
3. exploration_depth（探索深度）：未体验 / 体验中 / 已收敛

## 画像成熟度判据（必须据此判断，禁止随意升级）
- 低：兴趣/能力/价值观三个维度中，有明确证据的维度 ≤1 个。
- 中：≥2 个维度有证据，且兴趣维度已出现方向性（能说出"喜欢分析/喜欢表达/喜欢助人"等取向）。
- 高：≥2 个维度有证据，且兴趣已指向具体职业类别。
- "有效证据"标准：必须引用学生原话（quote 非空），且落在 兴趣/能力/价值观 之一。

## 状态与转移
- S0 破冰与行为证据采集：用具体行为问题采集证据。→ 累计 ≥3 条有效证据进入 S1；若已连续追问 3 轮以上仍未满 3 条，只要有 ≥1 条也可进入 S1（避免卡死）。
- S1 画像构建：追问矛盾点，形成结构化画像。→ 成熟度达到"中"且兴趣指向≠模糊，进入 S2。
- S2 职业簇扫描：调用 career_scan 呈现 3~5 个方向。→ 学生选定一个方向并表达"想试试"进入 S3；若学生看后仍无倾向，回退 S1 继续追问。
- S3 情境模拟：调用 scenario，逐轮呈现一个真实情境 + 一句思考建议，让学生自由表达自己会怎么做（不设选项、不列 ABCD）。→ 学生回答后，用 interpret_hints 温和反馈"你更看重什么、说明偏向哪种工作方式"，不做对错评判。跑完轮数即结束进入 S4；学生中途明确"不想继续"也进入 S4（需记录原因）。
- S4 行动规划：生成可执行、可追踪的高中阶段探索计划。→ 学生确认计划后进入 S5。
- S5 任务派发（实战任务）：调用 dispatch_task，给学生派一个真实世界的小任务，让他去做、再回来汇报。→ 学生汇报后，你解读反馈、再派下一个任务（S5 内循环）；任务全部完成或学生明确想收尾 → 进入 S6。
- S6 追踪与提醒：按时间节点提醒，按反馈调整。→ 可回 S2 / S3 / S5。

## 工具与状态的一致性（强约束）
- 一旦调用 career_scan，本轮 state.to 必须为 S2。
- 一旦调用 scenario，本轮 state.to 必须为 S3。
- 一旦调用 dispatch_task，本轮 state.to 必须为 S5。

## 关键判断规则
- 学生连续两次回答非常模糊（如"不知道""都可以"）→ 不推荐职业，改用更具体的"你最近一次实际做过的事"类行为场景追问。
- 成熟度=中 且 兴趣指向=簇状 → 调用 career_scan 做方向簇扫描，而不是直接给单一职业。
- 学生在剧本中明显排斥某类决策 → 在 S4 行动计划中降低该方向优先级，并说明理由。
- 学生任何时刻明确要求"直接给我答案/职业" → 温和拒绝一次，解释为什么先做两步探索更有效（不反复说教）。
- 任务派发时，一次只派一个任务，等学生汇报后再派下一个；学生汇报含糊时，先追问细节，不要急着下结论。

# 工具（由外部系统执行，你只负责"决定是否调用"并消费返回结果）
## tool: career_scan
- 用途：职业簇扫描，返回若干方向的"一日工作日志"片段
- 参数：{"interest_cluster": "兴趣簇", "count": 3~5}
- 兴趣簇只能从固定词表中选择（任选其一，不要自造）：分析机制型 / 表达创造型 / 助人服务型 / 动手实践型 / 商业经营型
- 可调时机：S1 或 S2
## tool: scenario
- 用途：生成 3~4 轮职业决策剧本，逐轮交互（开放式，不设选择题）
- 参数：{"career": "职业名称", "rounds": 3~4}
- 每轮结构：situation（情境）、question（要思考的问题）、guidance（给学生的思考建议）、interpret_hints（供你解读自由回答的参考）
- 交互方式：呈现 situation 和 guidance，让学生自由回答；学生答完后，依据 interpret_hints 反馈"你更看重 X，说明你偏向 X 型工作方式"，绝不设对错、不列选项
- 可调时机：S2 或 S3
## tool: dispatch_task
- 用途：派发真实世界的生涯探索小任务（实战任务），一次只派一个
- 参数：{"career": "职业名称", "task_index": 从 0 开始的任务序号}
- 每任务结构：title（任务名）、instruction（要做什么）、report（回来后要汇报什么）、interpret_hints（供你解读汇报的参考）
- 交互方式：呈现 instruction，让学生去真实世界完成、再回来汇报；学生汇报后，依据 interpret_hints 解读"他的感受说明什么"，再派下一个任务（task_index 递增）
- 可调时机：S4 或 S5

# 输出要求
每一轮必须且只能输出一个 json 对象，不得输出 json 以外的任何文字。json 结构必须为：
{"thought":"内部判断：一句话说明本轮为何这么做","state":{"from":"本轮开始状态","to":"本轮结束状态"},"portrait":{"self_portrait_maturity":"低|中|高","career_interest_direction":"模糊|簇状|聚焦","exploration_depth":"未体验|体验中|已收敛"},"evidence":[{"quote":"学生原话","dimension":"兴趣|能力|价值观","weight":"强|中|弱"}],"tool_call":null,"reply":"展示给学生的自然语言回复"}
tool_call 不调用填 null；调用填 {"tool":"career_scan","args":{"interest_cluster":"...","count":4}} 或 {"tool":"scenario","args":{"career":"...","rounds":4}}。工具回合 reply 可为一句过渡语。"""


# ---------------------------------------------------------------------------
# 基础工具函数
# ---------------------------------------------------------------------------
def get_api_key():
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    print("未检测到环境变量 DEEPSEEK_API_KEY。")
    key = getpass.getpass("请输入 DeepSeek API Key（输入不回显，按回车确认）: ").strip()
    if not key:
        print("[错误] 未输入 API Key，程序退出。")
        sys.exit(1)
    return key


def call_deepseek(api_key, messages):
    url = DEEPSEEK_BASE + "/chat/completions"
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": TEMPERATURE,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"DeepSeek API 返回 HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络错误，无法连接 DeepSeek API: {e.reason}")
    return body["choices"][0]["message"]["content"]


def extract_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# 状态机硬钳制与证据累积
# ---------------------------------------------------------------------------
def normalize_portrait(raw_portrait, fallback):
    out = dict(fallback)
    if isinstance(raw_portrait, dict):
        for k, allowed in PORTRAIT_FIELDS.items():
            v = raw_portrait.get(k)
            if v in allowed:
                out[k] = v
    return out


def merge_evidence(existing, new_items):
    """证据由 Python 侧累积，按原话去重，只收落在三维度之一的有效证据。"""
    seen = {e["quote"].strip() for e in existing}
    for item in (new_items or []):
        if not isinstance(item, dict):
            continue
        q = (item.get("quote") or "").strip()
        d = item.get("dimension")
        if q and d in EVIDENCE_DIMENSIONS and q not in seen:
            seen.add(q)
            w = item.get("weight")
            existing.append({
                "quote": q,
                "dimension": d,
                "weight": w if w in {"强", "中", "弱"} else "中",
            })
    return existing


def clamp(parsed, prev_state, evidence_count, s0_rounds):
    """硬钳制：强制 from、校验转移边、绑定工具与状态、执行证据门槛。"""
    state = parsed.get("state") if isinstance(parsed.get("state"), dict) else {}
    state["from"] = prev_state
    to = state.get("to")
    if to not in LEGAL_EDGES.get(prev_state, set()):
        to = prev_state

    tool_call = parsed.get("tool_call")
    if isinstance(tool_call, dict) and tool_call.get("tool") in TOOL_TARGET_STATE:
        tool = tool_call["tool"]
        if prev_state in TOOL_ALLOWED_FROM[tool]:
            to = TOOL_TARGET_STATE[tool]   # 工具决定目标状态
        else:
            tool_call = None               # 越权：此状态不允许调用该工具
    else:
        tool_call = None

    if to not in LEGAL_EDGES.get(prev_state, set()):
        to = prev_state
        tool_call = None

    # S0→S1 证据门槛（软门槛：已在 S0 追问满 3 轮则放宽到 ≥1 条）
    if prev_state == "S0" and to == "S1":
        threshold = 3 if s0_rounds < 3 else 1
        if evidence_count < threshold:
            to = "S0"

    state["to"] = to
    parsed["state"] = state
    parsed["tool_call"] = tool_call
    return parsed


# ---------------------------------------------------------------------------
# 知识库与工具执行
# ---------------------------------------------------------------------------
def load_kb():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[警告] 知识库读取失败：{e}", file=sys.stderr)
    return {"careers": []}


def execute_tool(kb, tool_call):
    tool = tool_call.get("tool")
    args = tool_call.get("args") or {}
    careers = kb.get("careers", []) if isinstance(kb, dict) else []

    if tool == "career_scan":
        cluster = args.get("interest_cluster", "")
        try:
            count = int(args.get("count", 4))
        except (TypeError, ValueError):
            count = 4
        matches = [c for c in careers if c.get("interest_cluster") == cluster and c.get("one_day_log")][:count]
        return {
            "tool": "career_scan",
            "interest_cluster": cluster,
            "results": matches,
            "note": "" if matches else "知识库暂无该方向簇的一日日志，请如实告知学生数据正在准备，不要编造职业内容。",
        }
    if tool == "scenario":
        career = args.get("career", "")
        c = next((x for x in careers if x.get("name") == career), None)
        rounds = (c.get("scenario") or {}).get("rounds", []) if c else []
        return {
            "tool": "scenario",
            "career": career,
            "rounds": rounds,
            "note": "" if rounds else "知识库暂无该职业的剧本，请如实告知学生剧本数据正在准备，不要编造剧情。",
        }
    if tool == "dispatch_task":
        career = args.get("career", "")
        c = next((x for x in careers if x.get("name") == career), None)
        tasks = c.get("tasks", []) if c else []
        try:
            idx = int(args.get("task_index", 0))
        except (TypeError, ValueError):
            idx = 0
        if not tasks:
            return {"tool": "dispatch_task", "career": career, "task_index": idx, "task": None,
                    "note": "知识库暂无该职业的实战任务，请如实告知学生任务正在准备，不要编造任务。"}
        idx = max(0, min(idx, len(tasks) - 1))
        return {"tool": "dispatch_task", "career": career, "task_index": idx, "task": tasks[idx],
                "total": len(tasks),
                "note": "" if idx < len(tasks) - 1 else "这是最后一个任务。"}
    return {"tool": tool, "note": "未知工具，忽略本次调用。"}


# ---------------------------------------------------------------------------
# 对话组装
# ---------------------------------------------------------------------------
def _format_evidence(evidence):
    if not evidence:
        return "（暂无）"
    return "\n".join(f'{i}. "{e["quote"]}"（{e["dimension"]}，{e["weight"]}）' for i, e in enumerate(evidence, 1))


def build_user_message(student_text, state):
    return (
        "[系统注入] 当前状态：{s}\n"
        "画像快照：{p}\n"
        "已采集有效证据（共{n}条）：\n{e}\n\n"
        "[学生输入] {t}\n\n"
        "（请按系统要求输出 json 对象）"
    ).format(
        s=state["current"],
        p=json.dumps(state["portrait"], ensure_ascii=False),
        n=len(state["evidence"]),
        e=_format_evidence(state["evidence"]),
        t=student_text,
    )


def tool_result_message(result, state):
    return {"role": "user", "content": (
        "[系统注入] 当前状态：{s}\n"
        "画像快照：{p}\n"
        "已采集有效证据（共{n}条）：\n{e}\n\n"
        "[工具返回结果]（仅可引用以下内容，禁止补充编造）：\n{r}\n\n"
        "[任务] 基于以上结果继续当前回合。若结果中的 note 提示知识库为空，请如实、自然地告诉学生'完整数据正在准备中'，"
        "并引导继续（例如确认他对该方向的直觉、或给出可自行检索的关键词），不要编造具体职业细节。请按系统要求输出 json 对象。"
    ).format(
        s=state["current"],
        p=json.dumps(state["portrait"], ensure_ascii=False),
        n=len(state["evidence"]),
        e=_format_evidence(state["evidence"]),
        r=json.dumps(result, ensure_ascii=False, indent=2),
    )}


# ---------------------------------------------------------------------------
# 单轮执行
# ---------------------------------------------------------------------------
def run_one_turn(api_key, messages, state):
    prev = state["current"]
    content = call_deepseek(api_key, messages)
    parsed = None
    for attempt in range(2):
        try:
            parsed = extract_json(content)
            break
        except Exception:
            if attempt == 0:
                messages.append({"role": "user", "content": "你上一次输出不是合法 json 对象，请严格只输出一个 json 对象，不要任何其他文字。"})
                content = call_deepseek(api_key, messages)
    if parsed is None:
        raise RuntimeError("模型连续两次未输出合法 json，请检查提示词或模型选择。")

    parsed = clamp(parsed, prev, len(state["evidence"]), state["s0_rounds"])

    state["portrait"] = normalize_portrait(parsed.get("portrait"), state["portrait"])
    merge_evidence(state["evidence"], parsed.get("evidence"))
    state["current"] = parsed["state"]["to"]
    if state["current"] == "S0":
        state["s0_rounds"] += 1
    else:
        state["s0_rounds"] = 0
    return parsed


def print_status_line(state):
    p = state["portrait"]
    print(f"[状态] 当前 {state['current']} | 画像 {p['self_portrait_maturity']}/{p['career_interest_direction']}/{p['exploration_depth']} | 证据 {len(state['evidence'])} 条")


# ---------------------------------------------------------------------------
# 共享：会话 / 整轮对话 / 数据来源（供 server.py 与 app.py 复用）
# ---------------------------------------------------------------------------
def load_api_key_env_or_config():
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
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


def new_session():
    return {
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
        "state": {
            "current": "S0",
            "portrait": {"self_portrait_maturity": "低", "career_interest_direction": "模糊", "exploration_depth": "未体验"},
            "evidence": [],
            "s0_rounds": 0,
        },
    }


def _uniq(seq):
    seen, out = set(), []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def collect_datasource(kb, tool, result):
    names = []
    if tool == "career_scan":
        names = [c.get("name") for c in result.get("results", []) if c.get("name")]
    elif tool == "scenario":
        n = result.get("career")
        if n:
            names = [n]
    elif tool == "dispatch_task":
        n = result.get("career")
        if n:
            names = [n]
    sources, confidences = [], []
    careers = kb.get("careers", []) if isinstance(kb, dict) else []
    for name in names:
        for c in careers:
            if c.get("name") == name:
                s = (c.get("source") or "").strip()
                cf = (c.get("confidence") or "").strip()
                if s:
                    sources.append(s)
                if cf:
                    confidences.append(cf)
                break
    return {
        "tool": tool,
        "careers": names,
        "source": "；".join(_uniq(sources)) or "待标注",
        "confidence": "；".join(_uniq(confidences)) or "待标注",
    }


def run_chat(session, text, api_key=None):
    if api_key is None:
        api_key = load_api_key_env_or_config()
    if not api_key:
        return {"error": "服务端未配置 DEEPSEEK_API_KEY。"}

    text = text or "（这是开场，请从 S0 破冰开始）"
    session["messages"].append({"role": "user", "content": build_user_message(text, session["state"])})

    pre_reply = None
    tools_used = []
    reply = None
    datasource = None
    kb = load_kb()

    for _ in range(MAX_TOOL_CALLS_PER_TURN):
        parsed = run_one_turn(api_key, session["messages"], session["state"])
        session["messages"].append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
        if parsed.get("tool_call"):
            tool = parsed["tool_call"].get("tool")
            tools_used.append(tool)
            if pre_reply is None:
                pre_reply = parsed.get("reply") or ""
            result = execute_tool(kb, parsed["tool_call"])
            datasource = collect_datasource(kb, tool, result)
            session["messages"].append(tool_result_message(result, session["state"]))
            continue
        reply = parsed.get("reply") or ""
        break
    else:
        reply = "（本轮工具调用次数过多，请重新描述一下你的想法。）"

    return {
        "reply": reply,
        "pre_reply": pre_reply,
        "tools_used": tools_used,
        "datasource": datasource,
        "status": {
            "state": session["state"]["current"],
            "portrait": session["state"]["portrait"],
            "evidence_count": len(session["state"]["evidence"]),
            "evidence": session["state"]["evidence"],
        },
    }


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------
def main():
    api_key = get_api_key()
    kb = load_kb()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    state = {
        "current": "S0",
        "portrait": {"self_portrait_maturity": "低", "career_interest_direction": "模糊", "exploration_depth": "未体验"},
        "evidence": [],
        "s0_rounds": 0,
    }

    print("=" * 62)
    print("「职途探照灯」主线 Agent 已启动（DeepSeek 直调）")
    print("命令：/quit 或 /exit 退出；/state 查看当前状态")
    print("=" * 62)

    first = True
    while True:
        try:
            if first:
                student_text = ""
                first = False
            else:
                student_text = input("\n学生 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[已退出]")
            break

        if student_text in {"/quit", "/exit"}:
            break
        if student_text == "/state":
            print_status_line(state)
            continue

        messages.append({
            "role": "user",
            "content": build_user_message(student_text or "（这是开场，请从 S0 破冰开始）", state),
        })

        # 工具循环：最多 3 次工具调用
        for _ in range(MAX_TOOL_CALLS_PER_TURN):
            parsed = run_one_turn(api_key, messages, state)
            messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
            print_status_line(state)

            if parsed.get("tool_call"):
                print(f"\n助手 > {parsed.get('reply', '')}")
                result = execute_tool(kb, parsed["tool_call"])
                messages.append(tool_result_message(result, state))
                continue

            print(f"\n助手 > {parsed.get('reply', '')}")
            break
        else:
            print("\n[警告] 单轮工具调用次数超限，已跳过本轮工具。")


if __name__ == "__main__":
    main()
