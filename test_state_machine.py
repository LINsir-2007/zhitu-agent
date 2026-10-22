# -*- coding: utf-8 -*-
"""状态机逻辑自测：不联网，仅验证 clamp / merge_evidence / normalize_portrait。"""
import sys, io
sys.path.insert(0, ".")
import agent

fail = 0
def check(name, cond):
    global fail
    if cond:
        print("PASS:", name)
    else:
        print("FAIL:", name)
        fail += 1

# --- clamp：状态转移 ---
# S0→S1 需 >=3 条证据（s0_rounds<3）
r = agent.clamp({"state":{"to":"S1"},"tool_call":None}, "S0", 3, 0)
check("S0->S1 证据足够(3条) 放行", r["state"]["to"] == "S1")
r = agent.clamp({"state":{"to":"S1"},"tool_call":None}, "S0", 1, 0)
check("S0->S1 证据不足(1条) 拦截回落S0", r["state"]["to"] == "S0")
r = agent.clamp({"state":{"to":"S1"},"tool_call":None}, "S0", 1, 3)
check("S0->S1 软门槛(s0>=3轮,1条) 放行", r["state"]["to"] == "S1")

# 非法边 S1->S3 回落
r = agent.clamp({"state":{"to":"S3"},"tool_call":None}, "S1", 5, 0)
check("S1->S3 非法 回落S1", r["state"]["to"] == "S1")

# 工具与状态一致性
r = agent.clamp({"state":{"to":"S1"},"tool_call":{"tool":"career_scan","args":{}}}, "S1", 5, 0)
check("career_scan 强制 to=S2", r["state"]["to"] == "S2" and r["tool_call"] is not None)
r = agent.clamp({"state":{"to":"S0"},"tool_call":{"tool":"scenario","args":{}}}, "S0", 5, 0)
check("S0 调 scenario 越权->tool_call置None", r["tool_call"] is None)

# from 强制等于 prev
r = agent.clamp({"state":{"from":"S5","to":"S1"},"tool_call":None}, "S2", 5, 0)
check("from 被强制改为 prev(S2)", r["state"]["from"] == "S2")

# --- merge_evidence 去重 + 过滤 ---
existing = []
agent.merge_evidence(existing, [{"quote":"我喜欢找规律","dimension":"兴趣","weight":"强"},
                                  {"quote":"我喜欢找规律","dimension":"能力"},
                                  {"quote":"写报告烦","dimension":"能力","weight":"弱"},
                                  {"quote":"","dimension":"兴趣"},
                                  {"quote":"乱入维度","dimension":"健康"}])
check("证据去重+过滤后共2条", len(existing) == 2)
check("默认权重补为'中'", existing[0]["weight"] in {"强","中","弱"})

# --- normalize_portrait ---
fallback = {"self_portrait_maturity":"低","career_interest_direction":"模糊","exploration_depth":"未体验"}
p = agent.normalize_portrait({"self_portrait_maturity":"中","career_interest_direction":"簇状","exploration_depth":"乱七八糟"}, fallback)
check("画像非法值回落为兜底值", p["exploration_depth"] == "未体验" and p["self_portrait_maturity"] == "中")

print("-" * 40)
print("FAIL 总数:", fail)
sys.exit(1 if fail else 0)
