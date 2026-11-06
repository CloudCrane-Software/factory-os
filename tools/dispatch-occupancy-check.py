#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""债号占用机检器（D2 全档阻断的机器面）—— P1 新建面。

为什么建（依据 30-工件/外派-bot-试点/长效机制方案-draft.md §3.3 C1–C5 + D-决议 D2）：
  · D-决议 D2：「占用机检 ①：**P1 内全档阻断**、不追溯三笔」⇒ 本件是派前必过的那一道机器闸。
  · §3.3 C4：任一面**不可解析 ⇒ fail-closed ⇒ 拒派**（不许因为读不到就放行）⇒ 本件 fail-closed。
  · §3.3 C2/C3：台账状态列不是占用权威面（它写「未开始/部分/迁移」也允许占用；
    写「✅」而另一面仍有 active ⇒ 冲突 ⇒ 拒派新占用）。
  · 「同题双解活例在烧双份成本」（D-决议 D2 一句理由）⇒ 这道闸要拦的正是它。

三面读法（本件实现的面；每面都给出**占用证据坐标**）：
  A 台账面   计划/阶段欠账台账.md 的该债号行的**状态列**（读行号 + 状态原文）
  B 登记面   30-工件/外派-bot-试点/外派登记.json 里**无同债号 active**（外派 lane 在飞态）
             ＋ af-state/dispatch/registry.json（注册表权威面；存在即读，不存在则跳过并提示）
  C 在飞面   状态/wf-gate/registry.json 的 **active** 条目（厂内在飞）
             ＋ 最近外派记录面（30-工件/外派-bot-试点/tasks/ 任务卡 + slices/ 切片）里同债号在飞的件
             ＋ 可选 --log 外派日志 grep

判定：三面全过 ⇒ **ALLOW**（rc=0）；任一面已占 ⇒ **BLOCK**（rc=1）并逐条打印占用证据坐标；
任一面不可解析 ⇒ 不可证 ⇒ 同样拒派（rc=2，fail-closed，不猜绿）。

占用态词表（三面统一口径，避免三套词）：
  登记面 item.state：published-awaiting-bot / claimed / submitted   ⇒ 在飞（占用）
                     folded-factory                                  ⇒ 已归厂内面（占用；不得再外派）
                     brief-ready-awaiting-hang                       ⇒ 待发（不占用，出提示）
                     merged / rejected / audited-green-content / reclaimed ⇒ 已结（不占用）
                     其它未知词                                        ⇒ 不可证（占用，fail-closed）
  注册表 task.state：published / claimed / submitted                 ⇒ 在飞（占用）
                     verdict 以 folded 开头                           ⇒ 已归厂内面（占用）
                     其余（queued / packaged / adjudicated / merged / rejected）⇒ 不占用
  wf-gate entry.state：active                                       ⇒ 在飞（占用）
  台账状态列：含「✅」⇒ 已销项（不占用）；含在飞词（在飞/施工中/进行中/在途/已派/派中/外派中）
              ⇒ 占用；未开始/部分/迁移等开放词 ⇒ 开放（不占用，但按 C2 出「状态列与占用面不一致」提示）

用法：
  python3 tools/dispatch-occupancy-check.py RT-E82
  python3 tools/dispatch-occupancy-check.py --debt RT-E82 --json
  python3 tools/dispatch-occupancy-check.py --selftest

退出码：0=ALLOW；1=BLOCK（已占）；2=不可证（fail-closed，等价拒派）。
本件零网络、零凭据正文；**只读**既有台账/登记面，不改 bot-reclaim / bot-scrub / bot-slice（止血批在飞）。
"""
import json
import os
import re
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_MD = os.path.join(ROOT, "计划", "阶段欠账台账.md")
DISPATCH_JSON = os.path.join(ROOT, "30-工件", "外派-bot-试点", "外派登记.json")
REGISTRY_JSON = os.path.join(ROOT, "af-state", "dispatch", "registry.json")
WF_GATE = os.path.join(ROOT, "状态", "wf-gate", "registry.json")
TASKS_DIR = os.path.join(ROOT, "30-工件", "外派-bot-试点", "tasks")
SLICES_DIR = os.path.join(ROOT, "30-工件", "外派-bot-试点", "slices")

# 占用态词表（见文件头）
ITEM_OCCUPYING = {"published-awaiting-bot", "claimed", "submitted", "folded-factory"}
ITEM_PENDING = {"brief-ready-awaiting-hang"}
ITEM_DONE = {"merged", "rejected", "audited-green-content", "reclaimed"}
REG_OCCUPYING = {"published", "claimed", "submitted"}
WF_INFLIGHT = {"active", "claimed", "in-flight", "inflight"}

# 台账状态列里的「在飞」词（不含「在役」——在役是既有部署，不是在飞占用）
INFLIGHT_MARKERS = ("在飞", "施工中", "进行中", "在途", "已派", "派中", "外派中",
                    "处理中", "认领", "占用中")
DONE_MARK = "✅"


# ---------------------------------------------------------------- 小工具

def rel(path):
    try:
        return os.path.relpath(path, ROOT)
    except ValueError:
        return path


def debt_regex(debt_id):
    """把债号编译成可在任意文本里定位的正则（容忍 P3-A1 / p3a1 / P3 A1 写法差异）。

    形如：RT-E82 → R[\\s\\-_]*T[\\s\\-_]*E[\\s\\-_]*8[\\s\\-_]*2（字母数字间可无分隔），
    前后用 (?<![A-Za-z0-9]) / (?![A-Za-z0-9]) 卡边界 ⇒ 不把 RT-E13 匹到 RT-E138。
    """
    parts = re.findall(r"[A-Za-z]+|\d+", debt_id or "")
    if not parts:
        return None
    sep = r"[\s\-_·．.]*"
    pat = sep.join(re.escape(p) for p in parts)
    return re.compile(r"(?<![A-Za-z0-9])" + pat + r"(?![A-Za-z0-9])", re.IGNORECASE)


def match_line(rx, text):
    if rx is None or not text:
        return None
    m = rx.search(text)
    if not m:
        return None
    return m.group(0)


# ---------------------------------------------------------------- 面 A：台账

def face_ledger(debt_id, path):
    """读台账该债号行的状态列。返回 face dict。"""
    face = {"face": "A-台账面", "surface": rel(path), "verdict": "UNKNOWN",
            "detail": "", "coordinate": "", "evidence": [], "notes": []}
    if not os.path.exists(path):
        face["verdict"] = "UNKNOWN"
        face["detail"] = "台账文件缺失：%s（不可解析 ⇒ fail-closed）" % rel(path)
        return face
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception as exc:                       # noqa: BLE001
        face["verdict"] = "UNKNOWN"
        face["detail"] = "台账不可读：%s（%s）" % (rel(path), exc)
        return face

    header_idx = None
    status_idx = None
    hit = None
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip().strip("|").split("|")]
        if cells and cells[0] == "编号":
            header_idx = i
            status_idx = None
            for j, c in enumerate(cells):
                if c == "状态":
                    status_idx = j
            if status_idx is None:
                status_idx = len(cells) - 1
            continue
        if not cells:
            continue
        if cells[0].strip().upper() == debt_id.strip().upper():
            hit = (i, cells)
            break
    if hit is None:
        face["verdict"] = "NO-ROW"
        face["detail"] = "台账无「%s」行（该债号未入账 ⇒ 不可证 ⇒ 拒派；" \
                         "--allow-missing-ledger-row 可降级为提示）" % debt_id
        return face
    lineno, cells = hit
    if status_idx is None or status_idx >= len(cells):
        face["verdict"] = "UNKNOWN"
        face["detail"] = "台账行状态列缺失（行 %d，列数 %d）⇒ 不可证" % (lineno, len(cells))
        face["coordinate"] = "%s:%d" % (rel(path), lineno)
        return face
    status = cells[status_idx].strip()
    face["coordinate"] = "%s:%d（状态列）" % (rel(path), lineno)
    face["detail"] = "状态列=%s" % (status if status else "(空)")
    if not status:
        face["verdict"] = "UNKNOWN"
        face["notes"].append("状态列为空 ⇒ 不可证 ⇒ 拒派")
        return face
    if DONE_MARK in status:
        face["verdict"] = "DONE"
        face["notes"].append("台账已销项（✅）⇒ 台账侧不构成占用；"
                             "若另一面仍有 active ⇒ C3 冲突（销项优先，但不得自动放行新占用）")
        return face
    if any(mk in status for mk in INFLIGHT_MARKERS):
        face["verdict"] = "OCCUPIED"
        face["evidence"] = [face["coordinate"]]
        face["notes"].append("台账状态列自称在飞 ⇒ 占用证据")
        return face
    face["verdict"] = "OPEN"
    face["notes"].append("台账开放态（非未开始/部分/迁移 也算开放）⇒ 台账侧不构成占用；"
                          "若四面皆无 active，占用行需记 reason=台账状态列与占用面不一致（C2）")
    return face


# ---------------------------------------------------------------- 面 B：登记面

def _item_state_verdict(state):
    """返回 (verdict, note)。verdict ∈ OCCUPIED / PENDING / DONE / UNKNOWN。"""
    s = (state or "").strip()
    if not s:
        return "UNKNOWN", "条目无 state 字段 ⇒ 不可证（fail-closed）"
    if s in ITEM_OCCUPYING:
        note = "外派 lane 在飞（state=%s）" % s
        if s == "folded-factory":
            note = "已改道厂内面（state=folded-factory）⇒ 该债号已归厂内，不得再外派"
        return "OCCUPIED", note
    if s in ITEM_PENDING:
        return "PENDING", "任务书已备待发（state=%s）⇒ 不算占用，但发布前须确认是否同一笔" % s
    if s in ITEM_DONE:
        return "DONE", "已结（state=%s）⇒ 不占用" % s
    return "UNKNOWN", "未知 state=%s ⇒ 不可证（fail-closed）" % s


def face_dispatch(debt_id, dispatch_json, registry_json):
    face = {"face": "B-登记面", "surface": "%s ＋ %s" % (rel(dispatch_json), rel(registry_json)),
            "verdict": "CLEAN", "detail": "", "coordinate": "", "evidence": [], "notes": []}
    rx = debt_regex(debt_id)
    occ = 0
    # B1 外派登记.json（人读投影）
    if not os.path.exists(dispatch_json):
        face["verdict"] = "UNKNOWN"
        face["detail"] = "外派登记面缺失：%s（不可解析 ⇒ fail-closed）" % rel(dispatch_json)
        return face
    try:
        with open(dispatch_json, "r", encoding="utf-8") as f:
            proj = json.load(f)
    except Exception as exc:                       # noqa: BLE001
        face["verdict"] = "UNKNOWN"
        face["detail"] = "外派登记面不可解析：%s（%s）" % (rel(dispatch_json), exc)
        return face
    items = proj.get("items")
    if not isinstance(items, list):
        face["verdict"] = "UNKNOWN"
        face["detail"] = "外派登记面无 items 列表 ⇒ 不可证"
        return face
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        debt_txt = it.get("debt") or it.get("debt_id") or ""
        if not match_line(rx, str(debt_txt)):
            continue
        v, note = _item_state_verdict(it.get("state"))
        coord = "%s:items[%d].state" % (rel(dispatch_json), idx)
        if v == "OCCUPIED":
            occ += 1
            face["evidence"].append("%s（task_id=%s，state=%s）"
                                    % (coord, it.get("task_id"), it.get("state")))
            face["notes"].append("%s：%s" % (it.get("task_id"), note))
        elif v == "PENDING":
            face["notes"].append("%s：%s" % (it.get("task_id"), note))
        elif v == "UNKNOWN":
            occ += 1
            face["evidence"].append("%s（task_id=%s，state=%r）"
                                    % (coord, it.get("task_id"), it.get("state")))
            face["notes"].append("%s：%s" % (it.get("task_id"), note))
        else:
            face["notes"].append("%s：%s" % (it.get("task_id"), note))
    # B2 注册表（权威面；存在即读）
    if os.path.exists(registry_json):
        try:
            with open(registry_json, "r", encoding="utf-8") as f:
                reg = json.load(f)
            reg_tasks = reg.get("tasks", {}) if isinstance(reg, dict) else {}
            if not isinstance(reg_tasks, dict):
                reg_tasks = {}
        except Exception as exc:                   # noqa: BLE001
            occ += 1
            face["verdict"] = "UNKNOWN"
            face["evidence"].append("%s（不可解析：%s）" % (rel(registry_json), exc))
            face["notes"].append("注册表不可解析 ⇒ 不可证（fail-closed）")
            reg_tasks = {}
        for tid, t in sorted(reg_tasks.items()):
            if not isinstance(t, dict):
                continue
            if not match_line(rx, str(t.get("debt_id") or "")):
                continue
            st = t.get("state") or ""
            verdict = (t.get("verdict") or "")
            occupied = st in REG_OCCUPYING or verdict.startswith("folded")
            coord = "%s:tasks[%s].state" % (rel(registry_json), tid)
            if occupied:
                occ += 1
                face["evidence"].append("%s（state=%s，verdict=%s）" % (coord, st, verdict or "-"))
                face["notes"].append("%s：注册表登记在飞（state=%s）⇒ 占用" % (tid, st))
            else:
                face["notes"].append("%s：注册表 state=%s ⇒ 不占用" % (tid, st))
    else:
        face["notes"].append("注册表不存在（%s）⇒ B 面只读了外派登记面" % rel(registry_json))
    if occ:
        face["verdict"] = "OCCUPIED"
        face["detail"] = "同债号占用证据 %d 条" % occ
    else:
        face["verdict"] = "CLEAN"
        face["detail"] = "外派登记面 + 注册表均无同债号在飞"
    return face


# ---------------------------------------------------------------- 面 C：在飞面

def _wf_entry_text(e):
    return " ".join(str(e.get(k) or "") for k in ("id", "label", "note"))


def face_inflight(debt_id, wf_gate, tasks_dir, slices_dir, extra_logs):
    face = {"face": "C-在飞面",
            "surface": "%s ＋ %s ＋ %s" % (rel(wf_gate), rel(tasks_dir), rel(slices_dir)),
            "verdict": "CLEAN", "detail": "", "coordinate": "", "evidence": [], "notes": []}
    rx = debt_regex(debt_id)
    occ = 0
    # C1 wf-gate 在飞登记
    if not os.path.exists(wf_gate):
        face["verdict"] = "UNKNOWN"
        face["detail"] = "wf-gate 台账缺失：%s（不可解析 ⇒ fail-closed）" % rel(wf_gate)
        return face
    try:
        with open(wf_gate, "r", encoding="utf-8") as f:
            wg = json.load(f)
    except Exception as exc:                       # noqa: BLE001
        face["verdict"] = "UNKNOWN"
        face["detail"] = "wf-gate 台账不可解析：%s（%s）" % (rel(wf_gate), exc)
        return face
    entries = wg.get("entries") if isinstance(wg, dict) else None
    if not isinstance(entries, list):
        face["verdict"] = "UNKNOWN"
        face["detail"] = "wf-gate 台账无 entries 列表 ⇒ 不可证"
        return face
    for idx, e in enumerate(entries):
        if not isinstance(e, dict):
            continue
        st = (e.get("state") or "").strip().lower()
        if st not in WF_INFLIGHT:
            continue
        hit = match_line(rx, _wf_entry_text(e))
        if not hit:
            continue
        occ += 1
        face["evidence"].append("%s:entries[%d]（id=%s，state=%s，命中=%s）"
                                % (rel(wf_gate), idx, e.get("id"), e.get("state"), hit))
        face["notes"].append("%s：厂内在飞条目命中同债号（label=%s）" % (e.get("id"), e.get("label")))

    # C2 最近外派记录面（任务卡 + 切片）：同债号在飞的件
    dispatch_state = {}
    if os.path.exists(DISPATCH_JSON):
        try:
            with open(DISPATCH_JSON, "r", encoding="utf-8") as f:
                proj = json.load(f)
            for it in proj.get("items") or []:
                if isinstance(it, dict) and it.get("task_id"):
                    dispatch_state[it["task_id"]] = it.get("state")
        except Exception:                          # noqa: BLE001
            dispatch_state = {}

    records = {}     # task_id -> {coord, title}
    if not os.path.isdir(tasks_dir):
        face["verdict"] = "UNKNOWN"
        face["detail"] = "外派任务卡目录缺失：%s（不可解析 ⇒ fail-closed）" % rel(tasks_dir)
        return face
    for name in sorted(os.listdir(tasks_dir)):
        d = os.path.join(tasks_dir, name)
        if not os.path.isdir(d):
            continue
        title = ""
        coord = ""
        meta_p = os.path.join(d, "meta.json")
        if os.path.exists(meta_p):
            try:
                with open(meta_p, "r", encoding="utf-8") as f:
                    m = json.load(f)
                title = str(m.get("title") or "")
                coord = "%s:%d（title）" % (rel(meta_p), 1)
            except Exception:                      # noqa: BLE001
                title = ""
        if not title:
            prob = os.path.join(d, "problem.md")
            if os.path.exists(prob):
                try:
                    with open(prob, "r", encoding="utf-8") as f:
                        for i, line in enumerate(f, 1):
                            if line.startswith("#"):
                                title = line.strip().lstrip("#").strip()
                                coord = "%s:%d（首标题）" % (rel(prob), i)
                                break
                except Exception:                  # noqa: BLE001
                    title = ""
        if not title:
            continue
        if not match_line(rx, title):
            continue
        rec = records.setdefault(name, {"coord": coord, "title": title, "srcs": []})
        rec["srcs"].append(coord)
    if os.path.isdir(slices_dir):
        for name in sorted(os.listdir(slices_dir)):
            d = os.path.join(slices_dir, name)
            if not os.path.isdir(d):
                continue
            man = os.path.join(d, "MANIFEST.json")
            if not os.path.exists(man):
                continue
            try:
                with open(man, "r", encoding="utf-8") as f:
                    m = json.load(f)
            except Exception:                      # noqa: BLE001
                continue
            title = str(m.get("note") or "")
            if not title:
                continue
            if not match_line(rx, title):
                continue
            tid = m.get("task_id") or name
            rec = records.setdefault(tid, {"coord": "%s:note" % rel(man), "title": title, "srcs": []})
            rec["srcs"].append("%s（note）" % rel(man))
    for tid in sorted(records):
        rec = records[tid]
        st = dispatch_state.get(tid)
        if st is None:
            occ += 1
            face["evidence"].append("外派记录 %s（登记面无该 task_id 的状态 ⇒ 不可证）"
                                    % "，".join(rec["srcs"]))
            face["notes"].append("%s：外派记录存在但登记面查不到状态 ⇒ fail-closed 占用" % tid)
            continue
        v, note = _item_state_verdict(st)
        if v == "OCCUPIED":
            occ += 1
            face["evidence"].append("外派记录 %s（task_id=%s，state=%s）"
                                    % ("，".join(rec["srcs"]), tid, st))
            face["notes"].append("%s：%s" % (tid, note))
        elif v == "UNKNOWN":
            occ += 1
            face["evidence"].append("外派记录 %s（task_id=%s，state=%r 不可证）"
                                    % ("，".join(rec["srcs"]), tid, st))
            face["notes"].append("%s：%s" % (tid, note))
        else:
            face["notes"].append("%s：%s" % (tid, note))

    # C3 可选外派日志 grep
    for lg in extra_logs or []:
        if not os.path.exists(lg):
            occ += 1
            face["verdict"] = "UNKNOWN"
            face["evidence"].append("%s（外派日志缺失 ⇒ 不可证）" % rel(lg))
            continue
        try:
            with open(lg, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except Exception as exc:                   # noqa: BLE001
            occ += 1
            face["verdict"] = "UNKNOWN"
            face["evidence"].append("%s（外派日志不可读：%s）" % (rel(lg), exc))
            continue
        for i, line in enumerate(lines, 1):
            hit = match_line(rx, line)
            if hit:
                occ += 1
                face["evidence"].append("%s:%d（命中=%s）" % (rel(lg), i, hit))
                face["notes"].append("外派日志命中同债号：%s" % line.strip()[:120])
                break

    if occ:
        face["verdict"] = "OCCUPIED"
        face["detail"] = "同债号在飞证据 %d 条" % occ
    else:
        face["verdict"] = "CLEAN"
        face["detail"] = "厂内在飞面 + 最近外派记录面均无同债号在飞"
    return face


# ---------------------------------------------------------------- 主判定

def run_check(debt_id, ledger, dispatch_json, registry_json, wf_gate, tasks_dir, slices_dir,
              extra_logs, allow_missing_row=False, out=None):
    out = out if out is not None else []
    out.append("DISPATCH-OCCUPANCY-CHECK · 债号=%s" % debt_id)
    out.append("  口径：台账状态列不是占用权威面（§3.3 C2）；任一面不可解析 ⇒ fail-closed 拒派（C4）")
    faces = []
    faces.append(face_ledger(debt_id, ledger))
    faces.append(face_dispatch(debt_id, dispatch_json, registry_json))
    faces.append(face_inflight(debt_id, wf_gate, tasks_dir, slices_dir, extra_logs))

    evidence = []
    for f in faces:
        out.append("  面%s %s：%s｜%s"
                   % (f["face"], f["surface"], f["verdict"], f["detail"]))
        if f.get("coordinate"):
            out.append("      读数坐标：%s" % f["coordinate"])
        for e in f["evidence"]:
            out.append("      占用证据坐标：%s" % e)
            evidence.append({"face": f["face"], "coordinate": e})
        for n in f["notes"]:
            out.append("      提示：%s" % n)

    blocking = []
    for f in faces:
        if f["verdict"] == "OCCUPIED":
            blocking.append("%s 已占" % f["face"])
        elif f["verdict"] == "UNKNOWN":
            blocking.append("%s 不可证（fail-closed）" % f["face"])
        elif f["verdict"] == "NO-ROW" and not allow_missing_row:
            blocking.append("%s 无该债号行（债号未入账 ⇒ fail-closed）" % f["face"])

    if blocking:
        verdict = "BLOCK"
        out.append("  判定：**BLOCK**（%s）" % "；".join(blocking))
        rc = 2 if any("不可证" in b for b in blocking) else 1
    else:
        verdict = "ALLOW"
        out.append("  判定：**ALLOW**（三面全过）")
        rc = 0
    result = {"schema": "af.dispatch.occupancy-check.v1",
              "debt_id": debt_id,
              "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "verdict": verdict,
              "rc": rc,
              "faces": faces,
              "occupancy_evidence": evidence,
              "blocking": blocking}
    return result, rc


# ---------------------------------------------------------------- selftest

def _w(d, name, obj):
    p = os.path.join(d, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        if isinstance(obj, (dict, list)):
            json.dump(obj, f, ensure_ascii=False, indent=1)
        else:
            f.write(obj)
    return p


def _fixtures(d, occupied):
    """造两态夹具：occupied=True ⇒ 该债号已占；False ⇒ 全净。"""
    ledger = _w(d, "计划/阶段欠账台账.md",
                "# 阶段欠账台账\n\n"
                "| 编号 | 欠什么 | 暴露自 | 验收门 | 批次归属 | 状态 |\n"
                "|---|---|---|---|---|---|\n"
                "| RT-E900 | 夹具债号 | 夹具 | 夹具门 | 夹具批 | 未开始 |\n")
    if occupied:
        disp = _w(d, "外派登记.json", {
            "schema": "af.bot.dispatch-registry.v1",
            "items": [{"task_id": "rt-e900-fixture", "debt": "RT-E900", "lane": "bot",
                       "state": "published-awaiting-bot", "base_sha": "aaa"}]})
    else:
        disp = _w(d, "外派登记.json", {
            "schema": "af.bot.dispatch-registry.v1",
            "items": [{"task_id": "rt-e800-fixture", "debt": "RT-E800", "lane": "bot",
                       "state": "published-awaiting-bot", "base_sha": "aaa"}]})
    wg = _w(d, "wf-gate.json", {
        "schema": 1, "entries": [
            {"id": "dwfrun-other", "label": "别的批", "note": "", "state": "active"},
            {"id": "dwfrun-released", "label": "已收", "note": "", "state": "released"}]})
    tasks = os.path.join(d, "tasks")
    os.makedirs(tasks, exist_ok=True)
    if occupied:
        _w(d, "tasks/rt-e900-fixture/meta.json",
           {"schema": "af.bot.task.v1", "task_id": "rt-e900-fixture",
            "title": "RT-E900 · 夹具任务书", "lane": "bot"})
    else:
        _w(d, "tasks/rt-e800-fixture/meta.json",
           {"schema": "af.bot.task.v1", "task_id": "rt-e800-fixture",
            "title": "RT-E800 · 别的任务书", "lane": "bot"})
    slices = os.path.join(d, "slices")
    os.makedirs(slices, exist_ok=True)
    return {"ledger": ledger, "dispatch": disp, "wf": wg, "tasks": tasks, "slices": slices}


def run_selftest(out):
    d = tempfile.mkdtemp(prefix="dispatch-occupancy-selftest-")
    fails = []
    n = 0
    try:
        # T1 已占态 ⇒ BLOCK（证据坐标必须打出）
        n += 1
        fx = _fixtures(d, occupied=True)
        res, rc = run_check("RT-E900", fx["ledger"], fx["dispatch"],
                             os.path.join(d, "no-registry.json"), fx["wf"],
                             fx["tasks"], fx["slices"], [], out=out)
        if res["verdict"] != "BLOCK" or rc == 0:
            fails.append("T1 已占态应 BLOCK 且 rc≠0，得 %s rc=%d" % (res["verdict"], rc))
        if not res["occupancy_evidence"]:
            fails.append("T1 已占态必须给出占用证据坐标")
        if not any("外派登记.json" in e["coordinate"] for e in res["occupancy_evidence"]):
            fails.append("T1 证据坐标应指向登记面")

        # T2 全净态 ⇒ ALLOW rc=0
        n += 1
        fx2 = _fixtures(os.path.join(d, "clean"), occupied=False)
        res2, rc2 = run_check("RT-E900", fx2["ledger"], fx2["dispatch"],
                              os.path.join(d, "no-registry.json"), fx2["wf"],
                              fx2["tasks"], fx2["slices"], [], out=out)
        if res2["verdict"] != "ALLOW" or rc2 != 0:
            fails.append("T2 全净态应 ALLOW rc=0，得 %s rc=%d" % (res2["verdict"], rc2))
        if res2["occupancy_evidence"]:
            fails.append("T2 全净态不应有占用证据")

        # T3 fail-closed：wf-gate 台账缺失 ⇒ 不可证 ⇒ 拒派
        n += 1
        res3, rc3 = run_check("RT-E900", fx2["ledger"], fx2["dispatch"],
                              os.path.join(d, "no-registry.json"),
                              os.path.join(d, "nope-wf.json"),
                              fx2["tasks"], fx2["slices"], [], out=out)
        if res3["verdict"] != "BLOCK" or rc3 != 2:
            fails.append("T3 wf-gate 缺件应 BLOCK rc=2，得 %s rc=%d" % (res3["verdict"], rc3))

        # T4 fail-closed：登记面不可解析 ⇒ 拒派
        n += 1
        bad = _w(d, "bad-dispatch.json", "{ 这不是 JSON")
        res4, rc4 = run_check("RT-E900", fx2["ledger"], bad,
                              os.path.join(d, "no-registry.json"), fx2["wf"],
                              fx2["tasks"], fx2["slices"], [], out=out)
        if res4["verdict"] != "BLOCK" or rc4 != 2:
            fails.append("T4 登记面不可解析应 BLOCK rc=2，得 %s rc=%d" % (res4["verdict"], rc4))

        # T5 台账无该债号行 ⇒ 默认拒派（fail-closed），带 flag 降级为提示
        n += 1
        res5, rc5 = run_check("RT-E999", fx2["ledger"], fx2["dispatch"],
                              os.path.join(d, "no-registry.json"), fx2["wf"],
                              fx2["tasks"], fx2["slices"], [], out=out)
        if res5["verdict"] != "BLOCK" or rc5 == 0:
            fails.append("T5 台账无行默认应拒派，得 %s rc=%d" % (res5["verdict"], rc5))
        res5b, rc5b = run_check("RT-E999", fx2["ledger"], fx2["dispatch"],
                                os.path.join(d, "no-registry.json"), fx2["wf"],
                                fx2["tasks"], fx2["slices"], [],
                                allow_missing_row=True, out=out)
        if res5b["verdict"] != "ALLOW":
            fails.append("T5 --allow-missing-ledger-row 后应 ALLOW，得 %s" % res5b["verdict"])

        # T6 台账行状态列自称在飞 ⇒ 占用
        n += 1
        led_inflight = _w(d, "led-inflight.md",
                          "| 编号 | 状态 |\n|---|---|\n| RT-E900 | 施工中（外派面在飞） |\n")
        res6, rc6 = run_check("RT-E900", led_inflight, fx2["dispatch"],
                              os.path.join(d, "no-registry.json"), fx2["wf"],
                              fx2["tasks"], fx2["slices"], [], out=out)
        if res6["verdict"] != "BLOCK":
            fails.append("T6 台账状态列自称在飞应 BLOCK，得 %s" % res6["verdict"])

        # T7 债号边界：RT-E13 不得命中 RT-E138
        n += 1
        wg2 = _w(d, "wg2.json", {"schema": 1, "entries": [
            {"id": "offload-a3-rte138-cont", "label": "波A3·RT-E138 键推广", "note": "",
             "state": "active"}]})
        res7, rc7 = run_check("RT-E13", fx2["ledger"], fx2["dispatch"],
                              os.path.join(d, "no-registry.json"), wg2,
                              fx2["tasks"], fx2["slices"], [],
                              allow_missing_row=True, out=out)
        face_c7 = [f for f in res7["faces"] if f["face"] == "C-在飞面"][0]
        if face_c7["verdict"] != "CLEAN":
            fails.append("T7 RT-E13 不得被 RT-E138 条目命中，C 面=%s" % face_c7["verdict"])
        res7b, rc7b = run_check("RT-E138", fx2["ledger"], fx2["dispatch"],
                                os.path.join(d, "no-registry.json"), wg2,
                                fx2["tasks"], fx2["slices"], [],
                                allow_missing_row=True, out=out)
        face_c7b = [f for f in res7b["faces"] if f["face"] == "C-在飞面"][0]
        if face_c7b["verdict"] != "OCCUPIED":
            fails.append("T7 RT-E138 应命中在飞条目，C 面=%s" % face_c7b["verdict"])

        # T8 外派记录面：登记面无该 task_id 状态 ⇒ 不可证 ⇒ 占用
        n += 1
        disp3 = _w(d, "disp3.json", {"schema": "af.bot.dispatch-registry.v1", "items": []})
        res8, rc8 = run_check("RT-E900", fx2["ledger"], disp3,
                              os.path.join(d, "no-registry.json"), fx2["wf"],
                              fx["tasks"], fx["slices"], [], out=out)
        if res8["verdict"] != "BLOCK":
            fails.append("T8 外派记录在、登记面无状态 ⇒ 应 BLOCK，得 %s" % res8["verdict"])

        if fails:
            out.append("FAIL selftest %d/%d 过：" % (n - len(fails), n))
            for f in fails:
                out.append("  " + f)
            return 1
        out.append("selftest %d/%d 过（已占⇒BLOCK+证据坐标/全净⇒ALLOW/fail-closed×2（wf-gate 缺件、"
                   "登记面不可解析）/台账无行默认拒派+flag 降级/台账自称在飞⇒占用/"
                   "债号边界 RT-E13≠RT-E138/外派记录在而登记面无状态⇒占用）" % (n, n))
        return 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------- CLI

def main(argv):
    out = []
    if "--selftest" in argv:
        rc = run_selftest(out)
        for ln in out:
            print(ln)
        return rc

    import argparse
    p = argparse.ArgumentParser(
        prog="dispatch-occupancy-check.py",
        description="债号占用机检（三面）：台账状态列 / 外派登记面 / 厂内在飞面 ⇒ ALLOW 或 BLOCK")
    p.add_argument("debt", nargs="?", help="债号（如 RT-E82）")
    p.add_argument("--debt", dest="debt_opt", help="债号（同位置参数）")
    p.add_argument("--ledger", default=LEDGER_MD)
    p.add_argument("--dispatch-json", default=DISPATCH_JSON)
    p.add_argument("--registry", default=REGISTRY_JSON)
    p.add_argument("--wf-gate", default=WF_GATE)
    p.add_argument("--tasks-dir", default=TASKS_DIR)
    p.add_argument("--slices-dir", default=SLICES_DIR)
    p.add_argument("--log", action="append", default=[], help="追加 grep 的外派日志（可多次）")
    p.add_argument("--allow-missing-ledger-row", action="store_true",
                   help="台账无该债号行时降级为提示（默认 fail-closed 拒派）")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    args = p.parse_args(argv)

    debt = args.debt_opt or args.debt
    if not debt:
        p.print_help()
        return 2
    result, rc = run_check(debt.strip(), args.ledger, args.dispatch_json, args.registry,
                            args.wf_gate, args.tasks_dir, args.slices_dir, args.log,
                            allow_missing_row=args.allow_missing_ledger_row, out=out)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        for ln in out:
            print(ln)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
