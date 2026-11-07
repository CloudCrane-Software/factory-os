#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""judge-deploy-recon-gate.py — 判官件部署面对账门（Q10 修·2026-11-07 红队门首考批）。

【为什么建本门（首考读数：证伪不了·按不过）】
  判官件 swev-judge-v2.py 的部署面长期只有「记录面」、没有「对账门」：
    · anolis 上 swev-judge-cache 的判官件实测 3f958c92（旧版 D-32），而仓内现役权威件
      为 4a7156dd（D-32＋A6 版）——判分链真实漂移在场，无任何一门能红；
    · 判分缓存 tasks/*.verify.json 记有 judge_sha256＋eval_script_sha256（记录面由
      swev-spec-fetch.py 写、swev-warm-relay.sh 落盘），但判分前无硬校验——记录面被
      污染（篡改 judge_sha256 / eval_script_sha256）时判分链照跑。
  本门把这两面变成机器对账：部署面逐路径 sha256 对账＋注册表完备性＋缓存记录面
  「双 sha」硬校验。判官件 swev-judge-v2.py 本体零改动（本门只读，铁律）。

【注册表（单一源）】
  .github/docs/judge-paths.md 的 `judge-deploy-registry` 机读段（begin/end 围栏内的
  表格）：每行 = 行号｜部署路径｜状态｜期望 sha256｜语义。状态两值：
    · active           ＝ 判分链此刻可载入的部署面；实测 sha256 必须 ≡ 期望值；
                        位于扫描根内而缺席 ⇒ 红（部署面被删）。
    · historical-frozen＝ 已收卷 bench 的历史 run 工件；字节冻结（实测 ≠ 登记 sha
                        ⇒ 红＝历史工件被改），不得用于新判分。
  路径为绝对路径（各机部署面）或仓内相对路径（相对 factory-os 仓根，--fos-root 解析）。
  期望 sha 变更唯一正路＝运营者裁决→同批改判据后重钉（与 gate-pins 同纪律）；本表
  只增不减（新增部署面/历史归档逐路径登记；删行＝缩小对账面，视同改判据）。

【三腿判据】
  leg-L1 部署面对账：active 行实测 sha256 ≡ 期望（不符/扫描根内缺席 ⇒ 红）；
    historical-frozen 行实测 sha256 ≡ 登记值（不符 ⇒ 红：历史工件字节被改）。
    行路径不在本机（跨机注册表）⇒ 记 INFO 不判（存在则仍验 sha）。
  leg-L2 注册表完备性：--scan-root 下全部 swev-judge-v2.py 拷贝必须逐一命中注册表
    （注册表外拷贝 ⇒ 红）。扫描根可配置；anolis 巡检扫 /data/bench（判官件调包/私搭
    拷贝的发现面）。pre-judge 模式不跑本腿（判分机只验部署面，完备性归巡检）。
  leg-L3 记录面双 sha 硬校验（--cache-dir 时）：
    · 配对：tasks/*.json ↔ tasks/*.verify.json 双向配对（单边 ⇒ 红：记录面缺件/
      孤儿记录，判分链不得消费未配对 spec）。
    · judge_sha256：必须 ∈ 注册表已知 sha 集（active 期望 ∪ historical 登记值）
      ⇒ 否则红（记录面被污染/引用了未登记判官版本）。
    · eval_script_sha256：必须为 64 位小写 hex ⇒ 否则红。
    · spec_ok 必须 true、source 必须 cache、live_http 必须空 ⇒ 否则红（离线 hermetic
      语义破：缓存内的 spec 记录不得自称实呼取数）。
    · --deep 时加跑内容复算（--fetch-python 提供带 swebench 的解释器）：逐 task 离线
      重跑 swev-spec-fetch.py（零外呼，--out 落临时件），复算 eval_script_sha256 与
      记录值对账（不符 ⇒ 红：spec 内容与记录面脱节）；复跑不可用（缺件/缓存未命中/
      执行错）⇒ 不可证（fail-closed，不猜绿）。--deep 未给 ⇒ 本复算记 SKIP。

【退出码（三态，与 ledger-face-recon-gate 同语义）】
  0=绿 / 1=红（逐条点名）/ 2=不可证（缺件/坏件 fail-closed，不猜绿）。

【正式升版 runbook（判官件版本推进时同批执行，禁跳步）】
  ① 仓内 tools/swev-judge-v2.py 换版＋judge-paths.md 注册表 active 期望 sha 同批重钉
    （走有意变更判官路径唯一正路：运营者裁决→@feasy898 审批合入）；
  ② 各 active 部署面对齐（cp 仓内权威件；本门 L1 转绿）；
  ③ 缓存记录面刷新：逐 task 重跑取数件重写 verify.json（`<py> <cache>/swev-spec-fetch.py
    --quiet --out <cache>/tasks/<iid>.verify.json <cache>/tasks/<iid>.json`）——旧版
    sha 退场后未刷新的记录会被 L3 判红（记录面引用了未登记版本），此步是升版闭环件；
  ④ 本门全绿留读数。

用法:
  judge-deploy-recon-gate.py [--registry F] [--fos-root D] [--scan-root D ...]
                             [--cache-dir D] [--fetch-python P] [--deep]
                             [--pre-judge] [--selftest]
  --pre-judge：cb-run 判分步起手模式（L1＋L3，不跑 L2；输出 PREJUDGE 结论行）。
  注册表查找序：--registry ＞ 环境变量 JUDGE_PATHS_MD ＞ --fos-root 的兄弟
  .github/docs/judge-paths.md ＞ 门本体上溯祖先的兄弟 .github/docs/judge-paths.md；
  全不中 ⇒ 不可证（fail-closed）。

本巡检只读：不改任何判官件/注册表/缓存记录/判据件；--deep 的复跑输出落系统临时目录。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

JUDGE_NAME = "swev-judge-v2.py"
REG_BEGIN = "<!-- judge-deploy-registry:begin -->"
REG_END = "<!-- judge-deploy-registry:end -->"
ROW_RE = re.compile(r"^(J|H)(\d+)$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ACTIVE = "active"
FROZEN = "historical-frozen"


# ---------------------------------------------------------------- 小工具

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def norm_path(p):
    return os.path.normpath(os.path.abspath(os.path.expanduser(p)))


def under(root, p):
    """p 是否位于 root 之内（含 root 本身）。"""
    root = norm_path(root)
    p = norm_path(p)
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


def read_text(p):
    return Path(p).read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 注册表解析

def parse_registry(reg_path):
    """解析 judge-paths.md 的 judge-deploy-registry 段。

    返回 (rows, errors)：rows=[{id,path,status,sha,note}]；errors 非空 ⇒ 注册表坏
    （调用方按不可证处置）。
    """
    errors = []
    rows = []
    if not reg_path or not os.path.isfile(reg_path):
        return None, ["注册表缺席：%s" % reg_path]
    text = read_text(reg_path)
    if REG_BEGIN not in text or REG_END not in text:
        return None, ["注册表机读段缺失（%s..%s 围栏不在 %s）" % (REG_BEGIN, REG_END, reg_path)]
    seg = text.split(REG_BEGIN, 1)[1].split(REG_END, 1)[0]
    seen_ids, seen_paths = set(), set()
    for ln, line in enumerate(seg.splitlines(), 1):
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 5:
            continue                       # 表头/分隔行（＜5 格）跳过
        rid, path, status, sha = cells[0], cells[1], cells[2], cells[3]
        note = cells[4] if len(cells) > 4 else ""
        if not ROW_RE.match(rid):
            continue                       # 非登记行（表头等）
        if rid in seen_ids:
            errors.append("注册表行号重复：%s" % rid)
            continue
        seen_ids.add(rid)
        if not path:
            errors.append("注册表 %s 路径为空" % rid)
            continue
        if status not in (ACTIVE, FROZEN):
            errors.append("注册表 %s 状态非法：%r（须 %s/%s）" % (rid, status, ACTIVE, FROZEN))
            continue
        if not SHA_RE.match(sha):
            errors.append("注册表 %s 期望 sha 非法：%r（须 64 位小写 hex）" % (rid, sha))
            continue
        if path in seen_paths:
            errors.append("注册表路径重复登记：%s（%s）" % (rid, path))
            continue
        seen_paths.add(path)
        rows.append({"id": rid, "path": path, "status": status, "sha": sha,
                     "note": note, "lineno": ln})
    if not rows and not errors:
        errors.append("注册表机读段内零登记行（%s）" % reg_path)
    return rows, errors


def find_registry(explicit, fos_root):
    """注册表查找序：--registry ＞ $JUDGE_PATHS_MD ＞ fos-root 兄弟 .github ＞ 门本体上溯。"""
    cands = []
    if explicit:
        cands.append(explicit)
    env = os.environ.get("JUDGE_PATHS_MD")
    if env:
        cands.append(env)
    if fos_root:
        cands.append(os.path.join(os.path.dirname(norm_path(fos_root)), ".github",
                                  "docs", "judge-paths.md"))
    gate_dir = Path(__file__).resolve().parent
    for anc in [gate_dir] + list(gate_dir.parents):
        cands.append(os.path.join(str(anc), ".github", "docs", "judge-paths.md"))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def resolve_row_path(row, fos_root):
    p = row["path"]
    if os.path.isabs(p):
        return norm_path(p)
    if not fos_root:
        return None
    return norm_path(os.path.join(norm_path(fos_root), p))


# ---------------------------------------------------------------- 三腿

class Leg(object):
    def __init__(self, name):
        self.name = name
        self.lines = []      # (kind, text)；kind ∈ PASS/FAIL/SKIP/INFO

    def add(self, kind, text):
        self.lines.append((kind, text))

    @property
    def red(self):
        return any(k == "FAIL" for k, _ in self.lines)

    @property
    def unprovable(self):
        return any(k == "SKIP" and "不可证" in t for k, t in self.lines)

    def emit(self, out=sys.stdout):
        for k, t in self.lines:
            out.write("  [%s] %s\n" % (k, t))


def leg_deploy(rows, fos_root, scan_roots):
    """L1：active 期望 sha 对账＋historical 冻结 sha 对账＋扫描根内 active 缺席即红。"""
    leg = Leg("L1 部署面对账")
    reg_paths = set()
    for row in rows:
        p = resolve_row_path(row, fos_root)
        if p is None:
            leg.add("FAIL", "%s 相对路径行但 --fos-root 缺席，无从解析（fail-closed）" % row["id"])
            continue
        reg_paths.add(p)
        in_scope = any(under(r, p) for r in scan_roots)
        if not os.path.exists(p):
            if row["status"] == ACTIVE and in_scope:
                leg.add("FAIL", "%s 活跃面缺席：%s（扫描根内应有既有）" % (row["id"], p))
            else:
                leg.add("INFO", "%s 不在本机：%s（%s，跨机登记行）"
                        % (row["id"], p, row["status"]))
            continue
        try:
            actual = sha256_file(p)
        except OSError as e:
            leg.add("FAIL", "%s 读取失败 %s：%s" % (row["id"], p, e))
            continue
        if actual != row["sha"]:
            if row["status"] == ACTIVE:
                leg.add("FAIL", "%s 活跃面 sha 不符：%s 实测 %s… ≠ 期望 %s…（漂移/调包）"
                        % (row["id"], p, actual[:12], row["sha"][:12]))
            else:
                leg.add("FAIL", "%s 历史工件字节被改：%s 实测 %s… ≠ 登记 %s…（禁改）"
                        % (row["id"], p, actual[:12], row["sha"][:12]))
        else:
            tag = "活跃面对账" if row["status"] == ACTIVE else "历史冻结对账"
            leg.add("PASS", "%s %s：%s ≡ %s…" % (row["id"], tag, p, row["sha"][:12]))
    return leg, reg_paths


def leg_completeness(rows, scan_roots, fos_root):
    """L2：扫描根下 swev-judge-v2.py 全集必须逐一命中注册表。"""
    leg = Leg("L2 注册表完备性")
    reg_paths = set()
    for row in rows:
        p = resolve_row_path(row, fos_root)
        if p:
            reg_paths.add(p)
    for root in scan_roots:
        r = norm_path(root)
        if not os.path.isdir(r):
            leg.add("FAIL", "扫描根不存在：%s（不可证 fail-closed）" % r)
            continue
        found = []
        for dirpath, dirnames, filenames in os.walk(r):
            # 剪枝：不下潜 .git/__pycache__（判官件不会只住在那里；剪枝防扫描面爆炸）
            dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__")]
            if JUDGE_NAME in filenames:
                found.append(norm_path(os.path.join(dirpath, JUDGE_NAME)))
        found.sort()
        if not found:
            leg.add("INFO", "扫描根 %s 内零个 %s（本根无判官件拷贝）" % (r, JUDGE_NAME))
        for p in found:
            if p in reg_paths:
                leg.add("PASS", "登记内拷贝：%s" % p)
            else:
                leg.add("FAIL", "注册表外拷贝：%s（私搭/调包/未登记部署面——"
                        "登记表只增不减，先登记后部署）" % p)
    return leg


def _pair_tasks(cache_dir):
    """tasks/*.json ↔ tasks/*.verify.json 配对。返回 (pairs, unpaired_json, orphan_verify)。"""
    tdir = os.path.join(norm_path(cache_dir), "tasks")
    jsons, verifies = set(), set()
    if os.path.isdir(tdir):
        for name in os.listdir(tdir):
            if name.endswith(".verify.json"):
                verifies.add(name[: -len(".verify.json")])
            elif name.endswith(".json"):
                jsons.add(name[: -len(".json")])
    pairs = sorted(jsons & verifies)
    return pairs, sorted(jsons - verifies), sorted(verifies - jsons)


def leg_records(cache_dir, known_shas, deep, fetch_python):
    """L3：记录面双 sha 硬校验（配对＋judge_sha256 已知集＋eval_script_sha256 形态＋
    离线语义）；--deep 时逐 task 离线复算 eval_script_sha256 对账。"""
    leg = Leg("L3 记录面双 sha 硬校验")
    if not cache_dir:
        leg.add("INFO", "未给 --cache-dir：本机无判分缓存记录面待验（L3 空转）")
        return leg
    cd = norm_path(cache_dir)
    if not os.path.isdir(cd):
        leg.add("FAIL", "缓存目录不存在：%s（不可证 fail-closed）" % cd)
        return leg
    pairs, only_json, only_verify = _pair_tasks(cd)
    for s in only_json:
        leg.add("FAIL", "记录面缺件：tasks/%s.json 无配对 .verify.json"
                "（spec 未经远端复用验证，禁入判分）" % s)
    for s in only_verify:
        leg.add("FAIL", "孤儿记录：tasks/%s.verify.json 无配对 task json" % s)
    if not pairs:
        leg.add("INFO", "缓存 tasks/ 零配对记录（记录面空）")
    tmp = tempfile.mkdtemp(prefix="judge-deploy-recon-")
    try:
        for stem in pairs:
            vp = os.path.join(cd, "tasks", stem + ".verify.json")
            tp = os.path.join(cd, "tasks", stem + ".json")
            try:
                rec = json.loads(read_text(vp))
            except Exception as e:
                leg.add("FAIL", "%s：verify.json 坏 JSON（%s）——记录面不可信" % (stem, e))
                continue
            jsha = rec.get("judge_sha256")
            esha = rec.get("eval_script_sha256")
            if jsha not in known_shas:
                leg.add("FAIL", "%s：judge_sha256=%s… 不在注册表已知 sha 集"
                        "（记录面被污染/引用未登记判官版本）" % (stem, str(jsha)[:12]))
            if not (isinstance(esha, str) and SHA_RE.match(esha)):
                leg.add("FAIL", "%s：eval_script_sha256=%r 形态非法（须 64 位小写 hex）"
                        % (stem, esha))
            if rec.get("spec_ok") is not True:
                leg.add("FAIL", "%s：spec_ok=%r ≠ true（缓存内 spec 未经取数验证）"
                        % (stem, rec.get("spec_ok")))
            if rec.get("source") != "cache":
                leg.add("FAIL", "%s：source=%r ≠ cache（缓存记录面不得自称实呼取数，"
                        "hermetic 语义破）" % (stem, rec.get("source")))
            if rec.get("live_http"):
                leg.add("FAIL", "%s：live_http 非空（%s）——记录面含实呼痕迹"
                        % (stem, rec.get("live_http")))
            if leg.red:
                continue                 # 本 task 已红，深校无谓
            if not deep:
                leg.add("SKIP", "%s：eval_script 内容复算未启用（--deep 才跑；"
                        "浅校已过：双 sha 形态＋已知集＋离线语义）" % stem)
                continue
            fetcher = os.path.join(cd, "swev-spec-fetch.py")
            if not fetch_python or not os.path.isfile(fetcher):
                leg.add("SKIP", "%s：不可证——--deep 复算缺件（fetch_python=%r fetcher=%s）"
                        % (stem, fetch_python, fetcher))
                continue
            outp = os.path.join(tmp, stem + ".recompute.json")
            env = dict(os.environ)
            env["SWEV_JUDGE_V2_ALLOW_LIVE"] = "0"   # 复算恒离线（禁外呼）
            try:
                r = subprocess.run(
                    [fetch_python, fetcher, "--quiet", "--cache-dir", cd,
                     "--out", outp, tp],
                    capture_output=True, text=True, timeout=180, env=env,
                    stdin=subprocess.DEVNULL)
            except Exception as e:
                leg.add("SKIP", "%s：不可证——复算执行异常 %s" % (stem, e))
                continue
            if r.returncode != 0 or not os.path.isfile(outp):
                leg.add("SKIP", "%s：不可证——复算未成（rc=%s；缓存未命中/取数件异常；"
                        "fail-closed 不猜绿）" % (stem, r.returncode))
                continue
            try:
                rec2 = json.loads(read_text(outp))
            except Exception as e:
                leg.add("FAIL", "%s：复算输出坏 JSON（%s）" % (stem, e))
                continue
            if rec2.get("eval_script_sha256") != esha:
                leg.add("FAIL", "%s：eval_script_sha256 复算不符（记录 %s… ≠ 复算 %s…）"
                        "——spec 内容与记录面脱节（缓存污染）"
                        % (stem, str(esha)[:12], str(rec2.get("eval_script_sha256"))[:12]))
            elif rec2.get("spec_ok") is not True or rec2.get("source") != "cache":
                leg.add("FAIL", "%s：复算语义不符（spec_ok=%r source=%r）"
                        % (stem, rec2.get("spec_ok"), rec2.get("source")))
            else:
                leg.add("PASS", "%s：eval_script 内容复算 ≡ 记录（%s…，离线零外呼）"
                        % (stem, str(esha)[:12]))
    finally:
        for f in os.listdir(tmp):
            os.unlink(os.path.join(tmp, f))
        os.rmdir(tmp)
    return leg


# ---------------------------------------------------------------- 主流程

def run_gate(args):
    fos_root = norm_path(args.fos_root) if args.fos_root else None
    scan_roots = [norm_path(r) for r in (args.scan_root or [])]
    reg_path = find_registry(args.registry, fos_root)
    rows, errors = parse_registry(reg_path)
    print("=== 判官件部署面对账门（Q10 修·部署漂移＋缓存记录面双 sha 硬校验）===")
    print("注册表：%s" % reg_path)
    print("factory-os 根：%s" % fos_root)
    print("扫描根：%s" % (", ".join(scan_roots) if scan_roots else "（无——L2 不跑）"))
    print("缓存面：%s%s" % (args.cache_dir or "（无——L3 空转）",
                          "｜deep=on（fetch-python=%s）" % args.fetch_python
                          if args.deep else ""))
    if errors:
        for e in errors:
            print("  [FAIL] 注册表坏：%s" % e)
        print("结论：不可证 —— 注册表不可信（fail-closed，不猜绿）")
        return 2
    print("注册表登记 %d 行（active %d／historical-frozen %d）"
          % (len(rows), sum(1 for r in rows if r["status"] == ACTIVE),
             sum(1 for r in rows if r["status"] == FROZEN)))

    legs = []
    l1, _ = leg_deploy(rows, fos_root, scan_roots)
    legs.append(l1)
    if not args.pre_judge and scan_roots:
        legs.append(leg_completeness(rows, scan_roots, fos_root))
    elif args.pre_judge:
        print("  [INFO] pre-judge 模式：L2 完备性扫描不跑（归巡检 cron）")
    known = set(r["sha"] for r in rows)
    legs.append(leg_records(args.cache_dir, known, args.deep, args.fetch_python))

    nred = 0
    ninf = 0
    for leg in legs:
        print("--- %s" % leg.name)
        leg.emit()
        if leg.red:
            nred += 1
        if leg.unprovable:
            ninf += 1
    if nred:
        print("结论：红（%d 腿有红项，见上——判分链必须拒判 fail-closed）" % nred)
        return 1
    if ninf:
        print("结论：不可证（%d 腿缺件/复算不可用——fail-closed，不猜绿）" % ninf)
        return 2
    if args.pre_judge:
        print("结论：绿（pre-judge 放行：部署面＋记录面全绿）")
    else:
        print("结论：绿（部署面对账＋注册表完备＋记录面双 sha 全绿）")
    return 0


# ---------------------------------------------------------------- selftest

def _mkfile(p, content):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return sha256_file(p)


def _registry_text(rows):
    """rows: [(id, path, status, sha)] → 带围栏的注册表段。"""
    out = [REG_BEGIN, "", "| 行 | 部署路径 | 状态 | 期望 sha256 | 语义 |",
           "|---|---|---|---|---|"]
    for rid, path, status, sha in rows:
        out.append("| %s | %s | %s | %s | 夹具 |" % (rid, path, status, sha))
    out.append("")
    out.append(REG_END)
    return "\n".join(out) + "\n"


def _fixture(td, *, active_content="active-v1\n", hist_content="hist-v1\n",
             stray=False, record=None, drop_verify=False, active_gone=False,
             hist_content2=None, active_content2=None):
    """构造一整套夹具；返回 dict（fos_root/reg/cache/scan_roots/expected shas）。"""
    fos = os.path.join(td, "fos")
    cache = os.path.join(td, "cache")
    sha_a = _mkfile(os.path.join(fos, "tools", JUDGE_NAME), active_content)
    sha_h = _mkfile(os.path.join(fos, "bench", "D-86", JUDGE_NAME), hist_content)
    rows = [("J1", "tools/" + JUDGE_NAME, ACTIVE, sha_a),
            ("H1", "bench/D-86/" + JUDGE_NAME, FROZEN, sha_h)]
    if stray:
        _mkfile(os.path.join(fos, "stray", JUDGE_NAME), "stray\n")
    if active_gone:
        os.unlink(os.path.join(fos, "tools", JUDGE_NAME))
    if hist_content2 is not None:
        _mkfile(os.path.join(fos, "bench", "D-86", JUDGE_NAME), hist_content2)
    if active_content2 is not None:
        _mkfile(os.path.join(fos, "tools", JUDGE_NAME), active_content2)
    reg = os.path.join(td, "judge-paths.md")
    _mkfile(reg, "# 夹具\n\n" + _registry_text(rows))
    # 缓存记录面（1 个配对 task）
    iid = "django__django-1"
    _mkfile(os.path.join(cache, "tasks", iid + ".json"),
            json.dumps({"instance_id": iid, "repo": "django/django", "version": "3.0",
                        "base_commit": "0" * 40, "test_patch": "",
                        "fail_to_pass": ["t1"], "pass_to_pass": ["t2"]}))
    if not drop_verify:
        rec = {"spec_ok": True, "instance_id": iid, "source": "cache",
               "elapsed_ms": 0, "live_http": [], "blocked_urls": [],
               "judge_sha256": sha_h, "eval_script_sha256": "a" * 64,
               "swebench_version": "4.1.0", "allow_live": False, "error": None}
        if record:
            rec.update(record)
        _mkfile(os.path.join(cache, "tasks", iid + ".verify.json"), json.dumps(rec))
    return {"fos": fos, "reg": reg, "cache": cache, "sha_a": sha_a, "sha_h": sha_h,
            "scan": [fos]}


def selftest():
    ok = True

    def rec(name, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        print("[%s] %s" % ("PASS" if cond else "FAIL", name)
              + (" — " + detail if detail else ""), flush=True)

    import tempfile
    import shutil

    def scenario(mut=None, argv_extra=None, **kw):
        td = tempfile.mkdtemp(prefix="judge-gate-selftest-")
        try:
            fx = _fixture(td, **kw)
            if mut:
                mut(fx)
            argv = ["--registry", fx["reg"], "--fos-root", fx["fos"],
                    "--scan-root", fx["fos"], "--cache-dir", fx["cache"]]
            if argv_extra:
                argv += argv_extra
            return run_gate(_Args(argv)), fx
        finally:
            shutil.rmtree(td, ignore_errors=True)

    class _Args(object):
        def __init__(self, argv):
            self.registry = self.fos_root = self.cache_dir = self.fetch_python = None
            self.scan_root = []
            self.deep = False
            self.pre_judge = False
            it = iter(argv)
            for a in it:
                if a == "--registry":
                    self.registry = next(it)
                elif a == "--fos-root":
                    self.fos_root = next(it)
                elif a == "--scan-root":
                    self.scan_root.append(next(it))
                elif a == "--cache-dir":
                    self.cache_dir = next(it)
                elif a == "--fetch-python":
                    self.fetch_python = next(it)
                elif a == "--deep":
                    self.deep = True
                elif a == "--pre-judge":
                    self.pre_judge = True

    # ① 基线全绿
    rc, fx = scenario()
    rec("基线全绿（active 对账＋无表外拷贝＋记录面双 sha 浅校）", rc == 0, "rc=%s" % rc)
    # ② 活跃面 sha 漂移 ⇒ 红（先按原内容建注册表，再换字节——模拟部署面被改）
    rc, _ = scenario(active_content2="active-TAMPERED\n")
    rec("活跃面 sha 不符 ⇒ 红", rc == 1, "rc=%s" % rc)
    # ③ 注册表外拷贝 ⇒ 红
    rc, _ = scenario(stray=True)
    rec("注册表外拷贝（扫描根内）⇒ 红", rc == 1, "rc=%s" % rc)
    # ④ 历史工件字节被改 ⇒ 红
    rc, _ = scenario(hist_content2="hist-TAMPERED\n")
    rec("历史工件字节被改 ⇒ 红", rc == 1, "rc=%s" % rc)
    # ⑤ 活跃面缺席（扫描根内）⇒ 红
    rc, _ = scenario(active_gone=True)
    rec("活跃面扫描根内缺席 ⇒ 红", rc == 1, "rc=%s" % rc)
    # ⑥ 记录面 judge_sha256 被污染（伪造 sha）⇒ 红
    rc, _ = scenario(record={"judge_sha256": "0" * 64})
    rec("记录面 judge_sha256 伪造（不在已知集）⇒ 红", rc == 1, "rc=%s" % rc)
    # ⑦ eval_script_sha256 形态坏 ⇒ 红
    rc, _ = scenario(record={"eval_script_sha256": "abc"})
    rec("记录面 eval_script_sha256 形态非法 ⇒ 红", rc == 1, "rc=%s" % rc)
    # ⑧ task 无配对 verify.json ⇒ 红
    rc, _ = scenario(drop_verify=True)
    rec("记录面缺件（task 无 verify.json）⇒ 红", rc == 1, "rc=%s" % rc)
    # ⑨ spec_ok=false ⇒ 红
    rc, _ = scenario(record={"spec_ok": False})
    rec("记录面 spec_ok=false ⇒ 红", rc == 1, "rc=%s" % rc)
    # ⑩ source=live（实呼痕迹）⇒ 红
    rc, _ = scenario(record={"source": "live", "live_http": ["https://x"]})
    rec("记录面自称实呼（source=live）⇒ 红", rc == 1, "rc=%s" % rc)
    # ⑪ 注册表围栏缺失 ⇒ 不可证
    def _break_reg(fx):
        _mkfile(fx["reg"], "# 无围栏\n")
    rc, _ = scenario(mut=_break_reg)
    rec("注册表机读段缺失 ⇒ 不可证(2)", rc == 2, "rc=%s" % rc)
    # ⑫ 注册表行 sha 形态坏 ⇒ 不可证
    def _bad_sha(fx):
        txt = read_text(fx["reg"]).replace(fx["sha_a"], "not-a-sha")
        _mkfile(fx["reg"], txt)
    rc, _ = scenario(mut=_bad_sha)
    rec("注册表期望 sha 形态坏 ⇒ 不可证(2)", rc == 2, "rc=%s" % rc)
    # ⑬ 扫描根不存在 ⇒ 红（L2 fail-closed）
    def _kill_scan(fx):
        import shutil as _sh
        _sh.rmtree(fx["scan"][0], ignore_errors=True)
    rc, _ = scenario(mut=_kill_scan)
    rec("扫描根不存在 ⇒ 红(fail-closed)", rc == 1, "rc=%s" % rc)
    # ⑭ deep 复算：stub fetcher 一致 ⇒ 绿
    def _stub_ok(fx):
        fetcher = os.path.join(fx["cache"], "swev-spec-fetch.py")
        _mkfile(fetcher,
                "import json,sys\n"
                "out=[a for a in sys.argv if a.endswith('.recompute.json')][0]\n"
                "json.dump({'spec_ok':True,'source':'cache','live_http':[],"
                "'eval_script_sha256':%r},open(out,'w'))\n" % ("a" * 64))
    rc, _ = scenario(mut=_stub_ok, argv_extra=["--deep", "--fetch-python",
                                               sys.executable])
    rec("deep 复算一致 ⇒ 绿", rc == 0, "rc=%s" % rc)
    # ⑮ deep 复算不一致 ⇒ 红
    def _stub_bad(fx):
        fetcher = os.path.join(fx["cache"], "swev-spec-fetch.py")
        _mkfile(fetcher,
                "import json,sys\n"
                "out=[a for a in sys.argv if a.endswith('.recompute.json')][0]\n"
                "json.dump({'spec_ok':True,'source':'cache','live_http':[],"
                "'eval_script_sha256':%r},open(out,'w'))\n" % ("b" * 64))
    rc, _ = scenario(mut=_stub_bad, argv_extra=["--deep", "--fetch-python",
                                                sys.executable])
    rec("deep 复算不符 ⇒ 红", rc == 1, "rc=%s" % rc)
    # ⑯ deep 复算不可用（fetcher 退出非 0）⇒ 不可证
    def _stub_fail(fx):
        fetcher = os.path.join(fx["cache"], "swev-spec-fetch.py")
        _mkfile(fetcher, "import sys\nsys.exit(2)\n")
    rc, _ = scenario(mut=_stub_fail, argv_extra=["--deep", "--fetch-python",
                                                 sys.executable])
    rec("deep 复算未成 ⇒ 不可证(2)", rc == 2, "rc=%s" % rc)
    # ⑰ pre-judge 模式：漂移 ⇒ 红
    rc, _ = scenario(active_content2="active-TAMPERED\n", argv_extra=["--pre-judge"])
    rec("pre-judge 活跃面漂移 ⇒ 红(拒判)", rc == 1, "rc=%s" % rc)
    # ⑱ pre-judge 模式：表外拷贝不跑 L2 ⇒ 仍绿（完备性归巡检）
    rc, _ = scenario(stray=True, argv_extra=["--pre-judge"])
    rec("pre-judge 不跑 L2（表外拷贝不拦判分）⇒ 绿", rc == 0, "rc=%s" % rc)
    # ⑲ pre-judge 模式：记录面污染 ⇒ 红（拒判）
    rc, _ = scenario(record={"judge_sha256": "0" * 64}, argv_extra=["--pre-judge"])
    rec("pre-judge 记录面污染 ⇒ 红(拒判)", rc == 1, "rc=%s" % rc)
    # ⑳ 无 --cache-dir：L3 空转不拦
    td = tempfile.mkdtemp(prefix="judge-gate-selftest-")
    try:
        fx = _fixture(td)
        a2 = _Args(["--registry", fx["reg"], "--fos-root", fx["fos"],
                    "--scan-root", fx["fos"]])
        rc2 = run_gate(a2)
        rec("无 --cache-dir ⇒ L3 空转 INFO 不拦", rc2 == 0, "rc=%s" % rc2)
    finally:
        shutil.rmtree(td, ignore_errors=True)
    return 0 if ok else 1


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--registry", default=None, help="judge-paths.md 路径（注册表单一源）")
    ap.add_argument("--fos-root", default=None,
                    help="factory-os 仓根（解析仓内相对路径行；默认=门本体上溯一级）")
    ap.add_argument("--scan-root", action="append", default=None,
                    help="L2 完备性扫描根（可重复；anolis 巡检用 /data/bench）")
    ap.add_argument("--cache-dir", default=None,
                    help="判分缓存目录（含 tasks/*.verify.json 记录面）")
    ap.add_argument("--fetch-python", default=None,
                    help="--deep 复算用解释器（须可 import swebench）")
    ap.add_argument("--deep", action="store_true",
                    help="L3 加跑 eval_script 内容复算（离线零外呼）")
    ap.add_argument("--pre-judge", action="store_true",
                    help="判分步起手模式（L1＋L3，不跑 L2）")
    ap.add_argument("--selftest", action="store_true", help="内嵌夹具自证（含负例）")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.fos_root:
        a.fos_root = str(Path(__file__).resolve().parents[1])
    return run_gate(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
