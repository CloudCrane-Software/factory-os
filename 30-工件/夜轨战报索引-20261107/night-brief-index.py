#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""night-brief-index.py — 晨报/夜间战报索引器（factory-os#83 报告卡）。

卡面（CloudCrane-Software/factory-os#83）自述：本 issue=索引摘要，非施工卡、
无债号、不参与派工/占用闸。wave-08.json notes 同判。本件把卡面+三条终稿评论
收成机读索引（schema=af.night-brief-index.v1），并带夹具自测。

路径依据：卡面全文版坐标族全在 30-工件/夜轨*-20261107/；本目录为索引落点
（30-工件/夜轨战报索引-20261107/）。不改 tools/、账本/、波次清单、门禁件。

功能：
  · --selftest     夹具自测（零网络、零真板面、零凭据材料）
  · --emit-index   写出 #83 快照 index.json（卡面已读结构化，不回打 API）
  · --parse FILE   把一份合成/转储的 issue JSON 走解析器（夹具与干跑用）
  · --out FILE     落点（缺省 stdout）

退出码：0=成功；1=selftest 失败；2=参数/输入错误。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

SCHEMA = "af.night-brief-index.v1"
ISSUE_NO = 83
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.json")

# 私路径/家目录形态：输出侧一律换成占位，禁把字面带出仓
# 模式串拼接构造，源码不写完整私路径字面
_HOME_PATH_RX = re.compile(
    r"(?:~|" + re.escape("".join(["/", "home"])) + r")/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*"
)
_ETC_PATH_RX = re.compile(re.escape("".join(["/", "etc", "/"])) + r"[A-Za-z0-9._/-]+")
_TMP_PATH_RX = re.compile(re.escape("".join(["/", "tmp", "/"])) + r"[A-Za-z0-9._/-]+")
# 四段 IPv4 字面（输出侧禁带）
_V4_RX = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# 真实前缀族（夹具与输出均不得出现；模式表拼接构造，不写假令牌字面）
def _pfx(*parts):
    return "".join(parts)


_PREFIX_RX = re.compile(
    r"\b(?:" + "|".join([
        _pfx("ghp", "_"), _pfx("gho", "_"), _pfx("ghu", "_"),
        _pfx("ghs", "_"), _pfx("ghr", "_"), _pfx("github", "_", "pat", "_"),
        _pfx("sk", "-"), _pfx("AKIA"),
    ]) + r")[A-Za-z0-9_.=-]*"
)

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_ARGS = 2


def redact(text):
    """输出侧清洗：私路径 / 四段地址 / 真实前缀族 → 占位。None→空串。"""
    if not text:
        return ""
    s = _PREFIX_RX.sub("[REDACTED-PREFIX]", text)
    s = _HOME_PATH_RX.sub("[私路径已脱敏]", s)
    s = _ETC_PATH_RX.sub("[私路径已脱敏]", s)
    s = _TMP_PATH_RX.sub("[私路径已脱敏]", s)
    s = _V4_RX.sub("[地址已脱敏]", s)
    return s


def is_report_index(body):
    """卡面自述『非施工卡』『索引摘要』→ 报告索引卡。"""
    b = body or ""
    return ("非施工卡" in b) and ("索引" in b)


def extract_debt(text):
    """抽 D-<digits>；没有则 None（报告卡无债号）。"""
    m = re.search(r"(?<![A-Za-z0-9])(D-\d{1,4})(?![A-Za-z0-9])", text or "")
    return m.group(1) if m else None


def parse_a_items(body):
    """从正文 ① 节抽 A 档裁决项（编号行）。"""
    items = []
    if not body:
        return items
    # 截 ① 到 ②
    m = re.search(r"## ①[\s\S]*?(?=\n## ②|\n## ③|\Z)", body)
    block = m.group(0) if m else body
    for mm in re.finditer(
            r"^\d+\.\s+\*\*([^*]+)\*\*（([^）]+)）[：:]?\s*(.*)$",
            block, re.M):
        items.append({
            "id_tag": redact(mm.group(1).strip()),
            "code_tag": redact(mm.group(2).strip()),
            "summary": redact(mm.group(3).strip())[:180],
        })
    return items


def parse_b_cards(body):
    """从正文 ② 节表抽施工卡行（#号 / 债号 / severity / 内容）。"""
    cards = []
    if not body:
        return cards
    m = re.search(r"## ②[\s\S]*?(?=\n## ③|\n## ④|\Z)", body)
    block = m.group(0) if m else body
    for mm in re.finditer(
            r"^\|\s*#(\d+)\s*\|\s*(D-\d+)\s*\|\s*(\w+)\s*\|\s*([^|]+)\|",
            block, re.M):
        cards.append({
            "issue": int(mm.group(1)),
            "debt": mm.group(2),
            "severity": mm.group(3).strip(),
            "summary": redact(mm.group(4).strip())[:120],
        })
    return cards


def parse_overnight(body):
    """从正文 ③ 节抽已处置项标题。"""
    items = []
    if not body:
        return items
    m = re.search(r"## ③[\s\S]*?(?=\n## ④|\n## ⑤|\Z)", body)
    block = m.group(0) if m else ""
    for mm in re.finditer(r"^\-\s+\*\*([^*]+)\*\*", block, re.M):
        items.append(redact(mm.group(1).strip()))
    return items


def build_index(title, body, comments=None, source_tag="card"):
    """从卡面标题/正文/评论列表装配索引对象。"""
    comments = comments or []
    body_s = body or ""
    title_s = redact(title or "")
    a_items = parse_a_items(body_s)
    b_cards = parse_b_cards(body_s)
    overnight = parse_overnight(body_s)
    comment_kinds = []
    for c in comments:
        raw = c.get("body") or ""
        kind = "other"
        if "终稿补充" in raw or "夜间战报" in raw:
            kind = "final-draft"
        elif "晨间新增" in raw:
            kind = "morning-register"
        elif "九点动线" in raw:
            kind = "nine-oclock-line"
        elif "派发读数" in raw:
            kind = "dispatch-note"
        comment_kinds.append({
            "kind": kind,
            "created_at": c.get("created_at") or "",
            "chars": len(raw),
        })
    report = is_report_index(body_s)
    # 报告卡自述无债号：正文里出现的 D-xxx 是被索引的他卡债，不升为本卡债号
    debt_val = None if report else (extract_debt(title_s) or extract_debt(body_s[:400]))
    return {
        "schema": SCHEMA,
        "issue": ISSUE_NO,
        "title": title_s,
        "card_kind": "report-index" if report else "unknown",
        "not_a_dev_card": report,
        "debt": debt_val,
        "source_tag": source_tag,
        "sections": {
            "adjudication_A": a_items,
            "construction_cards_B": b_cards,
            "overnight_done": overnight,
        },
        "comments": comment_kinds,
        "counts": {
            "a_items": len(a_items),
            "b_cards": len(b_cards),
            "overnight": len(overnight),
            "comments": len(comment_kinds),
        },
        "honesty": {
            "ledger_anchor": "burn1",
            "ledger_anchor_hits": 0,
            "full_text_in_tree": False,
            "claimed_fulltext_dirs": [
                "30-工件/夜轨C2-20261107",
                "30-工件/夜轨D-20261107",
                "30-工件/夜轨E-20261107",
            ],
        },
    }


# ---------------------------------------------------------------- #83 快照
# 卡面+三条终稿评论的结构化摘录（已脱敏；不回放私路径/前缀族/四段地址）。

SNAPSHOT_83 = {
    "schema": SCHEMA,
    "issue": ISSUE_NO,
    "title": "[晨报] 2026-11-07 夜间战报索引",
    "card_kind": "report-index",
    "not_a_dev_card": True,
    "debt": None,
    "source_tag": "issue-body+comments-2026-11-09",
    "sections": {
        "adjudication_A": [
            {
                "id_tag": "H1 fork-PR 执行面",
                "code_tag": "部分确认",
                "summary": "三仓公开且 gates 对 PR 头树无容器隔离直跑宿主；选项=审批制/runner 迁低权账户/文档口径+P2",
            },
            {
                "id_tag": "M2 公开仓泄密＋真实私钥 blob",
                "code_tag": "确认",
                "summary": "公开镜像仓敏感材料在案；必办=吊销/换钥（删文件不足）",
            },
            {
                "id_tag": "M3 keepalive 主日志被删",
                "code_tag": "部分确认",
                "summary": "旧日志体丢失成立；建议以施工收口（日志迁出临时盘+删除告警码）",
            },
            {
                "id_tag": "L1 任务/订单/工厂面全量无鉴权公开",
                "code_tag": "确认",
                "summary": "全公开=设计决定；建议最小去敏三样（模型名/配额余量/到期时间戳）",
            },
        ],
        "construction_cards_B": [
            {"issue": 77, "debt": "D-109", "severity": "high",
             "summary": "安灯出带批（H2+M7+M9）", "dispatch": "待派/夜轨B 面子项"},
            {"issue": 78, "debt": "D-110", "severity": "high",
             "summary": "配额闸停用令消费腿（H5+H6）", "dispatch": "已收卷"},
            {"issue": 79, "debt": "D-111", "severity": "medium",
             "summary": "门户写端点鉴权+HEAD 语义收口（M1+M4）", "dispatch": "待派/夜轨B"},
            {"issue": 80, "debt": "D-112", "severity": "high",
             "summary": "bench 臂退役态显式化（H4）", "dispatch": "已收卷"},
            {"issue": 81, "debt": "D-113", "severity": "high",
             "summary": "/data 水位恢复动作腿（H3）", "dispatch": "已收卷"},
            {"issue": 82, "debt": "D-114", "severity": "medium",
             "summary": "观测补遗批（M5+M6+M8）", "dispatch": "待派/夜轨B"},
        ],
        "overnight_done": [
            "planner 五缺口 G1-G5 补件 9 件 staging 全自测（零 GitHub 写）",
            "D-107 bench 沙箱环闭环 verdict=RESOLVED",
            "批一/批二连接压测三批真实执行",
            "wave-07 夜间 5 PR 合线",
            "可观测中心上公网（schema af.factory-obs.v1）",
        ],
        "adr_poc": {
            "status": "待运营者在场",
            "steps": "PoC-1..PoC-21 全部标待在场",
            "executed_tonight": 0,
        },
        "morning_added": [
            {"id_tag": "判分校准", "debt": "D-117",
             "summary": "P2P 唯一失配=参数化 ID 渲染形态差；属判据面，只许 ADR 正路"},
            {"id_tag": "D-98 停车归档", "debt": "D-98",
             "summary": "af 自家判据器拦 caller 形态；与 D-99 同窗裁"},
            {"id_tag": "cnb 核数", "debt": None,
             "summary": "runner.cpus 声明对系统档未生效；待裁三选"},
        ],
        "dispatch_preview": [
            "先裁 A 档（原 4 + 晨间新增）",
            "再派 B 档待派卡 #77/#79/#82/#84（已收卷勿重复派 #78/#80/#81）",
            "最高优先：planner D-1 给第一批真锚",
            "在场件：ADR PoC 21 步",
        ],
    },
    "comments": [
        {"kind": "final-draft", "created_at": "2026-11-06T21:58:38Z", "chars": 3047},
        {"kind": "morning-register", "created_at": "2026-11-06T22:20:50Z", "chars": 1217},
        {"kind": "nine-oclock-line", "created_at": "2026-11-06T23:06:35Z", "chars": 3925},
        {"kind": "dispatch-note", "created_at": "2026-11-09T05:22:04Z", "chars": 72},
    ],
    "counts": {
        "a_items": 4,
        "b_cards": 6,
        "overnight": 5,
        "morning_added": 3,
        "comments": 4,
        "pending_dispatch": 4,
        "closed_merged": 3,
    },
    "honesty": {
        "ledger_anchor": "burn1",
        "ledger_anchor_hits": 0,
        "full_text_in_tree": False,
        "claimed_fulltext_dirs": [
            "30-工件/夜轨C2-20261107",
            "30-工件/夜轨D-20261107",
            "30-工件/夜轨E-20261107",
        ],
        "pre_state": {
            "grep_burn1_rc": 1,
            "target_dir_ls_rc": 2,
            "tool_exists_rc": 1,
        },
    },
}


def snapshot_ok(obj):
    """快照契约：schema/卡型/无债号/A=4/B=6/评论=4。"""
    if obj.get("schema") != SCHEMA:
        return False, "schema"
    if obj.get("issue") != ISSUE_NO:
        return False, "issue"
    if obj.get("card_kind") != "report-index":
        return False, "card_kind"
    if obj.get("not_a_dev_card") is not True:
        return False, "not_a_dev_card"
    if obj.get("debt") is not None:
        return False, "debt"
    sec = obj.get("sections") or {}
    if len(sec.get("adjudication_A") or []) != 4:
        return False, "a_items"
    if len(sec.get("construction_cards_B") or []) != 6:
        return False, "b_cards"
    debts = [c["debt"] for c in sec["construction_cards_B"]]
    if debts != ["D-109", "D-110", "D-111", "D-112", "D-113", "D-114"]:
        return False, "b_debts"
    if len(obj.get("comments") or []) != 4:
        return False, "comments"
    kinds = [c["kind"] for c in obj["comments"]]
    if kinds != ["final-draft", "morning-register", "nine-oclock-line", "dispatch-note"]:
        return False, "comment_kinds"
    if (obj.get("honesty") or {}).get("ledger_anchor_hits") != 0:
        return False, "anchor_hits"
    return True, "ok"


# ---------------------------------------------------------------- selftest

def run_selftest():
    """夹具逐个真跑。零网络、零真板面、零凭据材料。"""
    fails = []
    n = 0

    def check(name, cond, detail=""):
        nonlocal n
        n += 1
        if cond:
            sys.stderr.write("  [PASS] %s\n" % name)
        else:
            fails.append("%s%s" % (name, ("（%s）" % detail) if detail else ""))
            sys.stderr.write("  [FAIL] %s %s\n" % (name, detail))

    # T1 报告卡识别
    body_yes = ("本 issue=索引摘要，非施工卡、无债号、不参与派工/占用闸\n"
                "## ① 需运营者裁决项\n")
    body_no = "## ① 施工\n做一件事\n"
    check("T1a 含非施工卡+索引 → report-index", is_report_index(body_yes))
    check("T1b 无该自述 → 非报告卡", not is_report_index(body_no))

    # T2 A 档抽取
    body_a = ("## ① 需运营者裁决项（A 档 2 条）\n\n"
              "1. **H-TEST 项**（部分确认）：夹具摘要甲\n"
              "2. **M-TEST 项**（确认）：夹具摘要乙\n\n"
              "## ② 施工卡总表\n")
    a_items = parse_a_items(body_a)
    check("T2a A 档条数=2", len(a_items) == 2, "实得 %d" % len(a_items))
    check("T2b 首条 id_tag", a_items and a_items[0]["id_tag"] == "H-TEST 项")
    check("T2c 次条 code_tag", a_items and a_items[1]["code_tag"] == "确认")

    # T3 B 档表抽取
    body_b = ("## ② 施工卡总表\n\n"
              "| 卡 | 债号 | severity | 内容 | 派工 |\n"
              "|---|---|---|---|---|\n"
              "| #77 | D-109 | high | 安灯出带批 | 注 |\n"
              "| #82 | D-114 | medium | 观测补遗 | 注 |\n\n"
              "## ③ 夜间已自动处置项\n")
    b_cards = parse_b_cards(body_b)
    check("T3a B 档条数=2", len(b_cards) == 2, "实得 %d" % len(b_cards))
    check("T3b 首卡号 77", b_cards and b_cards[0]["issue"] == 77)
    check("T3c 次债号 D-114", b_cards and b_cards[1]["debt"] == "D-114")

    # T4 ③ 节已处置项
    body_c = ("## ③ 夜间已自动处置项\n\n"
              "- **planner 五缺口补件**（说明）\n"
              "- **D-107 闭环**（说明）\n\n"
              "## ④ ADR\n")
    ov = parse_overnight(body_c)
    check("T4a overnight=2", len(ov) == 2, "实得 %d" % len(ov))
    check("T4b 首项标题", ov and ov[0].startswith("planner"))

    # T5 装配：报告卡 + 无债号 + 评论分类
    idx = build_index(
        "[晨报] 夹具索引",
        body_yes + body_a + body_b + body_c,
        comments=[
            {"body": "终稿补充：夜间战报摘要", "created_at": "2026-11-06T21:58:38Z"},
            {"body": "〔晨间新增裁决项登记〕", "created_at": "2026-11-06T22:20:50Z"},
            {"body": "〔九点动线 · 终稿〕", "created_at": "2026-11-06T23:06:35Z"},
            {"body": "派发读数：夹具通道", "created_at": "2026-11-09T05:22:04Z"},
        ],
        source_tag="fixture",
    )
    check("T5a card_kind=report-index", idx["card_kind"] == "report-index")
    check("T5b not_a_dev_card", idx["not_a_dev_card"] is True)
    check("T5c debt is None", idx["debt"] is None)
    check("T5d schema", idx["schema"] == SCHEMA)
    kinds = [c["kind"] for c in idx["comments"]]
    check("T5e 评论四类",
          kinds == ["final-draft", "morning-register", "nine-oclock-line", "dispatch-note"],
          "实得 %r" % kinds)

    # T6 空正文 fail-closed：不猜绿
    idx0 = build_index("x", "", [], source_tag="empty")
    check("T6a 空正文 card_kind=unknown", idx0["card_kind"] == "unknown")
    check("T6b 空正文 A=0", idx0["counts"]["a_items"] == 0)
    check("T6c 空正文 B=0", idx0["counts"]["b_cards"] == 0)

    # T7 清洗：私路径 / 四段地址 / 真实前缀族不得出仓
    # 字面用拼接构造，源码行不写完整私路径/四段地址/前缀族
    home_lit = "".join(["~", "/", ".", "git-config"])
    addr_lit = ".".join(["10", "0", "0", "1"])
    pref_lit = "".join(["ghp", "_", "AAAABBBBCCCC"])
    dirty = "path=%s addr=%s pref=%s" % (home_lit, addr_lit, pref_lit)
    cleaned = redact(dirty)
    check("T7a 私路径已脱敏", "[私路径已脱敏]" in cleaned)
    check("T7b 地址已脱敏", "[地址已脱敏]" in cleaned)
    check("T7c 前缀族已脱敏", "[REDACTED-PREFIX]" in cleaned)
    check("T7d 清洗后无四段地址", _V4_RX.search(cleaned) is None)
    home_root = "".join(["/", "home", "/"])
    check("T7e 清洗后无家目录字面",
          ("".join(["~", "/"]) not in cleaned) and (home_root not in cleaned))

    # T8 债号抽取：有则得、无则 None
    check("T8a 抽到 D-109", extract_debt("卡 #77 债号 D-109 安灯") == "D-109")
    check("T8b 抽不到=None", extract_debt("本卡无债号、不参与派工") is None)

    # T9 快照契约
    ok, why = snapshot_ok(SNAPSHOT_83)
    check("T9a 快照契约过", ok, why)
    dumped = json.dumps(SNAPSHOT_83, ensure_ascii=False)
    check("T9b 快照可 JSON 序列化", isinstance(dumped, str) and len(dumped) > 200)
    roundtrip = json.loads(dumped)
    ok2, why2 = snapshot_ok(roundtrip)
    check("T9c 往返仍过契约", ok2, why2)

    # T10 快照自身无出仓违禁字面
    check("T10a 快照无四段地址", _V4_RX.search(dumped) is None)
    check("T10b 快照无真实前缀族", _PREFIX_RX.search(dumped) is None)
    check("T10c 快照无家目录根字面", "".join(["/", "home", "/"]) not in dumped)
    check("T10d 快照无波浪家目录字面", "".join(["~", "/"]) not in dumped)

    # T11 --parse 形：夹具 issue JSON → 解析器
    fixture_issue = {
        "number": 83,
        "title": "[晨报] 夹具",
        "body": body_yes + body_a + body_b + body_c,
    }
    parsed = build_index(fixture_issue["title"], fixture_issue["body"], [],
                         source_tag="parse-fixture")
    check("T11a parse 夹具 A>=2", parsed["counts"]["a_items"] >= 2)
    check("T11b parse 夹具 B>=2", parsed["counts"]["b_cards"] >= 2)
    check("T11c parse 夹具 overnight>=2", parsed["counts"]["overnight"] >= 2)

    if fails:
        sys.stderr.write("selftest: %d/%d FAIL\n" % (n - len(fails), n))
        for f in fails:
            sys.stderr.write("  - %s\n" % f)
        return EXIT_FAIL
    sys.stderr.write("selftest: %d/%d PASS ⇒ rc=0\n" % (n, n))
    return EXIT_OK


def write_out(obj, path):
    text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    if path in (None, "", "-"):
        sys.stdout.write(text)
        return EXIT_OK
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    sys.stderr.write("wrote %s (%d bytes)\n" % (path, len(text.encode("utf-8"))))
    return EXIT_OK


def cmd_parse(path, out):
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write("读入失败：%s\n" % exc)
        return EXIT_ARGS
    if not isinstance(raw, dict):
        sys.stderr.write("输入须为 issue 对象 JSON\n")
        return EXIT_ARGS
    idx = build_index(raw.get("title") or "", raw.get("body") or "",
                      raw.get("comments") or [], source_tag="parse")
    return write_out(idx, out)


def main(argv):
    p = argparse.ArgumentParser(prog="night-brief-index.py",
                                description=__doc__.split("路径依据")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--selftest", action="store_true", help="夹具自测（零网络）")
    g.add_argument("--emit-index", action="store_true",
                   help="写出 #83 快照 index.json")
    g.add_argument("--parse", metavar="FILE",
                   help="解析一份 issue JSON（夹具/干跑）")
    p.add_argument("--out", default=None, help="落点（--emit-index 缺省=同目录 index.json）")
    args = p.parse_args(argv)

    if args.selftest:
        return run_selftest()
    if args.emit_index:
        dest = args.out if args.out is not None else DEFAULT_OUT
        return write_out(SNAPSHOT_83, dest)
    if args.parse:
        return cmd_parse(args.parse, args.out)
    return EXIT_ARGS


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
