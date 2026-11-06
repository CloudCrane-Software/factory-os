#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D-102-A 验收件：TAC `sde-fix-factual-mistake` 交付物机验（父卡 #34 / 子卡 #92）。

断言（任一不过即 exit 1，禁猜绿）：
  V1 修复后正本 L20 == "Thursday"（1-based 行号，任务书点名）
  V2 修复后正本 L24 ≈ 0.620537（容差 1e-6，任务书点名）
  V3 事实独立复核：2099-01-01 的星期由 datetime 现算（不采信任务书）；
     ∫₋₁¹ sin(x²)dx 由两法互证（Simpson 10⁶ 区间 + Taylor 级数）
  V4 diff 面仅触 `agenthub/micro/math_agent/agent.yaml` 一个文件、恰两行
  V5 pinned 原本文本与 GitHub API blob sha 对账值一致（防漂移）
  V6 统一 diff 与修复后正本自洽：把 diff 反应用到原本文本上得到修复后正本
"""
import datetime
import hashlib
import math
import re
import sys

HERE = __file__.rsplit("/", 1)[0]
AGENT_YAML = HERE + "/agent.yaml"
PATCH = HERE + "/agent.yaml.patch"
# GET /repos/All-Hands-AI/OpenHands/contents/agenthub/micro/math_agent/agent.yaml?ref=af5bdf67aa92
PINNED_BLOB_SHA = "9f7dd20c6cfe4d2671298cf6f1e7018d2580ad78"
PINNED_COMMIT = "af5bdf67aa92"
TARGET_PATH = "agenthub/micro/math_agent/agent.yaml"


def fail(msg):
    print("FAIL " + msg)
    sys.exit(1)


def main():
    raw = open(AGENT_YAML, encoding="utf-8").read()
    lines = raw.split("\n")
    # V1
    if lines[19] != '      answer: "Thursday"':
        fail("V1 L20 = %r，期望 '      answer: \"Thursday\"'" % lines[19])
    print("V1 ok  L20 =", lines[19].strip())
    # V2
    m = re.match(r'^\s*answer: "([0-9.]+)"\s*$', lines[23])
    if not m:
        fail("V2 L24 形态不符：%r" % lines[23])
    val = float(m.group(1))
    if abs(val - 0.620537) > 1e-6:
        fail("V2 L24 = %.9f，期望 ≈0.620537（容差 1e-6）" % val)
    print("V2 ok  L24 = %.9f（与 0.620537 差 %.2e）" % (val, abs(val - 0.620537)))
    # V3 事实独立复核
    wd = datetime.date(2099, 1, 1).strftime("%A")
    if wd != "Thursday":
        fail("V3a datetime 现算 2099-01-01 = %s，期望 Thursday" % wd)
    print("V3a ok  datetime.date(2099,1,1).strftime('%%A') = %s" % wd)
    f = lambda x: math.sin(x * x)
    n = 1000000
    h = 2.0 / n
    s = f(-1.0) + f(1.0)
    for i in range(1, n):
        s += f(-1.0 + i * h) * (4 if i % 2 else 2)
    simp = s * h / 3
    series = 0.0
    for k in range(12):
        series += 2 * ((-1) ** k) / (math.factorial(2 * k + 1) * (4 * k + 3))
    if abs(simp - series) > 1e-9 or abs(simp - 0.620536603) > 1e-8:
        fail("V3b 两法积分不一致：Simpson=%.9f series=%.9f" % (simp, series))
    print("V3b ok  Simpson=%.9f  series=%.9f（一致；0.620537 为 6 位有效数字表述）" % (simp, series))
    # V4 diff 面
    body = open(PATCH, encoding="utf-8").read()
    files = re.findall(r"^diff --git a/(\S+) b/(\S+)$", body, re.M)
    if not files or any(a != b or a != TARGET_PATH for a, b in files):
        fail("V4 diff 触的文件 = %r，期望仅 %s" % (files, TARGET_PATH))
    minus = [l for l in body.split("\n") if l.startswith("-") and not l.startswith("---")]
    plus = [l for l in body.split("\n") if l.startswith("+") and not l.startswith("+++")]
    if len(minus) != 2 or len(plus) != 2:
        fail("V4 diff 删除 %d 行/新增 %d 行，期望各 2（任务书点名两行）" % (len(minus), len(plus)))
    if [l[1:] for l in minus] != ['      answer: "Saturday"', '      answer: "0.603848"']:
        fail("V4 删除行集合不符：%r" % [l[1:] for l in minus])
    if [l[1:] for l in plus] != ['      answer: "Thursday"', '      answer: "0.620537"']:
        fail("V4 新增行集合不符：%r" % [l[1:] for l in plus])
    print("V4 ok  diff 仅触 %s，删 %d 行/增 %d 行（=任务书点名两处）" % (
        TARGET_PATH, len(minus), len(plus)))
    # V5 pinned 原本文本与 GitHub API blob sha 对账（防漂移）；diff index 行双 sha 前缀自洽
    m5 = re.search(r"^index ([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})(?: \d+)?$", body, re.M)
    if not m5:
        fail("V5 diff index 行缺失或形态不符")
    a_sha, b_sha = m5.group(1), m5.group(2)
    if not PINNED_BLOB_SHA.startswith(a_sha):
        fail("V5 diff index 原 sha = %s，非 pinned 值 %s 的前缀" % (a_sha, PINNED_BLOB_SHA))
    fixed_blob = _sha(raw)
    if not fixed_blob.startswith(b_sha):
        fail("V5 diff index 新 sha = %s，与交付正本 git blob sha %s 不符" % (b_sha, fixed_blob))
    print("V5 ok  diff index 原 sha %s… = pinned %s 前缀（commit %s）；新 sha %s… = 交付正本 blob sha" % (
        a_sha[:12], PINNED_BLOB_SHA[:12], PINNED_COMMIT, b_sha[:12]))
    # V6 链自洽：交付正本反向撤销两处订正 → 文本 git blob sha == pinned API 对账值
    orig = raw.replace('"Thursday"', '"Saturday"').replace('"0.620537"', '"0.603848"')
    if _sha(orig) != PINNED_BLOB_SHA:
        fail("V6 反向撤销两处订正得到的文本 blob sha = %s，≠ pinned %s" % (_sha(orig), PINNED_BLOB_SHA))
    if orig.replace('"Saturday"', '"Thursday"').replace('"0.603848"', '"0.620537"') != raw:
        fail("V6 反向链不自洽")
    print("V6 ok  交付正本→反撤两处订正→blob sha == pinned API 对账值（%s），链自洽" % PINNED_BLOB_SHA)
    print("VERDICT: A 交付物机验全过（V1-V6）")
    return 0


def _sha(text):
    return hashlib.sha1(("blob %d\x00" % len(text.encode())).encode() + text.encode()).hexdigest()




if __name__ == "__main__":
    sys.exit(main())
