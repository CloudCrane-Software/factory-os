#!/usr/bin/env python3
"""swev-prep.py — 从 SWE-bench Verified parquet 生成 af-bench swe-v 任务包。

用法: swev-prep.py <parquet> <instance_id...> --out <dir>
产物: <dir>/<iid>.json {instance_id, repo, problem_statement, image, test_patch, eval_script}
镜像命名实证：swebench/sweb.eval.x86_64.<iid 小写、__→_1776_>:latest

D-106（摩擦点②收编）：spec 取数统一经 swev-spec-fetch.py（判官件 guard 外层，
禁裸调 make_test_spec）——无网/挂起环境快败 exit≠0 且信息明确（被拒 URL+补缓存
指引），不再 90-120s 挂死；有网侧默认实呼并顺手写离线缓存（=预热副产物，
判官件 --warm-cache 同语义）。
"""
import json
import sys
from pathlib import Path

import pandas as pd

_SELF = Path(__file__).resolve().parent


def _load_spec_fetch():
    """importlib 载入同目录 swev-spec-fetch.py（取数统一入口，guard 在判官件外层）。"""
    import importlib.util

    p = _SELF / "swev-spec-fetch.py"
    if not p.is_file():
        sys.exit(f"FAIL swev-spec-fetch.py 不在本件同目录（{p}）——取数统一入口缺席")
    spec = importlib.util.spec_from_file_location("swev_spec_fetch", str(p))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["swev_spec_fetch"] = mod
    spec.loader.exec_module(mod)
    return mod


def image_name(iid: str) -> str:
    return f"swebench/sweb.eval.x86_64.{iid.replace('__', '_1776_').lower()}:latest"


def main():
    parquet = sys.argv[1]
    out_dir = sys.argv[sys.argv.index("--out") + 1]
    iids = [a for a in sys.argv[2:] if not a.startswith("--") and a != out_dir]
    df = pd.read_parquet(parquet)
    df = df[df.instance_id.isin(iids)]
    if len(df) != len(iids):
        missing = set(iids) - set(df.instance_id)
        sys.exit(f"parquet 缺 {missing}")

    spec_fetch = _load_spec_fetch()

    import os
    os.makedirs(out_dir, exist_ok=True)
    for _, row in df.iterrows():
        inst = row.to_dict()
        inst["image"] = image_name(inst["instance_id"])
        # D-106：取数统一经判官件 guard（禁裸调）；prep 属有网侧，默认实呼
        # （=判官件 --warm-cache 同语义，顺手写缓存）；无网/挂起→快败归因明确
        spec, info = spec_fetch.fetch_spec(inst, allow_live=True)
        if spec is None:
            sys.exit(f"FAIL make_test_spec 经 guard 未成（{inst['instance_id']}）："
                     f"{info.get('error')}（blocked={info.get('blocked_urls')}）")
        payload = {
            "instance_id": inst["instance_id"],
            "repo": inst["repo"],
            "version": inst["version"],
            "base_commit": inst["base_commit"],
            "problem_statement": inst["problem_statement"],
            "hints_text": inst.get("hints_text") or "",
            "image": image_name(inst["instance_id"]),
            "test_patch": inst["test_patch"],
            "eval_script": spec.eval_script,
            "fail_to_pass": json.loads(inst["FAIL_TO_PASS"]),
            "pass_to_pass": json.loads(inst["PASS_TO_PASS"]),
        }
        path = os.path.join(out_dir, inst["instance_id"] + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print("wrote", path)


if __name__ == "__main__":
    main()
