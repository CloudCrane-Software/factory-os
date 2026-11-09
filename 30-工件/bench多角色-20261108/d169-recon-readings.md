# D-169 收敛施工读数 · bench 布局侦察（w19-d169-bench-layout-recon · issue #264）

> 施工员：glm53-worker ｜ 日期：2026-11-09 ｜ 分支：task/264-w19 ｜ 允许路径：`30-工件/bench多角色-20261108`
> 读数纪律：pre-state 命令施工前跑留读数；selftest 真跑；改前后 sha256 对账；出仓词形自扫零命中才交。
> 环境预检回执：`dryrun-report.json`（needs-env-dryrun：仓内期望目录缺席 → 沙箱实盘坐标镜像入允许路径，
> 24 运行工件；私路径字面向化 6 件双 sha 留档）。

## 一、③ 改前后 SPEC sha256 对账（合线策略：改前 .bak ＋ 改前后对账）

| 件 | 角色 | sha256 |
|---|---|---|
| SPEC.md.v1.0.bak | 改前档（v1.0 字节原样，与沙箱实盘 cmp 逐字节同） | `c76726d9d08802780c36360383b2ec1d80d3c7d965ec13f1b399ffc1253ce5a1` |
| SPEC.md | 改后档（v1.1 · D-169 升版） | `7909276dab0b0c262415567e9933e809c38d14728e4a726fd7dc1e1172d8c856` |
| bench多角色复杂协同真跑.dwf.ts | 编排模板重建件（收敛版 v1.1；原 `.zcode/workflow-drafts/` 草稿不在盘，结构依 retrospective §一/§三 复原——件性声明见其头注） | `6c54820cae4825561492f0ebc4647651acd880b43ed8e3ef002e715b06ece296` |
| fix.patch | 运行工件（零触碰核：与实盘逐字节同） | `cad7015c642ce27b3d36b03d35a0a09266dd3c09f45182d68cd1a9ed5b9decaf`（= review.md key_for A2 值 ✓） |

镜像件向化指纹账（6 件 live/repo 双 sha）：见 `dryrun-report.json` redaction_ledger。

## 二、pre-state 读数（施工前实跑留档）

| # | 命令/探针 | 读数 | rc |
|---|---|---|---|
| P1 | `test -d "30-工件/bench多角色-20261108"`（worker 仓 @ task/264-w19） | 目录缺席（仓内全 refs/全历史零命中） | 1 |
| P2 | `test -f "…/SPEC.md"`（worker 仓） | 缺席 | 1 |
| P3 | `sha256sum "…/SPEC.md"`（worker 仓） | No such file | 1 |
| P4 | `grep -n 'D-169' 账本/阶段欠账台账.md` | 台账行在（199 行） | 0 |
| P5 | v1.0 §二表（21 位）对沙箱实盘机械分类（`layout-recon.py v10-pre` 逻辑） | **缺名 6**（card×4、A5、timing-ledger）＋**同物异名 5**（表侧 4：diagnosis/fix.patch/impl-notes/review ＋盘侧 A3 同容别名 1：test-report.md）＋盘侧替位 1（retrospective.md ↔ timing-ledger）＋条件件 1（Fb 回环不触发）——台账 D-169 行「6 缺＋5 同物异名」算术逐项复现 ✓ | 1（漂移态） |
| P6 | 判分产物产生点计数（盘面证据） | **2**：judge/judge.json（02:56:23，测试员腿全链内）＋ judge/judge-rejudge.json（03:15:09，编排器独立复判相）；两件 `cmp` 逐字节相同 rc=0；配套双跑证据 warm-relay-r1{-rejudge,}.json / prejudge-gate-r1{-rejudge,}.log 各两份——复盘 §三.1 双跑实证 | （计 2，违唯一性） |
| P7 | 改前 SPEC sha256（沙箱实盘） | `c76726d9d088…`（= .bak 档值） | 0 |

诚实注记：首轮 inline 预扫把在盘 warm-relay-r1/prejudge-gate-r1 误归「条件件不落」（`{n}`→`r1` 解析
错，应 `{n}`→`1`）；以 `layout-recon.py v10-pre`（提交件）复跑为准——上表 P5 即修正后读数，v10-pre
终读数「6 缺＋5 异名（4＋1）＋替位 1＋条件件 1」与复盘 §三.2 口径一致。

## 三、post-state 读数（施工后实跑；命令逐条可复算）

| # | 命令 | 读数 | rc |
|---|---|---|---|
| A1 | `python3 -I layout-recon.py --root . layout --face run`（施工须知①，运行工件面） | 核 24 项；缺名 0；孤儿 0 | **0** |
| A2 | `python3 -I layout-recon.py --root . layout`（①，全面 29 项） | 核 29 项；缺名 0；孤儿 0 | **0** |
| A3 | `python3 -I layout-recon.py --root . judge-unique`（施工须知②，产生点唯一性） | judge-producer-site 计数=1（SPEC.md §4.4 · spec-4.4-judge-leg）；模板 judge-ref=1（测试员相）；相清单判分相签名 0——冗余墙钟 ~5m 形态（独立复判相）结构性消解 | **0** |
| A4 | `python3 -I layout-recon.py --root . v10-pre`（改前态复现面） | 6 缺＋5 异名 复现 ✓（终行 `✓`） | 1（改前态恒漂移，读数件用） |
| A5 | `python3 -I layout-recon.py selftest` | 夹具 13 例全 PASS（尾 3 行见 §五） | **0** |
| A6 | 卡面验收集 `test -d` / `test -f` / `sha256sum SPEC.md` / `grep -n 'D-169' 账本/阶段欠账台账.md` | 全过（SPEC.md sha256 见 §一） | **0/0/0/0** |

## 四、收敛处置对账（F1 留一删一 ＋ F3 布局清零，逐项）

| 项 | 处置 | 落点 |
|---|---|---|
| F1 判分相归属 | **留**测试员腿全链（SPEC §4.3-6 → §4.4 唯一产生点，`judge-producer-site` 标记）；**删**编排器独立判分/复判相（模板相清单 p1–p7 零判分相；相序/禁相条款 SPEC §4.7；judge-unique 断言固化） | SPEC v1.1 §4.4/§4.7；模板重建件；layout-recon.py ② |
| F3 布局表 | §二改机器可读布局清单（face:run 24 ＋ face:meta 5，全部实盘名）；v1.0 A-名→实盘名映射表留档；缺件处置：card×4=派发载荷出布局（D-170 另卡）、A5=未落盘如实注记（F2 债）、timing-ledger=retrospective 替位注记（F7 债）、Fb=条件件；对账双向（缺名/异名/孤儿点名）rc=0 | SPEC v1.1 §二；layout-recon.py ① |
| F3 验收命令参数化 | §4.1（diagnosis.md 四节 grep）/§4.2-1/2/5（fix.patch）/§4.2-3（`^## 一、改动点` impl-notes.md——v1.0 字面验收红修复）/§4.3-4（A3-test-readings.md）/§4.5-1/2/3（review.md key_for/findings/裁决） | SPEC v1.1 §四 |
| 编排脚本坐标 | 模板入目录 `bench多角色复杂协同真跑.dwf.ts`（重建件，件性声明头注）；BASE 路径=SPEC §二清单同源，受对账门约束 | SPEC v1.1 §4.7 |
| 留痕件保全 | 复判产物 4 件（judge-rejudge.json/.stderr、warm-relay-r1-rejudge.json、prejudge-gate-r1-rejudge.log）留档为已删相 attestation（SPEC §二注记），不删不改 | judge/ |

## 五、selftest 尾 3 行（真跑留档；夹具 10 例）

```
  [PASS] 判分相 id 签名 ⇒ rc=1 拦截: got=True want=True
  [PASS] v10-pre 台账算术复现（6/4/2）rc=0: got=0 want=0
selftest: 10/10 PASS ⇒ rc=0
```

（夹具语义逐个：①happy 双向零差 ②happy 产生点=1 ③异名⇒rc=1 ④异名⇒缺名点名 ⑤异名⇒孤儿点名
⑥缺名⇒点名 ⑦孤儿⇒点名 ⑧双产生点⇒拦截 ⑨判分相签名⇒拦截 ⑩v10-pre 实树计数复现（6/4/2）——
10/10 PASS，rc=0。夹具期自纠留痕：初版夹具模板缺 producer 标记＋清单漏列模板件致 happy 二例红，
修夹具后全绿——被测断言语义未动。）

## 六、出仓词形自扫（commit 前终扫，四类形零命中才交）

| 形 | 扫描口径（自引字面以占位描述，避免自指命中） | 读数 |
|---|---|---|
| 真前缀族假令牌 | 四前缀族（ghp/sk/AKIA/PEM 头）＋对应最小长度字面后缀的正则全文扫描 | 0 命中 |
| 行内令牌族词＋长非数值串 | 四族词＋≤3 位分隔＋≥6 位字母下划线连字（大小写不敏感）全文扫描，命中行人工复核 | 0 命中（无字面值形态） |
| 内网 IP 四段 | 10/192/100.64-127 三段族四点十进全文扫描 | 0 命中 |
| 私路径字面 | 家目录前缀族（斜杠家目录形）全文扫描 | 0 命中（镜像向化 6 件，双 sha 见 dryrun-report.json） |

（终扫原文读数以 commit 前最后一次实跑为准，逐条 0 命中；扫描根=允许路径全量。）

（落定：2026-11-09 · glm53-worker · D-169 · issue #264）
