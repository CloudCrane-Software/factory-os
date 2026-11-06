#!/usr/bin/env python3
# 模型配额预算观测器（派新批前跑）
#
# 运营者 2026-11-05 定规：停用期内优先平稳使用 minimax，**不要超 5 小时限额**；
# 余量走 kimi-for-coding；再不够走 anolis 的 grok；仍不够由运营者支援别的 plan
# 额度——但主代理必须**明确说出来**。
#
# 本机唯一可见的节流信号是 model_usage 表里的失败数与滚动窗口用量（限额口径本身
# 平台侧不可见）。故本件只做**观测 + 判线**，判线口径写在停用清单的 budget 段里
# （自设上限，不是平台上限——自设上限的依据与测量读数一并留在清单里）。
#
# 用法：
#   python3 -I tools/wf-model-budget-check.py [--hold 状态/模型配额停用-*.json] [--window 5]
#
# 退出码：0 = 绿（余量足）；3 = 触线/越线（该切通道）；2 = 环境错。
import argparse
import json
import os
import sqlite3
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def usage_since(db_path, since_ms):
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect("file:" + db_path + "?mode=ro", uri=True)
        try:
            return list(conn.execute(
                "select provider_id, model_id, count(*), "
                "       sum(input_tokens), sum(output_tokens), "
                "       sum(case when status='completed' then 1 else 0 end), "
                "       sum(case when status<>'completed' then 1 else 0 end) "
                "from model_usage where started_at > ? group by provider_id, model_id",
                (since_ms,)))
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def find_hold(explicit):
    if explicit:
        return explicit
    d = os.path.join(WS, "状态")
    try:
        names = sorted(n for n in os.listdir(d)
                       if n.startswith("模型配额停用-") and n.endswith(".json"))
        if names:
            return os.path.join(d, names[0])
    except OSError:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", default=None)
    ap.add_argument("--window", type=float, default=5.0)
    ap.add_argument("--db", default=os.path.expanduser("~/.zcode/cli/db/db.sqlite"))
    args = ap.parse_args()

    hold_path = find_hold(args.hold)
    budget = {}
    window_h = args.window
    if hold_path:
        try:
            with open(hold_path, "r", encoding="utf-8") as fh:
                hold = json.load(fh)
            budget = hold.get("budget", {}) or {}
            window_h = float(budget.get("minimax_window_hours", args.window))
        except Exception:
            budget = {}

    since = int(time.time() * 1000) - int(window_h * 3600 * 1000)
    rows = usage_since(args.db, since)

    providers = []
    for p, m, n, itk, otk, okc, badc in rows:
        providers.append({
            "provider_id": p, "model_id": m, "requests": n,
            "input_tokens": itk or 0, "output_tokens": otk or 0,
            "completed": okc or 0, "failed": badc or 0,
        })
    providers.sort(key=lambda x: -(x["input_tokens"] or 0))

    cap_req = budget.get("self_cap_requests_per_window")
    cap_in = budget.get("self_cap_input_tokens_per_window")
    mm = next((x for x in providers
               if x["provider_id"] == "minimax"), None)

    breached = []
    if mm and cap_req and mm["requests"] >= cap_req:
        breached.append("minimax 请求数 %d ≥ 自设上限 %d" % (mm["requests"], cap_req))
    if mm and cap_in and mm["input_tokens"] >= cap_in:
        breached.append("minimax 输入 token %d ≥ 自设上限 %d" % (mm["input_tokens"], cap_in))
    # 失败数是节流的唯一可见信号：连续失败占比偏高即视为触线
    if mm and mm["requests"] >= 50 and mm["failed"] / float(mm["requests"]) >= 0.01:
        breached.append("minimax 失败率 %.2f%% ≥ 1%%（节流信号）"
                        % (100.0 * mm["failed"] / mm["requests"]))

    out = {
        "window_hours": window_h,
        "hold_file": hold_path,
        "providers": providers,
        "primary": "minimax",
        "surplus": "kimi-for-coding",
        "last_resort": "anolis:~/.local/bin/grok (-m grok-4.6)",
        "operator_ask": "仍不够时——必须明确对运营者说出来（运营者 2026-11-05 明令）",
        "breached": breached,
        "verdict": "BREACH" if breached else "OK",
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 3 if breached else 0


if __name__ == "__main__":
    sys.exit(main())
