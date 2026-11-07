#!/usr/bin/env python3
"""planner-ab-compare.py —— planner 正轨/影子轨 AB 对照采集器（规划质量一期）

读两轨最近 N 对 run（GitHub Actions API），按 created_at 就近配对，逐对出对照行：
  · LLM 步成败/时延   ← artifact planner-raw.json 的 calls（attempt/http/ms）
  · manifest 有效性   ← artifact manifest-validation.json 的 outcome
  · cards 数          ← manifest-validation.json 的 cards_total/new_cards
  · 候选 diff 摘要    ← 影子 manifest-candidate.json ↔ 正轨 manifest-candidate.json

凭据纪律：PAT 只经 af-github-askpass 现取（不进 argv/不落盘/不回显/不入 artifact）；
api.github.com 直连（不走代理）。零第三方依赖（stdlib only）。

用法：
  python3 -I tools/planner-ab-compare.py [--repo CloudCrane-Software/factory-os]
      [--main-workflow planner] [--shadow-workflow planner-shadow-anolis]
      [--n 12] [--window-min 20] [--md 输出.md] [--json 输出.json]
"""
import argparse
import datetime as dt
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

API = "https://api.github.com"
UA = "factory-os-ab-compare"
ASKPASS_DEFAULT = os.path.join("~", ".local", "bin", "af-github-askpass")


# ---------------------------------------------------------------- 凭据（askpass）
def _askpass_cred(askpass):
    """经 askpass 现取 (user, pat)；值只驻内存，零打印零落盘。"""
    def ask(prompt):
        r = subprocess.run([askpass, prompt], capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            raise SystemExit("askpass 取凭据失败（rc=%s）——检查 %s 与 openBao 可达性"
                             % (r.returncode, askpass))
        return r.stdout.rstrip("\n")
    user = ask("Username for 'https://github.com': ")
    pat = ask("Password for 'https://%s@github.com': " % user)
    return user, pat


class GH:
    def __init__(self, user, pat):
        self._auth = "Bearer " + pat

    def _open(self, req, timeout):
        """带重试的 urlopen（网络抖动：IncompleteRead/URLError/超时，3 次退避）。"""
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.read()
            except urllib.error.HTTPError:
                raise
            except Exception as e:            # IncompleteRead/URLError/timeout…
                last = e
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
        raise SystemExit("网络重试 3 次仍失败：%s: %s" % (type(last).__name__, last))

    def get(self, path):
        req = urllib.request.Request(API + path, method="GET")
        req.add_header("Authorization", self._auth)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", UA)
        try:
            raw = self._open(req, 120)
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read()
            except Exception:
                pass
            raise SystemExit("GitHub API %s → HTTP %s %s"
                             % (path, e.code, body.decode("utf-8", "replace")[:300]))
        return json.loads(raw.decode("utf-8"))

    def get_bytes(self, path):
        """下载二进制（artifact zip）：GitHub 302 到 blob Sas URL——两步走
        （先取 Location、再裸取 blob），禁把 Authorization 头带进 Azure
        （带上即 403/401：SAS 签名不含 Authorization 头）。"""
        req = urllib.request.Request(API + path, method="GET")
        req.add_header("Authorization", self._auth)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", UA)

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(req, timeout=300) as r:
                return r.read()          # 直给（未重定向）
        except urllib.error.HTTPError as e:
            if e.code != 302:
                if e.code == 404:
                    return None
                raise SystemExit("GitHub API %s → HTTP %s" % (path, e.code))
            loc = e.headers.get("Location")
            if not loc:
                raise SystemExit("artifact zip 302 无 Location：%s" % path)
        req2 = urllib.request.Request(loc, method="GET")
        req2.add_header("User-Agent", UA)
        try:
            with urllib.request.urlopen(req2, timeout=300) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise SystemExit("artifact blob 下载失败：HTTP %s" % e.code)


# ---------------------------------------------------------------- 轨发现/列举
def find_workflow(gh, repo, name):
    for wf in gh.get("/repos/%s/actions/workflows?per_page=100" % repo)["workflows"]:
        if wf["name"] == name:
            return wf["id"], wf["state"]
    return None, None


def list_runs(gh, repo, wf_id, want):
    """按 created_at 倒序取前 want 条（翻页到够为止）。"""
    runs, page = [], 1
    while len(runs) < want and page <= 10:
        d = gh.get("/repos/%s/actions/workflows/%s/runs?per_page=100&page=%d"
                   % (repo, wf_id, page))
        runs.extend(d["workflow_runs"])
        if len(d["workflow_runs"]) < 100:
            break
        page += 1
    runs.sort(key=lambda r: r["created_at"], reverse=True)
    return runs[:want]


# ---------------------------------------------------------------- artifact 读数
def parse_ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def run_readings(gh, repo, run):
    """拉 run 的 artifact 包（planner-run-<id>），解析 LLM/manifest 读数。"""
    out = {"run_id": run["id"], "run_number": run["run_number"],
           "created_at": run["created_at"], "conclusion": run.get("conclusion"),
           "event": run.get("event"), "head_sha": (run.get("head_sha") or "")[:8],
           "artifact": None, "llm": None, "manifest": None, "candidate": None,
           "note": None}
    arts = gh.get("/repos/%s/actions/runs/%d/artifacts" % (repo, run["id"]))["artifacts"]
    bundle = next((a for a in arts if a["name"] == "planner-run-%d" % run["id"]), None)
    if bundle is None:
        out["note"] = "artifact 缺场（run 未产包或已过期）"
        return out
    if bundle.get("expired"):
        out["note"] = "artifact 已过期"
        return out
    blob = gh.get_bytes("/repos/%s/actions/artifacts/%d/zip" % (repo, bundle["id"]))
    if blob is None:
        out["note"] = "artifact zip 404"
        return out
    files = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in ("planner-raw.json", "manifest-validation.json",
                     "manifest-candidate.json"):
            try:
                files[name] = json.loads(z.read(name).decode("utf-8"))
            except KeyError:
                files[name] = None
    out["artifact"] = bundle["name"]
    raw = files["planner-raw.json"]
    if raw:
        calls = raw.get("calls") or []
        out["llm"] = {
            "attempts": raw.get("attempts"),
            "calls": len(calls),
            "ok": bool(calls) and all(c.get("http") == 200 for c in calls),
            "ms_total": sum(c.get("ms") or 0 for c in calls),
            "ms_max": max((c.get("ms") or 0 for c in calls), default=0),
            "detail": [{"attempt": c.get("attempt"), "http": c.get("http"),
                        "ms": c.get("ms"), "note": c.get("note"),
                        "finish": c.get("finish_reason")} for c in calls],
        }
    val = files["manifest-validation.json"]
    if val:
        out["manifest"] = {"outcome": val.get("outcome"), "ok": val.get("ok"),
                           "wave": val.get("wave"),
                           "cards_total": val.get("cards_total"),
                           "new_cards": val.get("new_cards"),
                           "errors": len(val.get("errors") or [])}
    out["candidate"] = files["manifest-candidate.json"]
    return out


# ---------------------------------------------------------------- 配对与 diff
def pair_runs(main_runs, shadow_runs, window_min):
    """正轨每条配 created_at 最近的影子 run（窗口内）；一对一贪心（每个影子
    run 至多配一个正轨 run，按 Δt 升序先抢先得），避免影子稀疏时一条影子
    重复配多条正轨。返回 [(main, shadow|None, dt_s|None)]，按正轨新→旧序。"""
    cands = []
    for mi, m in enumerate(main_runs):
        tm = parse_ts(m["created_at"])
        for si, s in enumerate(shadow_runs):
            d = abs((parse_ts(s["created_at"]) - tm).total_seconds())
            if d <= window_min * 60:
                cands.append((d, mi, si))
    cands.sort(key=lambda x: (x[0], x[1], x[2]))
    used_m, used_s, pairs = set(), set(), {}
    for d, mi, si in cands:
        if mi in used_m or si in used_s:
            continue
        used_m.add(mi)
        used_s.add(si)
        pairs[mi] = (si, d)
    return [(m,
             shadow_runs[pairs[i][0]] if i in pairs else None,
             pairs[i][1] if i in pairs else None)
            for i, m in enumerate(main_runs)]


def candidate_diff(sh_cand, main_cand):
    """影子候选 ↔ 正轨产出 的 diff 摘要（紧凑串）。"""
    if not isinstance(sh_cand, dict) or not isinstance(main_cand, dict):
        return "—"
    sw, mw = sh_cand.get("wave"), main_cand.get("wave")
    sc, mc = sh_cand.get("cards") or [], main_cand.get("cards") or []

    def tids(cards):
        return sorted(str(c.get("task_id")) for c in cards if c.get("task_id"))
    st, mt = tids(sc), tids(mc)
    added = sorted(set(st) - set(mt))
    removed = sorted(set(mt) - set(st))
    bits = ["wave %s↔%s%s" % (sw, mw, "" if sw == mw else "（波次不一致）"),
            "cards %d↔%d" % (len(sc), len(mc))]
    if added:
        bits.append("影子独有+%d（%s）" % (len(added), ",".join(added[:4])))
    if removed:
        bits.append("正轨独有+%d（%s）" % (len(removed), ",".join(removed[:4])))
    if not added and not removed and st == mt:
        bits.append("task_id 集一致")
    same_bytes = json.dumps(sh_cand, sort_keys=True, ensure_ascii=False) == \
        json.dumps(main_cand, sort_keys=True, ensure_ascii=False)
    bits.append("逐字节一致" if same_bytes else "内容有差")
    return " · ".join(bits)


def llm_cell(r):
    if not r or not r.get("llm"):
        return "—"
    l = r["llm"]
    if l["ok"]:
        return "%d/%d ok · %dms" % (l["calls"], l["attempts"], l["ms_total"])
    bad = [c for c in l["detail"] if c.get("http") != 200]
    why = bad[0] if bad else {}
    return "%d/%d 败（http=%s %s）· %dms" % (
        l["calls"], l["attempts"], why.get("http"), why.get("note") or "",
        l["ms_total"])


def man_cell(r):
    if not r or not r.get("manifest"):
        return "—"
    m = r["manifest"]
    return "%s · cards=%s new=%s" % (m["outcome"], m["cards_total"], m["new_cards"])


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="planner 正轨/影子轨 AB 对照采集")
    ap.add_argument("--repo", default="CloudCrane-Software/factory-os")
    ap.add_argument("--main-workflow", default="planner")
    ap.add_argument("--shadow-workflow", default="planner-shadow-anolis")
    ap.add_argument("--n", type=int, default=12, help="正轨最近 N 拍（默认 12）")
    ap.add_argument("--window-min", type=int, default=20,
                    help="配对窗口（分钟；按 created_at 就近，默认 20）")
    ap.add_argument("--md", default=None, help="对照表 markdown 输出路径")
    ap.add_argument("--json", default=None, help="结构化 JSON 输出路径")
    ap.add_argument("--askpass", default=os.path.expanduser(ASKPASS_DEFAULT))
    args = ap.parse_args()

    user, pat = _askpass_cred(args.askpass)
    gh = GH(user, pat)

    main_id, main_state = find_workflow(gh, args.repo, args.main_workflow)
    if main_id is None:
        raise SystemExit("正轨工作流 %r 未找到（repo=%s）" % (args.main_workflow, args.repo))
    sh_id, sh_state = find_workflow(gh, args.repo, args.shadow_workflow)
    if sh_id is None:
        print("!! 影子轨工作流 %r 未找到——按「影子未上线」出正轨单边基线" %
              args.shadow_workflow, file=sys.stderr)
        shadow_runs = []
    else:
        shadow_runs = list_runs(gh, args.repo, sh_id, max(args.n * 2, 24))
    main_runs = list_runs(gh, args.repo, main_id, args.n)

    pairs = pair_runs(main_runs, shadow_runs, args.window_min)
    rows = []
    for m, s, dsec in pairs:
        mr = run_readings(gh, args.repo, m)
        sr = run_readings(gh, args.repo, s) if s else None
        rows.append({
            "main": mr, "shadow": sr,
            "pair_dt_s": dsec,
            "diff": candidate_diff((sr or {}).get("candidate"), mr.get("candidate")),
        })

    # ---- 汇总（判据面：成功率差）----
    def rate(rs):
        vals = [r for r in rs if r and r.get("llm")]
        if not vals:
            return None
        return sum(1 for r in vals if r["llm"]["ok"]) / len(vals)

    main_llm = [r["main"] for r in rows]
    sh_llm = [r["shadow"] for r in rows if r["shadow"]]
    summary = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "repo": args.repo,
        "main_workflow": {"name": args.main_workflow, "id": main_id, "state": main_state},
        "shadow_workflow": ({"name": args.shadow_workflow, "id": sh_id, "state": sh_state}
                            if sh_id else None),
        "n_requested": args.n, "pairs": len(rows),
        "paired": sum(1 for r in rows if r["shadow"]),
        "window_min": args.window_min,
        "llm_success_rate": {"main": rate(main_llm), "shadow": rate(sh_llm)},
        "manifest_outcome": {
            "main": [r["main"]["manifest"]["outcome"] if r["main"].get("manifest") else None
                     for r in rows],
            "shadow": [r["shadow"]["manifest"]["outcome"] if r["shadow"] and r["shadow"].get("manifest") else None
                       for r in rows],
        },
    }
    mr_, sr_ = summary["llm_success_rate"]["main"], summary["llm_success_rate"]["shadow"]
    if mr_ is not None and sr_ is not None:
        summary["llm_success_rate"]["delta_pp"] = round((sr_ - mr_) * 100, 1)

    # ---- markdown 对照表 ----
    lines = []
    lines.append("# planner 正轨 × 影子轨 AB 对照（%s）" % summary["generated_at"])
    lines.append("")
    lines.append("- repo=%s · 正轨=%s(id=%s,%s) · 影子轨=%s" % (
        args.repo, args.main_workflow, main_id, main_state,
        ("%s(id=%s,%s)" % (args.shadow_workflow, sh_id, sh_state)) if sh_id else "未上线"))
    lines.append("- 配对口径：created_at 就近，窗口 %d 分钟 · 请求 N=%d · 实际配对 %d 对" % (
        args.window_min, args.n, summary["paired"]))
    lines.append("- 成功率（LLM 步）：正轨 %s · 影子 %s%s" % (
        ("%.0f%%" % (mr_ * 100)) if mr_ is not None else "—",
        ("%.0f%%" % (sr_ * 100)) if sr_ is not None else "—",
        (" · 差 %+.1fpp" % summary["llm_success_rate"]["delta_pp"])
        if "delta_pp" in summary["llm_success_rate"] else ""))
    lines.append("")
    lines.append("| # | 正轨 run | created(UTC) | 结论 | 影子 run | created(UTC) | 结论 | Δt | LLM 正轨 | LLM 影子 | manifest 正轨 | manifest 影子 | 候选 diff 摘要 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        m, s = r["main"], r["shadow"]
        lines.append("| %d | #%s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            i, m["run_number"], m["created_at"].replace("T", " ").replace("Z", ""),
            m["conclusion"] or "…",
            ("#%s" % s["run_number"]) if s else "—",
            s["created_at"].replace("T", " ").replace("Z", "") if s else "—",
            (s["conclusion"] or "…") if s else "—",
            ("%.0fs" % r["pair_dt_s"]) if r["pair_dt_s"] is not None else "—",
            llm_cell(m), llm_cell(s), man_cell(m), man_cell(s), r["diff"]))
    lines.append("")
    for i, r in enumerate(rows, 1):
        for tag, rr in (("正轨", r["main"]), ("影子", r["shadow"])):
            if rr and rr.get("note"):
                lines.append("- 对%d %s #%s：%s" % (i, tag, rr["run_number"], rr["note"]))
    md = "\n".join(lines)
    print(md)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as f:
            f.write(md + "\n")
        print("\n[md 写出] %s" % args.md, file=sys.stderr)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "rows": rows}, f, ensure_ascii=False, indent=1)
        print("[json 写出] %s" % args.json, file=sys.stderr)


if __name__ == "__main__":
    main()
