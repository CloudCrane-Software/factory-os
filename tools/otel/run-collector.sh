#!/usr/bin/env bash
# run-collector.sh — OTel 非关键 lane collector 常驻启动器（批3 amvp 常驻化）
#
# 职责（只新增常驻面，不改五守护本体、不动 tools/otel/ 既有交付件）：
#   ① 现取 CH 凭据进 otelcol 子进程 env（零明文：不落盘、不进本脚本输出、不进本脚本
#     environ——DEB-2c 2026-10-29：口令不经 export，redact 脱敏走调用点参数传给单个
#     子进程，用后 unset）
#   ② 从交付配置 tools/otel/otelcol-config.yaml 派生运行时配置（受控替换，锚点断言：
#      storage 目录 / 绑定地址 / 内部遥测口三条，交付配置本体零改动）
#   ③ nohup+setsid 起 otelcol，带 PID 文件与日志轮转（copytruncate，常驻安全）
#   ④ 起后验活：进程存活 + OTLP 口可收（空体 400/415 即接收器在位）
#
# 凭据链（与 tools/otel/ch_client.py / otel-e2e-check.py 同口径，逐候选 SELECT 1 实验）：
#   1) env MES_CH_URL / OTEL_CH_URL（http://user:pass@host:port 整体形式）
#   2) openBao kv/data/company/otlp   ← 工单点名路径；字段名只打名，无 user/password 即跳过
#      （2026-10-29 实测：该路径 404/仅含 caddy bearer_token，非 CH 凭据——详见 otelp-report.md）
#   3) openBao kv/data/opch/obs/clickhouse-otel（ch_client.py:25 登记的 CH 凭据位；
#      2026-10-28 实测认证 mingda:15221 失败=D-3 降级；本脚本保留为显式覆盖位并复验）
#   4) 0600 凭据文件 ~/.config/mes-ch/url（F-11 既有链，当前生效链）
#   5) 缺省端点 http://mes-host.invalid:15221（无凭据→显性失败，不静默写错库）
#
# 用法：
#   tools/otel/run-collector.sh [start|restart|status]   # 缺省 start
#   tools/otel/stop-collector.sh                          # 停止（另一件）
# 环境变量（均有缺省）：OTELCOL_BIN / OTEL_BIND_ADDR / OTEL_RUNTIME / OTEL_WS
# 回滚：停进程（stop-collector.sh）+ 删 $OTEL_RUNTIME；交付配置与既有件零改动。
set -euo pipefail

WS="${OTEL_WS:-$HOME/workspace/agent黑灯工厂}"
OTEL_DIR="$WS/tools/otel"
CFG_SRC="$OTEL_DIR/otelcol-config.yaml"
RUNTIME="${OTEL_RUNTIME:-$HOME/otelcol-runtime}"
LOGDIR="$RUNTIME/logs"
PIDFILE="$RUNTIME/otelcol.pid"
STORAGE="$RUNTIME/storage"
LOG="$LOGDIR/collector.log"
BIND="${OTEL_BIND_ADDR:-pandev-host.invalid}"        # 本机 tailnet IP（hostname -I 实测）；交付配置 anolis-host.invalid=anolis 部署位
MAX_LOG_BYTES="${OTEL_MAX_LOG_BYTES:-8388608}"   # 8 MiB 轮转阈值
LOG_KEEP="${OTEL_LOG_KEEP:-3}"                    # 保留代数

log() { echo "[$(date '+%F %T')] run-collector: $*"; }
die() { log "FAIL: $*"; exit 1; }

# ---------------------------------------------------------------- 二进制定位
find_bin() {
  for c in "${OTELCOL_BIN:-}" "$HOME/otelcol-build/build/otelcol" \
           "$HOME/otelcol-build/bin/otelcol" "$OTEL_DIR/bin/otelcol"; do
    [ -n "$c" ] && [ -f "$c" ] && [ -x "$c" ] && { echo "$c"; return 0; }
  done
  return 1
}

# ---------------------------------------------------------------- 日志轮转（copytruncate）
# 常驻进程持 fd 追加写：复制后截断（cp+truncate），不换 fd、不丢后续行；
# 启动时轮转一次 + 常驻期由边车 emit-sidecar.py 每周期驱动（同一逻辑）。
rotate_log() {
  local f="$1" sz i
  [ -f "$f" ] || return 0
  sz=$(stat -c%s "$f" 2>/dev/null || echo 0)
  [ "$sz" -ge "$MAX_LOG_BYTES" ] || return 0
  i=$LOG_KEEP
  while [ "$i" -gt 1 ]; do
    [ -f "$f.$((i-1))" ] && mv -f "$f.$((i-1))" "$f.$i"
    i=$((i-1))
  done
  cp -f "$f" "$f.1" && : > "$f"
  log "日志轮转: $f (${sz}B ≥ ${MAX_LOG_BYTES}B) → $f.1（保留 ${LOG_KEEP} 代）"
}

# ---------------------------------------------------------------- 凭据现取（零明文）
# stdout 四行 = 来源标签 / ENDPOINT / USERNAME / PASSWORD（只进 shell 变量与 otelcol env）；
# stderr 只写候选标签、HTTP 码与字段名级诊断。口令值永不出现在任何输出。
resolve_creds() {
  OTEL_DIR="$OTEL_DIR" python3 - <<'PY'
import json, os, sys, urllib.error, urllib.request
sys.path.insert(0, os.environ["OTEL_DIR"])
import ch_client  # noqa: E402  既有凭据链真源（P1-4 单一真源不复制）

BAO = "http://gov-host.invalid:8200"
TOKEN_FILE = os.path.expanduser("~/.local/share/openbao-escrow/.root-token")


def bao_fields(path):
    """openBao kv/data/<path> → dict；任何失败返回 None（stderr 只记 HTTP 码/字段名）。"""
    try:
        with open(TOKEN_FILE) as f:
            token = f.read().strip()
    except OSError:
        print(f"bao: token 文件不可读（{TOKEN_FILE}）", file=sys.stderr)
        return None
    req = urllib.request.Request(f"{BAO}/v1/kv/data/{path}",
                                 headers={"X-Vault-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"bao: kv/data/{path} → HTTP {e.code}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"bao: kv/data/{path} 不可达 {e.__class__.__name__}", file=sys.stderr)
        return None
    return (d.get("data") or {}).get("data") or {}


def split_url(url):
    scheme, rest = url.split("://", 1)
    userinfo, host = rest.split("@", 1)
    user, pw = userinfo.split(":", 1)
    return f"{scheme}://{host}", user, pw


def verify(url):
    try:
        ch_client.query("SELECT 1", url=url)
        return True
    except Exception as e:
        print(f"verify: {str(e)[:140]}", file=sys.stderr)
        return False


cands = []   # (来源标签, endpoint, user, password)

for var in ("MES_CH_URL", "OTEL_CH_URL"):
    v = os.environ.get(var)
    if v and "@" in v:
        ep, u, p = split_url(v)
        cands.append((f"env:{var}", ep, u, p))
        break

f = bao_fields("company/otlp")          # 工单点名路径（字段名只打名）
if f is not None:
    if "user" in f and "password" in f:
        cands.append(("bao:company/otlp", ch_client.DEFAULT_ENDPOINT, f["user"], f["password"]))
    else:
        print(f"bao: kv/data/company/otlp 字段名={sorted(f)}（无 user/password，非 CH 凭据，跳过）",
              file=sys.stderr)

f = bao_fields("opch/obs/clickhouse-otel")   # ch_client.py:25 登记的 CH 凭据位（D-3 复验）
if f and "user" in f and "password" in f:
    cands.append(("bao:opch/obs/clickhouse-otel", ch_client.DEFAULT_ENDPOINT,
                  f["user"], f["password"]))

try:
    with open(ch_client.MES_CH_FILE) as fh:
        u = fh.read().strip()
    if "@" in u:
        ep, us, pw = split_url(u)
        cands.append((f"file:{ch_client.MES_CH_FILE}", ep, us, pw))
except OSError:
    pass

for label, ep, u, p in cands:
    print(f"候选 {label} 验证中…", file=sys.stderr)
    if verify(f"http://{u}:{p}@{ep.split('://', 1)[1]}"):
        print(label)          # stdout 首行=来源标签（只含路径/环境名，无值）
        print(ep)
        print(u)
        print(p)
        sys.exit(0)
    print(f"候选 {label} 验证失败，降级下一候选", file=sys.stderr)

print("凭据链全部候选验证失败（env→bao company/otlp→bao opch→0600 F-11）", file=sys.stderr)
sys.exit(3)
PY
}

# ---------------------------------------------------------------- 存活判定（防 PID 回收误杀）
proc_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }
proc_is_otelcol() {
  [ -r "/proc/$1/cmdline" ] && tr '\0' ' ' < "/proc/$1/cmdline" | grep -q "otelcol"
}

otlp_alive() {
  python3 - "$1" <<'PY'
import sys, urllib.error, urllib.request
ep = sys.argv[1]
try:
    req = urllib.request.Request(ep + "/v1/traces", data=b"{}",
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=2).read()
    print("ok")
except urllib.error.HTTPError as e:
    print("ok" if e.code in (400, 415) else f"http{e.code}")
except Exception as e:
    print(f"err:{e.__class__.__name__}")
PY
}

redact() {   # 日志尾脱敏（DEB-2c：口令由调用点作 $1 传入，只进本函数拉起的这一个
            # python 子进程 env——不经本脚本 environ、不进 argv/输出；无口令原样透传）
  CH_PASS="${1:-}" python3 -c '
import os, sys
s = sys.stdin.read()
p = os.environ.get("CH_PASS") or ""
sys.stdout.write(s.replace(p, "▉▉▉") if p else s)'
}

# ================================================================ 子命令
cmd_status() {
  if [ -f "$PIDFILE" ] && proc_alive "$(cat "$PIDFILE")"; then
    local pid; pid=$(cat "$PIDFILE")
    if proc_is_otelcol "$pid"; then
      log "运行中 pid=$pid bind=$BIND:4317/4318 OTLP探活=$(otlp_alive "http://$BIND:4318")"
      return 0
    fi
    log "PID $pid 存活但非 otelcol（PID 回收？）——请人工核对"; return 1
  fi
  log "未运行（pidfile 缺失或进程不在）"; return 1
}

cmd_start() {
  [ -f "$CFG_SRC" ] || die "交付配置不在: $CFG_SRC"

  # 已运行则拒双启（restart 走显式重启）
  if [ -f "$PIDFILE" ] && proc_alive "$(cat "$PIDFILE")" && proc_is_otelcol "$(cat "$PIDFILE")"; then
    log "已在运行 pid=$(cat "$PIDFILE")（双启拒绝；重启请用 restart）"
    cmd_status
    return 0
  fi

  # ---- ① 凭据现取（stdout 捕获进变量，不落盘不回显） ----------------------
  local creds src ep user pass
  if ! creds=$(resolve_creds); then
    die "CH 凭据解析/验证失败（链上诊断见上；口令零明文）"
  fi
  if [ "$(printf '%s\n' "$creds" | wc -l)" -ne 4 ]; then
    die "凭据解析输出形状异常（非 4 行）——中止，防半截口令进 env"
  fi
  { read -r src; read -r ep; read -r user; read -r pass; } <<<"$creds"
  unset creds
  # DEB-2c（2026-10-29 义务收口批）：删 export CH_PASS。原实现把口令副本塞进本脚本
  # environ——/proc/<pid>/environ 同机可读、且被后续全部子进程（tail/grep/sed/
  # python3 探活）无条件继承，属多余暴露面。脱敏改由调用点把口令作参数只传给
  # redact 的那一个 python 子进程（子进程隔离，见 redact()）；otelcol 仍走既有
  # 命令前缀 inline env（MES_CH_PASSWORD=…），不经本脚本 environ。
  log "CH 凭据现取成功（来源=$src；端点=$ep 用户=$user；口令只进 otelcol 子进程 env 与 redact 脱敏子进程）"

  # ---- ② 派生运行时配置（受控替换 + 锚点断言，与 e2e-check 同规则） --------
  local bin; bin=$(find_bin) || die "找不到 otelcol 二进制（OTELCOL_BIN/~/otelcol-build/build/otelcol）"
  local n_storage n_g n_h
  n_storage=$(grep -c "/data/otelcol/storage" "$CFG_SRC" || true)
  n_g=$(grep -c "anolis-host.invalid:4317" "$CFG_SRC" || true)
  n_h=$(grep -c "anolis-host.invalid:4318" "$CFG_SRC" || true)
  [ "$n_storage" -ge 2 ] || die "交付配置 storage 锚 <2（主+compaction，实 $n_storage）——配置漂移？"
  [ "$n_g" -eq 1 ] && [ "$n_h" -eq 1 ] || die "交付配置 bind 锚异常（4317=$n_g 4318=$n_h）——配置漂移？"
  mkdir -p "$RUNTIME" "$LOGDIR" "$STORAGE"
  local cfg="$RUNTIME/otelcol-config.yaml"
  # 常驻件第三条派生（resident-only，交付配置零改动）：
  #   service.telemetry.metrics.level: none —— 常驻 collector 不占 127.0.0.1:8888
  #   （内部 Prometheus 遥测口）。本厂 lane 无 Prometheus 抓取面（交付配置本就只配
  #   telemetry.logs）；且 otel-e2e-check.py 每轮自起的临时 collector 用缺省 8888，
  #   两个实例同主机并存时免端口互斥（2026-10-29 实证：缺省配置双实例=8888 bind 冲突，
  #   e2e C3 起不来）。锚点断言：level: info 行唯一在位，缺即视为配置漂移拒启。
  grep -c "^      level: info$" "$CFG_SRC" | grep -qx 1 \
    || die "交付配置 telemetry.logs.level 锚异常（非唯一）——配置漂移？"
  sed -e "s|/data/otelcol/storage|$STORAGE|g" \
      -e "s|anolis-host.invalid:4317|$BIND:4317|" \
      -e "s|anolis-host.invalid:4318|$BIND:4318|" \
      -e "/^      level: info$/a\\    metrics:\\n      level: none" \
      "$CFG_SRC" > "$cfg"
  grep -q "^    metrics:$" "$cfg" && grep -q "^      level: none$" "$cfg" \
    || die "派生配置缺 telemetry.metrics.level: none 块——替换规则漂移？"
  # 后置断言：派生件不得残留部署位绑定锚（注释里的 anolis-host.invalid 字样不算，只断 endpoint/storage 实键）
  if grep -qE "100\.64\.0\.7:431[78]|/data/otelcol/storage" "$cfg"; then
    die "派生配置残留部署位绑定锚（anolis-host.invalid:431x / /data/otelcol/storage）——替换规则漂移？"
  fi
  grep -q "$STORAGE" "$cfg" && grep -q "$BIND:4317" "$cfg" && grep -q "$BIND:4318" "$cfg" \
    || die "派生配置缺本机锚（storage/bind）——替换规则漂移？"

  # ---- ③ validate（真实 env；断言语义同 e2e C2b） -------------------------
  if ! MES_CH_ENDPOINT="$ep" MES_CH_USERNAME="$user" MES_CH_PASSWORD="$pass" \
       "$bin" validate "--config=$cfg" >"$LOGDIR/validate.log" 2>&1; then
    tail -5 "$LOGDIR/validate.log" | redact "$pass"
    die "validate 失败（详见 $LOGDIR/validate.log）"
  fi
  log "validate OK（$cfg；storage=$STORAGE bind=$BIND:4317/4318）"

  # ---- ④ 轮转 + nohup/setsid 常驻起 --------------------------------------
  rotate_log "$LOG"
  : >> "$LOG"
  log "启动 otelcol: bin=$bin cfg=$cfg pidfile=$PIDFILE log=$LOG"
  MES_CH_ENDPOINT="$ep" MES_CH_USERNAME="$user" MES_CH_PASSWORD="$pass" \
    setsid nohup "$bin" "--config=$cfg" >>"$LOG" 2>&1 &
  local pid=$!
  echo "$pid" > "$PIDFILE"

  # ---- ⑤ 验活：进程存活 + OTLP 口可收（最多 10s） ------------------------
  local ok="err" i
  for i in $(seq 1 50); do
    sleep 0.2
    proc_alive "$pid" || break
    ok=$(otlp_alive "http://$BIND:4318")
    [ "$ok" = "ok" ] && break
  done
  if [ "$ok" = "ok" ] && proc_alive "$pid" && proc_is_otelcol "$pid"; then
    log "存活验证通过 pid=$pid OTLP http://$BIND:4318 可收（空体 400/415=接收器在位）"
    log "storage=$STORAGE | 日志=$LOG（轮转阈值 ${MAX_LOG_BYTES}B / 保留 ${LOG_KEEP} 代）"
    unset pass   # DEB-2c：用后即清（shell 变量副本；environ 副本已删，见①）
    return 0
  fi
  log "启动失败（otlp=$ok pid_alive=$(proc_alive "$pid" && echo yes || echo no)）——日志尾："
  tail -30 "$LOG" | redact "$pass"
  unset pass   # DEB-2c：用后即清（失败路径同）
  kill "$pid" 2>/dev/null || true
  rm -f "$PIDFILE"
  return 1
}

cmd_restart() {
  "$WS/tools/otel/stop-collector.sh" || true
  sleep 1
  cmd_start
}

case "${1:-start}" in
  start)   cmd_start ;;
  restart) cmd_restart ;;
  status)  cmd_status ;;
  *) echo "用法: $0 [start|restart|status]" >&2; exit 2 ;;
esac
