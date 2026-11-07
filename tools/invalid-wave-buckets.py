#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""invalid-wave-buckets.py — 误拒率分桶直方图器（[真锚][D-137] · factory-os#152）

读什么（只读 artifact，零网络、零工作流改动）：
  manifest-validation.json 目录（planner 每波落盘的形制门校验读数；字段形制见
  .github/workflows/planner-core.yml:2340-2352——outcome/ok/wave/cards_total/
  new_cards/mem/missing_items/errors/warnings/v1_1）。另兼容无前缀裸名
  manifest-validation.json（单跑 artifact 目录直接落地即可读）。

算什么（宪章域1 DEF-15 / 判据 J-33，v1 只立读数不设容忍度）：
  ① 四态分离计数——idle / None / invalid / plan；None 态（outcome 键缺席或
     JSON null）单列禁混计（DEF-10 四态分离口径）。
  ② invalid 波按 M 码/SUB 码分解直方图——errors 串解析 `M-\\d+`/`SUB-\\d+`
     （现势 outcome_counts.invalid 是一个不分门码不分对错的桶，宪章 DEF-15
     可机检判据①）；missing_items 家族并列（门自身的逐 M 码计数，
     planner-core.yml:2337-2339）。
  ③ 每窗抽 N 例 invalid 的裁决对拍采样记录——按 (checked_at, 文件名) 排序后
     索引等距确定性选取（禁被审方自选，P4 防 Goodhart）；输出该拒/误拒两态
     留痕模板＋抽样依据（人权可覆写但须留痕）。
  ④ 口径注记段——直方图空≠无伤门（P2）；artifact 缺席点名、不计入分母（P3）。
  语义坐标（只读作证据，本器不改门）：
    .github/workflows/planner-core.yml:2334（outcome = "invalid" if errors
      else ("idle" if idle else "plan"——四态真源）
    .github/workflows/planner-core.yml:2239（M-4 错误串形制：
      "M-4: %s allowed_paths[%d] 命中判官面（judge-paths 登记表：%s）"）
    .github/workflows/planner-core.yml:2108-2123（M-6 错误串形制：task_id/
      debt 波内重复、双解占用、终态重复、无台账行四类）
    .github/workflows/planner-core.yml:2766/2903/3026/3039/3054（SUB-0..SUB-6
      错误串形制；SUB-4 为 amber 警告进 substance 段不拦——故 SUB 族声明含
      SUB-4 而 errors 直方图通常不见其码）
    .github/workflows/planner-core.yml:2337-2339（missing_items = 逐 M 码
      errors 计数——本器并列展示，不另立第二真源）
  实证伤门两例（宪章 :221，run#112 fail-closed）：errors 8 条两类=M-6×3
  「debt 无台账行」+M-4×3「allowed_paths 命中判官面 CODEOWNERS[/tools/]」
  ⇒ 候选未 commit 未建 Issue——该拒与误拒泡在同一桶里，正是本器要分解的面。

模式：
  --dir DIR [--out PATH] [--sample N]   读数（exit 0=计算成功——空窗/直方图
                                        空本身是诚实读数，禁为刷绿造数）
  --selftest                            夹具自证（零网络）：invalid 窗/idle 窗/
                                        坏行三夹具＋None 态/未知 outcome/无码
                                        错误串/SUB 码/artifact 缺席/空窗/采样
                                        选取八例临时目录边例

退出码：0=绿或计算成功；2=fail-loud（目录缺席、坏行非 JSON、JSON 非对象、
  outcome 值未知、--sample N<1——禁吞禁猜，禁 SKIP 冒充；未知≠0）。

纪律（卡面禁项照抄进代码）：
  P1 禁改在飞工作流：planner.yml / planner-core.yml / swev-judge-v2.py 只读，
    本器只立读数不修门（M-6/SUB-5 修法归运营者裁，宪章 CTX-2/DEF-5）；
  P2 禁把「invalid=0/直方图空」当「门完美」：输出必带口径注记；
  P3 artifact 缺席 ⇒ 未知≠0：缺席逐条点名、不计入分母；坏行 fail-loud；
  P4 判据/判官件零改动；对拍抽样由本器按 checked_at 确定性选取，禁被审方
    自选（抽样依据留痕，人权可覆写但须写 basis/reviewer/reviewed_at）。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- 常量

MANIFEST_SUFFIX = "-manifest-validation.json"
MANIFEST_BARE = "manifest-validation.json"
# 同窗共生的 planner artifact 族：其 manifest-validation.json 缺席 ⇒ 该 run
# 的 outcome 不可证（P3：点名缺席、不计入分母）。
SIBLING_SUFFIXES = ("-planner-raw.json", "-planner-call-log.json")

OUTCOMES = ("idle", "None", "invalid", "plan")  # 四态分离（DEF-10）

# 分解族声明（schema 级， provenance = planner-core.yml 只读坐标）：
#   M-1..M-8  = 形制门 missing_items 键族（planner-core.yml:2339）
#   SUB-0..6  = 08c 实质门码族（planner-core.yml:2766-3054；SUB-4 amber 不拦）
# 声明用途：空窗（invalid=0）时分解面仍须在输出 schema 内可导——禁把「直方图
# 空」呈现为「无分解面」。这是读数 schema 声明，不是门逻辑真源。
M_FAMILY = ["M-%d" % i for i in range(1, 9)]
SUB_FAMILY = ["SUB-%d" % i for i in range(0, 7)]

CODE_RE = re.compile(r"(?<![A-Za-z0-9-])(SUB-\d+|M-\d+)(?!\d)")

SCHEMA = "af.invalid-wave-buckets.v1"
CARD = "[真锚][D-137] factory-os#152（宪章域1 DEF-15 / 判据 J-33）"

# P2 口径标注（卡面禁项置顶）：直方图空≠无伤门。
CALIBER_EMPTY = (
    "直方图空 ≠ 无伤门：直方图空只证明该窗无 invalid 样本，不证明无系统性误拒"
    "（宪章 DEF-15：一道自带伤的唯一拦截层不能被记为质量防线在役）。"
    "一道把 100% 候选拒掉的坏门与一道完美的门，在四组数"
    "（空波率/成功率/出卡数/回评均分）上不可区分——故本读数必须存在。"
)
CALIBER_ABSENT = (
    "artifact 缺席 ⇒ 未知≠0：artifacts_absent 逐条点名、不计入分母（P3）。"
    "同窗共生件（*-planner-raw.json / *-planner-call-log.json）在场而其"
    "*-manifest-validation.json 缺席 ⇒ 该 run 的 outcome 不可证。"
)
CALIBER_FOUR_STATE = (
    "四态分离：idle/None/invalid/plan 分列计数；None 态（outcome 键缺席或 "
    "JSON null）单列，禁与 idle/plan 混计（DEF-10 口径）。"
)
CALIBER_SAMPLING = (
    "裁决对拍抽样由本器按 (checked_at, 文件名) 排序后索引等距确定性选取"
    "（P4 禁被审方自选防 Goodhart）；人权可覆写但须留痕——adjudication 模板"
    "的 verdict 只填「该拒」/「误拒」，basis/reviewer/reviewed_at 禁留空。"
)
CALIBER_NO_TOLERANCE = (
    "v1 不设误拒容忍度数字：无基线读数时设阈=编标准（宪章 DEF-15 v1 明示）。"
    "本器只立「读数必须存在 + 误拒率>0 即触发运营者裁」形制，不判过不判绿。"
)

FIXTURE_ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "invalid-wave-buckets")


class BucketError(Exception):
    """fail-loud（exit 2）：输入不可证——坏行/结构非法/目录缺席/未知 outcome。"""


# ---------------------------------------------------------------- 读数内核

def load_json_file(path):
    """读 JSON 件；非 JSON/非 UTF-8/读不动 ⇒ BucketError（坏行 fail-loud exit 2）。"""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except UnicodeDecodeError as e:
        raise BucketError("非 UTF-8（坏行）%s：%s" % (path, e))
    except OSError as e:
        raise BucketError("读不动 %s：%s" % (path, e))
    try:
        return json.loads(raw)
    except ValueError as e:
        raise BucketError("非 JSON（坏行）%s：%s" % (path, e))


def list_manifests(dirpath):
    """窗内 manifest-validation.json 件（含裸名），按文件名排序（确定性）。"""
    out = []
    for name in sorted(os.listdir(dirpath)):
        p = os.path.join(dirpath, name)
        if not os.path.isfile(p):
            continue
        if name.endswith(MANIFEST_SUFFIX) or name == MANIFEST_BARE:
            out.append(p)
    return out


def parse_codes(errors):
    """errors 串 ⇒ (by_code Counter 字典, unparsed 串列表)。

    `M-\\d+`/`SUB-\\d+` 前缀码从错误串原文抽取；无码串（如「manifest 命中凭据
    形态扫描」）进 unparsed 点名——禁猜码、禁吞（P3）。
    """
    by_code, unparsed = {}, []
    for e in errors:
        if not isinstance(e, str):
            unparsed.append(repr(e))
            continue
        codes = CODE_RE.findall(e)
        if not codes:
            unparsed.append(e)
            continue
        for c in codes:
            by_code[c] = by_code.get(c, 0) + 1
    return by_code, unparsed


def _sum_missing_items(docs):
    """missing_items 家族并列：逐键求和（键 union；缺键按 0）。"""
    fam = {}
    for d in docs:
        mi = d.get("missing_items")
        if not isinstance(mi, dict):
            continue
        for k, v in mi.items():
            if isinstance(v, bool) or not isinstance(v, int):
                continue
            fam[k] = fam.get(k, 0) + v
    return fam


def _absent_artifacts(dirpath, manifest_paths):
    """同窗共生件在场而其 manifest-validation.json 缺席 ⇒ 点名（不计入分母）。"""
    stems = set()
    for p in manifest_paths:
        base = os.path.basename(p)
        stems.add(base[:-len(MANIFEST_SUFFIX)]
                  if base.endswith(MANIFEST_SUFFIX) else base)
    absent = []
    for name in sorted(os.listdir(dirpath)):
        p = os.path.join(dirpath, name)
        if not os.path.isfile(p):
            continue
        for suf in SIBLING_SUFFIXES:
            if name.endswith(suf):
                stem = name[:-len(suf)]
                if stem and stem not in stems:
                    absent.append({"artifact": name,
                                   "reason": "同窗共生件在场而 %s%s 缺席——"
                                             "该 run 的 outcome 不可证"
                                             % (stem, MANIFEST_SUFFIX)})
                break
    return absent


def read_window(dirpath):
    """读窗 ⇒ 读数 dict。坏行/未知 outcome ⇒ BucketError（fail-loud exit 2）。"""
    if not os.path.isdir(dirpath):
        raise BucketError("目录缺席 %s——窗不可证（未知≠0，禁猜绿）" % dirpath)
    manifest_paths = list_manifests(dirpath)
    docs = []
    for p in manifest_paths:
        d = load_json_file(p)
        if not isinstance(d, dict):
            raise BucketError("JSON 非对象（坏行）%s——manifest-validation 须为"
                              " object，得 %s" % (p, type(d).__name__))
        oc = d.get("outcome", None)
        if oc is None:
            state = "None"
        elif oc in OUTCOMES:
            state = oc
        else:
            raise BucketError("outcome 值未知 %s：%r——四态（idle/None/invalid/"
                              "plan）之外不收（禁猜桶）" % (p, oc))
        docs.append((p, d, state))

    outcome_counts = {s: 0 for s in OUTCOMES}
    by_code, by_wave, unparsed = {}, {}, []
    for p, d, state in docs:
        outcome_counts[state] += 1
        if state != "invalid":
            continue
        errors = d.get("errors")
        if not isinstance(errors, list):
            raise BucketError("errors 非数组（坏行）%s——invalid 波 errors 须为"
                              " list，得 %s" % (p, type(errors).__name__))
        codes, unp = parse_codes(errors)
        for c, n in codes.items():
            by_code[c] = by_code.get(c, 0) + n
            by_wave[c] = by_wave.get(c, 0) + 1
        for u in unp:
            unparsed.append({"file": os.path.basename(p), "error": u})

    return {
        "schema": SCHEMA,
        "card": CARD,
        "dir": dirpath,
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(
            timespec="seconds"),
        "files_total": len(manifest_paths),
        "outcome_counts": outcome_counts,
        "invalid_waves": outcome_counts["invalid"],
        "histogram": {
            "by_code": dict(sorted(by_code.items())),
            "by_wave": dict(sorted(by_wave.items())),
            "missing_items_family": dict(sorted(_sum_missing_items(
                [d for _, d, _ in docs]).items())),
            "unparsed_errors": unparsed,
        },
        "decomposition_families": {"M": list(M_FAMILY), "SUB": list(SUB_FAMILY)},
        "artifacts_absent": _absent_artifacts(dirpath, manifest_paths),
        "caliber_notes": [CALIBER_EMPTY, CALIBER_ABSENT, CALIBER_FOUR_STATE,
                          CALIBER_SAMPLING, CALIBER_NO_TOLERANCE],
    }


def select_sample(reading, n):
    """按 (checked_at, 文件名) 排序后索引等距取 N 例 invalid 波（确定性）。

    等距而非取前 N：防时间窗偏置（只取最早/最晚几波）。人权可覆写但须留痕
    （P4）——覆写记录走 adjudication 模板字段，不改本器选取逻辑。
    """
    if n < 1:
        raise BucketError("--sample N 须 ≥1，得 %d（禁零样本/负样本冒充采样）" % n)
    cands = []
    for p in sorted(os.listdir(reading["dir"])):
        fp = os.path.join(reading["dir"], p)
        if not os.path.isfile(fp):
            continue
        if not (p.endswith(MANIFEST_SUFFIX) or p == MANIFEST_BARE):
            continue
        d = load_json_file(fp)
        if not isinstance(d, dict) or d.get("outcome") != "invalid":
            continue
        cands.append((str(d.get("checked_at") or ""), p, d))
    cands.sort(key=lambda t: (t[0], t[1]))
    if not cands:
        return [], {"basis": "窗内零 invalid 波——空窗是诚实读数，采样记录为空"
                            "（直方图空≠无伤门，见 caliber_notes）",
                    "candidates_total": 0, "requested": n, "selected": []}
    if len(cands) <= n:
        picked = list(range(len(cands)))
        basis = ("窗内 invalid 波 %d 例 ≤ N=%d，全取（按 (checked_at, 文件名) "
                 "排序）" % (len(cands), n))
    else:
        picked = [round(i * (len(cands) - 1) / (n - 1)) for i in range(n)]
        basis = ("窗内 invalid 波 %d 例 > N=%d，按 (checked_at, 文件名) 排序后"
                 "索引等距取 %s（禁取前 N——防时间窗偏置；P4 禁被审方自选）"
                 % (len(cands), n, picked))
    recs = []
    for i in picked:
        _, name, d = cands[i]
        codes, _ = parse_codes(d.get("errors") or [])
        recs.append({
            "file": name,
            "checked_at": d.get("checked_at"),
            "wave": d.get("wave"),
            "outcome": "invalid",
            "cards_total": d.get("cards_total"),
            "codes": dict(sorted(codes.items())),
            "errors": d.get("errors"),
            "adjudication": {          # 该拒/误拒两态留痕模板（P4）
                "verdict": None,       # 只填「该拒」/「误拒」
                "basis": "",
                "reviewer": "",
                "reviewed_at": "",
            },
        })
    return recs, {"basis": basis, "candidates_total": len(cands),
                  "requested": n,
                  "selected": [r["file"] for r in recs]}


def render_sample(recs, sel):
    """采样记录渲染（人读面）：候选＋checked_at 选取依据＋该拒/误拒两态模板。"""
    lines = ["== 裁决对拍采样记录（该拒/误拒两态留痕 · P4 抽样由本器确定性选取）=="]
    lines.append("抽样依据：%s" % sel["basis"])
    lines.append("候选总数 %d，本次取 %d 例：%s"
                 % (sel["candidates_total"], len(sel["selected"]),
                    ", ".join(sel["selected"]) or "（空窗——零 invalid 样本）"))
    if not recs:
        lines.append("（空窗：零 invalid 候选——直方图空≠无伤门，见 caliber_notes）")
        return "\n".join(lines)
    for i, r in enumerate(recs, 1):
        lines.append("—— 例%d：%s（checked_at=%s wave=%s cards_total=%s）"
                     % (i, r["file"], r["checked_at"], r["wave"],
                        r["cards_total"]))
        lines.append("   分解码：%s" % (json.dumps(r["codes"], ensure_ascii=False)
                                        if r["codes"] else "（无码错误串——见 "
                                        "unparsed_errors）"))
        for e in (r["errors"] or []):
            lines.append("   error：%s" % e)
        lines.append("   对拍留痕（人权可覆写但须填全）：verdict=[该拒|误拒] "
                     "basis=______ reviewer=______ reviewed_at=______")
    lines.append("== 留痕纪律：verdict 只填「该拒」/「误拒」；误拒率>0 即触发"
                 "运营者裁（v1 不设容忍度数字，宪章 DEF-15）==")
    return "\n".join(lines)


# ---------------------------------------------------------------- 夹具自证

def _fixture_doc(stem, outcome, errors=None, checked_at="2026-11-07T13:32:29+08:00",
                 wave="wave-09", cards_total=1):
    """造一份 manifest-validation.json 形制的 fixture dict（M-6/M-4 计数同门）。"""
    errors = errors or []
    missing = {k: sum(1 for e in errors if e.startswith(k + ":"))
               for k in M_FAMILY}
    return {
        "checked_at": checked_at,
        "outcome": outcome,
        "ok": not errors,
        "wave": wave,
        "cards_total": cards_total,
        "new_cards": 0 if (errors or outcome == "idle") else cards_total,
        "mem": {"anolis_sum_g": 0, "local_sum_g": 0, "anolis_cards": 0,
                "bot_cards": 0},
        "missing_items": missing,
        "errors": errors,
        "warnings": [],
        "v1_1": {"schema_spec": "af.wave-manifest.v1.1", "optional_fields": [],
                 "card_field_names_union": [], "key_completed": []},
    }


def selftest():
    """三夹具（invalid 窗/idle 窗/坏行）＋八例临时目录边例。返回 (fails, total)。"""
    fails = []

    def check(name, cond, detail=""):
        if not cond:
            fails.append("%s %s" % (name, detail))

    # —— 夹具一：invalid 窗（M-6×3+M-4×3，3 文件 × 每件 1×M-6+1×M-4）——————
    iw = os.path.join(FIXTURE_ROOT, "invalid-window")
    r = read_window(iw)
    oc = r["outcome_counts"]
    check("invalid窗.invalid=3", oc["invalid"] == 3, "得 %r" % oc["invalid"])
    check("invalid窗.idle=0", oc["idle"] == 0, "得 %r" % oc["idle"])
    check("invalid窗.None=0", oc["None"] == 0, "得 %r" % oc["None"])
    h = r["histogram"]
    check("invalid窗.M-6=3", h["by_code"].get("M-6") == 3,
          "得 %r" % h["by_code"].get("M-6"))
    check("invalid窗.M-4=3", h["by_code"].get("M-4") == 3,
          "得 %r" % h["by_code"].get("M-4"))
    check("invalid窗.by_wave", h["by_wave"] == {"M-4": 3, "M-6": 3},
          "得 %r" % h["by_wave"])
    check("invalid窗.missing族并列",
          h["missing_items_family"].get("M-6") == 3
          and h["missing_items_family"].get("M-4") == 3
          and h["missing_items_family"].get("M-1") == 0,
          "得 %r" % h["missing_items_family"])
    check("invalid窗.无无码串", h["unparsed_errors"] == [],
          "得 %r" % h["unparsed_errors"])
    check("invalid窗.零缺席", r["artifacts_absent"] == [],
          "得 %r" % r["artifacts_absent"])
    check("invalid窗.分解族在场",
          "M-6" in r["decomposition_families"]["M"]
          and "SUB-5" in r["decomposition_families"]["SUB"])
    recs, sel = select_sample(r, 2)
    check("invalid窗.采样2例", len(recs) == 2 and sel["candidates_total"] == 3,
          "得 %d/%d" % (len(recs), sel["candidates_total"]))
    check("invalid窗.采样确定性", [x["file"] for x in recs] == sel["selected"],
          "得 %r vs %r" % ([x["file"] for x in recs], sel["selected"]))
    check("invalid窗.采样等距", sel["selected"] == sorted(sel["selected"]),
          "得 %r" % sel["selected"])
    check("invalid窗.两态模板",
          all(x["adjudication"]["verdict"] is None
              and x["adjudication"]["basis"] == "" for x in recs))
    check("invalid窗.采样依据在场", "checked_at" in sel["basis"]
          and "等距" in sel["basis"], "得 %r" % sel["basis"])
    txt = render_sample(recs, sel)
    check("invalid窗.渲染含该拒误拒", "该拒" in txt and "误拒" in txt)
    check("invalid窗.渲染含选取依据", "抽样依据" in txt)

    # —— 夹具二：idle 窗（空 errors——不误桶）————————————————
    dw = os.path.join(FIXTURE_ROOT, "idle-window")
    r = read_window(dw)
    oc = r["outcome_counts"]
    check("idle窗.idle=1", oc["idle"] == 1, "得 %r" % oc["idle"])
    check("idle窗.invalid=0", oc["invalid"] == 0, "得 %r" % oc["invalid"])
    check("idle窗.直方图空", r["histogram"]["by_code"] == {},
          "得 %r" % r["histogram"]["by_code"])
    check("idle窗.分解族仍可导", "M-6" in json.dumps(
        r["decomposition_families"], ensure_ascii=False))
    check("idle窗.口径注记在场", any("直方图空" in n for n in r["caliber_notes"]))
    recs, sel = select_sample(r, 2)
    check("idle窗.采样空", recs == [] and sel["candidates_total"] == 0)
    check("idle窗.空窗渲染", "空窗" in render_sample(recs, sel))

    # —— 夹具三：坏行（非 JSON ⇒ fail-loud exit 2）——库内抛 + 子进程实测 ——
    bl = os.path.join(FIXTURE_ROOT, "bad-row")
    try:
        read_window(bl)
        check("坏行.库内抛", False, "未抛 BucketError")
    except BucketError:
        pass
    for extra in ([], ["--sample", "2"], ["--out", os.path.join(
            tempfile.gettempdir(), "d137-badrow-should-not-exist.json")]):
        p = subprocess.run(
            [sys.executable, "-I", os.path.abspath(__file__), "--dir", bl] + extra,
            capture_output=True, text=True)
        check("坏行.子进程%s=rc2" % ("+sample" if extra[:1] == ["--sample"]
                                    else ("+out" if extra else "")),
              p.returncode == 2 and "坏行" in p.stderr,
              "得 rc=%r stderr=%s" % (p.returncode, p.stderr[-200:]))
    check("坏行.不落读数", not os.path.exists(os.path.join(
        tempfile.gettempdir(), "d137-badrow-should-not-exist.json")))

    # —— 边例一（临时目录）：None 态单列禁混计 ——————————————————
    d = tempfile.mkdtemp(prefix="d137-selftest-")
    try:
        with open(os.path.join(d, "a" + MANIFEST_SUFFIX), "w",
                  encoding="utf-8") as f:
            json.dump(_fixture_doc("a", None, checked_at="2026-11-07T10:00:00+08:00",
                                   cards_total=0), f)
        with open(os.path.join(d, "b" + MANIFEST_SUFFIX), "w",
                  encoding="utf-8") as f:
            json.dump(_fixture_doc("b", "idle", checked_at="2026-11-07T10:05:00+08:00",
                                   cards_total=0), f)
        r = read_window(d)
        check("None态.单列", r["outcome_counts"]["None"] == 1
              and r["outcome_counts"]["idle"] == 1,
              "得 %r" % r["outcome_counts"])
        check("None态.不计invalid", r["invalid_waves"] == 0)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # —— 边例二（临时目录）：未知 outcome ⇒ fail-loud exit 2 ——————————
    d = tempfile.mkdtemp(prefix="d137-selftest-")
    try:
        with open(os.path.join(d, "a" + MANIFEST_SUFFIX), "w",
                  encoding="utf-8") as f:
            json.dump(_fixture_doc("a", "unknown-state"), f)
        try:
            read_window(d)
            check("未知outcome.库内抛", False, "未抛 BucketError")
        except BucketError:
            pass
        p = subprocess.run([sys.executable, "-I", os.path.abspath(__file__),
                            "--dir", d], capture_output=True, text=True)
        check("未知outcome.子进程=rc2", p.returncode == 2
              and "outcome 值未知" in p.stderr,
              "得 rc=%r stderr=%s" % (p.returncode, p.stderr[-200:]))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # —— 边例三（临时目录）：无码错误串点名进 unparsed（禁猜码禁吞）——————
    d = tempfile.mkdtemp(prefix="d137-selftest-")
    try:
        with open(os.path.join(d, "a" + MANIFEST_SUFFIX), "w",
                  encoding="utf-8") as f:
            json.dump(_fixture_doc("a", "invalid", errors=[
                "manifest 命中凭据形态扫描——fail-closed（secret 禁入 git）"]), f)
        r = read_window(d)
        check("无码串.点名", len(r["histogram"]["unparsed_errors"]) == 1
              and "凭据形态" in r["histogram"]["unparsed_errors"][0]["error"],
              "得 %r" % r["histogram"]["unparsed_errors"])
        check("无码串.不进by_code", r["histogram"]["by_code"] == {},
              "得 %r" % r["histogram"]["by_code"])
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # —— 边例四（临时目录）：SUB 码分解（SUB-5×1+SUB-6×2）————————————————
    d = tempfile.mkdtemp(prefix="d137-selftest-")
    try:
        with open(os.path.join(d, "a" + MANIFEST_SUFFIX), "w",
                  encoding="utf-8") as f:
            json.dump(_fixture_doc("a", "invalid", errors=[
                "SUB-5: card-x（task_id=t）debt 锚 D-1 台账行带显式裁决标记 "
                "【待裁】——须先落裁决",
                "SUB-6: card-x（task_id=t）debt 锚 D-2 台账行不在场"
                "（计划/阶段欠账台账.md）——锚可施工性不可证"]), f)
        r = read_window(d)
        check("SUB码.SUB-5=1", r["histogram"]["by_code"].get("SUB-5") == 1,
              "得 %r" % r["histogram"]["by_code"])
        check("SUB码.SUB-6=1", r["histogram"]["by_code"].get("SUB-6") == 1,
              "得 %r" % r["histogram"]["by_code"])
        check("SUB码.无M码误并", "M-6" not in r["histogram"]["by_code"],
              "得 %r" % r["histogram"]["by_code"])
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # —— 边例五（临时目录）：artifact 缺席点名、不计入分母 ——————————————
    d = tempfile.mkdtemp(prefix="d137-selftest-")
    try:
        with open(os.path.join(d, "run-1" + MANIFEST_SUFFIX), "w",
                  encoding="utf-8") as f:
            json.dump(_fixture_doc("run-1", "idle", cards_total=0), f)
        with open(os.path.join(d, "run-2-planner-raw.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"model": "fixture", "attempts": 1, "calls": []}, f)
        r = read_window(d)
        check("缺席.点名", len(r["artifacts_absent"]) == 1
              and r["artifacts_absent"][0]["artifact"] == "run-2-planner-raw.json",
              "得 %r" % r["artifacts_absent"])
        check("缺席.不计分母", r["outcome_counts"] ==
              {"idle": 1, "None": 0, "invalid": 0, "plan": 0},
              "得 %r" % r["outcome_counts"])
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # —— 边例六（临时目录）：空窗 exit 0（诚实读数，禁 fail-loud 造绿）—————
    d = tempfile.mkdtemp(prefix="d137-selftest-")
    try:
        r = read_window(d)
        check("空窗.files_total=0", r["files_total"] == 0)
        check("空窗.四态全零", all(v == 0 for v in r["outcome_counts"].values()))
        check("空窗.直方图空", r["histogram"]["by_code"] == {})
        p = subprocess.run([sys.executable, "-I", os.path.abspath(__file__),
                            "--dir", d], capture_output=True, text=True)
        check("空窗.子进程=rc0", p.returncode == 0,
              "得 rc=%r stderr=%s" % (p.returncode, p.stderr[-200:]))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # —— 边例七（临时目录）：--sample N>len(invalid) ⇒ 全取不炸 ——————————
    d = tempfile.mkdtemp(prefix="d137-selftest-")
    try:
        with open(os.path.join(d, "a" + MANIFEST_SUFFIX), "w",
                  encoding="utf-8") as f:
            json.dump(_fixture_doc("a", "invalid", errors=[
                "M-6: card-a debt 无台账行（占用闸 fail-closed）：D-9"]), f)
        r = read_window(d)
        recs, sel = select_sample(r, 5)
        check("超采.全取1例", len(recs) == 1 and sel["candidates_total"] == 1,
              "得 %d/%d" % (len(recs), sel["candidates_total"]))
        check("超采.依据注明", "全取" in sel["basis"])
        try:
            select_sample(r, 0)
            check("超采.N=0抛", False, "未抛 BucketError")
        except BucketError:
            pass
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # —— 边例八（临时目录）：等距选取确定性（3 候选取 2 ⇒ 首末）——————————
    d = tempfile.mkdtemp(prefix="d137-selftest-")
    try:
        for i, ts in enumerate(["2026-11-07T09:00:00+08:00",
                                "2026-11-07T10:00:00+08:00",
                                "2026-11-07T11:00:00+08:00"]):
            with open(os.path.join(d, "w%d%s" % (i, MANIFEST_SUFFIX)), "w",
                      encoding="utf-8") as f:
                json.dump(_fixture_doc("w%d" % i, "invalid",
                                       errors=["M-6: card-w%d debt 无台账行"
                                               "（占用闸 fail-closed）：D-%d"
                                               % (i, i)],
                                       checked_at=ts), f)
        r = read_window(d)
        recs1, sel1 = select_sample(r, 2)
        recs2, sel2 = select_sample(r, 2)
        check("等距.首末两例", sel1["selected"] ==
              ["w0-manifest-validation.json", "w2-manifest-validation.json"],
              "得 %r" % sel1["selected"])
        check("等距.两次同果", [x["file"] for x in recs1] ==
              [x["file"] for x in recs2] and sel1["basis"] == sel2["basis"])
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # 夹具一 15 + 夹具二 7 + 夹具三 5 + 边例 2+2+2+3+2+4+2+2 = 44 项断言
    return fails, 44


# ---------------------------------------------------------------- CLI

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        description="D-137 误拒率分桶直方图器（四态分离＋M/SUB 码分解直方图＋"
                    "裁决对拍采样；零网络零工作流改动）")
    ap.add_argument("--dir", help="manifest-validation.json 目录（读数窗）")
    ap.add_argument("--out", help="读数 JSON 落盘路径（缺省只打 stdout）")
    ap.add_argument("--sample", type=int, metavar="N",
                    help="每窗抽 N 例 invalid 渲染裁决对拍采样记录（按 checked_at "
                         "确定性选取）")
    ap.add_argument("--selftest", action="store_true",
                    help="夹具自证（零网络）")
    args = ap.parse_args(argv)

    if args.selftest:
        fails, total = selftest()
        if fails:
            print("FAIL selftest %d/%d 过：" % (total - len(fails), total),
                  file=sys.stderr)
            for f in fails:
                print("  [FAIL] %s" % f, file=sys.stderr)
            return 1
        print("selftest %d/%d 过（invalid 窗 M-6×3/M-4×3 分解正确＋采样 2 例"
              "等距确定性＋两态模板／idle 窗不误桶且直方图空≠无伤门／坏行 "
              "fail-loud exit 2 库内+子进程双测；边例：None 态单列/未知 "
              "outcome 拒收/无码串点名/SUB 码分解/artifact 缺席不计分母/空窗 "
              "rc=0/超采全取/N=0 拒收/等距两次同果）" % (total, total))
        return 0

    if not args.dir:
        ap.error("需 --dir（读数窗）或 --selftest")
    try:
        reading = read_window(args.dir)
        recs, sel = ([], {"basis": "（未请求采样）", "candidates_total": 0,
                          "requested": 0, "selected": []})
        if args.sample is not None:
            recs, sel = select_sample(reading, args.sample)
    except BucketError as e:
        print("FAIL-LOUD（exit 2，禁吞禁猜）：%s" % e, file=sys.stderr)
        return 2

    reading["sample"] = {"basis": sel["basis"], "candidates_total":
                         sel["candidates_total"], "requested":
                         sel["requested"], "records": recs}
    if args.out:
        outdir = os.path.dirname(os.path.abspath(args.out))
        if outdir and not os.path.isdir(outdir):
            os.makedirs(outdir, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(reading, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("读数落盘 %s" % args.out)
    oc = reading["outcome_counts"]
    print("窗 %s：files_total=%d 四态 idle=%d/None=%d/invalid=%d/plan=%d"
          % (args.dir, reading["files_total"], oc["idle"], oc["None"],
             oc["invalid"], oc["plan"]))
    print("直方图 by_code=%s by_wave=%s"
          % (json.dumps(reading["histogram"]["by_code"], ensure_ascii=False),
             json.dumps(reading["histogram"]["by_wave"], ensure_ascii=False)))
    print("missing_items 族=%s unparsed=%d artifacts_absent=%d"
          % (json.dumps(reading["histogram"]["missing_items_family"],
                        ensure_ascii=False),
             len(reading["histogram"]["unparsed_errors"]),
             len(reading["artifacts_absent"])))
    for n in reading["caliber_notes"]:
        print("口径：%s" % n)
    if args.sample is not None:
        print()
        print(render_sample(recs, sel))
    return 0


if __name__ == "__main__":
    sys.exit(main())
