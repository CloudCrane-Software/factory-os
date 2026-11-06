#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D-102-B 验收件：TAC `sde-update-readme` 交付物机验（父卡 #34 / 子卡 #93）。

任务书逐字要求：
  · level 2 heading：`Contribute to this project`
  · 标题下文本逐字：`We welcome contributions to this project. Please follow the guidelines to contribute.`
  · 内容后加一空行（"Remember to add a blank line after the content"）

断言（任一不过即 exit 1，禁猜绿）：
  V1 章节标题是 level-2（恰两个 #）且逐字等于 `Contribute to this project`
  V2 标题下文本逐字等于任务书指定句
  V3 内容后恰一空行（章节件末行即空行）
  V4 章节在交付正本中恰出现一次，且插在 License 段内容行之后、链接引用定义之前
  V5 交付正本撤下该章节后，git blob sha == pinned API 对账值（防漂移/防夹带）
  V6 统一 diff 单文件、纯新增 4 行、零删除零修改
  V7 patch index 双 sha 自洽（原 sha=pinned 前缀；新 sha=交付正本 blob sha）
"""
import hashlib
import re
import sys

HERE = __file__.rsplit("/", 1)[0]
SECTION = HERE + "/README-contribute-section.md"
AFTER = HERE + "/README-after.md"
PATCH = HERE + "/readme-contribute.patch"
PINNED_BLOB_SHA = "5c9acd4de3e8a0dc9a1ec9d81313191e94d05ca6"
PINNED_COMMIT = "af5bdf67aa92"
HEADING = "## Contribute to this project"
TEXT = ("We welcome contributions to this project. "
        "Please follow the guidelines to contribute.")


def fail(msg):
    print("FAIL " + msg)
    sys.exit(1)


def blob_sha(text):
    return hashlib.sha1(("blob %d\x00" % len(text.encode())).encode() + text.encode()).hexdigest()


def main():
    sec = open(SECTION, encoding="utf-8").read()
    after = open(AFTER, encoding="utf-8").read()
    body = open(PATCH, encoding="utf-8").read()
    sl = sec.split("\n")

    # V1
    if sl[0] != HEADING:
        fail("V1 章节标题 = %r，期望 %r" % (sl[0], HEADING))
    if not re.fullmatch(r"##[^#].*", sl[0]):
        fail("V1 标题不是 level-2（恰两个 #）：%r" % sl[0])
    print("V1 ok  标题 level-2 且逐字 = %s" % HEADING)
    # V2
    if sl[2] != TEXT:
        fail("V2 标题下文本 = %r，期望 %r" % (sl[2], TEXT))
    print("V2 ok  标题下文本逐字 = %s" % TEXT)
    # V3
    if sl[3] != "":
        fail("V3 内容后第 1 行 = %r，期望空行" % sl[3])
    if sec != HEADING + "\n\n" + TEXT + "\n\n":
        fail("V3 章节件形态不符（应恰 4 行：标题/空/文本/空）")
    print("V3 ok  内容后恰一空行（章节件 = 标题+空行+文本+空行，共 4 行）")
    # V4 插点与唯一性
    al = after.split("\n")
    hits = [i for i, l in enumerate(al) if l == HEADING]
    if len(hits) != 1:
        fail("V4 标题在交付正本出现 %d 次，期望 1" % len(hits))
    i = hits[0]
    if not (al[i + 2] == TEXT and al[i + 3] == ""):
        fail("V4 插点上下文不符：%r" % al[i:i + 4])
    if not (i > 0 and al[i - 2] == "Distributed under the MIT License. See [`LICENSE`](./LICENSE) for more information."
            and al[i - 1] == ""):
        fail("V4 章节未紧接 License 段内容行之后的空行：%r" % al[i - 3:i])
    if not (al[i + 4].startswith("[contributors-shield]:")):
        fail("V4 章节后未紧接链接引用定义段：%r" % al[i + 4])
    print("V4 ok  章节恰 1 次，插在 License 段内容行之后、链接引用定义之前（1-based 行 %d）" % (i + 1))
    # V5 撤下章节回 pinned
    stripped = "\n".join(al[:i] + al[i + 4:])
    if blob_sha(stripped) != PINNED_BLOB_SHA:
        fail("V5 撤下章节的 blob sha = %s，≠ pinned %s" % (blob_sha(stripped), PINNED_BLOB_SHA))
    print("V5 ok  交付正本撤下该 4 行 → blob sha == pinned API 对账值 %s（commit %s）" % (
        PINNED_BLOB_SHA, PINNED_COMMIT))
    # V6 diff 面
    files = re.findall(r"^diff --git a/(\S+) b/(\S+)$", body, re.M)
    if files != [("README.md", "README.md")]:
        fail("V6 diff 触的文件 = %r，期望仅 README.md" % files)
    minus = [l for l in body.split("\n") if l.startswith("-") and not l.startswith("---")]
    plus = [l for l in body.split("\n") if l.startswith("+") and not l.startswith("+++")]
    if minus:
        fail("V6 diff 有删除行 %r——任务书是纯新增章节" % minus)
    if [l[1:] for l in plus] != [HEADING, "", TEXT, ""]:
        fail("V6 diff 新增行集合不符：%r" % [l[1:] for l in plus])
    print("V6 ok  diff 单文件 README.md、删 0 行、增 4 行（=章节件四行逐字）")
    # V7 index 双 sha
    m = re.search(r"^index ([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})(?: \d+)?$", body, re.M)
    if not m:
        fail("V7 diff index 行缺失")
    a_sha, b_sha = m.group(1), m.group(2)
    if not PINNED_BLOB_SHA.startswith(a_sha):
        fail("V7 原 sha %s 非 pinned %s 前缀" % (a_sha, PINNED_BLOB_SHA))
    if not blob_sha(after).startswith(b_sha):
        fail("V7 新 sha %s 与交付正本 blob sha %s 不符" % (b_sha, blob_sha(after)))
    print("V7 ok  index 原 sha %s… = pinned 前缀；新 sha %s… = 交付正本 blob sha %s" % (
        a_sha[:12], b_sha[:12], blob_sha(after)[:12]))
    print("VERDICT: B 交付物机验全过（V1-V7）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
