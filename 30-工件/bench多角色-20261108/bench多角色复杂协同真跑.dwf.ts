// bench多角色复杂协同真跑.dwf.ts — bench 多角色冷交接协同编排模板（收敛版 v1.1 · D-169）
//
// 【件性声明（诚实面·先行）】本件为**重建件**，非 v1.0 原脚本字节拷贝：
//   - v1.0 实跑模板原坐标 `.zcode/workflow-drafts/bench多角色复杂协同真跑.dwf.ts`
//     （运行件 `.zcode/workflow-runs/dwfrun-916d661f-…mjs`），跑后草稿位不在盘——
//     SPEC 与编排脚本两份契约零对账的根源（retrospective.md §三.2）。
//   - 本件结构依据 = retrospective.md §一（相序与计时）/§三.1（独立判分相证据 .dwf.ts:50-53）/
//     §三.2（BASE 路径硬编码证据 .dwf.ts:8）＋ actor 留痕面
//     （sess_dwf-dwfrun-916d661f-*-actor_{2..6,9}_1）复原，2026-11-09 由 D-169 施工员重建。
//   - 重建同时落两处收敛（issue #264 · D-169，SPEC v1.1 §4.7 条款化）：
//     ① 判分相二选一（留一删一）：**删** v1.0 独立「判分执行员」复判相（原 :50-53；
//        两轮 judge.json cmp 逐字节同、冗余墙钟 ~5m——retrospective §三.1 实证）；
//        **留** 测试员腿全链判分（SPEC §4.3-6 → §4.4 唯一产生点）。
//     ② BASE 路径与 SPEC §二布局清单（v1.1 实盘名）同源：本件 ROOT 下所有坐标逐字取自
//        SPEC §二「布局清单（冻结 v1.1）」，由 layout-recon.py 双向对账（缺名/异名/孤儿 ⇒ rc=1）。
//   - 本件为契约/模板件：随目录落档受对账门约束；跑批执行由编排面按相序另起运行件，运行件
//     不回写本件。
//
// 【对账标记（layout-recon.py 消费；禁稀释）】
//   judge-producer-site 标记 —— 只允许出现在 SPEC §4.4（唯一产生点；本模板零处，文档行亦禁带冒号样值）
//   judge-ref 引用 —— 本模板测试员相对唯一产生点的引用（本件恰 1 处，即 p5 相内注释）
//   本模板相清单（PHASES[].id）零判分相/零复判相——判分执行员类相 id/kind 不得出现
//   （layout-recon.py 签名扫描，命中即 rc=1）。

type PhaseKind = "pick" | "design" | "investigate" | "build" | "test" | "review" | "retro";

interface Phase {
  id: string;                 // 相标识（对账扫描面；禁 judge*/rejudge* 相）
  kind: PhaseKind;
  role: string;               // 角色名（与 SPEC §三 串行主干一致）
  inputs: string[];           // 输入工件（ROOT 相对坐标；逐字 = SPEC §二布局清单实盘名）
  outputs: string[];          // 输出工件（同上；条件件注明）
  ask: string;                // 派发载荷要点（§4.0 形制；载荷内嵌本模板，不落 card-*.md 档）
  notes: string;
}

// ROOT：工件根 = 本目录（SPEC §二）。v1.0 「.dwf.ts:8 BASE 路径硬编码在先、SPEC 布局后写且引
// 入 A-名」的漂移形态在此收编：BASE 只此一处声明，且坐标集合受 layout-recon.py 对 SPEC §二
// 清单的双向对账约束——模板不得引用清单外名，清单不得缺模板所投名。
const ROOT = "30-工件/bench多角色-20261108";

const PHASES: Phase[] = [
  {
    id: "p1-topic-pick",
    kind: "pick",
    role: "选题员",
    inputs: [],
    outputs: [], // v1.0 跑：TaskPick 仅在脚本内存零落盘（retrospective §三.9 证据缺）——
    // v1.1 义务（SPEC §4.7/复盘 F2）：落 task-pick.json（mode/instance/top3/rationale），
    // 落盘后入 SPEC §二 face:run 清单。
    ask: "从题面池 top3 选单体实例（mode/instance/top3/rationale 落 task-pick.json）；零代码零判分接触。",
    notes: "输出为条件件：task-pick.json（落盘义务 v1.1 起）。",
  },
  {
    id: "p2-spec-design",
    kind: "design",
    role: "设计员",
    inputs: ["task-pick.json"],
    outputs: ["SPEC.md"],
    ask: "按卡先例写 SPEC.md（冻结 v1.1 形制：§二机器可读布局清单 + §4.7 编排条款）；判官件零触碰。",
    notes: "SPEC 冻结后本模板 BASE 即受其 §二清单约束（对账门）。",
  },
  {
    id: "p3-investigate",
    kind: "investigate",
    role: "调查员",
    inputs: ["SPEC.md"],
    outputs: ["diagnosis.md"],
    ask: "SPEC §4.1：六节诊断报告 diagnosis.md（问题复述/根因/修复方案/涉及文件清单/风险/诚实注记）；零代码工件。",
    notes: "H0① 载荷 = §4.0 形制 ask 直发；不落 card-investigator.md 档（v1.1 处置）。",
  },
  {
    id: "p4-build",
    kind: "build",
    role: "施工员",
    inputs: ["SPEC.md", "diagnosis.md"],
    outputs: ["fix.patch", "impl-notes.md"],
    ask: "SPEC §4.2：按诊断施工，出 fix.patch + impl-notes.md（节名「一、改动点」形制）；禁碰测试件。",
    notes: "回环轮追加输入 Fb-r{n}.json（条件件）；H0② 载荷 ask 直发。",
  },
  {
    id: "p5-test",
    kind: "test",
    role: "测试员",
    inputs: ["SPEC.md", "fix.patch", "judge/task.json"],
    outputs: [
      "A3-test-readings.md",
      "A3-test-readings.json",
      "judge/eval.sh",
      "judge/baseline_log.txt",
      "judge/judged_log.txt",
      "judge/warm-relay-r1.json",
      "judge/prejudge-gate-r1.log",
      "judge/judge.json",
      "judge/judge.stderr",
    ],
    // judge-ref: spec-4.4-judge-leg（测试员腿内跑判分全链 = 对 SPEC §4.4 唯一产生点的调用；
    // 本模板不设、也禁设独立判分/复判相——D-169 删相留痕见 judge/judge-rejudge.json 注记）
    ask: "SPEC §4.3 六步 + §4.4 判分腿全链（warm-relay 五步→pre-judge 门→官方判分→judge.json）；读数双落 A3-test-readings.md/.json。",
    notes: "判分链零改动零触碰；judge.stderr 0 字节为健康态；逐字测试 ID 只入 judge/（内档）。",
  },
  {
    id: "p6-review",
    kind: "review",
    role: "评审员",
    inputs: ["SPEC.md", "diagnosis.md", "fix.patch", "impl-notes.md", "A3-test-readings.md", "A3-test-readings.json"],
    outputs: ["review.md", "A5-loss-metrics.json"],
    ask: "SPEC §4.5：冷看三工件出 review.md（key_for 指纹/findings/裁决）；**另落 A5-loss-metrics.json（§六 schema，§4.5-4 验收）**（v1.1 · 复盘 F2 ask 义务）。",
    notes: "禁收 judge.json；A5 未落 = 欠账不收卷（v1.0 跑曾未落，如实记）。",
  },
  {
    id: "p7-retrospective",
    kind: "retro",
    role: "复盘员",
    inputs: ["SPEC.md", "diagnosis.md", "fix.patch", "impl-notes.md", "A3-test-readings.md", "review.md", "judge/judge.json"],
    outputs: ["retrospective.md", "timing-ledger.md"],
    ask: "全环复盘 retrospective.md（计时/损耗/摩擦/修复建议）+ timing-ledger.md（T0–T16 逐行证据坐标；禁替位——v1.0 落位差教训 F7）。",
    notes: "收口前跑 layout-recon.py 对账门（SPEC §七.7）：①布局对账 ②产生点唯一性 逐条留 rc 读数。",
  },
];

// 相序编排（串行主干 = SPEC §三；无判分相——判分在 p5 测试员腿内）：
//   pick → design → investigate → build → test(含判分腿全链) → review → retro
// 回环（SPEC §4.6）：judge.json resolved=false ⇒ test 相产 Fb-r{n}.json → build 再入
//   （≤2 轮；判分每轮在测试员腿内全量重跑，模板不增相）。
//
// 对账门调用样例（收口/改动后）：
//   python3 -I layout-recon.py --root <本目录> layout     # ① SPEC §二清单 ↔ 盘面双向（rc=0 才绿）
//   python3 -I layout-recon.py --root <本目录> judge-unique # ② producer 计数==1 ∧ 零判分相签名
//   python3 -I layout-recon.py --root <本目录> v10-pre      # 改前态漂移读数（6 缺+5 异名 复现面）
//
// 禁项（违一条即本模板不收卷）：禁独立判分相/复判相；禁 BASE 路径引用 SPEC §二清单外名；
// 禁 judge-producer-site 标记入本模板（产生点唯一归 SPEC §4.4）；禁凭据/内网段/私路径字面；
// 禁触碰判官件/判据面/门禁件。

export { ROOT, PHASES };
export type { Phase, PhaseKind };
