#!/usr/bin/env python3
"""swev-prep.py — 从 SWE-bench Verified parquet 生成 af-bench swe-v 任务包。

用法: swev-prep.py <parquet> <instance_id...> --out <dir>
产物: <dir>/<iid>.json {instance_id, repo, problem_statement, image, test_patch, eval_script}
镜像命名实证：swebench/sweb.eval.x86_64.<iid 小写、__→_1776_>:latest
"""
import json
import sys

import pandas as pd


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

    from swebench.harness.test_spec.test_spec import make_test_spec

    import os
    os.makedirs(out_dir, exist_ok=True)
    for _, row in df.iterrows():
        inst = row.to_dict()
        inst["image"] = image_name(inst["instance_id"])
        spec = make_test_spec(inst)
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
