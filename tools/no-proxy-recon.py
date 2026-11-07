#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""no-proxy 域名漂移闸（D-138 / 债本体 D-125；卡面 factory-os#153）。

【为什么建本闸】
  「哪些域名绕代理」此前以行内 export 散在 planner-core.yml 的各作业 step 内
  （现势两处：step 07 调查环、step 08d 顾问评审腿），无单源可读面——新 agent
  无从知道还有哪些域名要绕；域名集合演变时散点特判逐个漏改 = 当前漂移形态
  （债证 30-工件/技术债清册-20261107.md:98；实测依据：该域经 gov 代理空响应、
  直连正常 ⇒ 绕行必要）。本闸把该面固化为「机读清单 + 比对闸」：作业面域名集 A
  与清单面域名集 B 逐域对拍，见差即红、点名到域，禁为绿放宽（卡面 P4）。

【判据（三态，单一源；rc 口径与仓内对账门同款）】
  A == B                                  ⇒ rc=0（零漂移）
  A ⊃ B（工作流新增域名未入清单）           ⇒ rc=1，逐域点名缺失
  B ⊃ A（清单多出 / 已停用域名未清）        ⇒ rc=1，逐域点名多余
  不可证（文件缺席 / 坏行 / 形态非法 / 不可解码）⇒ rc=2 fail-loud，逐条点名，
    不猜绿、不用 SKIP 冒充。rc=2 优先于 rc=1：两面读不出就没有比对可言。

【作业面 A 的抽取（同一变量名的两种写法，漏一种即漂移）】
  ① shell 形态：`export … NO_PROXY="a,b" no_proxy="a,b"`——现势唯一在役形态
     （planner-core.yml 两处，2026-11-07 实读坐标 L1286 / L3143；卡面所引
     L1283 / L3159 为 D-122 重构后坐标，此后 #160 等合入致行号漂移，域名集未变）。
  ② YAML 形态：`no_proxy: a,b`（env: 映射）——runner 侧配置的同一变量名写法，
     二期消费方切换后在役；本闸同守，防「迁移即漂移」。
  · `${VAR}` / `$VAR` / `%VAR%` 变量引用不计入 A（非字面域名），但计入读数
    skipped_var_refs——透明计数，不静默吞掉。
  · 注释行（首个非空字符为 #）不计入 A；形似 `export … no_proxy=` 的注释行另行数
    登记 commented_export_lines——停用 export 是真实漂移信号，靠清单侧转红点名，
    不靠猜「注释不算」。
  · 通配符 / 端口 / 路径 / 空格 / 引号等非纯域名形态 ⇒ rc=2 点名，禁猜。

【清单面 B 的格式纪律】一行一域名；`#` 注释与空行忽略；禁行内注释、禁重复行、
  禁变量引用、禁空域名——坏形态 rc=2 点名行号（单源文件禁二义）。

【runner 侧扩展位（本卡先落工作流面）】`--runner-env PATH`（可重复）：把 runner
  env 转储件（`KEY=VALUE` 行）里的 no_proxy 值折进 A 同闸核——二期 runner 级
  配置就位后只需多传一个参数，闸语义不变。本卡默认不传（只落工作流面）。

【已知不覆盖面（如实声明，不装作扫过）】作业内 export 的**清除动作本身**不在本闸
  判据内（清 export 会让 A 缩小 ⇒ 清单侧转红点名，由运营者裁是否同批清清单）；
  其他代理特例（HTTP_PROXY/https_proxy 域、`--noproxy` 命令行参数）不守——本闸
  只守 NO_PROXY/no_proxy 域名集。
【默认面的边界与已实证的第三处 export（2026-11-07 实读，卡面未列）】默认作业面
  = planner-core.yml（卡面指定的在飞核心链）。当次实读另发现
  `.github/workflows/planner-audit-weekly.yml:161` 同形 export（域名集与卡面种子
  一致，故本卡零漂移读数不受影响）——该面不在默认判据内，纳管只需多传一个参数：
  `--workflow .github/workflows/planner-audit-weekly.yml`（可重复，见 selftest
  多作业面用例）。是否纳入默认面归运营者裁（本卡不越卡面扩面）。

【纪律】零网络；只读被检件；唯一写面 = `--out` 显式指定的落盘件与 `--selftest`
  的临时目录（用后即清）；判据 / 判官件 / 在飞工作流零改动。

用法：
  python3 -I tools/no-proxy-recon.py [--workflow PATH ...] [--list PATH]
                                      [--runner-env PATH ...] [--out PATH]
  python3 -I tools/no-proxy-recon.py --selftest
退出码：0 = 零漂移；1 = 漂移（点名）；2 = 不可证 / 坏形态（fail-loud）。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

DEFAULT_WORKFLOW = ".github/workflows/planner-core.yml"
DEFAULT_LIST = "tools/no-proxy-domains.list"

RC_OK = 0
RC_DRIFT = 1
RC_UNPROVABLE = 2

SCHEMA = "af.no-proxy.recon.v1"

# 域名形态：≥2 个标签；每标签 1-63；禁首字符连字符（⇒ 禁通配符/端口/路径/空格）
DOMAIN_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?:\.(?!-)[A-Za-z0-9-]{1,63})+$")

# shell 形态：export … no_proxy=<值>（双引号 / 单引号 / 裸串三种取值）
SH_ASSIGN_RE = re.compile(
    r"""(?ix)\bno_proxy\b\s*=\s*(?:"([^"\n]*)"|'([^'\n]*)'|([^\s;&|)\n]+))""")

# YAML 形态：no_proxy: <值>（env: 映射；行首可选列表短横）
YAML_ASSIGN_RE = re.compile(r"(?ix)^[ \t]*(?:-[ \t]+)?no_proxy[ \t]*:[ \t]*(.*?)[ \t]*$")

# 变量引用形态（非字面域名：跳过但计数，不静默）
VARREF_RE = re.compile(r"^(?:\$\{[^}\s]*\}|\$[A-Za-z_][A-Za-z0-9_]*|%[A-Za-z_][A-Za-z0-9_]*%)$")

BAD_FORM_REASON = "非纯域名形态（禁通配符/端口/路径/空格/引号；一行一域名）"


def read_text(path):
    """读文件为文本。返回 (text, None)；缺席/不可解码返回 (None, 原因串)。"""
    if not os.path.exists(path):
        return None, "文件缺席：%s（不可证，不猜绿）" % path
    if os.path.isdir(path):
        return None, "是目录不是文件：%s（不可证）" % path
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as exc:
        return None, "读取失败：%s（%s）" % (path, exc)
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError as exc:
        return None, "非 UTF-8 不可解码：%s（%s）" % (path, exc)


def _yaml_value(rest):
    """YAML 裸值/引号值 → 字面值串（截行尾注释）。"""
    v = rest.strip()
    if v[:1] in ('"', "'"):
        q = v[0]
        end = v.find(q, 1)
        return v[1:end] if end > 0 else v[1:]
    return re.split(r"\s+#", v, maxsplit=1)[0].strip()


def _absorb(rec, ln, form, value):
    """把一个 no_proxy 值串折进 rec（域名/变量引用/坏形态三类分流）。"""
    for tok in [t.strip() for t in value.split(",")]:
        if not tok:
            continue
        if VARREF_RE.match(tok):
            rec["skipped_var_refs"].append({"line": ln, "form": form, "varref": tok})
            continue
        if not DOMAIN_RE.match(tok):
            rec["errors"].append({"line": ln, "form": form, "value": tok,
                                  "reason": BAD_FORM_REASON})
            continue
        dom = tok.lower()
        slot = rec["domains"].setdefault(dom, {"domain": dom, "raw": tok,
                                               "lines": [], "forms": []})
        if ln not in slot["lines"]:
            slot["lines"].append(ln)
        if form not in slot["forms"]:
            slot["forms"].append(form)


def read_workflow_domains(path):
    """作业面：实读全部 no_proxy 赋值行（shell 形态 + YAML 形态）。"""
    rec = {"file": path, "domains": {}, "skipped_var_refs": [],
           "commented_export_lines": [], "errors": []}
    text, err = read_text(path)
    if err:
        rec["errors"].append({"line": None, "form": "file", "value": path, "reason": err})
        return rec
    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r")
        hits = [("export", m) for m in SH_ASSIGN_RE.finditer(line)]
        ym = YAML_ASSIGN_RE.match(line)
        if ym:
            hits.append(("yaml", ym))
        if not hits:
            continue
        if line.strip().startswith("#"):
            # 注释行不计入 A；仅登记形似 export 的停用行（漂移信号，清单侧会红）
            if SH_ASSIGN_RE.search(line):
                rec["commented_export_lines"].append(ln)
            continue
        for form, m in hits:
            if form == "export":
                value = m.group(1)
                if value is None:
                    value = m.group(2)
                if value is None:
                    value = m.group(3) or ""
            else:
                value = _yaml_value(m.group(1))
            _absorb(rec, ln, form, value)
    return rec


def read_env_domains(path):
    """runner env 转储面（二期扩展位）：KEY=VALUE 行里的 no_proxy 值。"""
    rec = {"file": path, "domains": {}, "skipped_var_refs": [], "errors": []}
    text, err = read_text(path)
    if err:
        rec["errors"].append({"line": None, "form": "file", "value": path, "reason": err})
        return rec
    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r")
        if line.strip().startswith("#"):
            continue
        for m in SH_ASSIGN_RE.finditer(line):
            value = m.group(1)
            if value is None:
                value = m.group(2)
            if value is None:
                value = m.group(3) or ""
            _absorb(rec, ln, "runner-env", value)
    return rec


def read_list_domains(path):
    """清单面：一行一域名；注释/空行忽略；坏形态与重复行 fail-loud。"""
    rec = {"file": path, "domains": {}, "errors": []}
    text, err = read_text(path)
    if err:
        rec["errors"].append({"line": None, "form": "file", "value": path, "reason": err})
        return rec
    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r").strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            rec["errors"].append({"line": ln, "form": "list", "value": line[:80],
                                  "reason": "禁行内注释（一行一域名，单源文件禁二义）"})
            continue
        if VARREF_RE.match(line):
            rec["errors"].append({"line": ln, "form": "list", "value": line[:80],
                                  "reason": "清单禁变量引用（须字面域名）"})
            continue
        if not DOMAIN_RE.match(line):
            rec["errors"].append({"line": ln, "form": "list", "value": line[:80],
                                  "reason": BAD_FORM_REASON})
            continue
        dom = line.lower()
        if dom in rec["domains"]:
            rec["errors"].append({"line": ln, "form": "list", "value": line[:80],
                                  "reason": "重复行（一行一域名，重复禁二义）"})
            continue
        rec["domains"][dom] = {"domain": dom, "raw": line, "lines": [ln],
                               "forms": ["list"]}
    return rec


def _merge(recs, key="domains"):
    """多面合并：domain → [providence, ...]（ provenance = (面名, 行号, 形态) ）。"""
    out = {}
    for rec in recs:
        face = os.path.basename(rec["file"])
        for dom, meta in rec[key].items():
            for ln in meta["lines"]:
                out.setdefault(dom, []).append(
                    {"face": face, "line": ln, "form": meta["forms"][0]})
    return out


def check(workflow_paths, list_path, runner_env_paths=()):
    """执行对拍。返回 (rc, reading dict)。"""
    reading = {"schema": SCHEMA, "workflow_face": [], "runner_env_face": [],
               "list_face": None, "caliber": []}
    errors = []

    wf_recs = [read_workflow_domains(p) for p in workflow_paths]
    reading["workflow_face"] = wf_recs
    for rec in wf_recs:
        errors.extend(rec["errors"])

    env_recs = [read_env_domains(p) for p in runner_env_paths]
    reading["runner_env_face"] = env_recs
    for rec in env_recs:
        errors.extend(rec["errors"])

    list_rec = read_list_domains(list_path)
    reading["list_face"] = list_rec
    errors.extend(list_rec["errors"])

    # rc=2 优先于 rc=1：读不出两面就没有比对可言
    if errors:
        reading["verdict"] = "UNPROVABLE"
        reading["rc"] = RC_UNPROVABLE
        reading["errors"] = errors
        reading["caliber"].append("fail-loud：不可证不猜绿，禁 SKIP 冒充")
        return RC_UNPROVABLE, reading

    A = _merge(wf_recs + env_recs)
    B = _merge([list_rec])
    missing = sorted(set(A) - set(B))     # 工作流（+runner env）新增域名未入清单
    extra = sorted(set(B) - set(A))       # 清单多出 / 已停用域名未清

    reading["A_workflow_domains"] = sorted(A)
    reading["B_list_domains"] = sorted(B)
    reading["A_provenance"] = A
    reading["missing_in_list"] = missing
    reading["extra_in_list"] = extra

    for rec in wf_recs + env_recs:
        if rec["skipped_var_refs"]:
            reading["caliber"].append(
                "%s：变量引用 %d 处不计入 A（非字面域名，透明计数）"
                % (os.path.basename(rec["file"]), len(rec["skipped_var_refs"])))
        if rec.get("commented_export_lines"):
            reading["caliber"].append(
                "%s：被注释的 export no_proxy 行 %s 不计入 A——若为有意停用，"
                "清单侧须同批清理，否则判红" % (os.path.basename(rec["file"]),
                                            rec["commented_export_lines"]))
    if not A and not B:
        reading["caliber"].append(
            "两侧皆空：零域名在役（export 已清除且清单已清）——空集合相等即零漂移")
    if not A and B:
        reading["caliber"].append(
            "作业面无域名而清单非空：疑 export 面已迁移/清除，或被指向了错文件——"
            "判红点名，由人工裁")

    if missing or extra:
        reading["verdict"] = "DRIFT"
        reading["rc"] = RC_DRIFT
        return RC_DRIFT, reading
    reading["verdict"] = "ZERO-DRIFT"
    reading["rc"] = RC_OK
    return RC_OK, reading


def _fmt_face(rec, key="domains"):
    face = os.path.basename(rec["file"])
    rows = []
    for dom, meta in sorted(rec[key].items()):
        rows.append("    L%s [%s] %s" % (",".join(str(x) for x in meta["lines"]),
                                         "/".join(meta["forms"]), meta["raw"]))
    return rows or ["    （无域名）"]


def report(rc, reading):
    lines = []
    lines.append("== no-proxy 漂移闸（D-138 / 债本体 D-125）==")
    for rec in reading["workflow_face"]:
        lines.append("[作业面] %s" % rec["file"])
        lines.extend(_fmt_face(rec))
    for rec in reading["runner_env_face"]:
        lines.append("[runner-env 面·二期扩展位] %s" % rec["file"])
        lines.extend(_fmt_face(rec))
    lrec = reading["list_face"]
    lines.append("[清单面] %s" % lrec["file"])
    lines.extend(_fmt_face(lrec))

    if rc == RC_UNPROVABLE:
        lines.append("不可证（fail-loud rc=2）——逐条点名：")
        for e in reading.get("errors", []):
            lines.append("    %s L%s [%s] %s：%s"
                         % (os.path.basename(str(e.get("value", ""))), e.get("line"),
                            e.get("form"), e.get("value"), e.get("reason")))
        for c in reading.get("caliber", []):
            lines.append("  口径：%s" % c)
        lines.append("VERDICT rc=%d（%s）" % (rc, reading["verdict"]))
        return "\n".join(lines)

    lines.append("A（作业面域名 %d）= %s" % (len(reading["A_workflow_domains"]),
                                          ",".join(reading["A_workflow_domains"]) or "∅"))
    lines.append("B（清单面域名 %d）= %s" % (len(reading["B_list_domains"]),
                                          ",".join(reading["B_list_domains"]) or "∅"))
    if reading["missing_in_list"]:
        for d in reading["missing_in_list"]:
            prov = reading.get("A_provenance", {}).get(d, [])
            lines.append("判定：A ⊃ B ⇒ 工作流新增域名未入清单：%s（作业面 %s）"
                         % (d, prov or "见上"))
    if reading["extra_in_list"]:
        for d in reading["extra_in_list"]:
            lines.append("判定：B ⊃ A ⇒ 清单多出域名：%s（清单面见上）" % d)
    for c in reading.get("caliber", []):
        lines.append("  口径：%s" % c)
    if rc == RC_OK:
        lines.append("判定：A == B ⇒ 零漂移（初始态=实读导出集）")
    lines.append("VERDICT rc=%d（%s）" % (rc, reading["verdict"]))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="no-proxy-recon.py",
        description="no-proxy 域名漂移闸：作业面 export 域名集 A vs 机读清单 B（D-138）")
    ap.add_argument("--workflow", action="append", default=None,
                    help="作业面 YAML 路径（可重复；默认 %s）" % DEFAULT_WORKFLOW)
    ap.add_argument("--list", dest="list_path", default=None,
                    help="机读清单路径（默认 %s）" % DEFAULT_LIST)
    ap.add_argument("--runner-env", action="append", default=None,
                    help="runner env 转储件（可重复；二期扩展位，默认不传=只落工作流面）")
    ap.add_argument("--out", default=None, help="读数落盘 JSON 路径（可选）")
    ap.add_argument("--selftest", action="store_true",
                    help="内嵌夹具自测（零网络、零仓内写入）")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    wf = args.workflow or [DEFAULT_WORKFLOW]
    lp = args.list_path or DEFAULT_LIST
    envs = args.runner_env or []
    rc, reading = check(wf, lp, envs)
    print(report(rc, reading))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(json.dumps(reading, ensure_ascii=False, indent=2) + "\n")
        print("读数落盘：%s" % args.out)
    return rc


# ---------------------------------------------------------------------------
# selftest：内嵌夹具（一致态 / 漂移两态 / tamper 反例 / 变量引用 / 扩展位 /
#   子进程 CLI 入口），零网络、零仓内写入（临时目录用后即清）。
# ---------------------------------------------------------------------------
FIX_WF_OK = """\
# 夹具：与现势 planner-core.yml 同形的两处 export（含 ${NO_PROXY:-} 变量引用与小写孪生）
steps:
  - name: "07 调查环"
    run: |
      export NO_PROXY="tokenrhythm.studio,${NO_PROXY:-}" no_proxy="tokenrhythm.studio,${no_proxy:-}"
  - name: "08d 顾问评审腿"
    run: |
      export NO_PROXY="tokenrhythm.studio,${NO_PROXY:-}" no_proxy="tokenrhythm.studio,${no_proxy:-}"
"""

FIX_WF_DRIFT = """\
steps:
  - name: "07 调查环"
    run: |
      export NO_PROXY="tokenrhythm.studio,${NO_PROXY:-}" no_proxy="tokenrhythm.studio,${no_proxy:-}"
  - name: "08d 顾问评审腿"
    run: |
      export NO_PROXY="tokenrhythm.studio,drift-added.example,${NO_PROXY:-}" no_proxy="tokenrhythm.studio,drift-added.example,${no_proxy:-}"
"""

FIX_WF_YAML = """\
jobs:
  recon:
    env:
      no_proxy: tokenrhythm.studio
      NO_PROXY: tokenrhythm.studio,${NO_PROXY:-}
"""

FIX_WF_BADFORM = """\
steps:
  - name: "07"
    run: |
      export NO_PROXY="tokenrhythm.studio,*.tokenrhythm.studio"
"""

FIX_WF_COMMENTED = """\
steps:
  - name: "07"
    run: |
      # export NO_PROXY="tokenrhythm.studio"   # 有意停用（注释行不计入 A）
      echo ok
"""

FIX_LIST_OK = """\
# 夹具清单：一致态
tokenrhythm.studio
"""

FIX_LIST_EXTRA = """\
# 夹具清单：多出一条
tokenrhythm.studio
stale.example
"""

FIX_LIST_BADFORM = """\
# 夹具清单：坏形态（空格）
tokenrhythm.studio
bad domain.example
"""

FIX_LIST_DUP = """\
# 夹具清单：重复行
tokenrhythm.studio
tokenrhythm.studio
"""

FIX_ENV_OK = """\
# runner env 转储件（二期扩展位夹具）
no_proxy=tokenrhythm.studio
NO_PROXY=tokenrhythm.studio,${NO_PROXY:-}
"""

FIX_ENV_DRIFT = """\
# runner env 转储件（二期扩展位夹具：runner 侧新增域名）
no_proxy=tokenrhythm.studio,runner-added.example
"""


def selftest():
    cases = []

    def case(name, fn):
        cases.append((name, fn))

    tmp = tempfile.mkdtemp(prefix="no-proxy-recon-selftest-")
    try:
        def wf(name, content):
            p = os.path.join(tmp, name)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
            return p

        def lst(name, content):
            p = os.path.join(tmp, name)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
            return p

        def badbytes(name):
            p = os.path.join(tmp, name)
            with open(p, "wb") as f:
                f.write(b"export NO_PROXY=\"\xff\xfe bad\"\n")
            return p

        wf_ok = wf("wf-ok.yml", FIX_WF_OK)
        wf_drift = wf("wf-drift.yml", FIX_WF_DRIFT)
        wf_yaml = wf("wf-yaml.yml", FIX_WF_YAML)
        wf_badtoken = wf("wf-badtoken.yml", FIX_WF_BADFORM)
        wf_commented = wf("wf-commented.yml", FIX_WF_COMMENTED)
        l_ok = lst("list-ok.txt", FIX_LIST_OK)
        l_extra = lst("list-extra.txt", FIX_LIST_EXTRA)
        l_badform = lst("list-badform.txt", FIX_LIST_BADFORM)
        l_dup = lst("list-dup.txt", FIX_LIST_DUP)
        e_ok = lst("env-ok.env", FIX_ENV_OK)
        e_drift = lst("env-drift.env", FIX_ENV_DRIFT)

        # ① 一致态 ⇒ rc=0，A==B=={tokenrhythm.studio}
        def c_ok():
            rc, r = check([wf_ok], l_ok)
            assert rc == RC_OK, "rc=%d verdict=%s" % (rc, r.get("verdict"))
            assert r["A_workflow_domains"] == ["tokenrhythm.studio"], r["A_workflow_domains"]
            assert r["B_list_domains"] == ["tokenrhythm.studio"], r["B_list_domains"]
            assert r["verdict"] == "ZERO-DRIFT"
            return "A==B=%s 零漂移" % r["A_workflow_domains"]

        # ② 漂移态一：工作流新增域名未入清单（A⊃B）⇒ rc=1 点名
        def c_drift_wf():
            rc, r = check([wf_drift], l_ok)
            assert rc == RC_DRIFT, "rc=%d" % rc
            assert r["missing_in_list"] == ["drift-added.example"], r["missing_in_list"]
            assert r["extra_in_list"] == []
            return "A⊃B 点名缺失 drift-added.example"

        # ③ 漂移态二：清单多出（B⊃A）⇒ rc=1 点名
        def c_drift_list():
            rc, r = check([wf_ok], l_extra)
            assert rc == RC_DRIFT, "rc=%d" % rc
            assert r["extra_in_list"] == ["stale.example"], r["extra_in_list"]
            assert r["missing_in_list"] == []
            return "B⊃A 点名多余 stale.example"

        # ④ tamper：清单坏形态（空格域名）⇒ rc=2 fail-loud，不是 0 也不是 1
        def c_tamper_badform():
            rc, r = check([wf_ok], l_badform)
            assert rc == RC_UNPROVABLE, "rc=%d（禁把坏行当漂移或当绿）" % rc
            assert any("坏" in str(e.get("reason", "")) or "形态" in str(e.get("reason", ""))
                       for e in r["errors"]), r["errors"]
            return "坏行 fail-loud rc=2 点名"

        # ⑤ tamper：清单重复行 ⇒ rc=2
        def c_tamper_dup():
            rc, r = check([wf_ok], l_dup)
            assert rc == RC_UNPROVABLE, "rc=%d" % rc
            assert any("重复" in str(e.get("reason", "")) for e in r["errors"]), r["errors"]
            return "重复行 fail-loud rc=2 点名"

        # ⑥ tamper：清单文件缺席 ⇒ rc=2
        def c_tamper_missing_list():
            rc, r = check([wf_ok], os.path.join(tmp, "no-such.list"))
            assert rc == RC_UNPROVABLE, "rc=%d" % rc
            assert any("缺席" in str(e.get("reason", "")) for e in r["errors"]), r["errors"]
            return "清单缺席 fail-loud rc=2 点名"

        # ⑦ tamper：作业面文件缺席 ⇒ rc=2
        def c_tamper_missing_wf():
            rc, r = check([os.path.join(tmp, "no-such.yml")], l_ok)
            assert rc == RC_UNPROVABLE, "rc=%d" % rc
            assert any("缺席" in str(e.get("reason", "")) for e in r["errors"]), r["errors"]
            return "作业面缺席 fail-loud rc=2 点名"

        # ⑧ tamper：作业面不可解码 ⇒ rc=2
        def c_tamper_undecodable():
            p = badbytes("wf-badbytes.yml")
            rc, r = check([p], l_ok)
            assert rc == RC_UNPROVABLE, "rc=%d" % rc
            assert any("UTF-8" in str(e.get("reason", "")) for e in r["errors"]), r["errors"]
            return "非 UTF-8 fail-loud rc=2 点名"

        # ⑨ tamper：作业面出现非纯域名形态（通配符）⇒ rc=2 点名，禁猜
        def c_tamper_wf_badform():
            rc, r = check([wf_badtoken], l_ok)
            assert rc == RC_UNPROVABLE, "rc=%d（禁把通配符当普通域）" % rc
            assert any(e.get("value") == "*.tokenrhythm.studio" for e in r["errors"]), r["errors"]
            return "作业面通配符 fail-loud rc=2 点名"

        # ⑩ 变量引用 fidelity：${NO_PROXY:-} 与小写孪生不计入 A
        def c_varref():
            rc, r = check([wf_ok], l_ok)
            assert rc == RC_OK
            assert len(r["workflow_face"][0]["skipped_var_refs"]) == 4, \
                r["workflow_face"][0]["skipped_var_refs"]
            return "变量引用 4 处跳过且透明计数"

        # ⑪ YAML 形态同守（env: 映射）⇒ rc=0
        def c_yaml_form():
            rc, r = check([wf_yaml], l_ok)
            assert rc == RC_OK, "rc=%d errors=%s" % (rc, r.get("errors"))
            assert r["A_workflow_domains"] == ["tokenrhythm.studio"], r["A_workflow_domains"]
            forms = r["workflow_face"][0]["domains"]["tokenrhythm.studio"]["forms"]
            assert "yaml" in forms, forms
            return "YAML env: 形态同守 rc=0（forms=%s）" % forms

        # ⑫ 注释行不计入 A；停用 export 由清单侧转红点名（不靠猜）
        def c_commented():
            rc, r = check([wf_commented], l_ok)
            assert rc == RC_DRIFT, "rc=%d（停用 export ⇒ 清单侧须红）" % rc
            assert r["extra_in_list"] == ["tokenrhythm.studio"], r["extra_in_list"]
            assert r["workflow_face"][0]["commented_export_lines"] == [4], \
                r["workflow_face"][0]["commented_export_lines"]
            return "注释行不计入 A，停用信号点名 L4 且清单侧转红"

        # ⑬ 两侧皆空 ⇒ rc=0（export 已清且清单已清）
        def c_both_empty():
            wf_empty = wf("wf-empty.yml", "steps:\n  - run: echo hi\n")
            l_empty = lst("list-empty.txt", "# 空清单\n\n")
            rc, r = check([wf_empty], l_empty)
            assert rc == RC_OK, "rc=%d" % rc
            assert r["A_workflow_domains"] == [] and r["B_list_domains"] == []
            return "两侧皆空 rc=0（空集合相等即零漂移）"

        # ⑭ 多作业面（--workflow 可重复）：第三处 export 面纳管后同样受闸
        def c_multi_workflow():
            rc, r = check([wf_ok, wf_drift], l_ok)
            assert rc == RC_DRIFT, "rc=%d" % rc
            assert r["missing_in_list"] == ["drift-added.example"], r["missing_in_list"]
            assert len(r["workflow_face"]) == 2, len(r["workflow_face"])
            return "多作业面合并判：第二面新增域名同样点名 rc=1"

        # ⑭ 二期扩展位：runner env 转储面折进 A 同闸核（一致 rc=0 / 漂移 rc=1）
        def c_runner_env_ok():
            rc, r = check([wf_ok], l_ok, [e_ok])
            assert rc == RC_OK, "rc=%d errors=%s" % (rc, r.get("errors"))
            return "runner-env 一致态 rc=0（扩展位在场）"

        def c_runner_env_drift():
            rc, r = check([wf_ok], l_ok, [e_drift])
            assert rc == RC_DRIFT, "rc=%d" % rc
            assert r["missing_in_list"] == ["runner-added.example"], r["missing_in_list"]
            return "runner-env 漂移态 rc=1 点名 runner-added.example"

        # ⑮ 子进程 CLI 入口（-I 隔离纪律）：一致 rc=0 / 漂移 rc=1
        def c_subprocess():
            tool = os.path.abspath(__file__)
            r1 = subprocess.run([sys.executable, "-I", tool, "--workflow", wf_ok,
                                 "--list", l_ok], capture_output=True, text=True, timeout=120)
            r2 = subprocess.run([sys.executable, "-I", tool, "--workflow", wf_drift,
                                 "--list", l_ok], capture_output=True, text=True, timeout=120)
            assert r1.returncode == RC_OK, "rc=%d %s" % (r1.returncode, r1.stderr[-300:])
            assert r2.returncode == RC_DRIFT, "rc=%d" % r2.returncode
            assert "VERDICT rc=0" in r1.stdout and "VERDICT rc=1" in r2.stdout
            return "子进程 CLI：一致 rc=0 / 漂移 rc=1（-I 隔离）"

        for name, fn in [
            ("一致态 ⇒ rc=0（A==B 零漂移）", c_ok),
            ("漂移态① 工作流新增域名未入清单 ⇒ rc=1 点名", c_drift_wf),
            ("漂移态② 清单多出 ⇒ rc=1 点名", c_drift_list),
            ("tamper 清单坏形态 ⇒ rc=2 fail-loud", c_tamper_badform),
            ("tamper 清单重复行 ⇒ rc=2 fail-loud", c_tamper_dup),
            ("tamper 清单缺席 ⇒ rc=2 fail-loud", c_tamper_missing_list),
            ("tamper 作业面缺席 ⇒ rc=2 fail-loud", c_tamper_missing_wf),
            ("tamper 作业面不可解码 ⇒ rc=2 fail-loud", c_tamper_undecodable),
            ("tamper 作业面通配符 ⇒ rc=2 fail-loud", c_tamper_wf_badform),
            ("变量引用 fidelity（${VAR} 不计入 A，透明计数）", c_varref),
            ("YAML env: 形态同守", c_yaml_form),
            ("注释行不计入 A，停用 export 信号点名", c_commented),
            ("两侧皆空 ⇒ rc=0", c_both_empty),
            ("多作业面（--workflow 可重复）合并判", c_multi_workflow),
            ("扩展位 runner-env 一致态 ⇒ rc=0", c_runner_env_ok),
            ("扩展位 runner-env 漂移态 ⇒ rc=1 点名", c_runner_env_drift),
            ("子进程 CLI 入口（-I）一致/漂移", c_subprocess),
        ]:
            case(name, fn)

        passed = 0
        for name, fn in cases:
            try:
                detail = fn()
            except AssertionError as exc:
                print("FAIL %s：%s" % (name, exc))
                continue
            except Exception as exc:               # 不可证不猜绿
                print("ERROR %s：%s: %s" % (name, type(exc).__name__, exc))
                continue
            passed += 1
            print("PASS %s —— %s" % (name, detail))
        print("SELFTEST %d/%d %s" % (passed, len(cases),
                                     "PASS" if passed == len(cases) else "FAIL"))
        return RC_OK if passed == len(cases) else RC_DRIFT
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
