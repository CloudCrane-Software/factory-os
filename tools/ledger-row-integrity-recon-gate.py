#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""台账行完整性门（锚行形态·暗行棘轮）——ESC-32/D-141 畸形行逃逸的 CI 化。

设计来源（PR body 引用面）：30-工件/逃逸问题台账-20261108.md ESC-32（新门设计：
  「台账行完整性门（锚行形态腿）…只检形态不检语义」）；债本体=账本/阶段欠账台账.md
  D-141 行（台账同步引擎只对锚行（≥7 未转义竖线）对账；畸形行对引擎/占用闸/planner
  锚宇宙均不可见=暗行）。gate 形态对齐仓内 ledger-face-recon-gate 族（出口 0/2/3、
  判据单一源自含、--selftest 造夹具自证会咬人）。

判据：只检锚行**形态**不检语义（卡面明令）——不读行内容含义、不判状态格、不判
  债的真假；只判「行是否在引擎的行界判定下可见」。

【行界判定与引擎同源】（tools/ledger-sync.sh:192-201 row_id_of/boundaries 同款）
  · 未转义竖线：`\` 转义其后一个字符，字面 `\|` 不计入行界。
  · 引擎锚行 = 行首 `|` + 未转义竖线 ≥7（引导|+6 格）+ 首格非空、非表头（编号）、
    非分隔行（|---|）。
  · 候选行 = 本册全部 `|` 起头的表体行（排除分隔行与表头行）；首格形态不进判据
    （引擎对首格无 id 形态要求，本门同口径）。候选行未转义竖线 <7 ⇒ 该行对引擎
    不可见 = **暗行**（D-141 的逃逸形态本体）。

【红（exit 2）——棘轮判据】
  R1 新暗行：候选行 <7 未转义竖线且首格 ∉ 存量基线（BASELINE_DARK_PIPES）。
  R2 基线暗行形状漂移：首格 ∈ 基线但实读竖线数 ≠ 基线值（仍 <7，如 6→5）。
  R3 基线编号整行消失：append-only 证明面整行蒸发 = 不可解释删除（篡改信号；
    合法演化只翻状态格+行尾 append，行仍在）。
  R4 登记行缺席：暗行在场而 D-141 登记行（首格=D-141）不在本册——豁免所系的
    上游登记被摘而债仍在 = 漂白形态（豁免随登记共存亡）。

【面缺（exit 3）】台账不可读/不可解码——不可证不猜绿。

【不判红只点名（诚实注记）】
  · ≥7 且 ≠7 的**超管行**：引擎可见（≥7 达卡面判据），逐条注记竖线数——ESC-32
    登记设计的 ≠7 更严腿如实留痕；收严=判据变更，须判官批 PR，本门不擅自扩红。
  · 基线内暗行转 ≥7（正形化已落）：响亮注记「基线须同批收紧」——修不受罚。
  · 存量基线暗行**逐轮全列**，附上游登记出处，「不得读作已消」。

【存量基线=棘轮，不是豁免】2026-11-08 现盘亲测（正本/仓本两份一致）：暗行 36 条
  （BASELINE_DARK_PIPES，全部 6 未转义竖线）。卡面判据「全部锚行 ≥7」对存量不可
  满足，而 /账本/ 为 judge-paths 登记证明面（判据面零改动纪律，本批禁入）——故按
  ledger-face-recon-gate 族「登记腿」形制落棘轮：存量逐轮点名不得读作已消；新增
  （R1）/漂移（R2）/消失（R3）/漂白（R4）即红；基线**只许收紧**（正形化落地后由
  判官批 PR 同批下调），扩大 = 新增豁免吸收真缺口，禁（/tools/ 判官锁 + 本门 CI
  腿双面把守）。本基线非上游逐条登记件：36 条是 D-141 登记现象（畸形行=暗行）的
  现盘实测全集，其中 D-101 为 D-141 行点名实证、其余 35 条同现象实测在册——如实
  声明，勿读作逐条上游豁免。

用法：
  python3 -I tools/ledger-row-integrity-recon-gate.py            # 现盘实跑（CI 腿）
  python3 -I tools/ledger-row-integrity-recon-gate.py --selftest # 夹具自证（零网络）

出口：0=绿；2=红；3=执行错（面缺/不可证，不猜绿）。
自证（--selftest，造夹具自证会咬人）：
  ① 注入基线外新暗行（6 竖线新编号）⇒ 必红（R1）；
  ② 基线暗行竖线数漂移（6→5）⇒ 必红（R2）；
  ③ 基线编号整行消失 ⇒ 必红（R3）；
  ④ 暗行在场而 D-141 登记行被摘 ⇒ 必红（R4）；
  ⑤ 基线暗行正形化（6→7）⇒ 绿+响亮收紧注记（修不受罚）；
  ⑥ 现盘未改动 ⇒ 绿（36 条基线暗行逐条点名+2 条超管行注记）。
"""
import os
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_REL = os.path.join("账本", "阶段欠账台账.md")
ANCHOR_PIPES_MIN = 7        # 引擎 row_id_of 同源：引导|+6 格 ≥7 未转义竖线
REG_ID = "D-141"            # 上游登记行（首格编号）；豁免与登记共存亡

# ---- 存量基线（2026-11-08 亲测棘轮；编号 → 未转义竖线数）------------------------
# 只许收紧不许扩大：收紧=正形化后判官批 PR 同批下调；扩大=新增豁免吸收真缺口，禁。
# 正本（计划/）与仓本（账本/）2026-11-08 实测同集（裁21 字节级收敛后）。
BASELINE_DARK_PIPES = {
    "D2-1": 6, "D2-2": 6, "P3-A1": 6, "P3-C1": 6, "RT-PP3": 6,
    "RT-E32-CLEAN": 6, "RT-E58": 6, "RT-E73": 6, "RT-E76": 6, "RT-E79": 6,
    "RT-E1": 6, "RT-E6": 6, "RT-E9": 6, "RT-E27": 6, "RT-E29": 6,
    "RT-E59": 6, "RT-E98": 6, "RT-E101": 6, "RT-E103": 6, "RT-E109": 6,
    "RT-E110": 6, "RT-E111": 6, "RT-E112": 6, "RT-E119": 6, "RT-E164": 6,
    "RT-E68": 6, "RT-E113": 6, "RT-E148": 6, "RT-E159": 6, "RT-E160": 6,
    "RT-E162": 6, "RT-E165": 6, "RT-E166": 6, "RT-E216": 6, "RT-E229": 6,
    "D-101": 6,
}


def err(msg):
    sys.stderr.write("[ledger-row-integrity-recon-gate] %s\n" % msg)


def unescaped_pipes(line):
    r"""未转义竖线计数（`\` 转义其后一个字符；与引擎 boundaries 同源）。"""
    n, esc = 0, False
    for ch in line:
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == "|":
            n += 1
    return n


def first_cell(line, npipes):
    """首格文本（pipe[0] 与 pipe[1] 之间；无第二枚竖线时取行首格尾）。"""
    if npipes < 2:
        return line[1:].strip()
    idx, esc = [], False
    for i, ch in enumerate(line):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == "|":
            idx.append(i)
            if len(idx) == 2:
                return line[idx[0] + 1:idx[1]].strip()
    return line[1:].strip()


def scan(text):
    """全量形态扫描 ⇒ (candidates, darks, overs)。

    candidates=[(行号, 首格, 竖线数)]（排除分隔行/表头行）；
    darks=candidates 中 <7 者；overs=candidates 中 ≥7 且 ≠7 者。
    """
    candidates, darks, overs = [], [], []
    for i, line in enumerate(text.split("\n"), 1):
        if not line.startswith("|"):
            continue
        s = line.strip()
        if s.startswith("|---") or set(s) <= set("|-: "):
            continue                      # 分隔行
        n = unescaped_pipes(s)
        cell1 = first_cell(s, n)
        if cell1 == "编号" or not cell1:
            continue                      # 表头行/空首格（引擎 row_id_of 同 exclusion）
        candidates.append((i, cell1, n))
        if n < ANCHOR_PIPES_MIN:
            darks.append((i, cell1, n))
        elif n != ANCHOR_PIPES_MIN:
            overs.append((i, cell1, n))
    return candidates, darks, overs


def check(path, baseline=None):
    """主判定 ⇒ (reds, notes, reading)；面不可读 ⇒ (None, [err], None)。"""
    baseline = BASELINE_DARK_PIPES if baseline is None else baseline
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return None, ["台账不可读：%s（%s）" % (path, exc)], None
    candidates, darks, overs = scan(text)
    reds, notes = [], []
    dark_ids = {c1: (ln, n) for ln, c1, n in darks}
    seen_ids = {c1 for _ln, c1, _n in candidates}
    reg_present = REG_ID in seen_ids

    # ---- R4 登记行缺席（豁免随登记共存亡）
    if darks and not reg_present:
        reds.append("R4 暗行 %d 条在场而 %s 登记行不在本册——上游登记被摘而债仍在"
                    "＝漂白形态（ESC-32/D-141）" % (len(darks), REG_ID))

    # ---- R1/R2 暗行棘轮
    for ln, c1, n in darks:
        if c1 not in baseline:
            reds.append("R1 %s:%d 新暗行「%s」（%d 未转义竖线 <7）——引擎不可见＝"
                        "D-141 逃逸形态复发（存量基线外，禁静默入册）"
                        % (os.path.basename(path), ln, c1, n))
        elif baseline[c1] != n:
            reds.append("R2 %s:%d 基线暗行「%s」形状漂移：基线=%d 竖线、实读=%d"
                        "（仍 <7；形状变化须对账不得静默）"
                        % (os.path.basename(path), ln, c1, baseline[c1], n))

    # ---- R3 基线编号整行消失
    for c1 in baseline:
        if c1 not in seen_ids:
            reds.append("R3 基线编号「%s」整行消失——append-only 证明面不可解释删除"
                        "（合法演化=翻状态格+行尾 append，行仍在；ESC-32/D-141）" % c1)

    # ---- 修不受罚：基线暗行正形化（≥7）→ 响亮收紧注记
    for c1 in baseline:
        ln, n = dark_ids.get(c1, (None, None))
        if n is None and c1 in seen_ids:
            notes.append("基线暗行「%s」已转 ≥7 竖线（正形化已落？）⇒ 基线须同批收紧"
                         "（判官批 PR 下调 BASELINE_DARK_PIPES；本门不罚修）" % c1)

    # ---- 超管行注记（≥7 且 ≠7；卡面判据已达，ESC-32 更严腿如实留痕）
    for ln, c1, n in overs:
        notes.append("%s:%d 超管行「%s」：%d 未转义竖线（≥7 引擎可见；≠7 为 ESC-32"
                     " 更严腿观察项，收严须判官批 PR）"
                     % (os.path.basename(path), ln, c1, n))

    # ---- 存量基线暗行逐轮点名（不得读作已消）
    if darks:
        notes.append("存量基线暗行 %d 条（棘轮基线 2026-11-08 亲测；D-141 登记现象"
                     "现盘全集，非逐条上游豁免；逐条如下，不得读作已消；D-141 正修批"
                     "落地后基线须同批收紧）：" % len(darks))
        for ln, c1, n in darks:
            notes.append("  暗行 %s:%d「%s」%d 未转义竖线（基线=%s）——引擎/占用闸/"
                         "planner 锚宇宙不可见（D-141）"
                         % (os.path.basename(path), ln, c1, n, baseline.get(c1, "缺")))

    reading = ("rows=%d visible=%d dark=%d baseline=%d over7=%d reg_row=%s"
               % (len(candidates), len(candidates) - len(darks), len(darks),
                  len(baseline), len(overs), "在" if reg_present else "缺"))
    return reds, notes, reading


def selftest():
    fails = []
    tmp = tempfile.mkdtemp(prefix="rowint-fixture-")

    def fixture(name, text):
        p = os.path.join(tmp, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    HDR = ("| 编号 | 欠什么 | 暴露自 | 验收门 | 批次归属 | 状态 |\n"
           "|---|---|---|---|---|---|\n")
    reg_row = ("| D-141 | 台账同步引擎只对锚行对账 | 逃逸台账 | 行完整性门 | 修批 "
               "| 未开始 |\n")
    ok_row = "| D-900 | 完好锚行样例 | 自证 | 七竖线 | 夹具 | 未开始 |\n"
    dark_row = "| D-901 | 畸形行样例（六竖线暗行）| 自证 | 行完整性门 | 夹具 | ✅ ｜〔注〕\n"
    over_row = ("| D-902 | 超管行样例 | 自证 | 九竖线 | 夹具 | rc=0 | 真锚喂入 |\n")

    base = {c1: 6 for c1 in BASELINE_DARK_PIPES}

    # ① 基线外新暗行 ⇒ 必红（R1）
    p1 = fixture("f1.md", HDR + reg_row + ok_row + dark_row)
    reds, _n, _r = check(p1, baseline=dict(base))
    if not any(r.startswith("R1") and "D-901" in r for r in reds):
        fails.append("夹具① 基线外新暗行应红未红：%s" % (reds or [])[:2])
    else:
        print("  夹具① 基线外新暗行 ⇒ 红（R1 点名 D-901）")

    # ② 基线暗行形状漂移（基线记 6、实读 5）⇒ 必红（R2）
    dark5 = "| D-901 | 畸形行样例（五竖线）| 自证 | 行完整性门 | ✅\n"
    p2 = fixture("f2.md", HDR + reg_row + ok_row + dark5)
    reds2, _n2, _r2 = check(p2, baseline={"D-901": 6})
    if not any(r.startswith("R2") and "D-901" in r for r in reds2):
        fails.append("夹具② 基线暗行形状漂移应红未红：%s" % (reds2 or [])[:2])
    else:
        print("  夹具② 基线暗行 6→5 漂移 ⇒ 红（R2）")

    # ③ 基线编号整行消失 ⇒ 必红（R3）
    p3 = fixture("f3.md", HDR + reg_row + ok_row)
    reds3, _n3, _r3 = check(p3, baseline={"D-901": 6})
    if not any(r.startswith("R3") and "D-901" in r for r in reds3):
        fails.append("夹具③ 基线编号整行消失应红未红：%s" % (reds3 or [])[:2])
    else:
        print("  夹具③ 基线编号整行消失 ⇒ 红（R3）")

    # ④ 暗行在场而 D-141 登记行被摘 ⇒ 必红（R4）
    p4 = fixture("f4.md", HDR + ok_row + dark_row)
    reds4, _n4, _r4 = check(p4, baseline={"D-901": 6})
    if not any(r.startswith("R4") for r in reds4):
        fails.append("夹具④ 登记行缺席应红未红：%s" % (reds4 or [])[:2])
    else:
        print("  夹具④ 暗行在场而 D-141 登记行缺席 ⇒ 红（R4）")

    # ⑤ 基线暗行正形化（6→7）⇒ 绿 + 响亮收紧注记（修不受罚）
    fixed = ("| D-901 | 畸形行样例（已正形化）| 自证 | 行完整性门 | 夹具 "
             "| ✅ ｜〔注〕 |\n")
    p5 = fixture("f5.md", HDR + reg_row + ok_row + fixed)
    reds5, notes5, _r5 = check(p5, baseline={"D-901": 6})
    if reds5:
        fails.append("夹具⑤ 正形化不应红：%s" % reds5[:2])
    elif not any("基线须同批收紧" in n for n in notes5):
        fails.append("夹具⑤ 正形化缺收紧注记（响亮面缺席）")
    else:
        print("  夹具⑤ 基线暗行正形化 ⇒ 绿+收紧注记（修不受罚）")

    # ⑥ 现盘未改动 ⇒ 绿（基线暗行逐条点名+超管行注记在注记面）
    reds6, notes6, reading6 = check(os.path.join(WS, LEDGER_REL))
    if reds6:
        fails.append("夹具⑥ 现盘应绿却红：%s" % reds6[:3])
    else:
        named = sum(1 for n in notes6 if n.strip().startswith("暗行 "))
        print("  夹具⑥ 现盘未改动 ⇒ 绿（%s；基线暗行点名 %d 条）"
              % (reading6, named))
        if named != len(BASELINE_DARK_PIPES):
            fails.append("夹具⑥ 基线暗行点名数 %d ≠ 基线 %d（点名面须逐条）"
                         % (named, len(BASELINE_DARK_PIPES)))
    return fails


def main(argv):
    if "--selftest" in argv:
        fails = selftest()
        for f in fails:
            err("自证失败：%s" % f)
        print("自证：%s" % ("全过" if not fails else "有 %d 项失败" % len(fails)))
        return 0 if not fails else 2
    reds, notes, reading = check(os.path.join(WS, LEDGER_REL))
    if reds is None:
        for n in notes:
            err(n)
        return 3
    print("[读数] %s" % reading)
    for n in notes:
        print("[注] %s" % n)
    if reds:
        for r in reds:
            print("[红] %s" % r)
        print("结论：红（台账行完整性门·暗行棘轮，ESC-32/D-141）")
        return 2
    print("结论：绿（台账行完整性门·暗行棘轮——新暗行 0、基线形状/在册/登记面对账全过；"
          "存量基线暗行见上方逐条点名，不得读作已消）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
