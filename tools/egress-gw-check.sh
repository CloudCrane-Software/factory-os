#!/usr/bin/env bash
# egress-gw-check.sh —— tailnet 共享境外出口网关巡检（计划/60 · P3）
#
# 对应 hk gost 事故的三条教训：连接量爆炸 / 日志失控 / 节点大面积失效。
# 凭据从 gov 上的 0600 文件读，全程不回显。
#
# 用法： bash tools/egress-gw-check.sh
# 退出码：0 全绿 / 1 有告警
set -uo pipefail

GW_IP="${GW_IP:-gov-host.invalid}"
GW_ADDR="${GW_ADDR:-root@$GW_IP}"
PROBE_URLS=("https://github.com" "https://huggingface.co" "https://api.x.ai")
rc=0

hr() { printf '%s\n' "──────────── $* ────────────"; }

# ① 服务与监听面
hr "① 服务与监听面"
ssh -o BatchMode=yes -o ConnectTimeout=10 "$GW_ADDR" '
  printf "  状态     : %s  (重启次数 %s)\n" "$(systemctl is-active egress-gw)" "$(systemctl show egress-gw -p NRestarts --value)"
  printf "  7890 绑定: %s\n" "$(ss -tln 2>/dev/null | awk "/:7890/{printf \$4}")"
  printf "  9090 绑定: %s\n" "$(ss -tln 2>/dev/null | awk "/:9090/{printf \$4}")"
  printf "  日志级别 : %s\n" "$(grep ^log-level /opt/egress-gw/config.yaml)"
  printf "  日志大小 : %s\n" "$(du -sh /opt/egress-gw/*.log 2>/dev/null | cut -f1 || echo 无文件日志)"
' || { echo "  ✗ gov 不可达"; rc=1; }

# 绑定面硬约束：7890 只能在 tailnet 地址，9090 只能在回环
bind7890=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$GW_ADDR" 'ss -tln 2>/dev/null | awk "/:7890/{print \$4}"' 2>/dev/null | tr -d ' ')
[ "$bind7890" = "$GW_IP:7890" ] && echo "  ✓ 7890 仅绑 tailnet" || { echo "  ✗ 7890 绑定异常: '$bind7890'"; rc=1; }
bind9090=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$GW_ADDR" 'ss -tln 2>/dev/null | awk "/:9090/{print \$4}"' 2>/dev/null | tr -d ' ')
[ "$bind9090" = "127.0.0.1:9090" ] && echo "  ✓ 9090 仅绑回环" || { echo "  ✗ 9090 绑定异常: '$bind9090'"; rc=1; }

# ② 节点存活（真实发起请求，不是看 alive 标志）
hr "② 节点真实可用率"
ssh -o BatchMode=yes -o ConnectTimeout=15 "$GW_ADDR" 'python3 - <<PY
import json,urllib.request,urllib.parse,concurrent.futures as cf
API="http://127.0.0.1:9090"
d=json.load(urllib.request.urlopen(API+"/proxies"))
tg=[n for n,v in d["proxies"].items() if isinstance(v,dict) and v.get("type")=="Trojan"]
def t(n):
    u=API+"/proxies/%s/delay?timeout=6000&url=http%%3A%%2F%%2Fwww.gstatic.com%%2Fgenerate_204"%urllib.parse.quote(n)
    try: return (n, json.load(urllib.request.urlopen(u,timeout=12)).get("delay"))
    except Exception: return (n, None)
with cf.ThreadPoolExecutor(16) as ex: res=list(ex.map(t,tg))
ok=sorted([r for r in res if r[1]], key=lambda x:x[1])
print("  可用 %d / %d   当前出口: %s" % (len(ok), len(tg),
      d["proxies"].get("AUTO-全组",{}).get("now")))
for n,ms in ok[:5]: print("    %-26s %sms" % (n[:26], ms))
PY' 2>/dev/null || { echo "  ✗ 节点查询失败"; rc=1; }

# ③ 连通性（无凭据必须被拒 = 未被裸奔）
hr "③ 连通性与认证"
CRED=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$GW_ADDR" 'cat /opt/egress-gw/gw-cred 2>/dev/null' 2>/dev/null)
if [ -z "$CRED" ]; then
  echo "  ✗ 取不到网关凭据"; rc=1
else
  noauth=$(curl -s -o /dev/null -w '%{http_code}' -m 12 -x "http://$GW_IP:7890" https://github.com 2>/dev/null)
  [ "$noauth" = "000" ] && echo "  ✓ 无凭据被拒（未裸奔）" || { echo "  ✗ 无凭据竟然通过（HTTP $noauth）—— 认证失效，立即排查"; rc=1; }
  for u in "${PROBE_URLS[@]}"; do
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 25 -x "http://$CRED@$GW_IP:7890" "$u" 2>/dev/null)
    case "$code" in 200|301|302|421) printf "  ✓ %-28s %s\n" "$u" "$code";;
                   *) printf "  ✗ %-28s %s\n" "$u" "$code"; rc=1;; esac
  done
  exitip=$(curl -s -m 20 -x "http://$CRED@$GW_IP:7890" 'http://ip-api.com/json/?fields=query,country&lang=zh-CN' 2>/dev/null)
  echo "  出口: $exitip"
  unset CRED
fi

hr "结论"
[ "$rc" = 0 ] && echo "  ✓ 全绿" || echo "  ✗ 有告警项，见上"
exit $rc
