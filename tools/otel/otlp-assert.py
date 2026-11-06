#!/usr/bin/env python3
"""otlp-assert.py — OTLP 合规断言器（离线，零网络）。

对 emit 面产出的 span/trace 结构做逐条断言，输出 PASS/FAIL 清单 + 退出码。

判据来源（唯一真源，不另抄一份）：
  · 键集/命名/派生式 → tools/otel/span-conventions.md 的 §6 机器可读块（运行时解析）
  · 树形状          → otlp-model.md §1.5（本文档 §4.2 的可执行化）
  · ID 派生式       → otlp-model.md §1.0

用法：
  otlp-assert.py --selftest                    # 好样本绿 + 坏样本红（门禁用，秒级）
  otlp-assert.py --input FILE [FILE...]        # 断言 OTLP/JSON 载荷文件（resourceSpans 形状）
  otlp-assert.py --sidecar [SNAPSHOT]          # 用现役 状态观测/otel-sidecar.json 快照：
                                                #   经真实发射器（tools/otel/emit-sidecar.py）
                                                #   在本地复原 factory 族 span 后断言（不发网）
                                                #   前置含快照新鲜度（ts 距今 ≤ 4 周期帽）+
                                                #   发射面当轮非零成功（读快照 emit 块回执，
                                                #   只取当轮 span_sent/metrics_sent、不取进程
                                                #   累计量），冻结/倒挂/发射全灭 → exit 2
                                                #   （现役语义耦合，2026-11-02 修；帽的阈值
                                                #   由断言侧常量定，不采信快照自声明
                                                #   interval_s；取证回放旧快照用 --stale-cap-s
                                                #   显式放宽——该旗标不豁免发射面死活判据）
  otlp-assert.py --make-samples DIR            # 重新生成 mock 样本（tools/otel/samples/）
  otlp-assert.py --production                  # 真库模式（本件唯一带网络的一条）：逐名册项近窗
                                                #   入库计数下界（P1）+ **订单域总体逐行回查**
                                                #   （P2 键覆盖 100% / P3 语义层键齐全率 /
                                                #   P4 一条订单=一条 trace / P5 真库 trace 结构
                                                #   合规——层序/父链/派生 ID 在真 span 上求值；
                                                #   判据源=§6 production 块；真库=otel.otel_traces）
                                                #   ——「名册有项」与「生产有 span」之间此前无任何
                                                #   一层对账（RT-E90 机制②下半段/③），本模式补
                                                #   这一层
  otlp-assert.py --production-check            # 零网络消费面：只读状态面 状态观测/otel-production.json
                                                #   （由 --production 定时跑落盘）——末次判定红即红、
                                                #   读数过期即红（巡检停摆=静默无人见）、缺件/坏
                                                #   JSON → rc=2 不可证不猜绿

退出码：0=全部断言 PASS 且**无真空绿断言**；1=有断言 FAIL（或内部错误）；2=前置不满足
（样本/快照不在位、熔断文件在位、快照冻结/时钟倒挂、**发射面当轮零成功**、
状态面缺件/不可解析）——
all-gates.sh 自 2026-10-31 RT 批起 rc=2 非零即红（缺件/前置不满足按红点名对账，不静默 SKIP）。

**真空绿（vacuous green）防线**（2026-11-02 RT 修复批）：逐条断言记录「判定记录数」
（该断言实际在几条记录上求值）；判定记录数=0 的断言记 **[VACUOUS]** 并单列计数、
**不计 PASS**——此前 0 条记录求值的断言照样报 PASS（sidecar 载荷只含 1 个 factory span
时，R4/A5/N2/S1~S7 等 10 条断言在空集上求值却计入 PASS=26）。任一断言真空 → rc=2（不标绿）。

纪律：
  · 零网络：--sidecar 路径把 otel_emit._post 本地截获，不发任何请求；--production-check
    只读状态面（零网络）；**--production 是本件唯一带网络的模式**（真库只 SELECT，
    凭据只走 ch_client 既有链，零明文）；
  · 只读：不改任何被断言件（样本由 --make-samples 显式生成）。
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(os.path.dirname(HERE))
CONVENTION_MD = os.path.join(HERE, "span-conventions.md")
SAMPLES_DIR = os.path.join(HERE, "samples")
DEFAULT_SIDECAR = os.path.join(WS, "状态观测", "otel-sidecar.json")

ZERO_SPAN_ID = "0" * 16
HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX16 = re.compile(r"^[0-9a-f]{16}$")

# 边车采集周期（秒）——断言侧钉死值。新鲜度帽 = 4 周期、下界 120s（见
# _sidecar_stale_cap）。阈值必须由「断言方」定，不能由「被测快照」定：快照里的
# interval_s 是被测件自己写的字段（tools/otel/emit-sidecar.py:298），曾可把帽
# 放宽到任意大（陈旧快照自称「我周期 10 天」→ 24h 陈旧也算现役）。
# 2026-11-02 RT 修复：帽不再读快照 interval_s，改用本常量（边车缺省 30s/周期，
# 在役实例 pid 534502 的环境里无 OTEL_SIDECAR_INTERVAL，与本值同源同值）。
SIDECAR_TRUSTED_INTERVAL_S = 30


# --------------------------------------------------------------------------- #
# 约定加载（span-conventions.md §6 机器可读块）
# --------------------------------------------------------------------------- #
def load_convention(path: str = CONVENTION_MD) -> dict:
    """解析约定文档里的 JSON 块。解析失败 → 抛异常（调用方按内部错误 → exit 1）。"""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"<!-- CONVENTION-JSON:BEGIN -->\s*```json\s*(.*?)\s*```\s*"
                  r"<!-- CONVENTION-JSON:END -->", text, re.S)
    if not m:
        raise ValueError(f"约定文档缺机器可读块：{path}")
    return json.loads(m.group(1))


# --------------------------------------------------------------------------- #
# A1 语义层名册正本（三面消费之一：断言器侧）——只许变严的一致性对账。
# 判据语义不动：正本与约定块一致时行为与旧版逐字节等价；正本缺席 ⇒ 行为
# 等价 + stderr 注明；正本在场且漂移 ⇒ FATAL（fail-closed，不猜绿）。
# --------------------------------------------------------------------------- #

def load_semantic_roster() -> dict | None:
    """名册正本（af 仓 otel/semantic-roster.json）。AF_SEMANTIC_ROSTER 覆盖；
    缺省 <工作区>/af/otel/ 检出位（af 仓检出，合流后即在场）。"""
    p = os.environ.get("AF_SEMANTIC_ROSTER") or os.path.join(
        WS, "af", "otel", "semantic-roster.json")
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("semantic_layers"), dict):
        return None
    return d


def roster_consistency_findings(roster: dict, conv: dict) -> list[str]:
    """正本 vs 约定块（span-conventions.md §6）共享投影的一致性。

    共享投影 = 名册键集 / kind / 父链 / 订单域键 / Resource 订单级键 /
    各层 span 订单级键。约定块的可执行超集（gen_ai.* 全表/allowed_keys/
    production 下界…）不在对账面——那些是判据面，正本不管。
    """
    problems: list[str] = []
    layers = roster.get("semantic_layers") or {}
    conv_layers = conv.get("semantic_layers") or {}
    if set(layers) != set(conv_layers):
        problems.append(
            f"名册键集 {sorted(layers)} ≠ 约定块语义层键集 {sorted(conv_layers)}")
    for name, spec in layers.items():
        cspec = conv_layers.get(name)
        if not isinstance(cspec, dict):
            continue                      # 键集差已报
        if spec.get("kind") != cspec.get("kind"):
            problems.append(f"{name}: kind 正本={spec.get('kind')!r} "
                            f"≠ 约定块={cspec.get('kind')!r}")
        if (spec.get("parent") or None) != (cspec.get("parent") or None):
            problems.append(f"{name}: parent 正本={spec.get('parent')!r} "
                            f"≠ 约定块={cspec.get('parent')!r}")
        miss = [k for k in (spec.get("span_order_keys") or [])
                if k not in (cspec.get("required_keys") or [])]
        if miss:
            problems.append(f"{name}: span 订单级键 {miss} 不在约定块 required_keys")
    prod = conv.get("production") or {}
    if set(roster.get("order_domain_keys") or []) != set(prod.get("order_keys") or []):
        problems.append(
            f"order_domain_keys {roster.get('order_domain_keys')} ≠ "
            f"production.order_keys {prod.get('order_keys')}")
    res_spec = conv.get("resource") or {}
    if set(roster.get("resource_order_keys") or []) != set(
            res_spec.get("af_required_order_keys") or []):
        problems.append(
            f"resource_order_keys {roster.get('resource_order_keys')} ≠ "
            f"resource.af_required_order_keys {res_spec.get('af_required_order_keys')}")
    return problems


# --------------------------------------------------------------------------- #
# OTLP/JSON 载荷解析
# --------------------------------------------------------------------------- #
def _decode_value(v) -> object:
    """OTLP/JSON AnyValue → python 值。"""
    if not isinstance(v, dict):
        return v
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        try:
            return int(v["intValue"])
        except (TypeError, ValueError):
            return v["intValue"]
    if "doubleValue" in v:
        return v["doubleValue"]
    if "boolValue" in v:
        return v["boolValue"]
    if "arrayValue" in v:
        return [_decode_value(x) for x in (v["arrayValue"] or {}).get("values", [])]
    if "kvlistValue" in v:
        return _attrs_to_dict((v["kvlistValue"] or {}).get("values", []))
    return v


def _attrs_to_dict(attrs) -> dict:
    out = {}
    for a in attrs or []:
        if isinstance(a, dict) and "key" in a:
            out[a["key"]] = _decode_value(a.get("value"))
    return out


def load_payloads(path: str) -> list:
    """读一个载荷文件 → 载荷列表（接受 resourceSpans 形状或数组）。"""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict) and "resourceSpans" in doc:
        return [doc]
    raise ValueError(f"{path}：既非 resourceSpans 形状也非数组")


def flatten(payloads: list) -> list:
    """载荷列表 → 扁平的 span 记录列表（含 resource 属性与 scope 名）。"""
    out = []
    for p in payloads:
        for rs in (p or {}).get("resourceSpans", []) or []:
            res_attrs = _attrs_to_dict((rs.get("resource") or {}).get("attributes"))
            for ss in rs.get("scopeSpans", []) or []:
                scope = (ss.get("scope") or {}).get("name")
                for sp in ss.get("spans", []) or []:
                    out.append({
                        "resource": res_attrs,
                        "scope": scope,
                        "name": sp.get("name"),
                        "kind": sp.get("kind"),
                        "trace_id": sp.get("traceId"),
                        "span_id": sp.get("spanId"),
                        "parent_span_id": sp.get("parentSpanId"),
                        "attrs": _attrs_to_dict(sp.get("attributes")),
                        "start": sp.get("startTimeUnixNano"),
                        "end": sp.get("endTimeUnixNano"),
                    })
    return out


def _sid(rec) -> str:
    return f"{rec.get('name')}[{str(rec.get('span_id'))[:8]}]"


# --------------------------------------------------------------------------- #
# 断言集（每条返回失败说明列表；空列表 = PASS）
# --------------------------------------------------------------------------- #
def _sha(seed: str, n: int) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:n]


def _recipe(recipe: str, rec: dict, res: dict) -> str | None:
    """按约定块里的配方名重算 ID；种子缺失 → None（不可判定，不算失败）。"""
    res = res or {}
    at = rec.get("attrs") or {}
    woid = res.get("af.work_order_id")
    run_id = at.get("af.run_id") or res.get("af.run_id")
    if recipe == "trace-order":
        return _sha("af-trace-v1|" + str(woid), 32) if woid else None
    if recipe == "span-order-l1":
        return _sha("af-span-v1|" + str(woid) + "|invoke_workflow", 16) if woid else None
    if recipe == "span-order-l2":
        return _sha("af-span-v1|" + str(woid) + "|" + str(run_id), 16) if (woid and run_id) else None
    if recipe == "span-order-l3":
        turn = at.get("af.turn")
        return (_sha("af-span-v1|" + str(run_id) + "|chat|" + str(turn), 16)
                if (run_id and turn is not None) else None)
    if recipe == "span-order-l4":
        seq = at.get("af.seq")
        return (_sha("af-span-v1|" + str(run_id) + "|tool|" + str(seq), 16)
                if (run_id and seq is not None) else None)
    if recipe == "trace-factory-sidecar":
        ts = at.get("af.sidecar.cycle_ts_ms")
        return _sha("af-factory-v1|sidecar|" + str(ts), 32) if ts is not None else None
    if recipe == "span-factory-sidecar":
        ts = at.get("af.sidecar.cycle_ts_ms")
        return _sha("af-span-v1|sidecar-round|" + str(ts), 16) if ts is not None else None
    if recipe == "trace-order-or-factory":
        return _sha("af-trace-v1|" + str(woid), 32) if woid else None
    return None


def _key_allowed(key: str, allowed: list) -> bool:
    for pat in allowed or []:
        if pat.endswith("*"):
            if key.startswith(pat[:-1]):
                return True
        elif key == pat:
            return True
    return False


def _family_of(name: str, conv: dict):
    """span 名 → (family, spec)。family ∈ {semantic, factory}。"""
    if name in (conv.get("semantic_layers") or {}):
        return "semantic", conv["semantic_layers"][name]
    if name in (conv.get("factory_spans") or {}):
        return "factory", conv["factory_spans"][name]
    return None, None


def run_assertions(spans: list, conv: dict) -> dict:
    """逐断言检查 → {assertion_id: (name, [failures...])}。"""
    semantic = conv.get("semantic_layers") or {}
    factory = conv.get("factory_spans") or {}
    kind_enum = conv.get("kind_enum") or {}
    kind_num = {v: k for k, v in kind_enum.items()}
    res_spec = conv.get("resource") or {}
    forb = conv.get("forbidden_keys") or []
    l1_only = conv.get("l1_only_keys") or []
    units = conv.get("units") or []
    stages = conv.get("stages") or []
    unit_stage_map = conv.get("unit_stage_map") or {}

    F: dict = {}

    # 判定记录数（真空绿防线，2026-11-02 RT 修复批）：每条断言记「它在几条记录上求值」。
    # 0 条 = 该断言在其管辖总体上从未被检验（空集求值）——此前照样报 PASS（真空绿）：
    # sidecar 载荷只含 1 个 factory span 时，R4/A5/S1~S7 在 0 条记录上求值却计入 PASS=26。
    # 各断言的总体口径见各处 add() 的实参（语义层总体 / 名册内总体 / 带键总体 …）。
    sem_recs = [r for r in spans if _family_of(r.get("name"), conv)[0] == "semantic"]
    fac_recs = [r for r in spans if _family_of(r.get("name"), conv)[0] == "factory"]
    known_recs = sem_recs + fac_recs
    non_l1 = [r for r in spans if r.get("name") != "invoke_workflow"]
    with_layer = [r for r in spans if "af.span.layer" in (r.get("attrs") or {})]
    with_unit_stage = [r for r in spans
                       if any(k in (r.get("attrs") or {})
                              for k in ("af.unit", "af.order.stage"))]

    def add(aid: str, title: str, fails: list, n_eval: int = 0) -> None:
        F[aid] = (title, fails, n_eval)

    # R0 载荷非空（G8 F-1 修复：空载荷曾使全部逐 span 断言真空绿）
    f = []
    if not spans:
        f.append("载荷为空：0 条 span 记录——逐 span 断言会全部真空绿（G8 F-1 修复，空载荷必须红）")
    add("R0", "载荷非空（真空绿防线）", f, len(spans))

    # R1 service.name / service.version 在位
    f = []
    for rec in spans:
        res = rec.get("resource") or {}
        for k in res_spec.get("required_keys", []):
            v = res.get(k)
            if v is None or (isinstance(v, str) and not v.strip()):
                f.append(f"{_sid(rec)}: resource 缺 {k}")
    add("R1", "Resource service.name/service.version 在位", f, len(spans))

    # R2 resource 的 af.* 键 ⊆ 九键正字法
    f = []
    afset = set(res_spec.get("af_keyset") or [])
    for rec in spans:
        for k in rec.get("resource") or {}:
            if k.startswith("af.") and k not in afset:
                f.append(f"{_sid(rec)}: resource 出现非正字法键 {k}")
    add("R2", "Resource af.* 键 ⊆ otlp-model §2 九键正字法", f, len(spans))

    # R3 af.arm 本批永远省略
    f = []
    for rec in spans:
        for where, keys in (("resource", rec.get("resource") or {}),
                            ("span", rec.get("attrs") or {})):
            for k in res_spec.get("forbidden_af_keys", []):
                if k in keys:
                    f.append(f"{_sid(rec)}: {where} 出现禁用键 {k}")
    add("R3", "af.arm 本批永远省略（otlp-model §2 注1）", f, len(spans))

    # R4 Resource 身份键在位（otlp-model §2「必有」列；红队 I4 修复）
    # 此前九键「必有」契约零强制：R2 只封上界（⊆九键），剥光 Resource af.* 键后
    # I4 派生重算因种子缺失返回 None 静默跳过 → 订单树照样全绿。此处按下界强制：
    #   · 订单级键恒有（§2:169）：af.order_id / af.work_order_id / af.line
    #     —— Resource 挂有语义层 span 即查；
    #   · run 级键（§2:175/178/179「run 级必有」）：af.run_id / af.profile / af.model
    #     —— 该 Resource 挂有 run 进程投影（L2/L3/L4）即查；纯 L1 离线投影只查订单级；
    #   · af.strategy_id / af.dsl_digest 的必有性以 records/plan 侧为条件（§2:180/:181），
    #     span 面不可判定，不在离线断言面（同 §7 U-3 口径）；af.arm 已由 R3 封。
    # 种子键 af.work_order_id 缺失由此变红；I4 对种子缺失仍跳过（不可判定≠派生失败），
    # 但跳过不再无声——缺失本身已被本条接住。
    f = []
    af_order_req = res_spec.get("af_required_order_keys") \
        or ["af.order_id", "af.work_order_id", "af.line"]      # 兜底=缺块时关门不真空绿
    af_run_req = res_spec.get("af_required_run_keys") \
        or ["af.run_id", "af.profile", "af.model"]
    run_level_names = {"invoke_agent", "chat", "execute_tool"}
    for rec in spans:
        fam, _spec = _family_of(rec.get("name"), conv)
        if fam != "semantic":
            continue                    # 九键契约只钉订单投影（otlp-model §2）；工厂族不查
        res = rec.get("resource") or {}
        need = list(af_order_req) + (list(af_run_req)
                                     if rec.get("name") in run_level_names else [])
        for k in need:
            v = res.get(k)
            if v is None or (isinstance(v, str) and not v.strip()):
                tier = "run 级必有" if k in af_run_req else "订单级恒有"
                f.append(f"{_sid(rec)}: resource 缺身份键 {k}（{tier}，otlp-model §2）")
    add("R4", "Resource 身份键在位（订单级恒有 + run 级投影必有，otlp-model §2）", f, len(sem_recs))

    # I1 trace_id 形状
    f = []
    for rec in spans:
        t = rec.get("trace_id")
        if not isinstance(t, str) or not HEX32.match(t) or t == "0" * 32:
            f.append(f"{_sid(rec)}: traceId 非 32 位小写十六进制或全零：{t!r}")
    add("I1", "trace_id 合法（32 位小写 hex、非全零）", f, len(spans))

    # I2 span_id 形状
    f = []
    for rec in spans:
        s = rec.get("span_id")
        if not isinstance(s, str) or not HEX16.match(s) or s == ZERO_SPAN_ID:
            f.append(f"{_sid(rec)}: spanId 非 16 位小写十六进制或全零：{s!r}")
    add("I2", "span_id 合法（16 位小写 hex、非全零）", f, len(spans))

    # I3 parent_span_id 形状（根=全零）
    f = []
    for rec in spans:
        p = rec.get("parent_span_id")
        if p in (None, "", ZERO_SPAN_ID):
            continue
        if not isinstance(p, str) or not HEX16.match(p):
            f.append(f"{_sid(rec)}: parentSpanId 非 16 位小写十六进制：{p!r}")
    add("I3", "parent_span_id 合法（全零=根，或 16 位小写 hex）", f, len(spans))

    # I4 派生 ID 重算（otlp-model §1.0）
    f = []
    for rec in spans:
        fam, spec = _family_of(rec.get("name"), conv)
        if not spec:
            continue
        recipe = spec.get("id_recipe") or {}
        want_trace = _recipe(recipe.get("trace"), rec, rec.get("resource"))
        want_span = _recipe(recipe.get("span"), rec, rec.get("resource"))
        if want_trace and rec.get("trace_id") != want_trace:
            f.append(f"{_sid(rec)}: traceId 与 §1.0 派生不符（期望 {want_trace}）")
        if want_span and rec.get("span_id") != want_span:
            f.append(f"{_sid(rec)}: spanId 与 §1.0 派生不符（期望 {want_span}）")
    add("I4", "派生 ID 与 otlp-model §1.0 逐位相符", f, len(known_recs))

    # K1 SpanKind 合法
    f = []
    legal_kinds = set(kind_enum.values())
    for rec in spans:
        k = rec.get("kind")
        if k not in legal_kinds:
            f.append(f"{_sid(rec)}: kind 非法：{k!r}（合法 {sorted(legal_kinds)}）")
    add("K1", "SpanKind 合法（OTLP 枚举 0-5）", f, len(spans))

    # K2 SpanKind 符合约定（语义层固定 / execute_tool 按 effect 分派）
    f = []
    for rec in spans:
        fam, spec = _family_of(rec.get("name"), conv)
        if not spec:
            continue
        want = spec.get("kind")
        if want == "BY_EFFECT":
            eff = (rec.get("attrs") or {}).get("af.tool.effect")
            mapping = spec.get("effect_kind") or {}
            if eff not in mapping:
                f.append(f"{_sid(rec)}: af.tool.effect={eff!r} 不在分派词表 {sorted(mapping)}")
            else:
                want_num = kind_enum.get(mapping[eff])
                if rec.get("kind") != want_num:
                    f.append(f"{_sid(rec)}: effect={eff} 应为 {mapping[eff]}({want_num})，实为 {rec.get('kind')}")
        else:
            want_num = kind_enum.get(want)
            if want_num is not None and rec.get("kind") != want_num:
                f.append(f"{_sid(rec)}: kind 应为 {want}({want_num})，实为 {rec.get('kind')}")
    add("K2", "SpanKind 符合约定（语义层固定 / L4 按 effect 分派）", f, len(known_recs))

    # N1 span 名在名册内
    f = []
    for rec in spans:
        if rec.get("name") not in semantic and rec.get("name") not in factory:
            f.append(f"{_sid(rec)}: span 名不在名册：{rec.get('name')!r}")
    add("N1", "span 命名符合约定（名册内）", f, len(spans))

    # N2 af.span.layer 与 span 名一致
    f = []
    for rec in spans:
        layer = (rec.get("attrs") or {}).get("af.span.layer")
        if layer is None:
            continue
        if layer != rec.get("name"):
            f.append(f"{_sid(rec)}: af.span.layer={layer!r} 与 span 名 {rec.get('name')!r} 不一致")
    add("N2", "af.span.layer 与 span 名一致", f, len(with_layer))

    # A1 必备键在位（组内任一成员即满足该组；组语义见约定块 required_key_groups）
    f = []
    for rec in spans:
        fam, spec = _family_of(rec.get("name"), conv)
        if not spec:
            continue
        at = rec.get("attrs") or {}
        groups = spec.get("required_key_groups") or {}
        for k in spec.get("required_keys", []):
            if k in at:
                continue
            alts = groups.get(k) or []
            if any(a in at for a in alts):
                continue          # 组内另一成员在场 → 该组已满足
            f.append(f"{_sid(rec)}: 缺必备键 {k}"
                     + (f"（组内可选：{alts}）" if alts else ""))
    add("A1", "必备属性键在位（按约定块 required_keys）", f, len(known_recs))

    # A2 无越界键
    f = []
    for rec in spans:
        fam, spec = _family_of(rec.get("name"), conv)
        if not spec:
            continue
        allowed = list(spec.get("allowed_keys") or [])
        for k in (rec.get("attrs") or {}):
            if not _key_allowed(k, allowed):
                f.append(f"{_sid(rec)}: 出现越界键 {k}")
    add("A2", "无越界属性键（按约定块 allowed_keys）", f, len(known_recs))

    # A3 禁用键不在位
    f = []
    for rec in spans:
        at = rec.get("attrs") or {}
        for k in forb:
            if k in at:
                f.append(f"{_sid(rec)}: 出现禁用键 {k}")
    add("A3", "禁用键不在位（af.payload / gen_ai.prompt 等）", f, len(spans))

    # A6 互斥键组：同组成员不得同时在场
    # （上游 otlp-model §3.4：gen_ai.usage.cache_read_tokens 与其降级名 af.usage.cache_read_tokens
    #   「两者不得同时出现」；本组把同一约束扩展到 semconv 现役名
    #   gen_ai.usage.cache_read.input_tokens——见约定文档 §3.1 勘误注）
    f = []
    for rec in spans:
        fam, spec = _family_of(rec.get("name"), conv)
        if not spec:
            continue
        at = rec.get("attrs") or {}
        for canon, alts in (spec.get("required_key_groups") or {}).items():
            present = [k for k in [canon] + list(alts) if k in at]
            if len(present) > 1:
                f.append(f"{_sid(rec)}: 互斥键组同时在场 {present}（只应出现其一）")
    add("A6", "互斥键组不同时出现（cache 计数键择一）", f, len(known_recs))

    # A4 L1 专属键只在 L1
    f = []
    for rec in spans:
        if rec.get("name") == "invoke_workflow":
            continue
        at = rec.get("attrs") or {}
        for k in l1_only:
            if k in at:
                f.append(f"{_sid(rec)}: L1 专属键 {k} 出现在非 L1 span 上")
    add("A4", "L1 专属键（af.unit / af.order.stage*）只在 invoke_workflow 上", f, len(non_l1))

    # A5 unit/stage 取值合法
    f = []
    for rec in spans:
        at = rec.get("attrs") or {}
        if "af.unit" in at and at["af.unit"] not in units:
            f.append(f"{_sid(rec)}: af.unit={at['af.unit']!r} 不在词表 {units}")
        if "af.order.stage" in at and at["af.order.stage"] not in stages:
            f.append(f"{_sid(rec)}: af.order.stage={at['af.order.stage']!r} 不在词表 {stages}")
    add("A5", "af.unit / af.order.stage 取值在词表内", f, len(with_unit_stage))

    # ---- 树形状断言（仅语义层 span 参与；工厂族不参与四层树断言） ----
    by_trace: dict = {}
    for rec in spans:
        if rec.get("name") not in semantic:
            continue
        by_trace.setdefault(rec.get("trace_id"), []).append(rec)

    f = []
    for tid, group in by_trace.items():
        roots = [r for r in group if r.get("parent_span_id") in (None, "", ZERO_SPAN_ID)]
        if len(roots) != 1:
            f.append(f"trace {str(tid)[:8]}: 根 span 数={len(roots)}（应恰为 1）")
    add("S1", "每 trace 恰一个根 span", f, len(sem_recs))

    f = []
    for tid, group in by_trace.items():
        ids = {r.get("span_id") for r in group}
        for r in group:
            p = r.get("parent_span_id")
            if p in (None, "", ZERO_SPAN_ID):
                continue
            if p not in ids:
                f.append(f"{_sid(r)}: parent {str(p)[:8]} 不在本 trace 内（断链）")
    add("S2", "非根 span 的 parent 必在本 trace 内可解析", f, len(sem_recs))

    f = []
    for tid, group in by_trace.items():
        byid = {r.get("span_id"): r for r in group}
        for r in group:
            seen, cur = set(), r
            while cur is not None:
                sid = cur.get("span_id")
                if sid in seen:
                    f.append(f"{_sid(r)}: 父链成环")
                    break
                seen.add(sid)
                p = cur.get("parent_span_id")
                if p in (None, "", ZERO_SPAN_ID):
                    break
                cur = byid.get(p)
    add("S3", "父链无环", f, len(sem_recs))

    f = []
    for tid, group in by_trace.items():
        byid = {r.get("span_id"): r for r in group}
        for r in group:
            name = r.get("name")
            p = r.get("parent_span_id")
            pname = byid.get(p).get("name") if p in byid else None
            if name == "invoke_workflow":
                if p not in (None, "", ZERO_SPAN_ID):
                    f.append(f"{_sid(r)}: L1 不得有父")
            elif name == "invoke_agent":
                if pname != "invoke_workflow":
                    f.append(f"{_sid(r)}: L2 的父必须是 L1，实为 {pname!r}")
            elif name in ("chat", "execute_tool"):
                if pname != "invoke_agent":
                    f.append(f"{_sid(r)}: {name} 的父必须是 L2（与 chat 同父兄弟），实为 {pname!r}")
                if name == "execute_tool" and pname == "chat":
                    f.append(f"{_sid(r)}: L4 不得挂在 L3 之下")
    add("S4", "层序正确（L2→L1、L3/L4→L2 且互为兄弟）", f, len(sem_recs))

    f = []
    for tid, group in by_trace.items():
        byid = {r.get("span_id"): r for r in group}
        for r in group:
            if r.get("name") not in ("chat", "execute_tool"):
                continue
            p = r.get("parent_span_id")
            anc = byid.get(p)
            if anc is None:
                continue
            a_run = (anc.get("attrs") or {}).get("af.run_id")
            c_run = (r.get("attrs") or {}).get("af.run_id")
            if a_run != c_run:
                f.append(f"{_sid(r)}: af.run_id={c_run!r} ≠ 其 L2 祖先 {a_run!r}（脱链）")
    add("S5", "L3/L4 的 af.run_id 与 L2 祖先一致", f, len(sem_recs))

    f = []
    for tid, group in by_trace.items():
        for r in group:
            if r.get("name") != "invoke_agent":
                continue
            if "af.terminal.kind" not in (r.get("attrs") or {}):
                f.append(f"{_sid(r)}: 树内 L2 必须带 af.terminal.kind（旁路 run 不入树）")
    add("S6", "树内 L2 必带 af.terminal.kind", f, len(sem_recs))

    f = []
    for tid, group in by_trace.items():
        l1 = next((r for r in group if r.get("name") == "invoke_workflow"), None)
        if l1 is None:
            continue
        at = l1.get("attrs") or {}
        unit, stage = at.get("af.unit"), at.get("af.order.stage")
        if unit is None or stage is None:
            continue
        need = (unit_stage_map.get(unit) or {}).get(stage)
        if need is None:
            continue
        present = {r.get("name") for r in group}
        for nm in need:
            if nm not in present:
                f.append(f"trace {str(tid)[:8]}: unit={unit}/stage={stage} 应含 {nm}，实缺")
    add("S7", "unit×stage 映射要求的语义层在位", f, len(sem_recs))

    return F


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def report(title: str, F: dict) -> tuple:
    """逐断言清单 → (PASS 数, FAIL 数, VACUOUS 数)。

    VACUOUS = 该断言的判定记录数=0（在空集上求值）——此前这类断言照样计入 PASS，
    是「真空绿」的来源（sidecar 载荷只含 1 个 factory span 时 PASS=26，其中 9 条
    断言实际未在任何记录上求值）。真空绿不计 PASS，且由 verdict_exit() 判 rc=2（不标绿）。
    """
    n_fail = n_vac = 0
    print(f"──── {title} ────")
    for aid in sorted(F):
        name, fails, n_eval = F[aid]
        if fails:
            n_fail += 1
            print(f"  [FAIL] {aid} {name}")
            for x in fails[:8]:
                print(f"         - {x}")
            if len(fails) > 8:
                print(f"         …（另 {len(fails) - 8} 条）")
        elif n_eval == 0:
            n_vac += 1
            print(f"  [VACUOUS] {aid} {name} —— 判定记录数=0（未覆盖，不计 PASS）")
        else:
            print(f"  [PASS] {aid} {name}（判定 {n_eval} 条）")
    print(f"  小计：PASS={len(F) - n_fail - n_vac} FAIL={n_fail} VACUOUS={n_vac}")
    return len(F) - n_fail - n_vac, n_fail, n_vac


def verdict_exit(n_fail: int, n_vac: int) -> int:
    """门语义：有红 → 1（红）；无红但有真空绿断言 → 2（覆盖不全，不标绿）；全过 → 0。"""
    if n_fail:
        return 1
    if n_vac:
        return 2
    return 0


def coverage_report(spans: list, conv: dict) -> dict:
    """名册覆盖块：本次断言实际覆盖了名册的哪几项（缺项显式点名）。

    「名册有项」≠「生产有 span」：名册 9 项（语义层 4 + 工厂族 5），而 sidecar 载荷
    只含 1 项（factory.sidecar_round）——此前该事实不出现在任何输出里，门只看见
    PASS=26。此块把覆盖面对摊开：覆盖不全不是绿灯（语义层腿的运行时可断言性由
    --production 模式在真库上逐名册项回查）。
    """
    sem = list((conv.get("semantic_layers") or {}).keys())
    fac = list((conv.get("factory_spans") or {}).keys())
    seen: dict = {}
    for r in spans:
        nm = r.get("name")
        if nm in sem or nm in fac:
            seen[nm] = seen.get(nm, 0) + 1
    sem_cov = [n for n in sem if n in seen]
    fac_cov = [n for n in fac if n in seen]
    sem_missing = [n for n in sem if n not in seen]
    fac_missing = [n for n in fac if n not in seen]
    print("──── 名册覆盖（本次断言实际覆盖面）────")
    print(f"  语义层名册：{len(sem_cov)}/{len(sem)} 项在载荷中"
          + (f"；缺：{', '.join(sem_missing)}" if sem_missing else ""))
    print(f"  工厂族名册：{len(fac_cov)}/{len(fac)} 项在载荷中"
          + (f"；缺：{', '.join(fac_missing)}" if fac_missing else ""))
    print(f"  载荷记录数：{len(spans)}（语义层 {sum(seen.get(n, 0) for n in sem)} 条 / "
          f"工厂族 {sum(seen.get(n, 0) for n in fac)} 条）")
    if sem_missing or fac_missing:
        print("  ⚠ 覆盖不全：名册有项而本次载荷无记录——该腿未覆盖，不得当「全绿」引用"
              "（语义层腿的运行时可断言性见 --production 模式：真库逐名册项回查）")
    return {"sem_covered": sem_cov, "fac_covered": fac_cov,
            "sem_missing": sem_missing, "fac_missing": fac_missing,
            "n_spans": len(spans)}


# --------------------------------------------------------------------------- #
# --sidecar：用现役快照经真实发射器复原 factory 族 span（本地截获，不发网）
# --------------------------------------------------------------------------- #
def _sidecar_stale_cap(cap_override: int | None = None) -> tuple:
    """返回 (鲜度帽秒数, 采信周期秒数)。

    帽由**断言侧常量**定阈：cap = max(4 × SIDECAR_TRUSTED_INTERVAL_S, 120)。
    绝不采信快照自声明的 interval_s——被测件自定阈 = 陈旧件可自行放宽帽到任意大
    （2026-11-02 RT 修复前的洞：interval_s=864000 → 帽 3456000s → 24h 陈旧算现役）。
    cap_override 仅来自 CLI 显式旗标 --stale-cap-s（取证回放陈旧快照用），
    环境变量一律不看：all-gates 门路径的子进程（timeout bash -c "$cmd"）继承
    调用者环境，环境变量放宽帽 = 从门路径旁路整条帽（曾有 OTEL_SIDECAR_STALE_CAP_S）。
    """
    interval = SIDECAR_TRUSTED_INTERVAL_S
    cap = max(4 * interval, 120)
    if cap_override is not None:
        try:
            cap = max(1, int(cap_override))
        except (TypeError, ValueError):
            pass
    return cap, interval


def _sidecar_stale_reason(snap: dict, cap_override: int | None = None) -> str | None:
    """快照冻结/时钟倒挂 → 原因串（关门，exit 2=红，all-gates rc=2 即红）；现役 → None。

    新鲜度帽 = 4 个采集周期、下界 120s：边车缺省 30s/周期，最坏正常周期
    （anolis ssh 45s 超时 + 14 发射点 × _post 2s 超时 ≈ 90s）仍 < 帽——慢周期不误伤；
    4 个周期未刷 = 发射面确定停更（边车死或曾 STOP），复原只是旧数据的空转回放，
    不得当「现役绿」。
    帽的阈值由断言侧常量定阈（_sidecar_stale_cap）：**不读快照自声明的 interval_s**
    （被测件自定阈 → 陈旧快照自称周期 10 天即可把帽放到任意大）；
    取证回放陈旧快照须显式加 CLI 旗标 --stale-cap-s（环境变量不再认，见上）。
    """
    ts = snap.get("ts")
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return f"快照缺合法 ts（{ts!r}）：无法判定新鲜度，不掺假绿"
    cap, interval = _sidecar_stale_cap(cap_override)
    declared = snap.get("interval_s")
    age_ms = time.time() * 1000 - ts
    if age_ms < -60_000:
        return f"快照 ts 在未来（age={age_ms / 1000:.0f}s）：时钟倒挂或伪造，非现役数据"
    if age_ms > cap * 1000:
        return (f"快照冻结：ts={ts}（age={age_ms / 1000:.0f}s > 鲜度帽 {cap}s"
                f"={interval}s 周期×4，断言侧定阈；快照自声明 interval_s={declared!r} 不参与定阈）"
                f"——发射面已停刷（边车死或 STOP 期），复原的是陈旧快照非现役状态")
    return None


def _sidecar_emit_dead_reason(snap: dict) -> str | None:
    """快照内记录的**当轮**发射结果 → 发射面已死 → 原因串（关门）；在流 → None。

    判据源 = 快照的 emit 块（tools/otel/emit-sidecar.py:296-305 落盘，值来自
    emit-sidecar.py:243-245 的 emit_round 返回）。该块两类字段语义不同，**只取当轮**：

      · span_sent / metrics_sent —— **当轮**结果：span_sent = 本轮汇总 span 的
        POST 是否成功；metrics_sent = 本轮成功落库的 gauge 条数。
      · spans / metrics / errors / skipped_stop —— **进程累计**计数（otel_emit.py:32
        的 _stats，进程内只增不清零）。**绝不可当判据**：在役边车 errors 已累计
        65828（= 2026-10-31→11-01 那 4702 轮停发的历史欠账，errors 14/轮）而当下
        发射正常——拿累计量判活会把「早已恢复」判成「发射面已死」。

    判据（零成功 = 发射面已死）：本轮 **span 未送达** 且 **一个 gauge 也没送达**
    ——发射面本轮完全空转，collector 不可达/被熔断/端点配置错皆落此形。
    单项失败不算死面：span 未送达而 gauge 仍在流（单轮 trace 偶发失败，
    2026-10-30 17:47 实录）不误伤；span 送达而 gauge 全灭（本轮指标源全哑，
    如实反映在 metrics/sources 块里）也不算发射面已死。

    为什么必须判：--sidecar 路径把 otel_emit._post 本地截获（fake_post 恒成功），
    复原必然产出 trace 载荷 → 「发射零成功」与「发射成功」在门输入里原本**不可
    表达**（RT-E89 只给「快照冻结」加了新鲜度帽，没给「快照在流但发射全灭」加
    判据）。故门必须自己读快照里的发射回执，且只认当轮。

    缺 emit 块 → 无法判定发射结果 → 不掺假绿（与「缺合法 ts」同处置）。
    """
    emit = snap.get("emit")
    if not isinstance(emit, dict):
        return ("快照缺 emit 块（当轮发射回执不可判）：无法判定发射面死活，"
                "不掺假绿")
    span_sent = emit.get("span_sent")
    metrics_sent = emit.get("metrics_sent")
    try:
        metrics_sent = int(metrics_sent)
    except (TypeError, ValueError):
        return (f"快照 emit.metrics_sent 不可判（{metrics_sent!r}）："
                f"无法判定发射面死活，不掺假绿")
    if not span_sent and metrics_sent <= 0:
        return (f"发射面已死：本轮零成功发射（emit.span_sent={span_sent!r}、"
                f"emit.metrics_sent={metrics_sent}）——快照在流但发射面本轮全灭"
                f"（collector 不可达/端点配置错/熔断），复原只是本地假载荷的空转"
                f"回放，不得当「现役在流」绿")
    return None


def collect_sidecar_payloads(snapshot_path: str,
                             cap_override: int | None = None) -> tuple:
    """返回 (payloads, note)。前置不满足 → (None, 原因)。

    前置五条：快照在位、OTEL-STOP 不在位、快照新鲜（ts 距今 ≤ 4 周期帽，
    见 _sidecar_stale_reason）、**本轮发射面非零成功**（见 _sidecar_emit_dead_reason）、
    复原确有 trace 载荷——门语义携带「现役/在流」，
    陈旧快照不再真空绿（2026-11-02 sidecar 断言新鲜度耦合修复；
    同日 RT 修复：帽的阈值不再由被测快照自声明、不得由环境变量放宽；
    同日 RT 修复：快照在流但发射面全灭亦不得真空绿——读快照自带的当轮发射回执）。
    """
    if not os.path.isfile(snapshot_path):
        return None, f"快照不在位：{snapshot_path}"
    with open(snapshot_path, encoding="utf-8") as fh:
        snap = json.load(fh)
    stop_file = os.path.join(WS, "状态观测", "OTEL-STOP")
    if os.path.exists(stop_file):
        return None, f"熔断文件在位（{stop_file}）：发射面静默，复原无意义"
    stale = _sidecar_stale_reason(snap, cap_override)
    if stale:
        return None, stale
    dead = _sidecar_emit_dead_reason(snap)
    if dead:
        return None, dead

    sys.path.insert(0, HERE)
    import otel_emit  # noqa: PLC0415

    captured: list = []
    orig_post = otel_emit._post

    def fake_post(path, payload, ep, timeout):  # noqa: ANN001
        captured.append((path, payload))
        return None

    otel_emit._post = fake_post
    old_disable = os.environ.pop("AF_OTEL_DISABLE", None)
    os.environ["AF_OTEL_ENDPOINT"] = os.environ.get("AF_OTEL_ENDPOINT") or "http://127.0.0.1:4318"
    try:
        spec = importlib.util.spec_from_file_location(
            "af_emit_sidecar", os.path.join(HERE, "emit-sidecar.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        metrics = snap.get("metrics") or {}
        src_ok = {n: bool((v or {}).get("ok")) for n, v in (snap.get("sources") or {}).items()}
        mod.emit_round(int(snap.get("round") or 0), int(snap.get("ts") or 0), metrics, src_ok)
    finally:
        otel_emit._post = orig_post
        if old_disable is not None:
            os.environ["AF_OTEL_DISABLE"] = old_disable
        else:
            os.environ.pop("AF_OTEL_DISABLE", None)

    traces = [p for path, p in captured if path.endswith("/v1/traces")]
    if not traces:
        return None, "复原未捕获到 trace 载荷（发射面未产出 span）"
    age_s = (time.time() * 1000 - int(snap.get("ts"))) / 1000
    cap, _interval = _sidecar_stale_cap(cap_override)
    fresh_note = ("鲜度在帽内=现役" if cap_override is None
                  else f"取证放宽帽={cap}s（--stale-cap-s）——不承载现役语义")
    return traces, (f"快照 round={snap.get('round')} ts={snap.get('ts')} "
                    f"（age={age_s:.1f}s，{fresh_note}）→ 复原 {len(traces)} 个 trace 载荷")


# --------------------------------------------------------------------------- #
# --production：真库逐名册项回查（RT-E90 机制②下半段「每名册项近窗入库计数下界」
#            + 机制③「断言层增 --production 模式逐名册项回查 CH 计数」）
#
# 缺口由来：名册（span-conventions.md §2.1/§6）9 项，断言层三模式（--selftest 合成
# 样本 / --sidecar 单名复原 / --input 无门内喂入）从未逐项回查过生产面——「名册有项」
# 被冒充为「名册生效性」。本模式把真库（otel.otel_traces）拉进来逐名册项计数：
#   P1 每名册项近窗入库计数下界（required 项=0 即红）——§6 production.required_spans
#   P2 订单级键在位（af.order_id / af.work_order_id 非空行数 ≥1）——「一条订单=一条
#      trace」在真库侧的直接判据（此前真库 0 行 → 全订单腿运行时未成立）
#   P3 语义层 span 的订单级键齐全率（语义层行=0 → N/A，不冒充 PASS；下界由 P1 判）
# 纪律：只 SELECT；凭据只走 ch_client 既有链（零明文）；判据源=§6 production 块（唯一源）。
# --------------------------------------------------------------------------- #
def _ch_client():
    """导入 ch_client.py 本体（凭据链单一真源；只 SELECT，零明文）。"""
    path = os.path.join(HERE, "ch_client.py")
    spec = importlib.util.spec_from_file_location("otel_ch_client", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ch_client spec 构建失败：%s" % path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def production_spec(conv: dict) -> dict:
    """§6 production 块（缺块 → 空字典；调用方按缺项判红，不静默放行）。"""
    return conv.get("production") or {}


def production_sql_by_name(window_min: int, skew_min: int) -> str:
    """逐 SpanName 近窗计数 SQL（双侧窗口 [now-w, now+skew]，与对账门同口径）。

    FINAL：2026-11-05 U-6 去重腿落地，otel_traces 换 ReplacingMergeTree(Timestamp)
    ORDER BY (TraceId, SpanId)——合并前重复行仍可见，读必须带 FINAL 才是去重后口径。"""
    w = (f"Timestamp > now() - INTERVAL {window_min} MINUTE "
         f"AND Timestamp <= now() + INTERVAL {skew_min} MINUTE")
    return (f"SELECT SpanName, count() AS n FROM otel.otel_traces FINAL WHERE {w} "
            f"GROUP BY SpanName")


def production_sql_keys(window_min: int, skew_min: int, semantic_names: list) -> str:
    """订单级键 + 语义层行数 + 订单域总体 SQL（资源属性面 af.order_id / af.work_order_id）。

    order_domain_rows = 订单域总体行数（语义层名册行 ∪ 带任一订单级键的行）——
    「全订单」判据的**分母**：键覆盖判据（P2）必须相对这个总体求值，否则
    「100 万行里 1 行带键」与「全订单都带键」在判据层不可区分。
    FINAL：同 production_sql_by_name——ReplacingMergeTree 读须带去重后口径。
    """
    w = (f"Timestamp > now() - INTERVAL {window_min} MINUTE "
         f"AND Timestamp <= now() + INTERVAL {skew_min} MINUTE")
    sem = ", ".join("'" + n.replace("'", "''") + "'" for n in semantic_names)
    return (
        "SELECT count() AS rows, "
        "countIf(ResourceAttributes['af.order_id'] != '') AS order_keyed, "
        "countIf(ResourceAttributes['af.work_order_id'] != '') AS woid_keyed, "
        f"countIf(SpanName IN ({sem})) AS semantic_rows, "
        f"countIf(SpanName IN ({sem}) AND (ResourceAttributes['af.order_id'] = '' "
        "OR ResourceAttributes['af.work_order_id'] = '')) AS semantic_missing_keys, "
        f"countIf(SpanName IN ({sem}) OR ResourceAttributes['af.order_id'] != '' "
        "OR ResourceAttributes['af.work_order_id'] != '') AS order_domain_rows, "
        f"uniqExactIf(TraceId, SpanName IN ({sem}) "
        "OR ResourceAttributes['af.order_id'] != '' "
        "OR ResourceAttributes['af.work_order_id'] != '') AS order_traces "
        f"FROM otel.otel_traces FINAL WHERE {w}")


def fetch_production_counts(window_min: int, skew_min: int, semantic_names: list) -> dict:
    """真库回查 → 计数字典（CH 不可达 → 抛；调用方 rc=2 不可证不猜绿）。"""
    ch = _ch_client()
    by_name = {r["SpanName"]: int(r["n"])
               for r in ch.query(production_sql_by_name(window_min, skew_min))}
    keys = ch.query(production_sql_keys(window_min, skew_min, semantic_names))[0]
    return {"by_name": by_name,
            "rows": int(keys.get("rows") or 0),
            "order_keyed": int(keys.get("order_keyed") or 0),
            "woid_keyed": int(keys.get("woid_keyed") or 0),
            "semantic_rows": int(keys.get("semantic_rows") or 0),
            "semantic_missing_keys": int(keys.get("semantic_missing_keys") or 0),
            "order_domain_rows": int(keys.get("order_domain_rows") or 0),
            "order_traces": int(keys.get("order_traces") or 0)}


# --------------------------------------------------------------------------- #
# --production：真库**订单域总体**逐行回查（P2~P5 的判据源）
#
# 缺口由来（红队 2026-11-03 批）：P2 原判据是「af.order_id / af.work_order_id
# 非空行 ≥1」——**下界=1** 的测法：真库 100 万行里只有 1 行带键即判 PASS，与
# 「全订单都带键」在判据层不可区分；且全部真库回查只 SELECT 聚合计数（SpanName
# 与两个 ResourceAttributes 键），**从不取回真库 span**（TraceId/SpanId/
# ParentSpanId/SpanAttributes 一列不取）→「一条订单=一条 trace」「全链 trace」
# 「span 层级正确」「派生 ID 一致」在判据层无从求值（只能在合成样本上验）。
#
# 本块把订单域总体逐行取回真库，在**真 span** 上判：
#   P2 键在位：订单域总体**每一行**都带非空 af.order_id/af.work_order_id（覆盖 100%）
#   P3 语义层键齐全率：语义层行 0 → N/A（不冒充 PASS）；否则必须 100% 齐全
#   P4 一条订单=一条 trace：每个 order_id/work_order_id 只落一个 trace；trace 内身份唯一
#   P5 真库订单 trace 结构合规：在真库语义层 span 上复用断言集（层序/父链/单根/派生 ID/键集）
#
# 纪律：只 SELECT；凭据只走 ch_client 既有链（零明文）；判据源=§6 production 块（唯一源）。
# --------------------------------------------------------------------------- #
SPAN_KIND_BY_NAME = {"Unspecified": 0, "Internal": 1, "Server": 2, "Client": 3,
                      "Producer": 4, "Consumer": 5}


def production_sql_order_rows(window_min: int, skew_min: int, semantic_names: list,
                              limit: int) -> str:
    """订单域总体逐行 SQL（真库 span 结构面）。

    订单域总体 = 语义层名册行 ∪ 带任一订单级键的行（与 production_sql_keys 的
    order_domain_rows 同口径）。取回 TraceId/SpanId/ParentSpanId/SpanName/SpanKind/
    ResourceAttributes/SpanAttributes —— 「一条订单=一条 trace」「层序/父链正确」
    「派生 ID 一致」只能在这些列上求值（只 SELECT 聚合计数则无从判）。
    FINAL：同 production_sql_by_name——ReplacingMergeTree 读须带去重后口径
    （P4/P5 在真 span 上判「单根/父链」，重复行会直接伪造多根）。
    """
    w = (f"Timestamp > now() - INTERVAL {window_min} MINUTE "
         f"AND Timestamp <= now() + INTERVAL {skew_min} MINUTE")
    sem = ", ".join("'" + n.replace("'", "''") + "'" for n in semantic_names)
    return (
        "SELECT TraceId AS trace_id, SpanId AS span_id, "
        "ParentSpanId AS parent_span_id, SpanName AS span_name, "
        "SpanKind AS span_kind, ResourceAttributes AS resource_attributes, "
        "SpanAttributes AS span_attributes "
        f"FROM otel.otel_traces FINAL WHERE {w} AND (SpanName IN ({sem}) "
        "OR ResourceAttributes['af.order_id'] != '' "
        "OR ResourceAttributes['af.work_order_id'] != '') "
        f"ORDER BY Timestamp DESC LIMIT {int(limit)}")


def fetch_order_rows(window_min: int, skew_min: int, semantic_names: list,
                     limit: int) -> list:
    """真库订单域逐行 → CH 原始行列表（CH 不可达 → 抛；调用方 rc=2 不可证不猜绿）。"""
    ch = _ch_client()
    return ch.query(production_sql_order_rows(window_min, skew_min,
                                              semantic_names, limit))


def ch_rows_to_spans(rows: list) -> list:
    """CH 行 → 断言器 span 记录（与 flatten() 同形：resource/attrs/trace_id/span_id/parent）。"""
    out = []
    for r in rows or []:
        res = dict(r.get("resource_attributes") or {})
        at = dict(r.get("span_attributes") or {})
        kind = r.get("span_kind")
        if isinstance(kind, str) and kind.startswith("SPAN_KIND_"):
            kind = kind[len("SPAN_KIND_"):]
        out.append({"resource": res, "scope": None, "name": r.get("span_name"),
                    "kind": SPAN_KIND_BY_NAME.get(kind, kind),
                    "trace_id": r.get("trace_id"), "span_id": r.get("span_id"),
                    "parent_span_id": r.get("parent_span_id"),
                    "attrs": at, "start": None, "end": None})
    return out


def _order_key(span: dict, key: str) -> str:
    """订单级键有效值：resource 面优先，span 属性面兜底；非空字符串才算在位。"""
    for src in (span.get("resource") or {}, span.get("attrs") or {}):
        v = src.get(key)
        if isinstance(v, str) and v.strip():
            return v
        if v is not None and not isinstance(v, str):
            return str(v)
    return ""


def judge_production(counts: dict, conv: dict, window_min: int) -> list:
    """纯函数：吃真库计数字典 → P1 名册计数下界判定清单（live 与 selftest 夹具同一条路径）。

    订单域总体判据（P2~P5）在 judge_order_spans()：它们需要真库 span 记录
    （TraceId/SpanId/ParentSpanId/属性面），只吃计数字典无从判「全订单」。

    返回 [{id, name, status, detail}]；status ∈ {PASS, FAIL, NA}。
    """
    spec = production_spec(conv)
    req = spec.get("required_spans") or {}
    opt = list(spec.get("optional_spans") or [])
    by_name = counts.get("by_name") or {}
    out = []

    # P1 每名册项近窗入库计数下界（required 项=0 即红）
    miss = []
    for name in sorted(req):
        n = int(by_name.get(name, 0))
        need = int(req[name])
        if n < need:
            miss.append(f"{name}: 近窗({window_min}min)入库 {n} < 下界 {need}")
    if not req:
        out.append({"id": "P1", "name": "每名册项近窗入库计数下界（§6 production.required_spans）",
                    "status": "FAIL",
                    "detail": "§6 production.required_spans 缺失或为空——判据无源，"
                              "不可证不猜绿（不得因「无 required 项」而判绿）"})
    else:
        out.append({"id": "P1", "name": "每名册项近窗入库计数下界（§6 production.required_spans）",
                    "status": "FAIL" if miss else "PASS",
                    "detail": ("；".join(miss) if miss else
                               f"{len(req)} 个 required 名册项全部在流"
                               + (f"；可选名册项 {', '.join(opt)} 近窗计数 "
                                  + ", ".join(f"{o}={by_name.get(o, 0)}" for o in opt)
                                  if opt else ""))})

    # P2/P3/P4/P5（订单域总体判据）见 judge_order_spans()——判据需要真库 span
    # 记录（TraceId/SpanId/ParentSpanId/属性面），只吃计数字典无从判「全订单」。
    return out


def judge_order_spans(spans: list, counts: dict, conv: dict, window_min: int) -> list:
    """纯函数：吃真库**订单域总体**的 span 记录 + 计数字典 → P2~P5 判定清单。

    判据（2026-11-03 RT 修复批；把「全订单」从下界=1 的测法改成总体普适判据）：
      · 订单域总体 = 语义层名册行 ∪ 带任一订单级键的行（counts['order_domain_rows'] 为
        真库口径的分母；本函数吃取回的逐行 span 记录）
      · P2 键在位：订单域总体**每一行**都要带非空 af.order_id + af.work_order_id
        （「100 万行里 1 行带键」不再算 PASS——覆盖率必须 100%）
      · P3 语义层键齐全率：语义层行 0 → N/A（不冒充 PASS）；否则必须 100% 齐全
      · P4 一条订单=一条 trace：每个 order_id/work_order_id 只允许落在一个 trace；
        同一 trace 内 order_id / work_order_id 必须唯一
      · P5 真库订单 trace 结构合规：在真库语义层 span 上复用断言集（单根/父链/层序/
        阶段下界/派生 ID/键集）——「全链 trace」「span 层级正确」首次在真 span 上求值

    返回 [{id, name, status, detail}]；status ∈ {PASS, FAIL, NA}。
    """
    semantic = conv.get("semantic_layers") or {}
    total_rows = int(counts.get("rows") or 0)
    dom_total = int(counts.get("order_domain_rows") or 0)
    spans = list(spans or [])
    fetched = len(spans)
    # 取回上限截断 → 判据未覆盖全体（不可全证，不猜绿）
    truncated = dom_total > fetched
    out = []

    # ---- P2 订单级键在位（订单域总体 100% 覆盖；不再用「非空行 ≥1」下界）----
    miss = [s for s in spans if not _order_key(s, "af.order_id")
            or not _order_key(s, "af.work_order_id")]
    if fetched == 0:
        out.append({"id": "P2", "name": "订单级键在位（订单域总体 100% 覆盖）",
                    "status": "FAIL",
                    "detail": f"订单域总体 0 行（近窗 {window_min}min 真库无任何语义层行/"
                              f"带订单级键行；真库总行数 {total_rows}）——"
                              f"「全订单」腿在运行时未成立"})
    else:
        fails = []
        if miss:
            fails.append(f"{len(miss)}/{fetched} 行未同时携带 af.order_id/af.work_order_id"
                         f"（例：{', '.join(_sid(s) for s in miss[:3])}）")
        if truncated:
            fails.append(f"订单域总体 {dom_total} 行仅取回 {fetched} 行（上限截断）"
                         f"——覆盖判据未覆盖全体，不猜绿")
        cov = 100.0 * (fetched - len(miss)) / fetched
        out.append({"id": "P2", "name": "订单级键在位（订单域总体 100% 覆盖）",
                    "status": "FAIL" if fails else "PASS",
                    "detail": (f"订单域行 {fetched}（真库总行数 {total_rows}），"
                               f"af.order_id+af.work_order_id 齐全 {fetched - len(miss)}/{fetched}"
                               f"（{cov:.1f}%）"
                               + ("；" + "；".join(fails) if fails else ""))})

    # ---- P3 语义层 span 的订单级键齐全率（语义层行=0 → N/A，不冒充 PASS）----
    sem_rows = [s for s in spans if s.get("name") in semantic]
    sem_miss = [s for s in sem_rows if not _order_key(s, "af.order_id")
                or not _order_key(s, "af.work_order_id")]
    if not sem_rows:
        out.append({"id": "P3", "name": "语义层 span 订单级键齐全率",
                    "status": "NA",
                    "detail": "语义层 span 行数=0 —— 订单级键齐全率不适用；"
                              "覆盖下界见 P1（required 名册项 0 入库即红）"})
    else:
        fails = []
        if sem_miss:
            fails.append(f"{len(sem_miss)}/{len(sem_rows)} 语义层行缺订单级键"
                         f"（例：{', '.join(_sid(s) for s in sem_miss[:3])}）")
        if truncated:
            fails.append(f"订单域总体 {dom_total} 行仅取回 {fetched} 行（上限截断）"
                         f"——未覆盖全体")
        out.append({"id": "P3", "name": "语义层 span 订单级键齐全率",
                    "status": "FAIL" if fails else "PASS",
                    "detail": (f"语义层行 {len(sem_rows)}，缺订单级键 {len(sem_miss)}"
                               + ("；" + "；".join(fails) if fails else ""))})

    # ---- P4 一条订单=一条 trace（订单标识 ↔ trace 一一对应；trace 内身份唯一）----
    o2t: dict = {}
    w2t: dict = {}
    t2o: dict = {}
    t2w: dict = {}
    for s in spans:
        tid = s.get("trace_id") or ""
        oid = _order_key(s, "af.order_id")
        wid = _order_key(s, "af.work_order_id")
        if oid:
            o2t.setdefault(oid, set()).add(tid)
            t2o.setdefault(tid, set()).add(oid)
        if wid:
            w2t.setdefault(wid, set()).add(tid)
            t2w.setdefault(tid, set()).add(wid)
    split = [f"order_id={k[:16]}… 落在 {len(v)} 个 trace" for k, v in o2t.items() if len(v) > 1]
    split += [f"work_order_id={k[:16]}… 落在 {len(v)} 个 trace"
              for k, v in w2t.items() if len(v) > 1]
    multi = [f"trace {t[:8]}… 承载 {len(v)} 个不同 order_id" for t, v in t2o.items() if len(v) > 1]
    multi += [f"trace {t[:8]}… 承载 {len(v)} 个不同 work_order_id"
              for t, v in t2w.items() if len(v) > 1]
    if not o2t and not w2t:
        out.append({"id": "P4", "name": "一条订单=一条 trace（订单标识 ↔ trace 一一对应）",
                    "status": "NA",
                    "detail": "订单域无任何订单标识行 —— 无从判「一条订单=一条 trace」；"
                              "键缺失见 P2"})
    else:
        fails = split + multi
        if truncated:
            fails.append(f"订单域总体 {dom_total} 行仅取回 {fetched} 行（上限截断）"
                         f"——未覆盖全体")
        out.append({"id": "P4", "name": "一条订单=一条 trace（订单标识 ↔ trace 一一对应）",
                    "status": "FAIL" if fails else "PASS",
                    "detail": (f"订单标识 {len(o2t)} 个 order_id / {len(w2t)} 个 work_order_id，"
                               f"涉及 trace {len({s.get('trace_id') for s in spans})} 条；"
                               f"跨 trace 拆分 {len(split)} 项、trace 内身份冲突 {len(multi)} 项"
                               + ("；" + "；".join(fails) if fails else ""))})

    # ---- P5 真库订单 trace 结构合规（真 span 上复用断言集）----
    if not sem_rows:
        out.append({"id": "P5", "name": "真库订单 trace 结构合规（单根/父链/层序/派生 ID/键集）",
                    "status": "NA",
                    "detail": "真库语义层 span 行数=0 —— 结构判据不适用（真空绿防线："
                              "不冒充 PASS）；覆盖下界见 P1"})
    else:
        F = run_assertions(sem_rows, conv)
        fails = []
        for aid in sorted(F):
            title, msgs, _n = F[aid]
            for m in msgs:
                fails.append(f"{aid} {title}：{m}")
        if truncated:
            fails.append(f"订单域总体 {dom_total} 行仅取回 {fetched} 行（上限截断）"
                         f"——未覆盖全体")
        out.append({"id": "P5", "name": "真库订单 trace 结构合规（单根/父链/层序/派生 ID/键集）",
                    "status": "FAIL" if fails else "PASS",
                    "detail": (f"真库语义层行 {len(sem_rows)} 上跑断言集 {len(F)} 条，"
                               f"失败 {len(fails)} 项"
                               + ("；" + "；".join(fails[:6]) if fails else ""))})
    return out


def report_production(checks: list) -> tuple:
    """production 判定清单打印 → (PASS 数, FAIL 数, NA 数)。"""
    n_fail = n_na = 0
    print("──── 真库名册/订单域总体判定（--production）────")
    for c in checks:
        if c["status"] == "FAIL":
            n_fail += 1
            print(f"  [FAIL] {c['id']} {c['name']}")
            print(f"         - {c['detail']}")
        elif c["status"] == "NA":
            n_na += 1
            print(f"  [N/A  ] {c['id']} {c['name']} —— {c['detail']}")
        else:
            print(f"  [PASS] {c['id']} {c['name']} —— {c['detail']}")
    print(f"  小计：PASS={len(checks) - n_fail - n_na} FAIL={n_fail} NA={n_na}")
    return len(checks) - n_fail - n_na, n_fail, n_na


def _production_state_path(conv: dict, override: str | None = None) -> str:
    if override:
        return override if os.path.isabs(override) else os.path.join(WS, override)
    rel = production_spec(conv).get("state_file") or "状态观测/otel-production.json"
    return rel if os.path.isabs(rel) else os.path.join(WS, rel)


def _write_production_state(path: str, payload: dict) -> None:
    """原子写状态面（tmp + os.replace）：门读到的一定是完整 JSON。"""
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    os.replace(tmp, path)


def _order_sample(spans: list, limit: int = 20) -> list:
    """状态面留证：订单域 trace 摘要（≤limit 条 trace；span 名 + 订单标识）。

    只留摘要不留全量行——状态面被门每 15min 读一次，必须小且可读。
    """
    seen: dict = {}
    for s in spans or []:
        tid = s.get("trace_id") or ""
        e = seen.get(tid)
        if e is None:
            e = {"trace": tid[:16], "order_id": _order_key(s, "af.order_id")[:48],
                 "work_order_id": _order_key(s, "af.work_order_id")[:48], "spans": []}
            seen[tid] = e
        if len(e["spans"]) < 12:
            e["spans"].append(s.get("name"))
    return list(seen.values())[:limit]


def cmd_production(conv: dict, args) -> int:
    """--production：真库回查（唯一带网络的模式）。"""
    spec = production_spec(conv)
    if not spec:
        print("FATAL: 约定文档 §6 缺 production 块（名册下界判据无源）——不可证不猜绿")
        return 1
    window_min = int(args.window_min or spec.get("window_min") or 360)
    skew_min = int(args.skew_min if args.skew_min is not None
                   else (spec.get("skew_min") if spec.get("skew_min") is not None else 5))
    max_rows = int(args.max_order_rows if args.max_order_rows is not None
                   else (spec.get("max_order_rows") or 5000))
    semantic = list((conv.get("semantic_layers") or {}).keys())
    print(f"（真库回查：窗口 {window_min}min（含未来戳容忍 {skew_min}min）"
          f"；名册 required 项 {len(spec.get('required_spans') or {})} 个"
          f"；订单域逐行取回上限 {max_rows} 行）")
    try:
        counts = fetch_production_counts(window_min, skew_min, semantic)
        rows = fetch_order_rows(window_min, skew_min, semantic, max_rows)
    except Exception as e:  # noqa: BLE001 —— CH 不可达=不可证
        print(f"FATAL: 真库不可达（不可证即不猜绿）：{e}")
        path = _production_state_path(conv, args.state)
        try:
            _write_production_state(path, {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                                           "ts_epoch": int(time.time()),
                                           "status": "error", "error": str(e)[:300],
                                           "window_min": window_min, "checks": []})
        except OSError:
            pass
        return 2
    spans = ch_rows_to_spans(rows)
    checks = judge_production(counts, conv, window_min) \
        + judge_order_spans(spans, counts, conv, window_min)
    _npass, nfail, _nna = report_production(checks)
    path = _production_state_path(conv, args.state)
    _write_production_state(path, {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "ts_epoch": int(time.time()),
        "status": "red" if nfail else "green", "window_min": window_min,
        "skew_min": skew_min, "counts": counts, "checks": checks,
        "order_sample": _order_sample(spans)})
    print(f"（状态面：{path}）")
    return 1 if nfail else 0


def cmd_production_check(conv: dict, args) -> int:
    """--production-check：零网络消费面（只读状态面；缺件/过期/红态→红）。"""
    spec = production_spec(conv)
    if not spec:
        print("FATAL: 约定文档 §6 缺 production 块——不可证不猜绿")
        return 2
    path = _production_state_path(conv, args.state)
    max_age = int(args.max_age_s if args.max_age_s is not None
                  else (spec.get("max_state_age_s") or 1800))
    try:
        with open(path, "rb") as fh:
            raw = fh.read().decode("utf-8", "replace")
    except OSError as e:
        print(f"SKIP: 状态面不可读（缺件即不可证，不猜绿）：{path}（{e}）")
        return 2
    try:
        st = json.loads(raw)
    except ValueError as e:
        print(f"SKIP: 状态面不可解析（坏 JSON）：{path}（{e}）")
        return 2
    if not isinstance(st, dict):
        print(f"SKIP: 状态面结构不可识别（非对象）：{path}")
        return 2
    try:
        age = time.time() - os.stat(path).st_mtime
    except OSError as e:
        print(f"SKIP: 状态面 stat 失败：{path}（{e}）")
        return 2
    if age > max_age:
        print(f"FAIL: 状态面读数过期（age={age:.0f}s > 阈 {max_age}s）——"
              f"巡检本身停摆即红（死手断言）")
        return 1
    status = st.get("status")
    if status == "error":
        print(f"FAIL: 末次实查为执行错（真库不可达等）：{st.get('error')}")
        return 1
    if status != "green":
        failed = [c.get("id") for c in (st.get("checks") or []) if c.get("status") == "FAIL"]
        print(f"FAIL: 末次判定红（status={status}，失败判定 {failed or '未知'}）；"
              f"ts={st.get('ts')} age={age:.0f}s")
        return 1
    print(f"PASS: 末次判定绿（status=green，ts={st.get('ts')} age={age:.0f}s ≤ 阈 {max_age}s）")
    return 0


# --------------------------------------------------------------------------- #
# 样本生成（--make-samples）
# --------------------------------------------------------------------------- #
def _sv(v) -> dict:
    return {"stringValue": str(v)}


def _iv(v) -> dict:
    return {"intValue": str(int(v))}


def _av(vs) -> dict:
    return {"arrayValue": {"values": [_sv(v) for v in vs]}}


def _span(name, trace_id, span_id, parent, kind, attrs, start=1_700_000_000_000_000_000):
    """attrs = {key: 已构造好的 OTLP AnyValue dict}（值包装由 _sv/_iv/_av 负责）。"""
    return {"traceId": trace_id, "spanId": span_id, "parentSpanId": parent,
            "name": name, "kind": kind,
            "startTimeUnixNano": str(start), "endTimeUnixNano": str(start),
            "attributes": [{"key": k, "value": v} for k, v in attrs.items()]}


def build_good_sample() -> dict:
    """好样本：一条订单语义树（L1→L2→{L3,L4}）+ 一个 factory 族 span。

    ID 按 otlp-model §1.0 派生式的**逐字转写**计算（与断言器的配方表是两处独立实现，
    避免同源错误互相掩盖）：§1.0 原文——
      trace_id   = SHA-256("af-trace-v1|"   + work_order_id)[0..32]
      L1 span_id = SHA-256("af-span-v1|"    + work_order_id + "|invoke_workflow")[0..16]
      L2 span_id = SHA-256("af-span-v1|"    + work_order_id + "|" + run_id)[0..16]
      L3 span_id = SHA-256("af-span-v1|"    + run_id + "|chat|" + turn)[0..16]
      L4 span_id = SHA-256("af-span-v1|"    + run_id + "|tool|" + seq)[0..16]
    """
    woid = "sid-9db2d04ac82e5283fbf88387ee48f15b1f776d1781810cd8e9733a570b41f94a"
    run_id = "django__django-11099-a2"
    order_id = "F1-swev-django-11099-glm-cp"
    turn = 3                 # L3 span_id 用 turn 派生（§1.0）
    chat_seq, tool_seq = 8, 9   # L4 span_id 用自己的 af.seq 派生（§1.0）
    trace_id = hashlib.sha256(("af-trace-v1|" + woid).encode()).hexdigest()[:32]
    l1 = hashlib.sha256(("af-span-v1|" + woid + "|invoke_workflow").encode()).hexdigest()[:16]
    l2 = hashlib.sha256(("af-span-v1|" + woid + "|" + run_id).encode()).hexdigest()[:16]
    l3 = hashlib.sha256(("af-span-v1|" + run_id + "|chat|" + str(turn)).encode()).hexdigest()[:16]
    l4 = hashlib.sha256(("af-span-v1|" + run_id + "|tool|" + str(tool_seq)).encode()).hexdigest()[:16]
    ts = 1_700_000_000_000

    res_attrs = {
        "service.name": _sv("af-otel-projector"),
        "service.version": _sv("0.1.0"),
        "af.order_id": _sv(order_id),
        "af.work_order_id": _sv(woid),
        "af.run_id": _sv(run_id),
        "af.line": _sv("line-A"),
        "af.profile": _sv("glm-cp"),
        "af.model": _sv("GLM-5.3-Flash"),
        "af.strategy_id": _sv(order_id),
        "af.dsl_digest": _sv("348a0142d883"),
    }
    spans = [
        _span("invoke_workflow", trace_id, l1, ZERO_SPAN_ID, 1, {
            "af.span.layer": _sv("invoke_workflow"),
            "af.order_id": _sv(order_id),
            "af.work_order_id": _sv(woid),
            "af.workflow.final_state": _sv("Closed"),
            "af.workflow.ledger_entries": _iv(22),
            "af.workflow.ops_ok": _sv("create_order,bind_line,attach_voucher,release"),
            "af.workflow.mes_kinds": _sv("release,start,complete,close"),
            "af.line": _sv("line-A"),
            "af.unit": _sv("swev"),
            "af.order.stage": _sv("agent-loop"),
            "af.order.stage_detail": _sv("swev-agent-loop"),
        }),
        _span("invoke_agent", trace_id, l2, l1, 1, {
            "af.span.layer": _sv("invoke_agent"),
            "af.run_id": _sv(run_id),
            "af.run_dir": _sv("swev-django__django-11099-glm-cp-a2"),
            "af.node_id": _sv("line-A"),
            "af.attempt": _iv(2),
            "af.model": _sv("GLM-5.3-Flash"),
            "af.terminal.kind": _sv("completed"),
            "af.terminal.signal": _sv("TASK_COMPLETE"),
            "gen_ai.operation.name": _sv("invoke_agent"),
            "gen_ai.agent.name": _sv("line-A"),
            "gen_ai.request.model": _sv("GLM-5.3-Flash"),
        }),
        _span("chat", trace_id, l3, l2, 3, {
            "af.span.layer": _sv("chat"),
            "af.run_id": _sv(run_id),
            "af.turn": _iv(turn),
            "af.seq": _iv(chat_seq),
            "af.ts_ms": _iv(1792838565312),
            "gen_ai.operation.name": _sv("chat"),
            "gen_ai.request.model": _sv("GLM-5.3-Flash"),
            "gen_ai.usage.input_tokens": _iv(1926),
            "gen_ai.usage.output_tokens": _iv(1052),
            "gen_ai.usage.cache_read_tokens": _iv(10624),
            "gen_ai.response.finish_reasons": _av(["tool_use"]),
            "gen_ai.system": _sv("anthropic"),
        }),
        _span("execute_tool", trace_id, l4, l2, 3, {
            "af.span.layer": _sv("execute_tool"),
            "af.run_id": _sv(run_id),
            "af.turn": _iv(turn),
            "af.seq": _iv(tool_seq),
            "af.ts_ms": _iv(1792838565999),
            "af.tool.effect": _sv("external_once"),
            "gen_ai.operation.name": _sv("execute_tool"),
            "gen_ai.tool.name": _sv("bash"),
        }),
    ]
    order_payload = {"resourceSpans": [{
        "resource": {"attributes": [{"key": k, "value": v} for k, v in res_attrs.items()]},
        "scopeSpans": [{"scope": {"name": "af-otel-projector"}, "spans": spans}],
    }]}

    # factory 族样本（sidecar 轮次形状；ID 按 otel_emit.trace_id_for/span_id_for 的域派生）
    f_ts = 1_700_000_000_000
    f_trace = hashlib.sha256(f"af-factory-v1|sidecar|{f_ts}".encode()).hexdigest()[:32]
    f_span = hashlib.sha256(f"af-span-v1|sidecar-round|{f_ts}".encode()).hexdigest()[:16]
    factory_payload = {"resourceSpans": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": _sv("otel-sidecar")},
            {"key": "service.version", "value": _sv("otel-mvp-20261028")},
        ]},
        "scopeSpans": [{"scope": {"name": "af-factory-lane"}, "spans": [
            _span("factory.sidecar_round", f_trace, f_span, ZERO_SPAN_ID, 1, {
                "af.factory.domain": _sv("sidecar"),
                "af.factory.mode": _sv("daemon"),
                "af.sidecar.round": _iv(7),
                "af.sidecar.cycle_ts_ms": _iv(f_ts),
                "af.sidecar.sources_ok": _sv("4/4"),
                "af.sidecar.queue_pending": _iv(0),
            }),
        ]}],
    }]}

    # 同树变体：cache 计数键改用 **semconv 现役名** gen_ai.usage.cache_read.input_tokens
    # （2026-10-31 实测：otlp-model §3.4 钉的 gen_ai.usage.cache_read_tokens 在任何已发布
    #  semconv 版本中都不存在，现役名为 ...cache_read.input_tokens——见约定文档 §3.1 勘误注）。
    #  该变体必须同样全绿：组内任一成员即满足必备键。
    order_semconv = json.loads(json.dumps(order_payload))
    for sp in order_semconv["resourceSpans"][0]["scopeSpans"][0]["spans"]:
        if sp["name"] != "chat":
            continue
        for a in sp["attributes"]:
            if a["key"] == "gen_ai.usage.cache_read_tokens":
                a["key"] = "gen_ai.usage.cache_read.input_tokens"

    return {"order": order_payload, "order_semconv_cache": order_semconv,
            "factory": factory_payload}


def _payload_to_ch_rows(payload: dict) -> list:
    """好样本载荷 → CH 行形状（--production 判据夹具用：与真库行同形）。"""
    kind_by_num = {v: k for k, v in SPAN_KIND_BY_NAME.items()}
    rows = []
    for rec in flatten([payload]):
        rows.append({"trace_id": rec["trace_id"], "span_id": rec["span_id"],
                     "parent_span_id": rec["parent_span_id"], "span_name": rec["name"],
                     "span_kind": kind_by_num.get(rec["kind"], rec["kind"]),
                     "resource_attributes": dict(rec["resource"]),
                     "span_attributes": dict(rec["attrs"])})
    return rows


def _fixture_split(conv: dict, rows: list, total_rows: int | None = None) -> tuple:
    """夹具行 → (订单域总体行, 计数字典)。

    口径与真库回查同构：订单域总体 = 语义层名册行 ∪ 带任一订单级键的行；
    计数字段由行派生（不手编矛盾数——旧夹具里「semantic_rows=4 而 order_keyed=1」
    这类互相矛盾的手编计数正是旧判据测不出问题的原因之一）。
    """
    semantic = list((conv.get("semantic_layers") or {}).keys())
    by_name: dict = {}
    for r in rows:
        by_name[r["span_name"]] = by_name.get(r["span_name"], 0) + 1

    def _k(r, key):
        for src in (r.get("resource_attributes") or {}, r.get("span_attributes") or {}):
            v = src.get(key)
            if isinstance(v, str) and v.strip():
                return v
        return ""

    dom = [r for r in rows if r["span_name"] in semantic
           or _k(r, "af.order_id") or _k(r, "af.work_order_id")]
    sem_rows = [r for r in dom if r["span_name"] in semantic]
    counts = {"by_name": by_name,
              "rows": len(rows) if total_rows is None else total_rows,
              "order_keyed": sum(1 for r in dom if _k(r, "af.order_id")),
              "woid_keyed": sum(1 for r in dom if _k(r, "af.work_order_id")),
              "semantic_rows": len(sem_rows),
              "semantic_missing_keys": sum(1 for r in sem_rows
                                           if not _k(r, "af.order_id")
                                           or not _k(r, "af.work_order_id")),
              "order_domain_rows": len(dom),
              "order_traces": len({r["trace_id"] for r in dom})}
    return dom, counts


def _mutate(payload: dict, kind: str) -> dict:
    """从好样本派生坏样本（每个变异只针对一条断言）。入参=order 载荷，返回变异后的载荷。"""
    d = json.loads(json.dumps(payload))
    rs = d["resourceSpans"][0]
    spans = rs["scopeSpans"][0]["spans"]
    by = {s["name"]: s for s in spans}
    res_attrs = rs["resource"]["attributes"]

    def set_res(k, v):
        for a in res_attrs:
            if a["key"] == k:
                a["value"] = v
                return
        res_attrs.append({"key": k, "value": v})

    def del_res(k):
        rs["resource"]["attributes"] = [a for a in res_attrs if a["key"] != k]

    def set_attr(span, k, v):
        for a in span["attributes"]:
            if a["key"] == k:
                a["value"] = v
                return
        span["attributes"].append({"key": k, "value": v})

    def del_attr(span, k):
        span["attributes"] = [a for a in span["attributes"] if a["key"] != k]

    if kind == "R1":
        del_res("service.name")
    elif kind == "R2":
        set_res("af.not_a_legal_key", _sv("x"))
    elif kind == "R3":
        set_res("af.arm", _sv("a1"))
    elif kind == "R4":
        # 剥掉订单级身份种子（含 af.work_order_id）——种子缺失曾使 I4 静默跳过→全绿
        for k in ("af.order_id", "af.work_order_id", "af.line"):
            del_res(k)
    elif kind == "R4-run":
        # 剥掉 run 级身份键（该 Resource 挂有 L2/L3/L4 → run 级必有）
        for k in ("af.run_id", "af.profile", "af.model"):
            del_res(k)
    elif kind == "I1":
        spans[0]["traceId"] = "not-hex"
    elif kind == "I2":
        spans[0]["spanId"] = ZERO_SPAN_ID
    elif kind == "I3":
        by["invoke_agent"]["parentSpanId"] = "abc"
    elif kind == "I4":
        spans[0]["spanId"] = "0123456789abcdef"
    elif kind == "K1":
        spans[0]["kind"] = 9
    elif kind == "K2":
        by["chat"]["kind"] = 1
    elif kind == "N1":
        spans[0]["name"] = "harness.model"
    elif kind == "N2":
        set_attr(by["execute_tool"], "af.span.layer", _sv("chat"))
    elif kind == "A1":
        del_attr(by["chat"], "af.turn")
    elif kind == "A2":
        set_attr(by["chat"], "af.unexpected", _sv("x"))
    elif kind == "A3":
        set_attr(by["chat"], "af.payload", _sv("{}"))
    elif kind == "A4":
        set_attr(by["invoke_agent"], "af.order.stage", _sv("agent-loop"))
    elif kind == "A5":
        set_attr(by["invoke_workflow"], "af.order.stage", _sv("running"))
    elif kind == "A6":
        # 互斥组同时在场：chat 同时带 gen_ai.usage.cache_read_tokens 与现役 semconv 名
        set_attr(by["chat"], "gen_ai.usage.cache_read.input_tokens", _iv(10624))
    elif kind == "S1":
        dup = json.loads(json.dumps(by["invoke_workflow"]))
        dup["spanId"] = "fedcba9876543210"
        spans.append(dup)
    elif kind == "S2":
        by["invoke_agent"]["parentSpanId"] = "aaaaaaaaaaaaaaaa"
    elif kind == "S3":
        by["invoke_agent"]["parentSpanId"] = by["chat"]["spanId"]
        by["chat"]["parentSpanId"] = by["invoke_agent"]["spanId"]
    elif kind == "S4":
        by["execute_tool"]["parentSpanId"] = by["chat"]["spanId"]
    elif kind == "S5":
        set_attr(by["chat"], "af.run_id", _sv("django__django-11099-a1"))
        # 保持 §1.0 派生自洽（run_id 变了 → span_id 也要跟着变，否则会连带触发 I4）
        new_l3 = hashlib.sha256(
            ("af-span-v1|django__django-11099-a1|chat|3").encode()).hexdigest()[:16]
        by["chat"]["spanId"] = new_l3
    elif kind == "S6":
        del_attr(by["invoke_agent"], "af.terminal.kind")
    elif kind == "S7":
        set_attr(by["invoke_workflow"], "af.unit", _sv("report"))
        set_attr(by["invoke_workflow"], "af.order.stage", _sv("judge"))
        rs["scopeSpans"][0]["spans"] = [s for s in spans if s["name"] == "invoke_workflow"]
    else:
        raise ValueError(f"未知变异：{kind}")
    return d


# 变异 → 期望命中的断言 ID（selftest 逐条核对）。
# "allow_extra" 列出**必然连带**的断言：例如把某个 span 的 traceId 改成非法值，
# 该 span 即脱离原 trace，树形状断言（S1/S2/S4/S7）随之必然失败——这是断言的真实语义，
# 不是探针失效；未列入 allow_extra 的额外命中一律判 selftest 红（防"变异没打中目标"被掩盖）。
MUTATIONS = {
    # R1: resource 缺 service.name
    "R1": {"expect": ["R1"], "allow_extra": []},
    # R2: resource 出现非正字法 af.* 键
    "R2": {"expect": ["R2"], "allow_extra": []},
    # R3: resource 出现本批禁用的 af.arm
    "R3": {"expect": ["R3"], "allow_extra": []},
    # R4: resource 剥掉订单级身份种子（af.order_id/work_order_id/line）
    #     —— span 属性面仍带同名键，A1/S5 不连带；I4 因种子缺失跳过（不连带），
    #     红由 R4 接（红队 I4 修复的负例）
    "R4": {"expect": ["R4"], "allow_extra": []},
    # R4-run: resource 剥掉 run 级身份键（该树含 L2/L3/L4 → run 级必有）
    "R4-run": {"expect": ["R4"], "allow_extra": []},
    # I1: L1 的 traceId 非 32 位 hex → 该 span 脱离原 trace（连带 I4/S1/S2/S4/S7）
    "I1": {"expect": ["I1"], "allow_extra": ["I4", "S1", "S2", "S4", "S7"]},
    # I2: L1 的 spanId 全零 → 子 span 的 parent 失联（连带 I4/S2/S4）
    "I2": {"expect": ["I2"], "allow_extra": ["I4", "S2", "S4"]},
    # I3: L2 的 parentSpanId 形状非法 → 父不可解析（连带 S2/S4）
    "I3": {"expect": ["I3"], "allow_extra": ["S2", "S4"]},
    # I4: L1 的 spanId 与 §1.0 派生不符 → L2 的 parent 失联（连带 S2/S4）
    "I4": {"expect": ["I4"], "allow_extra": ["S2", "S4"]},
    # K1: L1 的 kind 越界 → 同时违反 K2 的固定 kind（连带 K2）
    "K1": {"expect": ["K1"], "allow_extra": ["K2"]},
    # K2: chat 的 kind 应 CLIENT 实为 INTERNAL
    "K2": {"expect": ["K2"], "allow_extra": []},
    # N1: L1 改名 → 脱离语义层名册（连带 N2/A4/S1/S2/S4/S7）
    "N1": {"expect": ["N1"], "allow_extra": ["N2", "A4", "S1", "S2", "S4", "S7"]},
    # N2: L4 的 af.span.layer 与 span 名不一致
    "N2": {"expect": ["N2"], "allow_extra": []},
    # A1: chat 缺必备键 af.turn
    "A1": {"expect": ["A1"], "allow_extra": []},
    # A2: chat 出现越界键
    "A2": {"expect": ["A2"], "allow_extra": []},
    # A3: chat 出现禁用键 af.payload → 同时是越界键（连带 A2）
    "A3": {"expect": ["A3"], "allow_extra": ["A2"]},
    # A4: L1 专属键落到 L2 上 → 同时是越界键（连带 A2）
    "A4": {"expect": ["A4"], "allow_extra": ["A2"]},
    # A5: L1 的 af.order.stage 不在词表
    "A5": {"expect": ["A5"], "allow_extra": []},
    # A6: cache 计数键组同时在场（互斥）
    "A6": {"expect": ["A6"], "allow_extra": []},
    # S1: 同 trace 出现第二个根 → 该副本 spanId 非派生值（连带 I4）
    "S1": {"expect": ["S1"], "allow_extra": ["I4"]},
    # S2: L2 的 parent 指向不存在的 span → 层序随之断（连带 S4）
    "S2": {"expect": ["S2"], "allow_extra": ["S4"]},
    # S3: L2↔L3 互指成环 → 层序随之断（连带 S4）
    "S3": {"expect": ["S3"], "allow_extra": ["S4"]},
    # S4: L4 的 parent 改成 L3（chat）→ chat 与 execute_tool 不再同父
    "S4": {"expect": ["S4"], "allow_extra": []},
    # S5: chat 的 af.run_id 与 L2 祖先不一致（span_id 已同步重算，不连带 I4）
    "S5": {"expect": ["S5"], "allow_extra": []},
    # S6: L2 缺 af.terminal.kind
    "S6": {"expect": ["S6"], "allow_extra": []},
    # S7: L1 改成 unit=report/stage=judge 但树内无 invoke_agent（只剩 L1）
    "S7": {"expect": ["S7"], "allow_extra": []},
}


def make_samples(out_dir: str) -> list:
    os.makedirs(out_dir, exist_ok=True)
    good = build_good_sample()
    written = []
    p = os.path.join(out_dir, "good-order-tree.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(good["order"], fh, ensure_ascii=False, indent=1)
    written.append(p)
    p = os.path.join(out_dir, "good-factory-sidecar.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(good["factory"], fh, ensure_ascii=False, indent=1)
    written.append(p)
    p = os.path.join(out_dir, "good-order-tree-semconv-cache.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(good["order_semconv_cache"], fh, ensure_ascii=False, indent=1)
    written.append(p)
    for kind in sorted(MUTATIONS):
        p = os.path.join(out_dir, f"bad-{kind}-sample.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(_mutate(good["order"], kind), fh, ensure_ascii=False, indent=1)
        written.append(p)
    return written


# --------------------------------------------------------------------------- #
# selftest
# --------------------------------------------------------------------------- #
def selftest(conv: dict) -> int:
    print("== otlp-assert 自测：好样本必须绿，坏样本必须红（负例探针必须真实起作用）==")
    good = build_good_sample()
    failures = 0
    union_eval: dict = {}

    for label, payload in (("good-order-tree", good["order"]),
                           ("good-order-tree-semconv-cache", good["order_semconv_cache"]),
                           ("good-factory-sidecar", good["factory"])):
        F = run_assertions(flatten([payload]), conv)
        npass, nfail, nvac = report(f"好样本 {label}", F)
        if nfail:
            failures += 1
            print(f"  [BAD ] 好样本 {label} 意外有红（{nfail} 条）")
        # 好样本并集覆盖：任一断言在**全部好样本并集**上仍是 0 条记录求值 → 断言集
        # 出现真空绿（该断言自始至终没被任何样本检验过）→ selftest 红。
        for aid, (_t, _f, n_eval) in F.items():
            union_eval[aid] = union_eval.get(aid, 0) + n_eval

    for kind in sorted(MUTATIONS):
        spec = MUTATIONS[kind]
        payload = _mutate(good["order"], kind)
        F = run_assertions(flatten([payload]), conv)
        failed = {aid for aid, (_t, f, _n) in F.items() if f}
        expect, extra = set(spec["expect"]), set(spec["allow_extra"])
        missing = expect - failed
        unexpected = failed - expect - extra
        if missing:
            failures += 1
            print(f"  [BAD ] 负例 {kind}: 未命中期望断言 {sorted(missing)}"
                  f"（实际命中 {sorted(failed)}）—— 探针失效")
        elif unexpected:
            failures += 1
            print(f"  [BAD ] 负例 {kind}: 意外连带命中 {sorted(unexpected)}"
                  f"（允许连带 {sorted(extra)}）")
        else:
            casc = sorted(failed - expect)
            tail = ("（连带 %s，均为登记在册的必然连带）" % casc) if casc else "（无连带）"
            print(f"  [OK  ] 负例 {kind}: 命中期望断言 {sorted(expect)}{tail}")

    # ---- 新鲜度帽负例探针（2026-11-02 RT 修复钉死）--------------------------
    # 帽的阈值必须由断言侧常量定，不得由被测快照自声明、不得由环境变量放宽：
    # ① 自声明 interval_s=864000（自称周期 10 天）的 24h 陈旧快照 → 仍判陈旧；
    # ② 帽值恒等于断言侧定阈，与快照自声明值无关（30 与 864000 同帽同判）；
    # ③ 环境变量 OTEL_SIDECAR_STALE_CAP_S 无任何效果（门路径子进程继承调用者
    #    环境 → 环境变量放宽 = 门旁路）；
    # ④ 取证回放的显式旗标（cap_override / --stale-cap-s）仍可用；
    # ⑤ 现役快照（ts=now）判现役（即便它自称 interval_s=864000）；
    # ⑥ ts 在未来（时钟倒挂）判非现役。
    print("")
    print("== 新鲜度帽负例探针：帽阈值不得由被测快照自声明 / 不得由环境变量放宽 ==")
    now_ms = int(time.time() * 1000)
    stale_snap = {"ts": now_ms - 24 * 3600 * 1000, "interval_s": 864000}
    fresh_snap = {"ts": now_ms, "interval_s": 864000}
    future_snap = {"ts": now_ms + 3600 * 1000, "interval_s": 30}
    cap0, interval0 = _sidecar_stale_cap()
    probes = []

    r_stale = _sidecar_stale_reason(stale_snap)
    probes.append(("自声明 interval_s=864000 的 24h 陈旧快照仍判陈旧",
                   r_stale is not None and f"鲜度帽 {cap0}s" in r_stale,
                   f"reason={r_stale!r}"))

    r_stale_truth = _sidecar_stale_reason({"ts": stale_snap["ts"], "interval_s": 30})
    probes.append(("帽阈值与快照自声明 interval_s 无关（30 vs 864000 同帽同判）",
                   (r_stale is None) == (r_stale_truth is None)
                   and f"鲜度帽 {cap0}s" in (r_stale or r_stale_truth or ""),
                   f"cap={cap0}s 采信周期={interval0}s"))

    probes.append((f"断言侧定阈：帽 = max(4×{interval0}s, 120s) = {cap0}s（不随快照变）",
                   cap0 == max(4 * SIDECAR_TRUSTED_INTERVAL_S, 120) and cap0 == 120,
                   f"cap={cap0}"))

    old_env = os.environ.get("OTEL_SIDECAR_STALE_CAP_S")
    os.environ["OTEL_SIDECAR_STALE_CAP_S"] = "999999"
    try:
        r_env = _sidecar_stale_reason(stale_snap)
        cap_env, _ = _sidecar_stale_cap()
    finally:
        if old_env is None:
            os.environ.pop("OTEL_SIDECAR_STALE_CAP_S", None)
        else:
            os.environ["OTEL_SIDECAR_STALE_CAP_S"] = old_env
    probes.append(("环境变量 OTEL_SIDECAR_STALE_CAP_S 无效（不放宽帽、不放过陈旧件）",
                   r_env is not None and cap_env == cap0,
                   f"reason={r_env!r} cap={cap_env}"))

    probes.append(("取证显式旗标 --stale-cap-s 仍可放宽（cap_override 生效）",
                   _sidecar_stale_reason(stale_snap, cap_override=999999) is None,
                   "cap_override=999999 → 判现役"))

    probes.append(("现役快照（ts=now，即便自称 interval_s=864000）判现役",
                   _sidecar_stale_reason(fresh_snap) is None, ""))

    probes.append(("ts 在未来（时钟倒挂）判非现役",
                   _sidecar_stale_reason(future_snap) is not None, ""))

    for label, ok, detail in probes:
        if ok:
            print(f"  [OK  ] {label}" + (f"（{detail}）" if detail else ""))
        else:
            failures += 1
            print(f"  [BAD ] {label}：探针失效（{detail}）")

    # ---- 发射面死活探针（2026-11-02 RT 修复钉死：读快照 emit 块的当轮回执）------
    # 新鲜度帽只管「快照年龄」，管不住「快照在流但发射全灭」：--sidecar 的 fake_post
    # 恒成功 → 复原必然有载荷 → 发射零成功在门输入里原本不可表达（真实历史窗
    # 2026-10-31→11-01 连续 4702 轮 emit(span=False metrics=0) 而门全绿）。判据必须
    # 只取当轮（span_sent/metrics_sent），绝不可取进程累计量（spans/metrics/errors/
    # skipped_stop）——在役边车 errors 已背 4702 轮的历史欠账而当下发射正常。
    print("")
    print("== 发射面死活探针：当轮零成功发射不得过前置 / 累计量不得当判据 ==")
    e_probes = []
    dead_emit = {"span_sent": False, "metrics_sent": 0, "spans": 0, "metrics": 0,
                 "errors": 14, "skipped_stop": 0}
    r_dead = _sidecar_emit_dead_reason({"emit": dead_emit})
    e_probes.append(("打死端点当轮回执（span_sent=False metrics_sent=0）判发射面死",
                     r_dead is not None and "零成功" in r_dead, f"reason={r_dead!r}"))

    r_hist = _sidecar_emit_dead_reason(
        {"emit": {"span_sent": False, "metrics_sent": 0, "spans": 0, "metrics": 0,
                  "errors": 65828, "skipped_stop": 0}})
    e_probes.append(("历史停发窗末形态（errors=65828 累计）同样判死",
                     r_hist is not None, f"reason={r_hist!r}"))

    live_emit = {"span_sent": True, "metrics_sent": 13, "spans": 2670,
                 "metrics": 34724, "errors": 65828, "skipped_stop": 0}
    r_live = _sidecar_emit_dead_reason({"emit": live_emit})
    e_probes.append(("在役快照（span_sent=True errors=65828 历史欠账）判现役——"
                     "累计量绝不当判据", r_live is None, f"reason={r_live!r}"))

    r_span_flake = _sidecar_emit_dead_reason(
        {"emit": {"span_sent": False, "metrics_sent": 13, "spans": 0,
                  "metrics": 13, "errors": 1, "skipped_stop": 0}})
    e_probes.append(("span 单发失败而 gauge 在流（2026-10-30 17:47 实录形态）不判死",
                     r_span_flake is None, f"reason={r_span_flake!r}"))

    r_metric_dry = _sidecar_emit_dead_reason(
        {"emit": {"span_sent": True, "metrics_sent": 0, "spans": 1,
                  "metrics": 0, "errors": 0, "skipped_stop": 0}})
    e_probes.append(("span 送达而 gauge 全灭（指标源全哑非发射面死）不判死",
                     r_metric_dry is None, f"reason={r_metric_dry!r}"))

    r_noemit = _sidecar_emit_dead_reason({})
    e_probes.append(("快照缺 emit 块 → 不掺假绿（无法判定即关门）",
                     r_noemit is not None and "emit 块" in r_noemit,
                     f"reason={r_noemit!r}"))

    r_badms = _sidecar_emit_dead_reason({"emit": {"span_sent": False,
                                                  "metrics_sent": None}})
    e_probes.append(("emit.metrics_sent 不可判（None）→ 不掺假绿",
                     r_badms is not None and "metrics_sent" in r_badms,
                     f"reason={r_badms!r}"))

    for label, ok, detail in e_probes:
        if ok:
            print(f"  [OK  ] {label}" + (f"（{detail}）" if detail else ""))
        else:
            failures += 1
            print(f"  [BAD ] {label}：探针失效（{detail}）")

    # ---- 真空绿防线探针（2026-11-02 RT 修复批）------------------------------
    # ① 好样本并集覆盖：任一断言在全部好样本并集上仍 0 条记录求值 → 该断言自始至终
    #    未被任何样本检验（断言集真空绿）→ selftest 红；
    # ② 覆盖不全不标绿：只含 factory 载荷时，语义层总体为空 → 断言记 VACUOUS，
    #    verdict_exit(0, VACUOUS>0) 必须返回 2（不标绿），不得返回 0。
    print("")
    print("== 真空绿防线探针：0 记录求值的断言不得计 PASS / 覆盖不全不得标绿 ==")
    vac_probes = []
    vac_only = sorted(aid for aid, n in union_eval.items() if n == 0)
    vac_probes.append((f"好样本并集覆盖：{len(union_eval)} 条断言全部有判定记录"
                       f"（并集 0 记录者：{vac_only or '无'}）",
                       not vac_only, f"并集={union_eval}"))
    fac_only = flatten([good["factory"]])
    F_fac = run_assertions(fac_only, conv)
    vac_ids = sorted(aid for aid, (_t, _f, n) in F_fac.items() if n == 0)
    vac_probes.append(("factory-only 载荷：语义层总体为空 → 断言记 VACUOUS（不计 PASS）",
                       "S1" in vac_ids and "R4" in vac_ids,
                       f"VACUOUS 断言={vac_ids}"))
    vac_probes.append(("覆盖不全 → verdict_exit 返回 2（不标绿），不得返回 0",
                       verdict_exit(0, len(vac_ids)) == 2 and verdict_exit(0, 0) == 0
                       and verdict_exit(1, 0) == 1,
                       "verdict_exit(0,>0)=2 / (0,0)=0 / (1,0)=1"))
    for label, ok, detail in vac_probes:
        if ok:
            print(f"  [OK  ] {label}" + (f"（{detail}）" if detail else ""))
        else:
            failures += 1
            print(f"  [BAD ] {label}：探针失效（{detail}）")

    # ---- --production 订单域总体判据探针（零网络：纯函数 + 夹具）--------------
    # 真库回查的判定逻辑是纯函数 judge_production()（P1 名册计数下界）+ 
    # judge_order_spans()（P2~P5 订单域总体判据）；夹具自证——
    # ① 绿路：完整订单 trace + 名册全在流 → P1~P5 无 FAIL（防把门改成恒红也能过）；
    # ② 某个 required 名册项计数 0 → P1 FAIL（required 项=0 即红）；
    # ③ 订单域总体 0 行 → P2 FAIL；语义层行 0 → P3 记 N/A（不冒充 PASS）；
    # ④ 「100 万行里仅 1 行带键」→ **不得判绿**（旧下界=1 判据在此判绿；新判据红）；
    # ⑤ 一条订单被拆到两个 trace → P4 FAIL（旧判据完全测不出）；
    # ⑥ 派生 ID 与 §1.0 不符 → P5 FAIL（真库 span 面首次可判）；
    # ⑦ 订单域总体取回被上限截断 → 覆盖不全，红（不可全证，不猜绿）。
    print("")
    print("== --production 订单域总体判据探针（零网络夹具）==")
    spec_p = production_spec(conv)
    req_names = sorted((spec_p.get("required_spans") or {}).keys())

    # 夹具工厂行：只用于把 required 名册项喂到计数里（无订单级键 → 不进订单域总体）
    fac_rows = [{"span_name": n, "trace_id": hashlib.sha256(
        ("fixture-fac|" + n).encode()).hexdigest()[:32],
        "span_id": hashlib.sha256(("fixture-fac-span|" + n).encode()).hexdigest()[:16],
        "parent_span_id": "",
        "resource_attributes": {"service.name": "af-otel-projector",
                                "service.version": "0.1.0"},
        "span_attributes": {}} for n in req_names
        if n not in (conv.get("semantic_layers") or {})]

    good_rows = _payload_to_ch_rows(good["order"])

    def _judge(rows, total_rows=None):
        dom, counts = _fixture_split(conv, rows, total_rows)
        spans = ch_rows_to_spans(dom)
        return judge_production(counts, conv, 360) + judge_order_spans(spans, counts, conv, 360), counts

    p_probes = []
    chk_green, _c = _judge(good_rows + fac_rows)
    p_probes.append(("绿路对照：完整订单 trace + required 名册项全在流 → P1~P5 无 FAIL",
                     not any(c["status"] == "FAIL" for c in chk_green),
                     f"checks={[(c['id'], c['status']) for c in chk_green]}"))
    missing_name = req_names[0] if req_names else "invoke_workflow"
    rows_miss = [r for r in (good_rows + fac_rows) if r["span_name"] != missing_name]
    chk_red, _c = _judge(rows_miss)
    p1 = next((c for c in chk_red if c["id"] == "P1"), None)
    p_probes.append((f"required 名册项 {missing_name} 入库 0 → P1 FAIL（required 项=0 即红）",
                     p1 is not None and p1["status"] == "FAIL" and missing_name in p1["detail"],
                     f"P1={p1['status'] if p1 else None}"))
    chk_nokeys, _c = _judge(fac_rows)
    p2 = next((c for c in chk_nokeys if c["id"] == "P2"), None)
    p3 = next((c for c in chk_nokeys if c["id"] == "P3"), None)
    p4 = next((c for c in chk_nokeys if c["id"] == "P4"), None)
    p5 = next((c for c in chk_nokeys if c["id"] == "P5"), None)
    p_probes.append(("订单域总体 0 行（无任何语义层行/带键行）→ P2 FAIL",
                     p2 is not None and p2["status"] == "FAIL",
                     f"P2={p2['status'] if p2 else None}"))
    p_probes.append(("语义层行数 0 → P3 记 N/A（不冒充 PASS）",
                     p3 is not None and p3["status"] == "NA",
                     f"P3={p3['status'] if p3 else None}"))
    p_probes.append(("订单域总体 0 行 → P4/P5 记 N/A（不冒充 PASS）",
                     p4 is not None and p4["status"] == "NA" and p5 is not None
                     and p5["status"] == "NA",
                     f"P4={p4['status'] if p4 else None} P5={p5['status'] if p5 else None}"))

    # ④ 半键行（带 af.order_id 不带 af.work_order_id 的非语义层行）——旧下界判据
    #    （P2「非空行 ≥1」+ P3 只查语义层行）在此夹具上判绿；新判据必须红。
    half_rows = [dict(r) for r in good_rows] + [dict(r) for r in fac_rows]
    for r in half_rows:
        if r["span_name"] == "factory.order_round":
            r["resource_attributes"] = dict(r["resource_attributes"])
            r["resource_attributes"]["af.order_id"] = "F1-half-keyed"
    chk_half, half_counts = _judge(half_rows)
    old_half_ok = (int(half_counts.get("order_keyed") or 0) >= 1
                   and int(half_counts.get("woid_keyed") or 0) >= 1
                   and int(half_counts.get("semantic_missing_keys") or 0) == 0)
    p2h = next((c for c in chk_half if c["id"] == "P2"), None)
    p_probes.append(("订单域总体内有「只带 order_id」半键行 → P2 FAIL（旧 ≥1 下界判据在此判绿）",
                     old_half_ok and p2h is not None and p2h["status"] == "FAIL",
                     f"旧判据可绿={old_half_ok}；P2={p2h['status'] if p2h else None}"))

    # ⑤ 「100 万行里仅 1 行带键」——旧判据只看计数（≥1 即 PASS），新判据按**订单 trace
    #    结构**判：那条订单的 trace 不成链 → P5 红（不得判绿）。
    game_rows = [r for r in good_rows if r["span_name"] == "invoke_workflow"] + fac_rows
    chk_game, game_counts = _judge(game_rows, total_rows=1_000_000)
    old_ok = (int(game_counts.get("order_keyed") or 0) >= 1
              and int(game_counts.get("woid_keyed") or 0) >= 1
              and int(game_counts.get("semantic_missing_keys") or 0) == 0)
    p5g = next((c for c in chk_game if c["id"] == "P5"), None)
    p_probes.append(("「100 万行里仅 1 行带键」不得判绿（按订单 trace 结构判，不按 ≥1 计数判）",
                     old_ok and p5g is not None and p5g["status"] == "FAIL",
                     f"旧判据可绿={old_ok}；P5={p5g['status'] if p5g else None}"))

    # ⑤ 一条订单被拆到两个 trace（旧判据测不出：每条 trace 各带键 → P2 仍 PASS）
    split_rows = [dict(r) for r in good_rows]
    for r in split_rows:
        if r["span_name"] == "invoke_agent":
            r["trace_id"] = "b" * 32
    chk_split, _c = _judge(split_rows + fac_rows)
    p4s = next((c for c in chk_split if c["id"] == "P4"), None)
    p_probes.append(("一条订单被拆到两个 trace → P4 FAIL（旧下界判据测不出）",
                     p4s is not None and p4s["status"] == "FAIL",
                     f"P4={p4s['status'] if p4s else None}"))

    # ⑥ 派生 ID 与 §1.0 不符 → P5 FAIL（真库 span 面首次可判；旧判据只有计数）
    badid_rows = [dict(r) for r in good_rows]
    for r in badid_rows:
        r["trace_id"] = "c" * 32
    chk_id, _c = _judge(badid_rows + fac_rows)
    p5i = next((c for c in chk_id if c["id"] == "P5"), None)
    p_probes.append(("派生 ID 与 §1.0 不符 → P5 FAIL（真库 span 面首次可判）",
                     p5i is not None and p5i["status"] == "FAIL" and "I4" in p5i["detail"],
                     f"P5={p5i['status'] if p5i else None}"))

    # ⑦ 订单域总体取回被上限截断 → 覆盖不全，红（不可全证，不猜绿）
    dom_g, counts_g = _fixture_split(conv, good_rows + fac_rows)
    counts_g["order_domain_rows"] = len(dom_g) + 5      # 真库总体比取回行数大
    chk_trunc = judge_production(counts_g, conv, 360) \
        + judge_order_spans(ch_rows_to_spans(dom_g), counts_g, conv, 360)
    p2t = next((c for c in chk_trunc if c["id"] == "P2"), None)
    p_probes.append(("订单域总体取回被截断 → P2 FAIL（覆盖不全不可全证，不猜绿）",
                     p2t is not None and p2t["status"] == "FAIL"
                     and "截断" in p2t["detail"],
                     f"P2={p2t['status'] if p2t else None}"))
    for label, ok, detail in p_probes:
        if ok:
            print(f"  [OK  ] {label}" + (f"（{detail}）" if detail else ""))
        else:
            failures += 1
            print(f"  [BAD ] {label}：探针失效（{detail}）")

    print("")
    if failures:
        print(f"SELFTEST FAIL：{failures} 项不符（好样本红或负例探针失效）")
        return 1
    print(f"SELFTEST PASS：好样本全绿 + {len(MUTATIONS)} 个负例全部命中期望断言且无连带"
          f" + {len(probes)} 个新鲜度帽负例探针全过"
          f" + {len(e_probes)} 个发射面死活探针全过"
          f" + {len(vac_probes)} 个真空绿防线探针全过"
          f" + {len(p_probes)} 个 --production 订单域总体判据探针全过")
    return 0


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="OTLP 合规断言器（离线，零网络）")
    ap.add_argument("--selftest", action="store_true", help="好样本绿 + 坏样本红自测")
    ap.add_argument("--input", action="append", default=[],
                    help="OTLP/JSON 载荷文件（可重复）")
    ap.add_argument("--sidecar", nargs="?", const=DEFAULT_SIDECAR,
                    help="用现役 otel-sidecar.json 快照经真实发射器复原后断言")
    ap.add_argument("--stale-cap-s", type=int, default=None, metavar="N",
                    help="取证回放专用：显式把新鲜度帽放宽到 N 秒（门路径不用此旗标；"
                         "环境变量 OTEL_SIDECAR_STALE_CAP_S 已废——门路径子进程继承"
                         "调用者环境，环境变量放宽 = 门旁路）")
    ap.add_argument("--make-samples", metavar="DIR", help="生成 mock 样本到 DIR")
    ap.add_argument("--production", action="store_true",
                    help="真库模式：逐名册项近窗入库计数下界 + 订单级键在位"
                         "（§6 production 块为唯一判据源；本模式是本件唯一带网络的路径）")
    ap.add_argument("--production-check", action="store_true",
                    help="零网络消费面：只读状态面（由 --production 落盘），"
                         "末次判定红即红、读数过期即红、缺件/坏 JSON → rc=2")
    ap.add_argument("--window-min", type=int, default=None, metavar="N",
                    help="--production 近窗时间窗（分钟；缺省取 §6 production.window_min）")
    ap.add_argument("--max-order-rows", type=int, default=None, metavar="N",
                    help="--production 订单域总体逐行取回上限（行；缺省取 §6 "
                         "production.max_order_rows）——取回不足总体行数时判据判红"
                         "（覆盖不全不可全证，不猜绿）")
    ap.add_argument("--skew-min", type=int, default=None, metavar="N",
                    help="--production 未来戳容忍（分钟；缺省取 §6 production.skew_min）")
    ap.add_argument("--state", metavar="PATH", help="状态面路径（默认 §6 production.state_file）")
    ap.add_argument("--max-age-s", type=int, default=None, metavar="N",
                    help="--production-check 读数可信上界（秒；缺省取 §6 production.max_state_age_s）")
    a = ap.parse_args()

    try:
        conv = load_convention()
    except Exception as e:  # noqa: BLE001 —— 约定不可解析=内部错误=红
        print(f"FATAL: 约定文档不可解析：{e}")
        return 1

    # A1：名册正本一致性对账（在场才查；缺席 ⇒ 行为等价旧版，不红）。
    roster = load_semantic_roster()
    if roster is None:
        print("[roster] 语义层名册正本缺席（af/otel/semantic-roster.json 不在位）"
              "——名册判据沿用约定块，行为等价", file=sys.stderr)
    else:
        drift = roster_consistency_findings(roster, conv)
        if drift:
            print("FATAL: 名册正本与约定块（span-conventions.md §6）不一致：")
            for p in drift:
                print(f"  - {p}")
            return 1

    if a.make_samples:
        paths = make_samples(a.make_samples)
        print(f"已生成 {len(paths)} 个样本：{a.make_samples}")
        for p in paths:
            print(f"  - {os.path.basename(p)}")
        return 0

    if a.production_check:
        return cmd_production_check(conv, a)

    if a.production:
        return cmd_production(conv, a)

    if a.selftest:
        return selftest(conv)

    if a.sidecar:
        if os.environ.get("OTEL_SIDECAR_STALE_CAP_S"):
            print("⚠ OTEL_SIDECAR_STALE_CAP_S 已废（2026-11-02 RT 修复）并被忽略："
                  "环境变量放宽新鲜度帽 = 从门路径旁路整条帽；取证回放请用 --stale-cap-s")
        if a.stale_cap_s is not None:
            print(f"⚠ 取证放宽：新鲜度帽被显式放宽到 {a.stale_cap_s}s（--stale-cap-s）——"
                  f"本结果不承载「现役」语义，不得当门绿引用")
        payloads, note = collect_sidecar_payloads(a.sidecar, a.stale_cap_s)
        if payloads is None:
            print(f"SKIP: {note}")
            return 2
        print(f"（{note}）")
        spans = flatten(payloads)
        F = run_assertions(spans, conv)
        _npass, nfail, nvac = report(f"sidecar 快照断言 [{a.sidecar}]", F)
        coverage_report(spans, conv)
        # 覆盖不全（真空绿）→ rc=2 不标绿；名册缺项在覆盖块里显式点名
        return verdict_exit(nfail, nvac)

    if a.input:
        total_fail = total_vac = 0
        for path in a.input:
            if not os.path.isfile(path):
                print(f"SKIP: 载荷文件不在位：{path}")
                return 2
            try:
                payloads = load_payloads(path)
            except Exception as e:  # noqa: BLE001
                print(f"FATAL: {path} 解析失败：{e}")
                return 1
            spans = flatten(payloads)
            F = run_assertions(spans, conv)
            _npass, nfail, nvac = report(f"载荷断言 [{os.path.basename(path)}]", F)
            coverage_report(spans, conv)
            total_fail += nfail
            total_vac += nvac
        return verdict_exit(total_fail, total_vac)

    ap.print_usage()
    print("（须给 --selftest / --input / --sidecar / --make-samples / --production"
          " / --production-check 之一）")
    return 2


if __name__ == "__main__":
    sys.exit(main())
