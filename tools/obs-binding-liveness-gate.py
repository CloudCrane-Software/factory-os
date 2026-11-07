#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门绑定活性扫描（obs 巡检形制）——ESC-33/G10 strategies_glob 路径腐烂逃逸的扫描化。

设计来源（PR body 引用面）：30-工件/逃逸问题台账-20261108.md ESC-33（新门设计：
  「门绑定活性扫描：registry 每个 strategies_glob 断言①路径存在性②glob ≥1 文件
  命中（0 命中⇒红且输出区分『路径腐烂/集合空』两态）」）；动机事件=G10 绑定
  strategies_glob 指向已删工作树 af-wt-sil-writeback，红线自 11-05 起常亮，根因系
  路径腐烂非策略库消失（2026-11-07 repath 勘正至 af-wt-neu，备份
  .bak-20261107-g10-repath）。形制对齐仓内 obs-* 族（obs-deadcode-scan-gate.py /
  obs-runtime-guard-gate.py：出口 0/2/3、判据单一源自含、登记面=gate-registry.json、
  --selftest 造夹具自证会咬人）。

判据源=单一源（本文件自含判据）；登记面=
  30-工件/观测面清偿批-20261105/gate-registry.json 的 greenclaim_bindings
  （与 tools/ledger-greenclaim-recon-gate.py 同一登记面——**分工**：本门只扫
  绑定的**活性**（路径存在性+≥1 文件命中）；绑定计数（confirmed 数）与台账
  行态 ✅ 的对账仍归 ledger-greenclaim-recon-gate 机制④既有判据，不重复不搬家
  （confirmed=0 时 G10 不得 ✅ 的红线原样保留）。

【红（exit 2）】
  B1 路径腐烂：strategies_glob 目录缺席（G10 的 11-05 形态本体——目录被删/
     改名后绑定零命中，红线常亮而无人分诊）。
  B2 集合空：目录在、glob 零命中——与 B1 **分开点名**（ESC-33 根因细节：
     「路径腐烂」与「策略库真空」两态在绑定腿读数上不可分辨 = 真信号淹没；
     腐烂被读成缺口、缺口也被读成腐烂）。
  B3 绑定面形状漂移：greenclaim_bindings 段缺席/空；known 绑定条目缺
     strategies_glob（登记面自身坏行不可证，不猜绿）。
【面缺（exit 3）】登记面不可读/不可解析——不可证不猜绿。
【绿（exit 0）】每个绑定：目录在 + glob ≥1 枚现存普通文件命中（读数含命中总数
  与前 3 枚样例名）。

部署面（如实声明）：obs 巡检形制、登记面为 org 工作区件 ⇒ **不进 factory-os PR
  CI**（PR 检出树无该登记面，点选即 rc=2/3 缺件显式红——D-103 机制步同口径）。
  消费面=anolis crontab obs 门族（obs-deadcode-scan-gate / ledger-greenclaim-
  recon-gate / obs-runtime-guard-gate 同一 cron 行，18 分拍）——本批 22:00–06:00
  禁改窗内零 crontab/服务配置改动，接线留下一运营者窗（PR body 如实登记）。

用法：
  python3 -I tools/obs-binding-liveness-gate.py             # 现盘实跑（obs 巡检腿）
  python3 -I tools/obs-binding-liveness-gate.py --registry <路径>  # 指定登记面
  python3 -I tools/obs-binding-liveness-gate.py --selftest  # 夹具自证（零网络）

出口：0=绿；2=红；3=执行错（面缺/不可证，不猜绿）。
自证（--selftest，造夹具自证会咬人）：
  ① glob 目录被删（路径腐烂）⇒ 必红且输出含「路径腐烂」；
  ② 目录在、零命中（集合空）⇒ 必红且输出含「集合空」；
  ③ 目录在且 ≥1 枚命中 ⇒ 绿；
  ④ 绑定条目缺 strategies_glob（known 类型）⇒ 必红（B3）；
  ⑤ greenclaim_bindings 段缺席 ⇒ 必红（B3）；
  ⑥ 现盘登记面未改动 ⇒ 绿（登记面缺席的检出树环境=如实跳过，不冒充绿）。
"""
import glob as globmod
import json
import os
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG_PATH = os.path.join(WS, "30-工件", "观测面清偿批-20261105", "gate-registry.json")
BIND_KEY = "greenclaim_bindings"
KNOWN_KINDS = ("confirmed_strategy_count",)   # 已知绑定类型（缺 strategies_glob 即 B3）


def err(msg):
    sys.stderr.write("[obs-binding-liveness-gate] %s\n" % msg)


def glob_dir(pattern):
    """glob 模式的宿主目录（无通配元字符的模式按其 dirname）。"""
    return os.path.dirname(pattern) or "."


def check(registry_path):
    """主判定 ⇒ (reds, notes, reading)；登记面不可读 ⇒ (None, [err], None)。"""
    try:
        with open(registry_path, encoding="utf-8") as fh:
            reg = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, ["登记面不可读：%s（%s）" % (registry_path, exc)], None
    if not isinstance(reg, dict):
        return None, ["登记面形状漂移：顶层非对象（%s）" % registry_path], None
    reds, notes = [], []
    bindings = reg.get(BIND_KEY)
    if not isinstance(bindings, dict) or not bindings:
        reds.append("B3 登记面 %s 段缺席/空——绑定面形状漂移（不可证不猜绿；"
                    "G10 绑定在册为登记事实，段消失即登记面坏行）" % BIND_KEY)
        return reds, notes, "bindings=0"
    hits_total = 0
    live = 0
    for rid in sorted(bindings):
        b = bindings.get(rid) or {}
        kind = b.get("kind")
        pattern = b.get("strategies_glob")
        if not pattern:
            if kind in KNOWN_KINDS:
                reds.append("B3 绑定 %s（kind=%s）缺 strategies_glob——known 类型"
                            "绑定必须有可扫描 glob（登记面坏行，不可证不猜绿）"
                            % (rid, kind))
            else:
                notes.append("绑定 %s：未知类型 %s 无 strategies_glob ⇒ 登记不判"
                             "（登记缺口，只注记不扩红）" % (rid, kind))
            continue
        d = glob_dir(pattern)
        if not os.path.isdir(d):
            reds.append("B1 路径腐烂：绑定 %s strategies_glob 宿主目录缺席：%s"
                        "（glob 必零命中——G10 11-05 形态：目录被删/改名后红线"
                        "常亮无人分诊；处置=repath 勘正并留 repath_note）"
                        % (rid, pattern))
            continue
        try:
            matches = sorted(globmod.glob(pattern))
        except (OSError, ValueError) as exc:
            reds.append("B3 绑定 %s glob 执行异常（%s）——不可证不猜绿"
                        % (rid, exc))
            continue
        files = [m for m in matches if os.path.isfile(m)]
        if not files:
            reds.append("B2 集合空：绑定 %s strategies_glob 零文件命中：%s"
                        "（目录在、集合空——与路径腐烂分开点名；若策略库真迁移，"
                        "登记面 repath 勘正同批留痕）" % (rid, pattern))
            continue
        hits_total += len(files)
        live += 1
        notes.append("绑定 %s：活性 OK——目录在、命中 %d 枚（样例：%s）"
                     % (rid, len(files), "、".join(os.path.basename(f) for f in files[:3])))
    reading = "bindings=%d live=%d hits_total=%d" % (len(bindings), live, hits_total)
    return reds, notes, reading


def selftest():
    fails = []
    tmp = tempfile.mkdtemp(prefix="binding-liveness-fixture-")

    def regfile(name, bindings):
        p = os.path.join(tmp, name)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({BIND_KEY: bindings}, fh, ensure_ascii=False)
        return p

    live_dir = os.path.join(tmp, "strategies-live")
    os.makedirs(live_dir, exist_ok=True)
    with open(os.path.join(live_dir, "st-000.yaml"), "w", encoding="utf-8") as fh:
        fh.write("status: confirmed\n")

    # ① 路径腐烂：目录被删 ⇒ 必红且含「路径腐烂」
    rot_dir = os.path.join(tmp, "strategies-rot")   # 刻意不创建
    p1 = regfile("f1.json", {"G10": {"kind": "confirmed_strategy_count",
                                     "strategies_glob": os.path.join(rot_dir, "st-*.yaml")}})
    reds, _n, _r = check(p1)
    if not any(r.startswith("B1") and "路径腐烂" in r for r in reds):
        fails.append("夹具① 路径腐烂应红未红：%s" % (reds or [])[:2])
    else:
        print("  夹具① glob 目录缺席 ⇒ 红（B1 路径腐烂点名）")

    # ② 集合空：目录在、零命中 ⇒ 必红且含「集合空」
    empty_dir = os.path.join(tmp, "strategies-empty")
    os.makedirs(empty_dir, exist_ok=True)
    p2 = regfile("f2.json", {"G10": {"kind": "confirmed_strategy_count",
                                     "strategies_glob": os.path.join(empty_dir, "st-*.yaml")}})
    reds2, _n2, _r2 = check(p2)
    if not any(r.startswith("B2") and "集合空" in r for r in reds2):
        fails.append("夹具② 集合空应红未红：%s" % (reds2 or [])[:2])
    else:
        print("  夹具② 目录在零命中 ⇒ 红（B2 集合空，与腐烂分开点名）")

    # ③ 目录在且 ≥1 命中 ⇒ 绿
    p3 = regfile("f3.json", {"G10": {"kind": "confirmed_strategy_count",
                                     "strategies_glob": os.path.join(live_dir, "st-*.yaml")}})
    reds3, notes3, _r3 = check(p3)
    if reds3:
        fails.append("夹具③ 存在命中应绿却红：%s" % reds3[:2])
    else:
        print("  夹具③ 目录在命中 1 枚 ⇒ 绿（%s）" % (notes3[0] if notes3 else ""))

    # ④ known 绑定缺 strategies_glob ⇒ 必红（B3）
    p4 = regfile("f4.json", {"G10": {"kind": "confirmed_strategy_count"}})
    reds4, _n4, _r4 = check(p4)
    if not any(r.startswith("B3") for r in reds4):
        fails.append("夹具④ known 绑定缺 strategies_glob 应红未红：%s" % (reds4 or [])[:2])
    else:
        print("  夹具④ known 绑定缺 strategies_glob ⇒ 红（B3）")

    # ⑤ greenclaim_bindings 段缺席 ⇒ 必红（B3）
    p5 = os.path.join(tmp, "f5.json")
    with open(p5, "w", encoding="utf-8") as fh:
        json.dump({"note": "no bindings section"}, fh, ensure_ascii=False)
    reds5, _n5, r5 = check(p5)
    if not any(r.startswith("B3") for r in reds5) or r5 != "bindings=0":
        fails.append("夹具⑤ 绑定段缺席应红未红：%s" % (reds5 or [])[:2])
    else:
        print("  夹具⑤ 绑定段缺席 ⇒ 红（B3 形状漂移）")

    # ⑥ 现盘登记面未改动 ⇒ 绿（登记面缺席环境=如实跳过，不冒充绿）
    if os.path.isfile(REG_PATH):
        reds6, notes6, reading6 = check(REG_PATH)
        if reds6:
            fails.append("夹具⑥ 现盘应绿却红：%s" % reds6[:3])
        else:
            print("  夹具⑥ 现盘登记面未改动 ⇒ 绿（%s）" % reading6)
    else:
        print("  夹具⑥ 现盘登记面缺席（org 工作区件，检出树环境）⇒ 如实跳过不冒充绿")
    return fails


def main(argv):
    path = REG_PATH
    if "--registry" in argv:
        path = argv[argv.index("--registry") + 1]
    if "--selftest" in argv:
        fails = selftest()
        for f in fails:
            err("自证失败：%s" % f)
        print("自证：%s" % ("全过" if not fails else "有 %d 项失败" % len(fails)))
        return 0 if not fails else 2
    reds, notes, reading = check(path)
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
        print("结论：红（门绑定活性扫描，ESC-33——绑定面有死 glob，禁读作策略库缺口）")
        return 2
    print("结论：绿（门绑定活性扫描，ESC-33——全部绑定路径在+≥1 命中；绑定计数↔台账"
          "行态对账仍归 ledger-greenclaim-recon-gate 机制④，本门不重复）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
