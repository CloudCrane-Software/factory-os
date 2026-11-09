#!/usr/bin/env python3
"""tools/negative-control-recon-gate.py — 负控件登记册起手对账门（D-157，2026-11-08）

为什么有本门（逃逸台账 ESC-19）：回归门判据依赖具名负控件文件（修前快照 .bak），
却无存在性/命名对账——归档/改名（tools/ 归档面动作，在门管辖域外）即令守门件
自身红（test-quota-gate-criteria-parity.py G6 实跑 FAIL「负控件缺失」在案）。
本门把「对账」做成独立门：读 tools/negative-controls.list（负控件登记册：
件名+sha256+现势位），逐条解析件位并对账 sha256；缺席 ⇒ 红并**点名**——
缺哪件、登记在哪、现势位里有哪些近似名件（如 ESC-19 的「缺 -dead 后缀」近似
件）——而非裸 FAIL。归档面规矩：归档改名/迁移须同批更新登记册，只挪件不更册
⇒ sha 失配或缺席点名（预期红）。

登记册格式（parse_register 为唯一解析实现，fail-closed）：
  CTRL <件名>            开一条登记（精确件名）
    sha256=<64位小写hex>   必填
    loc_repo=<相对repo根>  在役位检索目录（可多行）
    loc_ws=<相对工作区根>  归档位检索目录（可多行；工作区根候选见 ws_root_candidates）
    fixture=<依赖夹具件>   必填（消费方对账用）
    source=<来源债号/条目> 必填（溯源用）
  以 # 开头为注释；空行忽略；未知键/无法识别行/缺必填键 ⇒ RegisterError。

退出码：0=全部登记条目解析到场且 sha256 对账一致；1=缺席/sha 失配（已点名）；
       2=fail-closed（登记册缺失/不可解析/条目缺必填键）。
用法：
  python3 -I tools/negative-control-recon-gate.py                # 实扫登记册
  python3 -I tools/negative-control-recon-gate.py --json         # 机器可读（单行 JSON）
  python3 -I tools/negative-control-recon-gate.py --selftest     # 沙箱自证（不触真实件）
夹具复用：test-quota-gate-criteria-parity.py G6 经 SourceFileLoader 载入本件
（load_register/parse_register/resolve_entry/ws_root_candidates），件位解析
单一实现、判据不分叉。
本件零网络、零凭据、零写入（除 --selftest 的 tempfile 沙箱）。
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

SCHEMA = "af.tools.negative-control-recon-gate.v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_KEYS = ("sha256", "fixture", "source")
LOCATION_KEYS = ("loc_repo", "loc_ws")
KNOWN_KEYS = set(REQUIRED_KEYS) | set(LOCATION_KEYS)
NEAR_RATIO = 0.72          # 近似名判定阈（difflib.SequenceMatcher）
NEAR_SHOW = 5              # 点名时最多列出的近似名件数


class RegisterError(Exception):
    """登记册缺失/不可解析/条目缺必填键——一律 fail-closed。"""


def parse_register(text, origin="<register>"):
    """解析登记册全文 → [entry, ...]；无法识别行/缺必填键 ⇒ RegisterError（带行号）。"""
    entries = []
    cur = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("CTRL "):
            if cur:
                entries.append(cur)
            cur = {"name": line[5:].strip(), "line": lineno,
                   "loc_repo": [], "loc_ws": []}
            if not cur["name"]:
                raise RegisterError("%s:%d CTRL 行缺件名" % (origin, lineno))
            continue
        if cur is None:
            raise RegisterError(
                "%s:%d 无法识别行 %r（任何数据行都必须隶属于其前的 CTRL 条目）"
                % (origin, lineno, line[:60]))
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if not m:
            raise RegisterError("%s:%d 无法识别行 %r（期望 key=value）"
                                % (origin, lineno, line[:60]))
        key, val = m.group(1), m.group(2).strip()
        if key not in KNOWN_KEYS:
            raise RegisterError(
                "%s:%d 未认键 %r（可认：%s）" % (origin, lineno, key,
                                               ",".join(sorted(KNOWN_KEYS))))
        if key == "sha256":
            if not HEX64.match(val):
                raise RegisterError("%s:%d sha256 非 64 位小写 hex：%r"
                                    % (origin, lineno, val[:70]))
            cur["sha256"] = val
        elif key in LOCATION_KEYS:
            cur[key].append(val)
        else:
            cur[key] = val
    if cur:
        entries.append(cur)
    if not entries:
        raise RegisterError("%s 无任何 CTRL 条目（登记册空壳=不可证）" % origin)
    for e in entries:
        missing = [k for k in REQUIRED_KEYS if k not in e]
        locs = e.get("loc_repo", []) + e.get("loc_ws", [])
        if missing:
            raise RegisterError("%s:%d 条目 %s 缺必填键 %s"
                                % (origin, e["line"], e["name"], ",".join(missing)))
        if not locs:
            raise RegisterError("%s:%d 条目 %s 无任何检索位（loc_repo/loc_ws 至少一项）"
                                % (origin, e["line"], e["name"]))
    return entries


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ws_root_candidates(repo_root):
    """工作区实例根候选（顺序=优先级；全部只读探测，不存在即落空）。

    本实例布局：<工作区根>/repos/<repo> 与 <工作区根>/.w-*/<repo>（worktree），
    故 repo_root.parent.parent 为工作区根；repo_root.parent 兜底（repo 直挂工作区根）。
    env AF_WS_ROOT 显式指定时置顶。CI 等无工作区实例的环境自然全落空 ⇒ 走缺席点名。
    """
    cands = []
    env = os.environ.get("AF_WS_ROOT")
    if env:
        cands.append(os.path.abspath(env))
    repo_root = os.path.abspath(repo_root)
    parent = os.path.dirname(repo_root)
    grand = os.path.dirname(parent)
    if grand and grand != repo_root:
        cands.append(grand)
    if parent and parent != repo_root:
        cands.append(parent)
    out, seen = [], set()
    for c in cands:
        if c not in seen and os.path.isdir(c):
            out.append(c)
            seen.add(c)
    return out


def near_names(directories, name):
    """在检索目录里找与 <name> 相似的现存件名（ESC-19 型「归档时命名漂移」点名用）。"""
    hits = []
    seen = set()
    for d in directories:
        if not os.path.isdir(d):
            continue
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            if n == name or n in seen or not os.path.isfile(os.path.join(d, n)):
                continue
            if difflib.SequenceMatcher(None, name, n).ratio() >= NEAR_RATIO:
                seen.add(n)
                hits.append(n)
    return hits[:NEAR_SHOW]


def resolve_entry(entry, repo_root, ws_roots):
    """单条登记的起手对账。返回 verdict ∈ {FOUND, SHA-MISMATCH, ABSENT} + 点名明细。

    检索顺序：loc_repo（在役位，repo_root 相对）→ loc_ws（归档位，ws_roots 逐个候
    选根展开）。**全部**命中件逐一 sha256 对账（任一失配 ⇒ SHA-MISMATCH 并点名
    册钉值与现势值；全一致取第一命中为解析位）。缺席时列近似名件。
    """
    name = entry["name"]
    searched, found = [], []
    for base, key in ((repo_root, "loc_repo"),) + tuple(
            (ws, "loc_ws") for ws in ws_roots):
        for rel in entry.get(key, []):
            p = os.path.join(base, rel, name)
            searched.append(p)
            if os.path.isfile(p):
                found.append((p, "loc_repo" if key == "loc_repo" else "loc_ws"))
    if not found:
        near_dirs = [os.path.join(repo_root, rel) for rel in entry.get("loc_repo", [])]
        near_dirs += [os.path.join(ws, rel) for ws in ws_roots
                      for rel in entry.get("loc_ws", [])]
        near = near_names(near_dirs, name)
        detail = ("缺席点名：负控件 %r 登记在册（fixture=%s；source=%s；sha256=%s…%s），"
                  "现势检索 %s 处皆无此件%s") % (
            name, entry.get("fixture"), entry.get("source"),
            entry["sha256"][:12], entry["sha256"][-6:],
            "；".join(searched) if searched else "（无可用检索位）",
            ("；近似名件（命名漂移线索）：" + "、".join(near)) if near
            else "；亦无近似名件（疑真缺失而非漂移）")
        return {"verdict": "ABSENT", "path": None, "hits": [], "detail": detail}
    mism = []
    for p, _tag in found:
        actual = sha256_of(p)
        if actual != entry["sha256"]:
            mism.append((p, actual))
    if mism:
        detail = "sha256 失配点名：%s（册钉 %s ≠ 现势 %s）——只挪件不更册属预期红；" \
                 "先按归档面规矩同批重锚登记册再跑门" % (
                     "；".join(p for p, _ in mism), entry["sha256"],
                     "、".join(a for _, a in mism))
        return {"verdict": "SHA-MISMATCH", "path": None, "hits": [p for p, _ in found],
                "detail": detail}
    return {"verdict": "FOUND", "path": found[0][0], "hits": [p for p, _ in found],
            "detail": "FOUND %s（%s；sha256 对账一致 %s…%s；命中 %d 处）" % (
                found[0][0], found[0][1], entry["sha256"][:12], entry["sha256"][-6:],
                len(found))}


def load_register(path):
    """读登记册；缺失/不可解析 ⇒ RegisterError（fail-closed 由调用方转 rc=2）。"""
    if not os.path.isfile(path):
        raise RegisterError("登记册缺失 %s（负控件存在性无从对账——fail-closed）" % path)
    with open(path, encoding="utf-8") as f:
        return parse_register(f.read(), origin=path)


def reconcile(register_path, repo_root, ws_roots=None):
    """全册对账。返回 (rc, report_dict)；rc: 0 全绿 / 1 缺席或失配 / 2 fail-closed。"""
    try:
        entries = load_register(register_path)
    except RegisterError as e:
        return 2, {"schema": SCHEMA, "verdict": "FAIL-CLOSED", "register": register_path,
                   "detail": str(e), "results": []}
    if ws_roots is None:
        ws_roots = ws_root_candidates(repo_root)
    results = [dict(resolve_entry(e, repo_root, ws_roots), name=e["name"],
                    fixture=e.get("fixture"), source=e.get("source"))
               for e in entries]
    bad = [r for r in results if r["verdict"] != "FOUND"]
    rc = 1 if bad else 0
    report = {"schema": SCHEMA, "register": register_path,
              "ws_roots": ws_roots, "entries": len(entries), "results": results,
              "verdict": "PASS" if rc == 0 else "FAIL",
              "detail": ("全部 %d 条登记件位解析到场且 sha256 对账一致" % len(entries))
                        if rc == 0 else "；".join("%s: %s" % (r["name"], r["detail"])
                                                  for r in bad)}
    return rc, report


# ---- 沙箱自证（--selftest）：合成登记册四态（FOUND 在役/FOUND 归档/SHA失配/缺席
#      点名）＋fail-closed 两态（册缺失/未认键）＋CLI 三态退出码映射（subprocess
#      实取 returncode，同 -I 调用形制）。全程 tempfile，零真实件触碰。----
def _selftest():
    ok = []

    def check(label, cond):
        ok.append((label, bool(cond)))
        print("  %s %s" % ("PASS" if cond else "FAIL", label))

    with tempfile.TemporaryDirectory(prefix="negctrl-selftest.") as td:
        def entry_text(name, sha, extra=""):
            return ("CTRL %s\n  sha256=%s\n  fixture=test-fixture.py（自证）\n"
                    "  source=SELFTEST\n%s" % (name, sha, extra))

        # 沙箱工作区根：repo 在 ws/repos/rp（对齐本实例布局，同时验证 ws_root_candidates）
        ws = os.path.join(td, "ws")
        repo = os.path.join(ws, "repos", "rp")
        arch = os.path.join(ws, "90-归档", "20261106-tools-bak")
        ship = os.path.join(repo, "tools")
        os.makedirs(ship)
        os.makedirs(arch)

        def digest(body):
            return hashlib.sha256(body.encode("utf-8")).hexdigest()

        # ① FOUND（在役位在场且 sha 一致）
        body_a = "pre-fix snapshot A\n"
        open(os.path.join(ship, "ctl-a.bak"), "w").write(body_a)
        reg_a = os.path.join(td, "reg-a.list")
        open(reg_a, "w").write(entry_text("ctl-a.bak", digest(body_a),
                                          "  loc_repo=tools\n"))
        rc, rep = reconcile(reg_a, repo)
        check("①在役位在场 sha 一致 ⇒ rc=0 verdict=PASS",
              rc == 0 and rep["verdict"] == "PASS"
              and rep["results"][0]["verdict"] == "FOUND")

        # ② FOUND（在役位缺席、登记归档位在场且一致——ESC-19 正解路径）
        body_b = "pre-fix snapshot B\n"
        open(os.path.join(arch, "ctl-b.bak"), "w").write(body_b)
        reg_b = os.path.join(td, "reg-b.list")
        open(reg_b, "w").write(entry_text("ctl-b.bak", digest(body_b),
                                          "  loc_repo=tools\n"
                                          "  loc_ws=90-归档/20261106-tools-bak\n"))
        rc, rep = reconcile(reg_b, repo)
        check("②归档位解析 ⇒ rc=0 且解析位在归档面",
              rc == 0 and os.path.basename(os.path.dirname(
                  rep["results"][0]["path"])) == "20261106-tools-bak")

        # ③ SHA-MISMATCH（件在但内容漂移=只挪件不更册的姊妹形态）
        open(os.path.join(ship, "ctl-a.bak"), "w").write(body_a + "drifted\n")
        rc, rep = reconcile(reg_a, repo)
        check("③sha 失配 ⇒ rc=1 SHA-MISMATCH 且点名册钉/现势",
              rc == 1 and rep["results"][0]["verdict"] == "SHA-MISMATCH"
              and "册钉" in rep["results"][0]["detail"])

        # ④ ABSENT（两处皆缺）＋近似名件点名（缺后缀型漂移线索）
        os.remove(os.path.join(ship, "ctl-a.bak"))
        open(os.path.join(ship, "ctl-a.bak.bak"), "w").write("near-name decoy\n")
        rc, rep = reconcile(reg_a, repo)
        det = rep["results"][0]["detail"]
        check("④缺席 ⇒ rc=1 ABSENT 且点名近似名件 ctl-a.bak.bak",
              rc == 1 and rep["results"][0]["verdict"] == "ABSENT"
              and "ctl-a.bak.bak" in det and "缺席点名" in det)

        # ⑤ fail-closed：册缺失
        rc, rep = reconcile(os.path.join(td, "nope.list"), repo)
        check("⑤册缺失 ⇒ rc=2 FAIL-CLOSED", rc == 2 and rep["verdict"] == "FAIL-CLOSED")

        # ⑥ fail-closed：未认键 ⇒ parse_register 抛 RegisterError；reconcile 收敛 rc=2
        reg_bad = os.path.join(td, "reg-bad.list")
        open(reg_bad, "w").write(entry_text("ctl-x.bak", digest("x"), "  weird_key=1\n"))
        try:
            parse_register(open(reg_bad).read(), origin=reg_bad)
            check("⑥未认键 ⇒ parse_register RegisterError", False)
        except RegisterError:
            check("⑥未认键 ⇒ parse_register RegisterError", True)
        rc, rep = reconcile(reg_bad, repo)
        check("⑥未认键经 reconcile ⇒ rc=2 FAIL-CLOSED（吞错收敛、不崩栈）",
              rc == 2 and rep["verdict"] == "FAIL-CLOSED")

        # ⑦ CLI 三态退出码映射（subprocess 实取 returncode，--json 单行 JSON）
        cli = os.path.abspath(__file__)
        for regx, expect, label in ((reg_b, 0, "②的册"),
                                    (reg_a, 1, "④的册"),
                                    (os.path.join(td, "nope.list"), 2, "缺册")):
            r = subprocess.run([sys.executable, "-I", cli,
                                "--register", regx, "--repo-root", repo, "--json"],
                               capture_output=True, text=True, timeout=60)
            check("⑦CLI rc=%d（%s）" % (expect, label), r.returncode == expect)
            try:
                rep2 = json.loads(r.stdout.strip().splitlines()[-1])
                check("⑦CLI JSON verdict（%s）＝%s" % (label, rep2.get("verdict")),
                      rep2.get("verdict") in ("PASS", "FAIL", "FAIL-CLOSED")
                      and rep2.get("schema") == SCHEMA)
            except (ValueError, IndexError):
                check("⑦CLI JSON verdict（%s）" % label, False)

    n_ok = sum(1 for _, c in ok if c)
    print("SELFTEST %d/%d 过（沙箱 FOUND 在役/FOUND 归档/SHA 失配/缺席点名 + "
          "fail-closed 册缺失/未认键 + CLI 三态退出码映射；零真实件触碰）"
          % (n_ok, len(ok)))
    return 0 if n_ok == len(ok) else 1


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="负控件登记册起手对账门（D-157/ESC-19）")
    ap.add_argument("--register", default=os.path.join(here, "negative-controls.list"),
                    help="登记册路径（默认 tools/negative-controls.list）")
    ap.add_argument("--repo-root", default=os.path.dirname(here),
                    help="repo 根（默认本件上级目录）")
    ap.add_argument("--ws-root", action="append", default=None,
                    help="工作区实例根（可多次；默认 env AF_WS_ROOT+布局探测）")
    ap.add_argument("--json", action="store_true", help="机器可读报告（仅一行 JSON）")
    ap.add_argument("--selftest", action="store_true",
                    help="沙箱自证（tempfile 合成态，不触真实件）")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    ws_roots = [os.path.abspath(w) for w in a.ws_root] if a.ws_root else None
    rc, rep = reconcile(a.register, a.repo_root, ws_roots)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False))
    else:
        print("RECON %s：%s" % (rep["verdict"], rep["detail"]))
        for r in rep.get("results", []):
            print("  [%s] %s — %s" % (r["verdict"], r["name"], r["detail"]))
    return rc


if __name__ == "__main__":
    sys.exit(main())
