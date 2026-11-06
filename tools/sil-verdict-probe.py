#!/usr/bin/env python3
"""sil-verdict-probe.py — SIL 裁决产出腿活性门（常驻巡检面，all-gates L3 挂载）。

背景（2026-11-02 确证发现）：SIL 环的活性/清洁信号全绿而裁决产出腿可无限期停摆——
镜像真实性门（self-improve-loop.py mirror_source_ro_gate，RT-E12①）把非机制性只读
的镜像源 fail-closed 拒用后：签名不前进、聚合器不跑、裁决不产生，但轮照跑、队列
「清洁」、守护 60s 心跳把 loop-state.json 恒保新鲜——keepalive 只看新鲜度（300s 判
据恒绿）、all-gates 无任何 sil 门位（grep=0）、metrics 面（状态观测/self-improve.json）
无 gate 状态、变更日志告警仅门位翻转写一次（2026-11-02 实证：00:13 双源拒用一行后
3.5h+ 零告警）——「环活性」监测测不出「裁决产出永久停摆」，G-SIL/锚3 活性读数全绿
失真。本探针把「无任何可信镜像源=产出腿停摆」读成显式红挂进 all-gates，停摆对巡检
常驻可见；源以 ro 方式挂载（findmnt OPTIONS 含 ro）后守护下轮自动解拒、本门自动
翻绿（RT-E85④：chmod 收权不构成机制性只读，权限位同 uid 可逆——不得作恢复路径）。

v1.1（2026-11-02，修复本常驻门的**失效型**缺陷——判据只读可改写文件）：v1.0 的判据
只读 状态观测/loop-state.json（mode=664，同 uid 可写）里的 mirror_ro_gate 布尔、无
任何完整性校验——同 uid 进程改写该文件即可把停摆读成绿（2026-11-02 亲测：真文件
FAIL exit=1 → 注入副本把 mirror_ro_gate 改成 {"exp1":true,"exp2":true} → PASS
exit=0），即 RT-E88「真相在册无人订阅」可被订阅者喂假值、常驻红可被同 uid 进程静音。
修法（最小、不弱化任何既有断言、判据不复制）：**绿不再由可改写的文件背书**——状态面
布尔降级为辅证，物理镜像面的机械实测升为准据，两者逐源取交集（绿 ⟺ 每一源
「状态面记可信」∧「机械实测=机制性只读」），机械实测直接调用守护**在册的只读门判据**
（self-improve-loop.mirror_source_ro_gate，判据单一源）。

判据（只读 状态观测/loop-state.json + 物理镜像面实测，无任何写动作）：
  ① 状态面在位且可解析——缺失/坏 JSON → rc=2（缺件红：摘门必须显式红，不静默 SKIP，
    与 all-gates「缺件不静默放行」同口径）；
  ② 读数新鲜：state mtime 与 heartbeat_ts 均 <1800s（守护心跳 60s=keepalive 300s 判
    据的写盘节奏；1800s=6 倍容差）——读数过期不背书绿（守护停写/已死时拒绝放行）；
  ③ mirror_ro_gate 逐源读数在位（非空 dict）→ 否则 rc=2（守护版本过旧或③段从未跑过，
    产出腿状态不可证——不可证即红，不猜绿）；
  ④【v1.1 新增】机械实测交叉核验——对守护在册的每个镜像源当场复算只读门（findmnt
    OPTIONS 面，RT-E85④ 口径），逐源与状态面记录对账：
      · 绿 ⟺ 每一源「状态面记可信」∧「机械实测=机制性只读」；
      · 状态面记可信 ∧ 机械实测拒用 → rc=1（产出腿实为停摆 + 状态面被喂假值/改写
        嫌疑——v1.0 被注入翻绿的那条通道在此堵死）；
      · 状态面记拒用 ∧ 机械实测可信 → rc=1（守护尚未翻转，产出腿未恢复——不早绿）；
      · 源集不一致（状态面源集 ≠ 守护在册源集）→ rc=2（读数不可证，不猜绿）；
      · 状态面自相矛盾（mirror_ro_gate 与 last_round 逐源 ro_gate 读数不一致）→ rc=2
        （状态面被改写嫌疑，不可证即红）；
      · 机械实测不可得（判据源不可导入/在册源枚举失败）→ rc=2（不可证即红，不猜绿）；
  ⑤ 机械实测拒用（物理面非机制性只读）→ rc=1（裁决产出腿停摆：签名不前进、无新裁
    决/回写；轮次/队列/心跳等环活性读数不代表产出）。

v1.2（2026-11-02，修复本常驻门的**覆盖面**缺陷——绿只证「源可信」不证「产出腿在
产出」）：v1.1 的绿判据仍只落在输入信任面（逐源「状态面记可信」∧「机械实测=机制
性只读」），**不证明产出腿在产出**——源可信但守护签名不前进（无新终态单可裁/聚合
失败/判定门失败/策略册不可用）时，产出腿零产出而门照绿（红队确证：逃逸台账 RT-E88
拦截机制②「产出腿 dead-man 断言」自认「机制②③④未见」，且目的-监测项映射以本门
为「产出腿门」达成证据——映射结论覆盖面宽于门判据本身）。修法（最小、**不弱化任
何既有判据**、只读）：在信任面对账之后**追加**⑥产出腿前进断言——绿不再止于「源可
信」，须另证「产出腿未停摆」：
  ⑥ 产出腿前进断言（RT-E88 拦截机制②；落在①②③④⑤之后，不改既有任一判据）：
    A 积压（有活未产出）：守护本轮算出的逐源镜像签名 ≠ 已签收签名
      （last_round.experiments.mirror.sigs vs exp_mirror_sigs）——守护已见新终态
      单/新汇总却签名不前进（聚合失败/判定门失败/策略册不可用/源被拒用）⇒ 产出腿
      有活而零产出 ⇒ rc=1；
    B 死手（空转环）：轮在前进（rounds>0）∧ 末次裁决/回写长期零（>DEADMAN_S；末次
      ts 取 verdict_log 末条，无则取 started_at）∧ 拒用持续（任一源被真实性门拒
      用）⇒ rc=1（区分「空转环」与「产出环」）。
    ⑥ 读数不可得（状态面无 last_round.experiments.mirror 段＝STOP/异常轮/老版本）
    时不猜绿也不猜红：⑥ 判据跳过，结论并入绿行说明（信任面判据仍独立成立）。

v1.3（2026-11-03，修复本常驻门的**双判据并行**缺陷——探针量盘上现码、在役守护跑
其启动时载入的旧码，两套真相并行且无人对账）：本门机械实测调用的是**盘上现码**的
只读门判据，而状态面里的 mirror_ro_gate 读数来自**在役守护载入时**的判据——两者
不一致时，本门测的是「盘上码怎么判」，在役跑的是「旧码怎么判」，同一镜像面两套结
论（2026-11-03 实证：在役守护 06:53:37 起跑、盘上源码 17:53:28 已改、17h 未重载＝
轮4 SIL 修整体未在役；沙盒 A/B 实证同一棵 chmod-555 树：在役旧码 trusted=True「权限
强制只读」＝RT-E85④ 旁路仍开，盘上现码 trusted=False「非 ro 挂载…不得用 chmod 收权
替代」；本门报双源拒用而守护写盘旧口径 RT-E12①，无人对账）。修法（最小、不弱化既有
判据、只读）：**追加 ⑦ 源码版本钉对账**——状态面登记的「在役载入版本 sha256」（守护
v1.3.11 起每次写盘登记 daemon_src）必须等于盘上判据源此刻的 sha256，否则状态面读数
与机械实测**不可对账**⇒ rc=2（不可证即红，不猜绿）：
  ⑦ 版本钉缺席（状态面无 daemon_src.sha256＝在役码早于版本钉机制）→ rc=2；
  ⑦ 版本钉不等（在役 ≠ 盘上＝两套真相并行）→ rc=2（红，并点名两个指纹前缀）；
  ⑦ 版本钉一致 → 判据继续（并在 PASS 行附「在役判据版本=盘上判据版本」证据）。
本门**只读不换码**：换码由监督面执行（tools/factory-keepalive.py 源码版本钉判活：
在役载入版本≠盘上源码⇒判死⇒拉起新码；keepalive 自身源码变更⇒os.execv 自我重载）。

v1.4（2026-11-03 状态面面收口批，修复本常驻门对**状态面封条完全失明**的缺陷）：
本门此前读的状态面是「同 uid/同组可写的文件」而**零完整性校验**（grep seal = 0）——
守护 v1.3.9 起虽已有状态面封条（HMAC，写盘签发/读盘验签，不过即 fail-closed 隔离
未过段），**巡检面看不见**：注入者改写状态面后由守护下一轮重新签发封条即被「洗白」成
守护自产件（内容面机制在、监测面不在）。修法（最小、不弱化任何既有判据、只读）：
**追加 ⑧ 状态面封条+权限面对账**——本门读的内容必须**是守护签发的那一份**，
且落盘件必须**没人能写**（封条保证内容不被注入，不保证「谁能写」）：
  ⑧a 封条验签（判据单一源＝守护在册 verify_state_seal，不复制验签逻辑）：
      封条验签失败（内容与守护签发时不一致＝疑被篡改/注入）→ rc=1；
      无封条（在役守护早于封条机制/封条被抹）→ rc=2（不可证即红，不猜绿）；
  ⑧b 守护读盘判定 state_seal_ok=False ⇒ 守护上轮不信任这份状态面：已隔离条目
      ⇒ rc=1（注入/篡改确实发生过，红，不因守护随后重新签发而洗白）；无隔离条目
      ⇒ rc=2（首启无旧件可比/封条被抹，不可证）；
  ⑧c quarantine_log 里「验签失败」类隔离记录＝篡改/注入事件在册 ⇒ rc=1（sticky：
      红到人工处置为止，不许被下一次重新签发洗白；「无封条」类＝升级前旧件/首启，
      不属篡改，不据此判红）；
  ⑧d 落盘件权限面（独立实测文件权限位，不采信守护自述）：同组/他人可写（mode &
      0o022）⇒ rc=1（改写面开着；守护 v1.3.13 起写盘即 0600 + 读盘权限自愈）。

v1.6-rt85wip（2026-11-06，RT-E85② 密钥出域 shadow——P4-H3/H4 吸收，只增不改既有判据①-⑨）：
  ⑩ 签名钥可用性对账（新，P4-H4 阻塞项）：读 loop-state.key_status（守护 save_state
    唯一写盘点）——state 非 ok ⇒ rc=1 精确红（停摆分类+恢复路径=重启守护续跑）；
    读数缺失/非法 ⇒ rc=2 不猜绿。台账:747 口径「停摆显式在册**且有人订阅**」的订阅面。
  ⑧a 停摆口径分离（P4-H3）：封条复算遇守护「签名停摆（复算不可得）」⇒ fail(2)
    不可证（不诬篡改）；篡改类 fail(1) 原样。
  取钥面（F1 口径，2026-11-06 部署窗据 H4-探针十.md R1 更正——原「独立进程不取钥」
  仅对 ⑩ 成立）：⑧a 复算借判据源函数，openbao 模式下**每探针进程取钥一次**（新
  进程无钥缓存，首查必走 bao-token 签发+kv 读；停摆世=一次失败尝试后进程内短
  路）；⑩ 只读状态面、不取钥。
v1.5（2026-11-03，修复本常驻门对**判据读出通道换件**的同源失明）：④机械实测与守护
判据共用同一 mirror_source_ro_gate → findmnt 读出——守护 v1.3.13 及以前 findmnt 按
**裸名走进程 PATH** 解析，而在役守护 PATH 前置 ~/bin、~/.local/bin、~/.cargo/bin
三个**同 uid 可写**目录（2026-11-03 亲读 /proc/<pid>/environ + 权限位佐证）：同 uid
进程落一个恒打印 ro 的假 findmnt 即**同时换掉两腿的读出**——④的「交叉核验」用的
正是被换掉的那条通道，结构性测不出（沙盒复现：PATH 前置假件 + rw 挂载镜像 →
trusted=True「挂载 ro」＝RT-E85④ 信任锚被整体伪造）。修法（最小、不弱化任何既有
判据、只读）：守护 v1.3.14 起 findmnt 按 confstr _CS_PATH 解析绝对路径（读出通道
自身收口）；本门在机械实测前加**读出通道独立复算对账**——本进程不经判据模块、
自行按 _CS_PATH 解析 findmnt 绝对路径，与判据模块在册解析结果对账：
  ⑨ 判据模块无 _system_tool 读出解析口（版本过旧/被改）→ rc=2（不可证即红）；
  ⑨ 判据解析 ≠ 本进程独立复算（含任一方缺席）→ rc=2（读出通道被换件嫌疑/两套
    解析并行——机械实测读数不可证，不猜绿）；
  ⑨ 两方一致且为系统工具目录内绝对路径 → 通道可证，④继续（在 PASS 行附通道证据）。
残余边界（如实）：_CS_PATH 目录本身（/bin、/usr/bin，root 所有）被写则面仍在——
那超出「同 uid 换件」威胁模型；confstr 读 libc 常量不经进程 PATH，故 keepalive
拉起不洗 PATH 环境不再构成该面。

用法:
  sil-verdict-probe.py                    # 读在役状态面（all-gates 挂载姿势）
  sil-verdict-probe.py --state <path>     # 指定状态文件（夹具回归用）

退出码：0=可信源在位且机械实测=机制性只读且产出腿未停摆且在役判据版本=盘上判据版本
且状态面封条验签通过且落盘件同组/他人不可写（⑥ 绿：源可信 ∧ 无积压 ∧ 无空转死手 ∧
⑦ 版本钉对齐 ∧ ⑧ 封条+权限面对账通过 ∧ ⑨ 读出通道独立复算一致）；1=产出腿停摆/
有活未产出/空转死手/读数过期/状态面与机械实测背离/封条验签失败/封条未过且已隔离/
篡改事件在册/落盘件权限过宽（红）；2=状态面缺件/不可证/版本钉不对齐/无封条/封条未过
且无可隔离内容/判据 findmnt 读出通道独立复算不一致（红）。
纪律：只读；无第三方依赖（纯标准库 + 判据源守护模块本身）；python3 -I 可跑（WS 路径
由 __file__ 推导；判据源按绝对路径导入，不依赖 sys.path——-I 隔离模式下亦可）。

残余边界（如实登记，不粉饰）：
  · 本门与状态面同 uid 同信任域。v1.1 把「可改写文件里的布尔」从绿的唯一凭据降为
    辅证、把物理镜像面提为准据：同 uid 攻击者无法靠改写 loop-state.json 把停摆读成
    绿（机械实测照实判拒用→红）；攻击者若把镜像真以 ro 方式挂载，守护下一轮亦判可信
    并恢复产出——该路径下绿与产出腿实况一致（不是静音停摆）。
  · 守护在册判据随守护源码演进（判据唯一源）：本门读的是**当前在册源码**的判据，
    在役守护进程跑的是其启动时载入的版本——v1.3 起本门**显式对账**该差异（⑦ 版本
    钉：在役载入版本 sha256 ≠ 盘上判据源 sha256 ⇒ rc=2「两套真相并行、不可对账」，
    不再只是「本门可能更严」的软声明）；守护重启换判据后自动对齐（监督面 keepalive
    源码版本钉判活会自动换码）。守护换源（在册源集变化）未重启期间本门显式红（源集
    不一致=不可证），不猜绿。
  · ⑦ 的残余：版本钉只证明「在役判据＝盘上判据」，**不证明盘上判据本身正确**——盘上
    判据若有洞（如 RT-E85④ 前的 chmod-555 旁路），版本对齐也照样绿/红照旧；另，
    同一时刻「盘上源码」与「在役载入内容」若在启动瞬间被并发改写，钉值可能取到改写
    后内容（窗口为进程启动的毫秒级，如实登记）。
  · 状态面本体的完整性 HMAC 钉 + 守护 load_state 验签 fail-closed（逃逸台账 RT-E86
    拦截机制②）**已施工**（守护 v1.3.9 起：写盘签发/读盘验签，未过即隔离回写面四段；
    v1.3.12 补第四段 verdict_log）——v1.4 起本门**显式对账**它（⑧a⑧b⑧c：验签不过
    即红、篡改事件 sticky 红，不再是「本门看不见」）。
  · ⑧ 的残余（如实登记，不粉饰）：封条**覆盖面**＝回写面四段（verdict_queue /
    auto_create_retry / projection_todos / verdict_log）——本门另读的几段
    （mirror_ro_gate / last_round / exp_mirror_sigs / rounds / commits）**不在封条
    覆盖内**：其中 mirror_ro_gate 由④的机械实测交叉核验兜住（状态面与物理面背离即
    红），但 exp_mirror_sigs / rounds / commits 的改写**无内容面保护**（⑥A 积压
    判定与⑥B 死手判定可被改写掩盖）——封条扩面属守护侧改动（会致升级首轮整段隔离），
    不在本门最小修范围内，如实登记为残余。另：封条**不防重放**——旧封条件整份回放
    仍验签通过（ts 无单调性校验）；权限面（0600）把「谁能写」收窄到 owner，是当前
    防重放的主要防线。
  · **绿≠「此刻正在产出」（v1.2 口径收窄，如实登记）**：⑥ 只在两种**可判定**的停
    摆形态上背书红——A「有活未产出」（守护已见新终态单/新汇总却签名不前进）与
    B「拒用持续 ∧ 末次裁决长期零」（空转环）。「无新终态单可裁 ⇒ 本就无产出」不是
    故障（镜像终态单最近到货 2026-10-30 07:06，其后产出为零属该系统常态，非故障
    形态——见下方回归用例 F7），此时绿=「产出腿**未停摆**」而非「正在产出」——口径
    收窄是让门**不越权背书**，不是把停摆藏起来：产出为零且源被拒用的形态由 B 判
    红（用例 F6/F8），产出为零且源可用但无活的形态由 A 判红（用例 F5）。
"""
import importlib.util
import hashlib
import json
import os
import stat
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DEFAULT = os.path.join(WS, "状态观测", "loop-state.json")
GATE_SRC = os.path.join(WS, "tools", "self-improve-loop.py")
STALE_S = 1800          # 读数可信上界（守护 60s 心跳；keepalive 判据 300s 的 6 倍容差）
DEADMAN_S = 10800       # 产出腿死手窗（3h，s）：末次裁决/回写「长期零」判据窗
                         # （RT-E88 拦截机制②「轮前进∧verdict/commits 长期零∧拒用
                         # 持续=红」；3h 对齐 RT-E88 登记口径「产出腿已死逾 3 小时」）
HB_FMT = "%Y-%m-%d %H:%M:%S"


def fail(rc, msg):
    print("FAIL %s" % msg)
    sys.exit(rc)


def gate_src_sha256():
    """盘上判据源（守护源码 tools/self-improve-loop.py）此刻的 sha256。

    本门机械实测用的判据就是这份文件（live_ro_gate 直接导入它）——故它的指纹
    ＝「本门实测所用的判据版本」。"""
    h = hashlib.sha256()
    with open(GATE_SRC, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_gate_module(name="sil_self_improve_loop"):
    """按绝对路径导入守护判据源模块（判据单一源；不依赖 sys.path——-I 隔离模式下
    亦可）。导入失败/依赖缺失 → 抛异常（调用方 fail-closed：不可证即红，不猜绿）。"""
    spec = importlib.util.spec_from_file_location(name, GATE_SRC)
    if spec is None or spec.loader is None:
        raise RuntimeError("判据源 spec 构建失败：%s" % GATE_SRC)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit as e:                     # 守护模块自退（如缺 PyYAML → exit 2）
        raise RuntimeError("判据源导入自退 rc=%s（守护模块依赖缺失？）" % e.code)
    return mod


def _resolve_system_tool(name):
    """⑨ 独立复算原语（v1.5，2026-11-03 判据读出通道换件面）：本进程**不经判据模块**、
    直接按 confstr _CS_PATH（libc 系统默认工具目录，如 /bin:/usr/bin——不含任何用户
    PATH 目录；confstr 读 libc 编译期常量，不经进程 PATH 环境变量）逐目录解析系统
    工具绝对路径；解析不到返回 None。与判据模块 _system_tool 同算法**独立实现**
    ——两腿各算各的，交叉对账（堵「交叉核验共用同一被换件读出」的同源失明）。"""
    try:
        cs = os.confstr("CS_PATH") or "/bin:/usr/bin"
    except (ValueError, OSError):
        cs = "/bin:/usr/bin"
    for d in cs.split(":"):
        if not d:
            continue
        p = os.path.join(d, name)
        try:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
        except OSError:
            continue
    return None


def live_ro_gate():
    """机械实测：用守护在册的只读门判据对在册镜像源当场复算 → {name: (trusted, reason)}。

    判据单一源：直接调用 self-improve-loop.py 的 mirror_source_ro_gate（不复制判定
    逻辑、不在本门另立一套口径）。导入失败/依赖缺失 → 抛异常（调用方 fail-closed：
    不可证即红，不猜绿）。

    v1.5（⑨ 读出通道独立复算对账，2026-11-03）：本门④与守护判据共用同一 findmnt
    读出——守护 v1.3.13 及以前按裸名走进程 PATH 解析，同 uid 在 PATH 前置可写目录
    落恒打印 ro 的假件即**同时换掉两腿读出**（④交叉核验结构性失明；沙盒复现在案：
    rw 挂载镜像 + PATH 前置假件 → trusted=True「挂载 ro」）。故实测前先对账：本进程
    独立按 _CS_PATH 复算 findmnt 绝对路径，须与判据模块在册解析（_system_tool，守护
    v1.3.14 起即判据实际调用的绝对路径）逐字一致——不一致/判据无解析口 → RuntimeError
    （调用方 fail-closed rc=2，不猜绿）。"""
    mod = load_gate_module()
    mine = _resolve_system_tool("findmnt")               # 本进程独立复算（不经判据模块）
    res = getattr(mod, "_system_tool", None)
    if res is None:
        raise RuntimeError("判据模块无 _system_tool 读出解析口（在役码早于 v1.3.14 或"
                           "判据源被改）——判据 findmnt 读出通道不可证（不猜绿）")
    theirs = res("findmnt")                              # 判据实际调用的绝对路径
    if theirs != mine:
        raise RuntimeError("判据 findmnt 读出通道独立复算不一致（判据解析=%s ≠ 本进程"
                           "按 _CS_PATH 独立复算=%s）——判据读出可被同 uid PATH 换件/"
                           "两套解析并行，机械实测读数不可证（不猜绿）"
                           % (theirs, mine))
    out = {}
    for src in mod.exp_sources():
        trusted, reason = mod.mirror_source_ro_gate(src)
        out[src["name"]] = (bool(trusted), str(reason))
    return out


def key_status_verdict(st):
    """⑩ 签名钥可用性对账（RT-E85②，v1.6，P4-H4）：读 st["key_status"]（守护
    save_state 唯一写盘点）。返回 (level, msg)：0=绿（msg 供 PASS 行）；1=停摆
    精确红；2=不可证（不猜绿）。与 ⑧a 的分工：⑧a 是封条内容面复算（停摆时
    fail(2)「不可证」，H3 口径），⑩ 是取钥链路真相的**精确红**——停摆订阅面。"""
    ks = st.get("key_status")
    if not isinstance(ks, dict) or not str(ks.get("state") or "").strip():
        return 2, ("loop-state 无 key_status 读数——在役守护早于 RT-E85② 出域机制/"
                   "键被抹，签名钥可用性不可证（不猜绿）")
    state = str(ks.get("state"))
    if state == "ok":
        return 0, ("签名钥在役（source=%s fp16=%s ts=%s）"
                   % (ks.get("source"), ks.get("fp16"), ks.get("ts")))
    if state.startswith("failed"):
        return 1, ("SIL 签名钥停摆（state=%s：%s）——签名功能停摆中（②③④冻结，"
                   "不降级不自生成）；恢复=钥源可用后**重启守护进程**自动续跑（停摆"
                   "态粘滞不重取）；四段保留不销毁（T18e6）"
                   % (state, str(ks.get("err") or "")[:140]))
    return 2, ("key_status.state=%r 非法（非 ok/failed:*）——读数不可证（不猜绿）" % state)


def state_seal_verdict(st):
    """⑧ 状态面封条验签（判据单一源＝守护在册 verify_state_seal）→ (ok, reason)。

    守护（v1.3.9 起）每次写盘签发状态面封条（HMAC，覆盖回写面四段），每次读盘
    验签——不过即 fail-closed 隔离未过段（内容面）。本门此前**对封条完全失明**
    （grep seal = 0）：本门读的状态面是**同 uid/同组可写的文件**，注入者改写后
    由守护下一轮重新签发封条即被「洗白」成守护自产件——巡检面看不见。

    本门不复制验签逻辑：直接调用守护在册的 _bound_state_sections + verify_state_seal
    （读盘裁剪口径与守护 load_state 同口径：签发前已定界，故对守护自产件幂等）。
    导入失败 → 抛异常（调用方 fail-closed：不可证即红，不猜绿）。"""
    mod = load_gate_module("sil_self_improve_loop_seal")
    mod._bound_state_sections(st)               # 读盘裁剪口径＝守护 load_state 同口径
    return mod.verify_state_seal(st)


def state_detailed_ro_gate(st):
    """状态面内守护逐源只读门读数（last_round.experiments.mirror.ro_gate
    = {name: {trusted, reason}}）。老版本守护或 STOP/异常轮无此段 → {}（无内部一致性
    证据可对账，非红）。"""
    try:
        lr = st.get("last_round") or {}
        ex = lr.get("experiments") or {}
        mir = ex.get("mirror") or {}
        det = mir.get("ro_gate") or {}
    except Exception:
        return {}
    return det if isinstance(det, dict) else {}


def _parse_ts(s):
    """'%Y-%m-%d %H:%M:%S' → epoch（不可解析 → None）。"""
    if not isinstance(s, str):
        return None
    try:
        return time.mktime(time.strptime(s, HB_FMT))
    except ValueError:
        return None


def output_leg_check(st):
    """⑥ 产出腿前进断言（RT-E88 拦截机制②；只读状态面，无任何写动作）。

    绿 ⟺ 产出腿「未停摆」，而不止「镜像源可信」——v1.1 前的绿只落在输入信任面：
    源可信而守护签名不前进（无新终态单可裁/聚合失败/判定门失败/策略册不可用）时，
    产出腿零产出而门照绿（红队确证：RT-E88 机制②未施工；映射以本门为「产出腿门」
    达成证据，结论覆盖面宽于门判据）。

    两条判据（任一不成立即红）：
      A 积压（有活未产出）：守护本轮算出的逐源镜像签名 ≠ 已签收签名
        （last_round.experiments.mirror.sigs vs exp_mirror_sigs）——守护已见新终
        态单/新汇总却签名不前进 ⇒ 产出腿有活而零产出。
      B 死手（空转环）：轮在前进（rounds>0）∧ 末次裁决/回写长期零（>DEADMAN_S；
        末次 ts 取 verdict_log 末条，无则取 started_at）∧ 拒用持续（任一源被真
        实性门拒用）⇒ 区分「空转环」与「产出环」。

    返回 (rc, msg)：rc=1 红（msg=红因）；rc=0 绿（msg=绿证据说明）。
    """
    mir = ((st.get("last_round") or {}).get("experiments") or {}).get("mirror") or {}
    csigs = mir.get("sigs")
    stored = st.get("exp_mirror_sigs") or {}
    backlog = []
    if isinstance(csigs, dict) and csigs:
        for name in sorted(csigs):
            if stored.get(name) != csigs[name]:
                backlog.append(name)
    if backlog:
        return 1, ("SIL 产出腿有活未产出（积压）：守护本轮算出的镜像签名≠已签收签名"
                   "（%s）——已见新终态单/新汇总却签名不前进（聚合失败/判定门失败/"
                   "策略册不可用/源被拒用），产出腿零产出（轮次/队列/心跳等环活性"
                   "读数不代表产出）" % ",".join(backlog))
    gate = st.get("mirror_ro_gate") or {}
    refused = sorted(k for k, v in gate.items() if not v)
    last_out, src_ts = None, None
    for v in st.get("verdict_log") or []:
        t = _parse_ts((v or {}).get("ts"))
        if t is not None and (last_out is None or t > last_out):
            last_out, src_ts = t, (v or {}).get("ts")
    if last_out is None:
        last_out, src_ts = _parse_ts(st.get("started_at")), st.get("started_at")
    rounds = st.get("rounds")
    if refused and isinstance(rounds, int) and rounds > 0 and last_out is not None:
        age = time.time() - last_out
        if age > DEADMAN_S:
            return 1, ("SIL 产出腿长期零产出（空转环）：轮在前进（rounds=%s）但末次"
                       "裁决/回写停在 %s（距今 %.0fs，阈 %ds）且拒用持续（%s）——"
                       "环照跑、产出为零（轮次/队列/心跳等环活性读数不代表产出）"
                       % (rounds, src_ts, age, DEADMAN_S, ",".join(refused)))
    if not (isinstance(csigs, dict) and csigs):
        note = "⑥ 读数不可得（无 last_round.experiments.mirror 段——STOP/异常轮/" \
               "老版本守护），本轮未判积压"
    else:
        note = "⑥ 无积压（守护已见终态单全部签收）"
    if last_out is not None:
        note += "；末次裁决/回写=%s（距今 %.0fs）" % (src_ts or "无", time.time() - last_out)
    else:
        note += "；末次裁决/回写=无读数"
    return 0, note


def main():
    state = STATE_DEFAULT
    argv = sys.argv[1:]
    if "--state" in argv:
        i = argv.index("--state")
        if i + 1 >= len(argv):
            fail(2, "--state 需要路径参数")
        state = argv[i + 1]
    if not os.path.isfile(state):
        fail(2, "SIL 状态面缺件：%s 不在位（守护从未起/状态被删——不静默放行）" % state)
    try:
        with open(state, "rb") as f:
            st = json.loads(f.read().decode("utf-8", "replace"))
    except (OSError, ValueError) as e:
        fail(2, "SIL 状态面不可解析（%s）：%s" % (state, e))
    try:
        mtime_age = time.time() - os.stat(state).st_mtime
    except OSError as e:
        fail(2, "SIL 状态面 stat 失败：%s" % e)
    hb = st.get("heartbeat_ts")
    hb_age = None
    if isinstance(hb, str):
        try:
            hb_age = time.time() - time.mktime(time.strptime(hb, HB_FMT))
        except ValueError:
            hb_age = None
    if mtime_age >= STALE_S or hb_age is None or hb_age >= STALE_S:
        fail(1, "SIL 状态读数过期：state_age=%.0fs heartbeat=%s（age=%s，阈 %ds）"
                "——守护停写/已死，活性读数不可背书（keepalive 面按 300s 判据另有处置）"
                % (mtime_age, hb,
                   ("%.0fs" % hb_age) if hb_age is not None else "缺失", STALE_S))
    # ⑧ 状态面封条对账 + 权限面（2026-11-03 状态面面收口批）：本门读的状态面是
    # **同 uid/同组可写的文件**——守护 v1.3.9 起的封条（HMAC，覆盖回写面四段）
    # 才是「这份内容确由守护写」的证明，守护读盘验签不过即 fail-closed 隔离未过段。
    # 本门此前对封条**完全失明**（grep seal = 0）：注入者改写状态面后由守护下一轮
    # 重新签发封条即被洗白，巡检面看不见——内容面机制在、监测面不在。
    # 判据单一源：直接调用守护在册 verify_state_seal（不复制验签逻辑）。
    try:
        seal_ok, seal_why = state_seal_verdict(st)
    except Exception as e:
        fail(2, "状态面封条验签不可得（判据源不可用：%s: %s）——状态面不可证（不猜绿）"
                % (type(e).__name__, e))
    if not seal_ok:
        if "签名停摆" in seal_why:
            # H3（P4-联评，v1.6）：RT-E85② 停摆世复算不可得 ⇒ **不可证口径 fail(2)**
            # ——不猜绿也不诬篡改（⑧a 原 fail(1) 文案引运维去找篡改，误报口径漂移）；
            # 停摆的精确红由 ⑩ key_status 提供（见下）。
            fail(2, "SIL 状态面封条复算不可得（%s）——签名钥停摆态（RT-E85②），非篡改"
                    "证据；不猜绿也不诬篡改，精确红见 ⑩ key_status" % seal_why)
        if "无封条" in seal_why:
            fail(2, "SIL 状态面无封条（%s）——在役守护早于封条机制/封条被抹，状态面"
                    "内容不可证（不猜绿）" % seal_why)
        fail(1, "SIL 状态面封条验签失败（%s）——状态面被改写/注入（非守护签发内容）"
                % seal_why)
    # ⑧b 守护读盘时的封条判定：state_seal_ok=False ⇒ 守护上轮**不信任**这份状态面
    # （已 fail-closed 隔离未过段）。有隔离条目 ⇒ 注入/篡改确实发生过（红，不因
    # 守护随后重新签发封条而洗白）；无隔离条目 ⇒ 不可证（首启无旧件可比/封条被抹）。
    if st.get("state_seal_ok") is False:
        ql = st.get("quarantine_log") or []
        if ql:
            fail(1, "SIL 状态面封条未过且守护已隔离条目（state_seal_ok=False，隔离 %d 条："
                    "%s）——状态面注入/篡改发生过，红" % (
                        len(ql), ",".join(str(q.get("section")) for q in ql[:8])))
        fail(2, "SIL 状态面封条未过且无可隔离内容（state_seal_ok=False）——守护上轮不信任"
                "这份状态面，不可证（不猜绿）")
    # ⑧c 篡改事件不许被下一次重新签发「洗白」：quarantine_log 里**验签失败**类
    # 隔离记录＝内容面被改写/注入的确证（sticky：红到人工处置为止）。「无封条」
    # 类（升级前旧件/首启无旧件）不属篡改，不据此判红。
    tamper = [q for q in (st.get("quarantine_log") or [])
              if isinstance(q, dict) and "验签失败" in str(q.get("reason") or "")]
    if tamper:
        fail(1, "SIL 状态面篡改/注入事件在册（quarantine_log 验签失败隔离 %d 条，最近 %s）"
                "——红不许被守护重新签发洗白，须人工处置" % (
                    len(tamper), str((tamper[-1] or {}).get("ts"))))
    # ⑧d 状态面落盘件**权限面**：同组/他人可写 ⇒ 改写面开着（封条只保证内容不被
    # 注入，不保证「没人能写」——改写后由守护重新签发即洗白）。守护 v1.3.13 起写盘
    # 即 0600。本门独立实测文件权限位（不采信守护自述）。
    try:
        fmode = stat.S_IMODE(os.stat(state).st_mode)
    except OSError as e:
        fail(2, "状态面权限面不可证（stat 失败：%s）——不猜绿" % e)
    if fmode & 0o022:
        fail(1, "SIL 状态面落盘件权限过宽（mode=%o：同组/他人可写）——改写面开着，"
                "封条不能替代权限面（须 0600）" % fmode)
    # ⑩ 签名钥可用性对账（RT-E85②，v1.6，P4-H4 阻塞项落码）：「停摆要显式在册
    # **且有人订阅**」（台账:747 口径）——key_status 是守护 save_state 的唯一写盘点
    # （wip save_state ⑩ 同步点注释），state 非 ok ⇒ rc=1 精确红（停摆分类+恢复
    # 路径）；读数缺失/非法 ⇒ rc=2 不可证（不猜绿）。判据独立成函数（可被夹具
    # 直调负控）；⑩ 只读状态面、不取钥（⑧a 的复算借判据源函数——openbao 模
    # 式下每探针进程取钥一次，F1 口径；停摆时走 H3 的 fail(2) 口径）。
    r10, msg10 = key_status_verdict(st)
    if r10 == 1:
        fail(1, msg10)
    if r10 == 2:
        fail(2, msg10)
    gate = st.get("mirror_ro_gate")
    if not isinstance(gate, dict) or not gate:
        fail(2, "loop-state 无 mirror_ro_gate 读数——守护版本过旧或③段从未跑过，"
                "裁决产出腿状态不可证（不猜绿）")
    # ④ 机械实测交叉核验：绿不再由可改写的状态面布尔单独背书
    try:
        live = live_ro_gate()
    except Exception as e:
        fail(2, "机械实测不可得（守护在册只读门判据不可用：%s: %s）——产出腿状态"
                "不可证（不猜绿）" % (type(e).__name__, e))
    if not live:
        fail(2, "机械实测无源（守护在册镜像源枚举为空）——产出腿状态不可证（不猜绿）")
    if set(gate.keys()) != set(live.keys()):
        fail(2, "状态面源集与守护在册源集不一致（状态面=%s 在册=%s）——读数不可证"
                "（守护换源未重启/状态面被改写，不猜绿）"
                % (",".join(sorted(gate.keys())) or "无",
                   ",".join(sorted(live.keys())) or "无"))
    # 状态面内部一致性：扁平读数 vs 守护逐源读数（同一轮落盘应逐字一致）
    det = state_detailed_ro_gate(st)
    if det:
        contra = []
        for k in sorted(gate.keys()):
            d = det.get(k)
            dt = d.get("trusted") if isinstance(d, dict) else d
            if dt is None or bool(dt) != bool(gate[k]):
                contra.append(k)
        if contra:
            fail(2, "状态面自相矛盾（mirror_ro_gate 与 last_round 逐源 ro_gate 读数不一致："
                    "%s）——状态面被改写嫌疑，读数不可证（不猜绿）" % ",".join(contra))
    # ⑦ 源码版本钉对账（2026-11-03 SIL 环修复批）：状态面读数来自**在役守护载入
    # 时**的判据；本门机械实测用的是**盘上现码**的判据。两版本不一致 ⇒ 同一镜像面
    # 两套结论（两套真相并行）：2026-11-03 实证——在役守护 06:53 起跑、盘上 17:53
    # 已改、17h 未重载（在役旧判据 rw+收权⇒可信＝RT-E85④ 旁路仍开，盘上已收紧），
    # 本门报「产出腿停摆/双源拒用」而守护写盘旧口径「RT-E12①」，无人对账。
    # 处置：不可证即红（rc=2）——状态面与机械实测**不可对账**时，任何绿都是越权
    # 背书（在役守护的宽松判据才是真正在跑的那一份）。在役守护须重启方能对齐
    # （keepalive 源码版本钉判活会自动换码；本门只读、不动手）。
    try:
        disk_sha = gate_src_sha256()
    except OSError as e:
        fail(2, "判据源 sha256 不可得（%s：%s）——在役判据版本不可证（不猜绿）"
                % (GATE_SRC, e))
    stamp = st.get("daemon_src") or {}
    live_sha = stamp.get("sha256") if isinstance(stamp, dict) else None
    if not live_sha:
        fail(2, "在役守护未登记载入源码版本（状态面无 daemon_src.sha256）——在役判据"
                "版本不可证（在役码早于版本钉机制，与盘上判据两套真相可能并行，不猜绿）；"
                "须重启在役守护方能对齐（keepalive 源码版本钉判活会自动换码）")
    if live_sha != disk_sha:
        fail(2, "在役守护载入源码版本 ≠ 盘上判据源版本（在役 %s… ≠ 盘上 %s…）——同一"
                "镜像面两套判据并行，状态面读数与机械实测不可对账（不可证即红，不猜绿）；"
                "在役守护须重启以载入盘上判据（keepalive 源码版本钉判活会自动换码）"
                % (str(live_sha)[:12], disk_sha[:12]))
    # 逐源对账：绿 ⟺ 状态面记可信 ∧ 机械实测=机制性只读
    trusted, untrusted = [], []
    for k in sorted(gate.keys()):
        rec = bool(gate[k])
        me, reason = live[k]
        if rec and me:
            trusted.append(k)
        elif rec and not me:
            # v1.0 注入翻绿的那条通道：文件说可信、物理面拒用 → 产出腿实为停摆
            fail(1, "SIL 状态面与机械实测背离（%s 源：状态面记「可信」但物理实测=拒用）"
                    "——产出腿实为停摆，且状态面读数被喂假值/改写嫌疑；机械实测=%s"
                    % (k, reason))
        elif me and not rec:
            fail(1, "SIL 产出腿未恢复（%s 源：物理实测已=机制性只读，但守护状态面仍记"
                    "「拒用」——守护尚未翻转，产出未复）" % k)
        else:
            untrusted.append((k, reason))
    if untrusted:
        fail(1, "SIL 裁决产出腿停摆：全部镜像源被真实性门拒用（%s）——签名不前进、"
                "无新裁决/回写；轮次/队列/心跳等环活性读数不代表产出。恢复=把镜像"
                "目录以 ro 方式挂载（findmnt OPTIONS 含 ro）后守护下轮自动解拒"
                "——不得用 chmod 收权替代（权限位同 uid 可逆，不构成机制性只读）；"
                "机械实测=%s"
                % ("+".join(k for k, _ in untrusted),
                   "｜".join("%s: %s" % (k, r) for k, r in untrusted)))
    # ⑥ 产出腿前进断言（RT-E88 拦截机制②，v1.2 新增）：绿不止「源可信」，须另证
    # 「产出腿未停摆」——A 有活未产出（积压）/ B 空转死手（拒用持续 ∧ 长期零产出）。
    rc6, msg6 = output_leg_check(st)
    if rc6 == 1:
        fail(1, msg6)
    note6 = msg6
    print("PASS SIL 裁决产出腿（未停摆）：可信源=%s；拒用源=%s（状态面记录可信 ∧ 机械"
          "实测=机制性只读，双证齐）；%s；在役判据版本=盘上判据版本（daemon_src sha256=%s…"
          "，⑦ 版本钉对账通过）；⑧ 状态面封条验签通过且落盘件权限=%o（0600 口径：同组/"
          "他人不可写，护 v1.3.13 起）；⑨ 读出通道独立复算一致（findmnt=%s，_CS_PATH "
          "解析、不消费进程 PATH）；⑩ %s；rounds=%s commits=%s heartbeat_age=%.0fs"
          % (",".join(trusted),
             ",".join(k for k in sorted(gate.keys()) if not gate[k]) or "无",
             note6, disk_sha[:12], fmode, _resolve_system_tool("findmnt"),
             msg10, st.get("rounds"), len(st.get("commits") or []), hb_age))
    sys.exit(0)


if __name__ == "__main__":
    main()
