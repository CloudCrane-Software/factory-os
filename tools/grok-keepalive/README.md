# grok-keepalive runbook —— D-135 grok 路径 A 前置②：token 续期机制

卡面正本：CloudCrane-Software/factory-os#150（债号 D-135，台账`计划/阶段欠账台账.md` 第一批真锚段）。
本目录 = 卡面交付 2（保活机制，P2 选型 (b) 形制）：anolis `systemd --user` unit+timer，
定时跑保活工人 `tools/grok-auth-probe.py --renew`，使 `~/.grok/auth.json` 保持新鲜。

## 1. 选型记录（按探针读数二选一，P4 禁假绿）

卡面 P2 二选一：(a) 网关实现 OIDC refresh；(b) anolis `systemd --user` 定时跑 CLI 保活。
探针读数（2026-11-07，anolis 实跑，详见留痕件`30-工件/真锚喂入-20261107/留痕/D-135-token续期机制.md`）：

| 读数项 | 值 | 判据 |
|---|---|---|
| issuer（auth.json `oidc_issuer` 条目） | `https://auth.x.ai` | 字段名/时间戳只读，值零取 |
| TTL 观察值 | 21600s（6h，create_time→expires_at 实测差） | 与卡面"TTL 6h 观察值"一致 |
| access token 状态 | 已过期（expires_at 2026-11-05T11:55Z，跑读数时已过约 2 天） | expires_at − now < 0 |
| refresh 端点可用性 | **不可用**（connect timeout） | anolis 直连、SOCKS5 hk-gateway、gov 代理三路皆不可达 |
| refresh_token 当前有效性 | **不可证**（端点不可达 ⇒ 试转未发生，禁假设有效） | P4 纪律 |

选型结论：**(b) systemd --user 保活**。(a) 网关 refresh 模块依赖同一 issuer 端点（同样不可达），
且卡面明禁本卡越权建网关（P1 原型另卡/运营者点头项）。(b) 与网关原型解耦：先把保活机制落地，
端点恢复（路径 A 前置①，运营者再裁事项）后机制即自动生效，期间失败路径 fail-closed+告警。

## 2. 机制形态

```
grok-keepalive.timer  ──每 30 分钟──▶  grok-keepalive.service（oneshot）
                                          └─▶ python3 -I grok-auth-probe.py --renew
                                                ├─ 新鲜（余量 >30min）⇒ no-op，退出 0
                                                ├─ 临期/过期 ⇒ discovery → refresh grant 试转
                                                │     ├─ 成功 ⇒ 原子回写 auth.json（先 0600 备份）
                                                │     │           ＋ last-renew.json ＋ freshness.json
                                                │     └─ 失败 ⇒ fail-closed：auth.json 零改动、
                                                │               退出码 4、alerts.jsonl 落一条告警
                                                └─ 告警内容禁含凭据形态（只记失败类/端点/HTTP 语义）
```

- 节拍 30 分钟 ≪ TTL 6h；`Persistent=true` 补跑关机期间错过的窗口。
- 续期余量 30 分钟（`RENEW_MARGIN_S`，探针内常量）。
- 请求侧 fail-closed 闸：`python3 -I grok-auth-probe.py --check`（0=新鲜 / 3=过期 / 2=不可证），
  供网关/请求腿在派发前调用（P5 接线选型归运营者，本卡只提供调用面）。

## 3. 安装（anolis）

```bash
# 在 factory-os 检出树上（检出含 tools/grok-auth-probe.py）：
bash tools/grok-keepalive/install.sh            # 安装并启用 timer
bash tools/grok-keepalive/install.sh --uninstall
```

安装面（全部为新增件，零改既有 grok 配置）：

| 路径 | 说明 |
|---|---|
| `~/.local/opt/grok-keepalive/grok-auth-probe.py` | 保活工人（自本仓复制，0755） |
| `~/.config/systemd/user/grok-keepalive.service` | oneshot 服务 |
| `~/.config/systemd/user/grok-keepalive.timer` | 30 分钟节拍定时器 |
| `~/.local/state/grok-keepalive/` | 状态目录 0700：freshness.json / alerts.jsonl / last-renew.json |

linger 已开（`loginctl show-user -p Linger` = yes），用户管理器随系统常驻。

## 4. 验证（验收命令集逐条）

```bash
python3 -I tools/grok-auth-probe.py --selftest                                   # rc=0
bash -n tools/grok-keepalive/install.sh                                          # rc=0
grep -cE "OnCalendar|Persistent=true" tools/grok-keepalive/grok-keepalive.timer  # ≥1
ls 30-工件/真锚喂入-20261107/留痕/D-135-token续期机制.md                          # 留痕件在场
ssh anolis "systemctl --user is-active grok-keepalive.timer"                      # active
grep -c "续期成功" 30-工件/真锚喂入-20261107/留痕/D-135-token续期机制.md            # ≥1
grep -c "告警"    30-工件/真锚喂入-20261107/留痕/D-135-token续期机制.md            # ≥1
```

注意：`ssh anolis` 直连（tailnet 地址）由 tailscale SSH 终止，会话无 PAM 环境
（无 XDG_RUNTIME_DIR ⇒ `systemctl --user` 连不上 bus）。验收时经本机跳板落 anolis
真实 sshd（127.0.0.1:22）执行，`systemctl` 读数为用户管理器真值。

## 5. 失败路径（fail-closed + 告警，禁静默）

- 端点不可达/试转失败 ⇒ 工人退出码 4，`auth.json` sha256 前后一致（亲证项），
  `freshness.json` 记 `fresh=false` + 失败类，`alerts.jsonl` 追加一条：
  `{"schema":"af.grok-keepalive.alert.v1","ts":…,"reason_class":…,"endpoint":…,"http_status":…,"detail":…}`
- 告警点名失败类（如 `endpoint_unavailable` / `token_http_400` / `dns_failure`），
  内容禁含凭据形态（无 AT/refresh 值、无完整 JWT、无长度以外的 token 形态）。
- 窗口内请求侧：`--check` 返回 3/2 ⇒ 调用方 fail-closed 禁派（与厂内门禁家族一致）。

## 6. 凭据纪律（卡面 P1，最高）

- AT/JWT/refresh 值只进工人内存（试转请求体）；零回显、零进日志、零进 argv、零进读数 JSON。
- 读数/告警只记：条目字段名、create_time/expires_at、HTTP 语义、token 形态长度。
- 工人对 `~/.grok/auth.json` 的唯一写路径 = 续期成功后的原子回写（0600 备份 + 临时件
  fsync + rename）；失败路零改动。这是"保活使 auth.json 保持新鲜"的机制本体。
- 本 runbook 与探针脚本经 bot-scrub 同内核（mirror-disclose.sh scan_text）零命中。

## 7. 边界（本卡不做什么）

不建回环网关本体（P1 原型另卡）；不做沙箱侧联调（P3）、反滥用回归（P4）、
接线选型（P5 归运营者）；不修 gov 出口/刷新 mihomo 订阅（路径 A 前置① = 再裁事项）；
不碰 tokenrhythm 免费档链路。禁改面：anolis 在役 grok 配置与 `~/.grok/`（探针只读）、
`tools/wf-offload-grok.sh`、判官/门/判据面、在飞件（planner.yml / planner-core.yml）。
