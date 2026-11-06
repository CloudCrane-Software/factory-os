#!/usr/bin/env python3
"""factory-kb-worker.py — 论文抽取改道批的卡面机械辅件（2026-10-31 运营者令：
不再考虑沙箱 agent，m3.1f/glm5.3f 直接经 af-jobs 门户清完剩余论文抽取/验证卡）。

定位
----
门户 HTTP 侧（claim/heartbeat/report）与收割方同款的机械校验（结构 + quote 逐字
回查）都在这里；模型调用（原子抽取 / 独立裁决）在改道批工作流的子代理里。
预检与 sandbox-harvester.validate 逐字一致——回查对象是
kb-seed/sandbox/evidence-cache/<aid>/{abs.md,full.md} 的原文，任何一条 miss
整份会作废，所以这里先拦下来给整改员一轮，拦不住再丢原子，绝不把废报告烧上门户。

子命令（stdout 单 JSON；机械失败也回 JSON ok:false，退出码 0 正常 / 2 失败）：
  quota-ok                                → {ok, go, stale, age_s, mm_pct, wk_pct}
                                           # 2026-11-03 OBS 回头：源读数（quota.json 的 ts）
                                           # 陈旧>600s 或无 ts → go=false（fail-closed）
  board                                   → {ok, cards:[{id,kind}], counts}
  claim <task_id>                         → {ok, claim_token, expires_at, reason?}
  heartbeat <claim_token> <note>          → {ok, reason?}
  post-report <claim_token> <payload_path>→ {ok, resp}
  card <task_id>                          → {ok, kind, problem_md, evidence,
                                             rows?}   # verify 卡附机器 quote_check 行
  validate <kind> <payload_path> <aid_dir> → {ok, reason, quote_miss_ids,
                                             structure_bad, stats}
  finalize-atoms <payload_path> <aid_dir> → {ok, kept, dropped}   # 就地丢 miss 原子
  finalize-verify <payload_path> <rows_json_path> → {ok, patched, unmatched}
                                             # ok:false+exit 2 当未全量覆写
                                             # （unmatched/非对象项→模型自报 qc 残留，
                                             #   RT-E67 对账腿 fail-closed，2026-11-02）

取证据规则（与 sandbox-harvester.fetch_arxiv 同构）：缓存命中即用；未命中经
anolis `curl -sSL` 抓 arxiv.org/abs|html/<aid>，仅 2xx 且非空才落缓存——绝不写
空文件污染收割方缓存（收割方 miss 时不落盘，语义一致）。
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
CACHE = os.path.join(WS, "kb-seed/sandbox/evidence-cache")
SANDBOX = os.path.join(WS, "kb-seed/sandbox")
HELPER_DIR = os.path.join(WS, "kb-seed/factory-worker")
PORTAL = os.environ.get("AF_JOBS_BASE") or "http://gov-host.invalid:8090"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "root@gov-host.invalid"]
KINDS = {"claim", "concept", "procedure", "evidence_record", "failure_pattern", "evaluator"}
VERDICTS = {"uphold", "refute", "unverifiable"}
ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})")
WORKER_NAME = "factory-m31f-worker"
# 源读数（状态观测/quota.json 的 ts）陈旧阈——与 factory-scheduler QUOTA_STALE、
# burn-runner SRC_STALE_S、status-push QUOTA_SRC_STALE_S 同值（600s）；同一环境变量
# FS_QUOTA_STALE_S 可统一调。
QUOTA_STALE_S = 600
try:
    QUOTA_STALE_S = int(os.environ.get("FS_QUOTA_STALE_S", "") or QUOTA_STALE_S)
except (TypeError, ValueError):
    pass


def out(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(code)


def sh(cmd, timeout=120):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def http_post(path, body, timeout=30):
    """POST 一次，连接层瞬断（RemoteDisconnected 等）自动重试一次。"""
    import time as _t
    req = urllib.request.Request(
        PORTAL + path, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    last = {}
    for attempt in (1, 2):
        try:
            r = urllib.request.urlopen(req, timeout=timeout)
            return r.getcode(), json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8"))
            except Exception:
                return e.code, {}
        except Exception as e:
            last = {"error": f"{type(e).__name__}: {e}"}
            if attempt == 1:
                _t.sleep(2)
    return 0, last


def http_get_json(path, timeout=30):
    r = urllib.request.urlopen(PORTAL + path, timeout=timeout)
    return json.loads(r.read().decode("utf-8"))


def fetch_via_anolis(url):
    """anolis curl -L 单发；回 (code, body)。非 2xx 或空体即失败，绝不落缓存。"""
    cmd = SSH + [f"curl -sSL -m 90 -w '\\n__HTTP__%{{http_code}}' {url!r}"]
    code, o, e = sh(cmd, timeout=150)
    if code != 0:
        return None, f"ssh 退出 {code}: {e.strip()[:120]}"
    marker = o.rfind("\n__HTTP__")
    if marker < 0:
        return None, "anolis curl 未带回状态码"
    body, status = o[:marker], o[marker + len("\n__HTTP__"):].strip()
    if not status.startswith("2"):
        return None, f"HTTP {status}"
    if not body.strip():
        return None, "空响应体"
    return body, None


def evidence_for(aid):
    """确保缓存里有 <aid> 的 abs.md/full.md。回 {aid, files:{name:{path,len,sha256,ok}}, errors}。

    与收割方同款：缓存命中优先（收割方将读到同一份字节）；miss 时抓取，
    只有成功才写盘。full.md 常态 404（论文无 HTML 渲染），abs.md 拿到即够用。
    """
    d = os.path.join(CACHE, aid)
    os.makedirs(d, exist_ok=True)
    files, errors = {}, {}
    for name, url in [("abs.md", f"https://arxiv.org/abs/{aid}"),
                      ("full.md", f"https://arxiv.org/html/{aid}")]:
        p = os.path.join(d, name)
        if os.path.exists(p):
            text = open(p, encoding="utf-8", errors="replace").read()
            files[name] = {"path": p, "len": len(text),
                           "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                           "ok": bool(text.strip())}
            continue
        body, err = fetch_via_anolis(url)
        if err is not None:
            errors[name] = err
            continue
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
        files[name] = {"path": p, "len": len(body),
                       "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                       "ok": True}
    return {"aid": aid, "files": files, "errors": errors}


def aid_of(task_id):
    m = ARXIV_ID_RE.search(task_id)
    return m.group(1) if m else None


def kind_of(task_id):
    if task_id.startswith("kb-verify"):
        return "kb-verify"
    if task_id.startswith("kb-atoms"):
        return "kb-atoms"
    return "other"


def evidence_texts(ev):
    """回查用的文本集：与收割方 any(q in t for t in ev_texts.values() if t) 同构。"""
    return {n: open(v["path"], encoding="utf-8", errors="replace").read()
            for n, v in ev["files"].items() if v.get("ok")}


def parse_verify_rows(problem_md):
    """从验证卡 problem.md 的待裁决表解析行。回 [{n, atom_id, quote}]，解析不了则 []。"""
    rows = []
    for ln in problem_md.splitlines():
        if not ln.strip().startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 6 or not cells[0].isdigit():
            continue
        atom_id = cells[1].strip("` ")
        if not atom_id or atom_id in ("atom_id",):
            continue
        quote = cells[5].strip().strip("`")
        rows.append({"n": int(cells[0]), "atom_id": atom_id, "quote": quote})
    return rows


def atom_orig_quotes(card_id):
    """原子正本 quote 表（2026-10-31 RT 审计修复）：卡任务种子 meta.json 记的
    candidates_file JSONL 按 candidate_id 取 source.quote。正本未经卡面表格净化
    （cross-verify._cell 去换行/转义竖线/截 300 字），quote 含换行时卡面行必失真，
    机器真值回查一律优先正本；取不到（老卡无种子/meta 缺键）回 {}，调用方退卡面行。"""
    try:
        meta = json.load(open(os.path.join(SANDBOX, "task-seeds", card_id, "meta.json"),
                              encoding="utf-8"))
        cf = (meta.get("verify") or {}).get("candidates_file")
        if not cf:
            return {}
        quotes = {}
        with open(os.path.join(SANDBOX, cf), encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                cid = r.get("candidate_id") or r.get("atom_id")
                q = ((r.get("source") or {}).get("quote") or "").strip()
                if cid and q:
                    quotes[cid] = q
        return quotes
    except Exception:
        return {}


def cmd_quota_ok():
    """mavis 配额闸探针（消费侧新鲜度纪律，2026-11-03 OBS 回头·派生闸）。

    此前只把 quota.json 的 minimax.go 直接透出（无任何源新鲜度判定）：源读数停写
    （quota-governor 进程死/冻结）时，本命令仍报 go=true → 消费侧按停写前的旧配额
    裁决继续动作。全链唯一的源新鲜度检查在派发侧（factory-scheduler read_quota），
    执行/消费侧三处无一落地——此处补齐：源读数 ts 缺失或年龄 > 阈 → go=false
    （fail-closed，方向与派发侧一致）。"""
    try:
        q = json.load(open(os.path.join(WS, "状态观测/quota.json")))
        mm = q.get("minimax", {})
        ts = q.get("ts") or 0
        age_s = max(0, int((time.time() * 1000 - ts) / 1000)) if ts else None
        stale = (not ts) or (age_s > QUOTA_STALE_S)
        out({"ok": True, "go": bool(mm.get("go")) and not stale,
             "stale": stale, "age_s": age_s,
             "mm_pct": mm.get("five_hour_remaining_pct"), "wk_pct": mm.get("weekly_remaining_pct")})
    except Exception as e:
        out({"ok": False, "reason": f"quota.json 读取失败: {e}"}, 2)


def cmd_board():
    try:
        d = http_get_json("/tasks.json?status=open&limit=1000")
        cards = [{"id": t["task_id"], "kind": kind_of(t["task_id"])}
                 for t in d.get("tasks", []) if kind_of(t["task_id"]) != "other"]
        out({"ok": True, "cards": cards, "counts": d.get("counts", {})})
    except Exception as e:
        out({"ok": False, "reason": f"板面查询失败: {e}"}, 2)


def cmd_claim(task_id):
    code, resp = http_post("/claim", {"task_id": task_id, "sandbox": WORKER_NAME})
    if code == 200 and resp.get("claim_token"):
        out({"ok": True, "claim_token": resp["claim_token"], "expires_at": resp.get("expires_at")})
    reason = resp.get("error") or resp.get("hint") or f"HTTP {code}"
    out({"ok": False, "reason": reason, "status": code})


def cmd_heartbeat(token, note):
    code, resp = http_post("/heartbeat", {"claim_token": token, "note": note[:200]})
    out({"ok": code == 200, "reason": resp.get("error"), "status": code},
        0 if code == 200 else 2)


def cmd_post_report(token, payload_path):
    try:
        payload = json.load(open(payload_path, encoding="utf-8"))
    except Exception as e:
        out({"ok": False, "reason": f"payload 读取失败: {e}"}, 2)
    code, resp = http_post("/report", {"claim_token": token, "payload": payload})
    out({"ok": code == 200, "resp": resp, "status": code}, 0 if code == 200 else 2)


def cmd_card(task_id):
    try:
        problem_md = urllib.request.urlopen(
            f"{PORTAL}/task/{task_id}/problem.md", timeout=30).read().decode("utf-8")
    except Exception as e:
        out({"ok": False, "reason": f"problem.md 拉取失败: {e}"}, 2)
    kind = kind_of(task_id)
    aid = aid_of(task_id)
    if not aid:
        out({"ok": False, "reason": "卡号里解析不出 arXiv id", "problem_md": problem_md[:200]}, 2)
    ev = evidence_for(aid)
    usable = [n for n, v in ev["files"].items() if v.get("ok")]
    if not usable:
        out({"ok": False, "reason": f"证据全缺: {ev['errors']}", "aid": aid}, 2)
    res = {"ok": True, "kind": kind, "aid": aid, "problem_md": problem_md,
           "evidence": ev}
    if kind == "kb-verify":
        texts = evidence_texts(ev)
        orig = atom_orig_quotes(task_id)
        rows = []
        for r in parse_verify_rows(problem_md):
            q = orig.get(r["atom_id"]) or r["quote"]  # 正本优先，卡面行兜底（RT 审计）
            r["quote_check"] = any(q in t for t in texts.values() if t)
            rows.append(r)
        res["rows"] = rows
        if not rows:
            out({"ok": False, "reason": "验证卡待裁决表解析为空", "aid": aid}, 2)
    out(res)


def load_payload(path):
    """读 payload；缺文件/坏 JSON 优雅失败（ok:false）——工作流整改员回路会接手。"""
    if not os.path.isfile(path):
        out({"ok": False, "reason": f"payload 未落盘：{path}（执行员未写文件）"}, 2)
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception as e:
        out({"ok": False, "reason": f"payload JSON 损坏: {e}"}, 2)


def validate_atoms(payload, ev):
    texts = evidence_texts(ev)
    shas = {n: v["sha256"] for n, v in ev["files"].items() if v.get("ok")}
    bad, miss, seen_id, seen_q = [], [], set(), {}
    atoms = payload.get("atoms")
    if not isinstance(atoms, list) or not atoms:
        return {"ok": False, "reason": "payload.atoms 缺失或为空", "structure_bad": [], "quote_miss_ids": []}
    for a in atoms:
        aid_, src = a.get("atom_id"), a.get("source") or {}
        q = (src.get("quote") or "").strip()
        if (not aid_ or a.get("kind") not in KINDS or not (a.get("text") or "").strip()
                or not (src.get("locator") or "").strip()):
            bad.append(f"{aid_}:结构缺件")
            continue
        if aid_ in seen_id:
            bad.append(f"{aid_}:atom_id 重复")
            continue
        seen_id.add(aid_)
        fname = src.get("file")
        if fname not in shas:
            bad.append(f"{aid_}:source.file 不在证据集")
            continue
        if src.get("evidence_sha256") and src["evidence_sha256"] != shas[fname]:
            bad.append(f"{aid_}:evidence_sha256 与证据不符")
            continue
        if not q or len(q) > 240:
            bad.append(f"{aid_}:quote 空或超长")
            continue
        h = hashlib.sha256(q.encode()).hexdigest()[:12]
        seen_q[h] = seen_q.get(h, 0) + 1
        if not any(q in t for t in texts.values()):
            miss.append(aid_)
    ids = {a.get("atom_id") for a in atoms}
    for a in atoms:
        for rel in a.get("relations") or []:
            # 关系项可能是非对象（崩过一次：模型写成数组）——按结构缺件拒收，不崩收割预检
            if not isinstance(rel, dict):
                bad.append(f"{a.get('atom_id')}:relations 含非对象项")
                continue
            to = rel.get("to")
            if to and to not in ids:
                bad.append(f"{a.get('atom_id')}:relations 悬空引用 {to}")
    srcs = payload.get("evidence", {}).get("sources")
    if not isinstance(srcs, list) or not srcs:
        bad.append("evidence.sources 缺失")
    dup = sum(1 for v in seen_q.values() if v > 1)
    ok = not bad and not miss
    return {"ok": ok,
            "reason": "" if ok else ";".join((bad + [f"{m}:quote 回查 miss" for m in miss])[:8]),
            "structure_bad": bad, "quote_miss_ids": miss,
            "stats": {"atoms": len(atoms), "dup_quotes": dup}}


def validate_verify(payload, card_id):
    vs = payload.get("verdicts") or payload.get("verifications")
    if not isinstance(vs, list) or not vs:
        return {"ok": False, "reason": "payload.verdicts 缺失或为空"}
    if payload.get("verify") is not True:
        return {"ok": False, "reason": "payload.verify 必须为 true"}
    if payload.get("card_id") != card_id:
        return {"ok": False, "reason": f"payload.card_id 应为 {card_id}"}
    bad = []
    for i, v in enumerate(vs, 1):
        if not isinstance(v, dict):
            bad.append(f"#{i}:非对象")
            continue
        if not v.get("atom_id") or v.get("verdict") not in VERDICTS:
            bad.append(f"{v.get('atom_id', '#' + str(i))}:verdict 缺或非法")
        if not isinstance(v.get("quote_check"), bool):
            bad.append(f"{v.get('atom_id', '#' + str(i))}:quote_check 非布尔")
        if not (v.get("reason") or "").strip():
            bad.append(f"{v.get('atom_id', '#' + str(i))}:reason 空")
        elif len(v["reason"]) > 200:
            bad.append(f"{v.get('atom_id')}:reason 超长")
    up = sum(1 for v in vs if isinstance(v, dict) and v.get("verdict") == "uphold")
    return {"ok": not bad, "reason": ";".join(bad[:8]),
            "stats": {"verdicts": len(vs), "uphold": up}}


def cmd_validate(kind, payload_path, aid_dir, card_id=""):
    try:
        payload = load_payload(payload_path)
    except Exception as e:
        out({"ok": False, "reason": f"payload 读取失败: {e}"}, 2)
    ev = {"files": {}}
    for name in ("abs.md", "full.md"):
        p = os.path.join(aid_dir, name)
        if os.path.exists(p):
            text = open(p, encoding="utf-8", errors="replace").read()
            ev["files"][name] = {"path": p, "ok": bool(text.strip()),
                                 "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    if kind == "kb-verify":
        out(validate_verify(payload, card_id))
    out(validate_atoms(payload, ev))


def cmd_finalize_atoms(payload_path, aid_dir):
    payload = load_payload(payload_path)
    texts = {}
    for name in ("abs.md", "full.md"):
        p = os.path.join(aid_dir, name)
        if os.path.exists(p):
            texts[name] = open(p, encoding="utf-8", errors="replace").read()
    kept, dropped = [], []
    for a in payload.get("atoms", []):
        q = ((a.get("source") or {}).get("quote") or "").strip()
        if q and any(q in t for t in texts.values()):
            kept.append(a)
        else:
            dropped.append(a.get("atom_id"))
    payload["atoms"] = kept
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    out({"ok": True, "kept": len(kept), "dropped": dropped})


def cmd_finalize_verify(payload_path, card_id):
    """用机器复核值覆写 verdicts[].quote_check（防摆烂条款的机械真值）。

    回查 quote 取原子正本（atom_orig_quotes），卡面行仅兜底：卡面表格经 _cell
    净化（去换行/转义竖线/截断），quote 含换行时卡面行必失真，实测机器假阴性
    52-54%（2026-10-31 RT 审计：667/1245）。
    """
    payload = load_payload(payload_path)
    try:
        problem_md = urllib.request.urlopen(
            f"{PORTAL}/task/{card_id}/problem.md", timeout=30).read().decode("utf-8")
        aid = aid_of(card_id)
        ev = evidence_for(aid)
        texts = evidence_texts(ev)
        orig = atom_orig_quotes(card_id)
        parsed = parse_verify_rows(problem_md)
        rows = {r["atom_id"]: any((orig.get(r["atom_id"]) or r["quote"]) in t
                                  for t in texts.values() if t)
                for r in parsed}
    except Exception as e:
        out({"ok": False, "reason": f"机器行重算失败: {e}"}, 2)
    truth_src = {"orig": sum(1 for r in parsed if r["atom_id"] in orig),
                 "cardface": sum(1 for r in parsed if r["atom_id"] not in orig)}
    patched, unmatched, badd = 0, [], []
    for v in payload.get("verdicts") or payload.get("verifications") or []:
        if not isinstance(v, dict):  # 同族防御：模型偶发写非对象项，拒收不崩
            badd.append(str(v)[:40])
            continue
        if v.get("atom_id") in rows:
            v["quote_check"] = bool(rows[v["atom_id"]])
            patched += 1
        else:
            unmatched.append(v.get("atom_id"))
    payload["verdicts"] = payload.get("verdicts") or payload.get("verifications")
    payload.pop("verifications", None)
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    # RT-E67 对账腿（2026-11-02）：quote_check 是 router 聚合 admit 的唯一机械依据
    # （event-router.py uphold 逐条消费 qc），只有整份 payload 全部经机器覆写
    # （patched == 裁决条数，无 unmatched / 无非对象项）才准 ok:true。原实现
    # unmatched（atom_id 不在卡面表解析集，含卡面表整体解析失败 patched=0 的情形）
    # 照写 payload 仍 ok:true——模型自报 qc 残留原样上门户。fail-closed：未全量
    # 覆写即 ok:false + 退出码 2，执行方消费返回值拦截本卡（改道批工作流同步修）。
    if unmatched or badd:
        out({"ok": False, "patched": patched, "unmatched": unmatched,
             "non_dict": badd, "truth_src": truth_src,
             "reason": ("finalize-verify 未全量覆写（模型自报 quote_check 残留，"
                        f"不得上门户）：unmatched={unmatched[:8]}"
                        f"{'…' if len(unmatched) > 8 else ''} non_dict={len(badd)}")}, 2)
    out({"ok": True, "patched": patched, "unmatched": [], "non_dict": [],
         "truth_src": truth_src})


def main():
    argv = sys.argv[1:]
    if not argv:
        out({"ok": False, "reason": "缺子命令"}, 2)
    cmd, rest = argv[0], argv[1:]
    if cmd == "quota-ok":
        cmd_quota_ok()
    if cmd == "board":
        cmd_board()
    if cmd == "claim" and len(rest) == 1:
        cmd_claim(rest[0])
    if cmd == "heartbeat" and len(rest) >= 1:
        cmd_heartbeat(rest[0], rest[1] if len(rest) > 1 else "working")
    if cmd == "post-report" and len(rest) == 2:
        cmd_post_report(rest[0], rest[1])
    if cmd == "card" and len(rest) == 1:
        cmd_card(rest[0])
    if cmd == "validate" and len(rest) in (3, 4):
        cmd_validate(rest[0], rest[1], rest[2], rest[3] if len(rest) == 4 else "")
    if cmd == "finalize-atoms" and len(rest) == 2:
        cmd_finalize_atoms(rest[0], rest[1])
    if cmd == "finalize-verify" and len(rest) == 2:
        cmd_finalize_verify(rest[0], rest[1])
    out({"ok": False, "reason": f"未知子命令或参数: {cmd} {rest}"}, 2)


if __name__ == "__main__":
    main()
