#!/usr/bin/env python3
# 模型配额停用闸（外派前置检查器）
#
# 背景（2026-11-05 运营者定规）：GLM-5.3-Flash 周限即将耗尽（明天下午恢复），
# 此期间不再使用，统一用 kimi-for-coding 替代。外派通道（tools/wf-offload.sh）
# 在**派发前**查目标机当前在役模型，命中停用清单即 fail-loud 拒绝派发，
# 不静默烧掉额度。
#
# 用法（在目标机上跑）：
#   python3 -I wf-model-hold-check.py --hold <停用清单.json> [--db <model_usage.sqlite>]
#
# 退出码：0 = 未命中停用清单（放行）；3 = 命中（拒绝派发）；2 = 用法/环境错。
# 输出：一行 JSON（provider_id / model_id / held / reason）。
#
# ★ 只读：本件只 open(..., "rb"/sqlite mode=ro) 读，不写任何文件。
import argparse
import json
import os
import sqlite3
import sys


def read_active_model(db_path):
    """读 model_usage 表最近一行的 provider_id / model_id。"""
    if not os.path.exists(db_path):
        return None, None
    try:
        conn = sqlite3.connect("file:" + db_path + "?mode=ro", uri=True)
        try:
            row = conn.execute(
                "select provider_id, model_id from model_usage order by rowid desc limit 1"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None, None
    if not row:
        return None, None
    return row[0], row[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", required=True, help="停用清单 JSON 路径")
    ap.add_argument("--db", default=os.path.expanduser("~/.zcode/cli/db/db.sqlite"))
    args = ap.parse_args()

    try:
        with open(args.hold, "r", encoding="utf-8") as fh:
            hold = json.load(fh)
    except (OSError, ValueError) as exc:
        print(json.dumps({"held": False, "reason": "停用清单不可读：%s" % exc}, ensure_ascii=False))
        return 2

    banned_providers = set(hold.get("banned", {}).get("providers", []) or [])
    banned_models = set(hold.get("banned", {}).get("model_ids", []) or [])

    provider, model = read_active_model(args.db)
    hits = []
    if provider and provider in banned_providers:
        hits.append("provider=%s" % provider)
    if model and model in banned_models:
        hits.append("model=%s" % model)

    out = {
        "provider_id": provider,
        "model_id": model,
        "held": bool(hits),
        "hit": hits,
        "statement": hold.get("statement", ""),
        "replacement": hold.get("replacement", {}).get("model_id", ""),
        "fallback": hold.get("fallback_path", {}).get("rule", ""),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 3 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
