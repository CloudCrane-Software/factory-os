#!/usr/bin/env python3
"""factory-keepalive.py — 黑灯工厂守护进程的守护（keepalive 常驻，30s 一轮）。

【2026-10-26 §三-2 退役改造（ADR-008，运营者裁决 B·放弃 D1/D3 全量臂并退役）】
旧 bench 链（factory-sched/mcode-dispatch/cb-run/ch-mes-local 锚/anolis-proxy-8124 等）
已退役，本脚本看护清单收敛为观察期 5 对象（2026-10-29 循环产线批新增 self-improve-loop）：

  watch        python3 tools/factory-watch.py（判据不变：进程在+watch-state.json<300s）
  dash         python3 -m http.server 8790（看板，判据=进程在）
  af-execline  af 统一执行面判活（订单驱动非守护）：af-order/af-execline 进程在场
               或 WS/af-state/orders/ 最近订单 ledger 心跳<72h；空闲=amber 报警不拉起
  mes-ch       mingda MES（mes-host.invalid:15221）查询级连通探活（原 ch-mes-local 探针
               原样复用，仅更名登记）；失联=四类告警码只报警不拉起
  higress      LLM 网关（higress-host.invalid:8080）HTTP 判活探针（D-114/factory-os#82，
               夜轨C2 红队分诊 M8 收口批 2026-11-08；GET / 欢迎页 200=活签名，
               env AF_HIGRESS_TARGET 可覆）；失联=amber higress-down 1800s 去重
               只报警**不拉起**——gov 保留资产（AGENT.md 纪律 2），重启/改动须
               30-遗产处置.md 授权面
  self-improve-loop  python3 tools/self-improve-loop.py（自改进循环产线守护，600s 周期；
               判据同 watch 同构：进程在+状态观测/loop-state.json mtime<300s；守护带
               全寿命 60s 心跳重写 state（轮周期 600s>300s 判据，无心跳会被反复误判
               拉起——2026-10-29 实测后加）；STOP 熔断轮同样记账故不会因熔断
               被判失联）

DEB-3（2026-10-30 产线续能批）扩容：本机五守护（router/scheduler/status-push/
emit-sidecar/self-improve-loop）入 keepalive watch 清单。判据统一为「进程在 +
（状态文件 mtime<阈值 **或** 日志尾 mtime<阈值）」——双信号 OR 判活：
  · 状态文件：各守护自己的状态产物（router=kb-seed/sandbox/.router-state.json、
    scheduler=状态观测/factory-scheduler-state.json、status-push=（无独立状态文件，
    以日志尾为状态面）、emit-sidecar=状态观测/otel-sidecar.json、
    self-improve-loop=状态观测/loop-state.json）；
  · 日志尾：各守护自己的日志文件 mtime（router=状态观测/event-router.log、
    scheduler=状态观测/factory-scheduler.log、status-push=状态观测/status-push.log、
    emit-sidecar=状态观测/otel-sidecar.log、self-improve-loop=状态观测/self-improve-loop.log）；
  · OR 而非 AND 的理由（实测依据，勿改回 AND）：本机五守护的「写盘节奏」差异极大——
    router 一轮 poll_verify_reports 要 ssh 遍历 gov 报告目录（实测单轮 995–1226s，
    状态文件与日志尾可同时 >300s 而进程健康），scheduler 单轮含 anolis/gov 多路 ssh
    可达 1258s，status-push 一轮可达 119s，emit-sidecar 30s，self-improve-loop 60s。
    若用 AND 判据，router/scheduler 会被系统性误杀（对活进程假阳性 >0，违反验收）；
    OR 判据下任一信号新鲜即判活，只有「进程在 + 两信号同时僵死」才判死。
  · 阈值逐守护标定（实测校准全文见 计划/研究组/产线续能批-20261030/DEB3-判据校准.md）：
    status-push/emit-sidecar/self-improve-loop = 300s（实测写盘 ≤119s/41s/60s，留 2.5–7×
    余量）；scheduler = 2400s（实测单轮 p99=784s/max=1258s）；router = 3600s（实测单轮
    995–1226s 且 gov 报告目录持续增长，轮长随之线性变长——阈值随实测留足余量）。
  · 拉起宽限（grace）：判活宽限期只看「进程在不看新鲜度」，取各守护首轮写盘时间的上界
    （router/scheduler=1800s，status-push=300s，emit-sidecar=120s，self-improve-loop=150s）——
    宽限内进程不在仍判死并拉起（拉起节奏不受宽限影响）。
  · 拉起命令一律用各守护「在役启动行」（见 LAUNCH_PLAN），不另造姿势：cwd=WS、
    stdout/stderr 追加各自日志文件、setsid 脱离（与在役进程的 fd/1 落点逐字一致）。
  · 单实例纪律：五守护里 self-improve-loop 自带 pidfile 守卫；router/scheduler/
    status-push/emit-sidecar 无守卫——keepalive 拉起前先清该守护的残留进程（同 argv
    basename 精确匹配，不用 pgrep -f 防自匹配），避免双实例并发写同一状态文件；且每轮
    发现同守护多实例时保留最新、杀掉其余（收敛到恰好一实例）。

DEB-7（2026-10-31 义务批）扩容：quota-governor 入 watch 清单（本机第六守护）。
  · 根因：quota-governor 无常驻写者（仅巡检 hourly 被调），两次调用间 quota.json
    读数老化可达 ~60min，配额闸（factory-scheduler QUOTA_STALE=600s）据此误判
    fail-closed——EXP-2 B2 臂 2026-10-31 00:06 实证被误跳。
  · 判据：进程在（/proc argv 精确匹配 tools/quota-governor.py **且子命令=daemon**）
    + 状态观测/quota.json mtime<600s。子命令 token 是必需的——一次性 poll 与常驻
    daemon 同脚本名，只认脚本名会把手动 poll 变成「进程在」的假阳性。
  · AND 而非 OR：governor 的两个信号同源（每轮同写 quota.json 与自己的日志），
    OR 判据会让「进程活但 quota.json 停写」逃过判活（正是本次要治的病）；
    故该守护走 and_mode=state 新鲜 AND（日志尾仅作参考）。
  · 阈值 600s 与配额闸 stale 阈同值；写盘密度（daemon 60s 一轮，远严于「≥300s
    一轮」下界）恒满足该阈。
  · 拉起宽限 grace=120s：governor 首轮写盘含一次 ssh anolis 取 token（超时上限
    60s），首写最坏 ~60s，120s 覆盖。
  · 单实例纪律：governor 自带 pidfile 守卫（tools/.quota-governor.pid，活进程即拒
    双开、陈旧 pidfile 自动接管），叠加 keepalive 侧的多实例收敛。

DEB57（2026-11-01 误杀复盘）：quota-governor 判活证据链自相矛盾一次，两处收敛。
  · 事实链：01:20:42 判「进程不在」→拉起 1839901（governor 日志 61s 节奏证实老 daemon
    死于 01:20:01–01:20:42，该次处置合法）；01:25:50 却读得 state_age=7201s（mtime=
    23:25:49）与 log_age=2s 同轮并存，而日志尾 [01:25:48] poll ok ⇒ poll() 已走完
    os.replace(quota.json)（quota-governor.py:125→206），mtime 此刻必新鲜——stat 假读数
    与 61s 写盘节奏互斥（ext4 本地盘、写者/judge 同路径同根、全仓无第二写者、无时钟跳变
    证据，根因未钉死）→误杀在役 1839901；01:26:50 防抖 ALARM「进程仍死」系静态文案，
    与活体不符（1848178 存活且持续写盘）。
  · 收敛①：check_guard and_mode 加「判读矛盾门」（spec.log_ok_token）——state 假死读数
    撞上日志尾 poll ok（=状态面必已重写）时改判存活、只记疑不处置，不杀在役不烧防抖窗；
    真病（进程活但停写）日志尾=poll error、不含 ok token，照旧判死拉起，对该病强度不变。
  · 收敛②：Debounce 超限 ALARM 文案去掉「进程仍死」断言——报警时进程是否仍死以判活
    为准，而该轮判活本身可能正是假读数。

RT 收口批（2026-11-02）：gov 公网门户入 watch 清单（第八看护对象，首个远程对象）。
  · 背景：门户（jobs.hkmingdajiaoyu.com 宿主 gov-host.invalid:/opt/company/af-jobs/
    af-jobs-portal.py，监听 8090）在 gov 宿主是裸进程（PPID=1，无 systemd/supervisor/
    cron/at），gov 无任何守护面；本清单原不含门户、watch 亦无门户探针——2026-11-02
    09:02 门户重启未带 AF_JOBS_DATA 板面全零 20+min（计划/变更日志.md:40794），
    alarms.log 全窗零门户条目：无守护+无告警两缺口并存。
  · 与 mes-ch「跨机只报警不拉起」的边界：mes-ch 对端（mingda MES）非本厂所有物；
    门户宿主 root 可达、启动行已脚本化（gov:/opt/company/af-jobs/start-portal.sh，
    AF_JOBS_DATA 导出内嵌——11-02 事故修复物本身），且与 all-gates L5
    deploy-consistency-probe 同一宿主同一对账域——自动拉起属本厂交付面自愈，非越权。
  · 判据三签名：①/healthz 200 且 {"ok":true}；②/tasks.json?status=open&limit=1 信封
    可解析（total:int 或旧版裸数组）；③gov 在役进程 /proc/<pid>/environ 含
    AF_JOBS_DATA=（11-02 事故根因签名：wrong-data-dir 下 ①② 照样全绿——进程在、
    板面空）。①②任一败=服务面死；①②全过+③败=进程在但数据面脱锚；两者都拉起。
  · ssh 不可达 → ③读数 unknown：只按 ①② 裁决、klog 注记 env 未验证（mes-ch 同款：
    不据「未知」动手）；处理轮 ssh 亦断则只报警不拉起（越权纪律）。
  · 处置=ssh gov 杀旧进程 → start-portal.sh setsid 拉起 → 远端 curl /healthz 验活；
    拉起后 90s 判活宽限（远端冷启动+首刷）；Debounce 同款 600s 窗 2 次防风暴；
    alarms.log red code=portal-down（1800s 去重）+ MES kind=keepalive_restart。

生产接线批（2026-11-03）：trigger-inbox 入 watch 清单（第九看护对象，只判活**不拉起**）。
  · 背景：gitea→gov 门户(:8090 /trigger/gitea-webhook 段A HMAC)→本机
    trigger-inbox(:8765 段B X-AF-Signature) 触发链接通批——门户转发腿在役，收件箱
    本体 tools/trigger-inbox.py 的 bind 可配与拉起由主代理串行执行（PoC-D 修复批
    正在改同一文件，禁争；拉起闸=主代理——**已由 2026-11-05 常驻化批移交 systemd
    --user 常驻单元 af-trigger-inbox.service，见下段**）。本守护对收件箱
    **只报警不拉起**：bind 形态与 secret 落位在主代理裁决链上，自动拉起会双开/错绑。
  · 判据三件：①进程在（argv basename=trigger-inbox.py）；②AF_TRIGGER_HOME
    （读在役进程 environ，缺省=WS/af-state/triggers）的 inbox/ 目录可写；
    ③在役进程 environ 含 AF_TRIGGER_SECRET_GITEA_WEBHOOK（段B）——**缺 secret
    =不判活（安全缺省）**：收件箱自身 fail-closed（无 secret 一律 401），进程在
    而无 secret 的形态下「判活」是假绿。
  · 失联处置=只报警（amber，code=trigger-inbox-down，1800s 去重）不拉起；
    恢复=主代理串行拉起（bind/secret 由其裁决）。

常驻化批（2026-11-05，B清单§三-1「现网正断」）：trigger-inbox 落 systemd --user
常驻单元 ~/.config/systemd/user/af-trigger-inbox.service（拉起闸移交）。
  · 背景（现网正断实证）：状态观测/trigger-inbox-liveness.json 20:42 process_alive=false、
    收件箱静默 19.4h、alarms.log trigger-inbox-down 三连（19:41/20:11/20:42）、末次投递
    11-05 01:21——裸进程形态下「死＝静默到人工巡检才发现」，无任何自动恢复面
    （RT-E169② 同型先例：无 systemd 守护的裸进程，宿主面一抖动就长期断供）。
  · 单元三件套（与在役 factory-keepalive.service 同型，RT-E169② 先例口径）：
    EnvironmentFile=/home/pan-ding/.config/af-trigger/gitea-webhook.env（段B secret
    解绑人工串行导出——不再依赖「先 source 再起」的人工步骤）；Restart=always +
    KillMode=process（进程死→systemd 10s 内自动拉起，杀进程演练留证）；
    AF_TRIGGER_BIND=pandev-host.invalid + AF_TRIGGER_BIND_ACK=pandev-host.invalid（**主代理裁决＝
    序列 B**，af/poc/poc-t5-2-t6-3-trigger-resident/README.md §2.2-A：gov 门户
    转发目标写死 pandev-host.invalid:8765，tools/af-jobs-portal.py:148-149；回环绑定＝
    生产 Fast Path 断链（门户回 502）。ACK 与绑定地址同字面＝resolve_bind()
    显式确认闸，缺确认/通配一律拒起 exit 3；暴露面收窄在 headscale ACL
    gov→pandev 仅 8765 一条，不由本件承担）。
  · 判据/边界/处置**零弱化**：三件判据（进程在+inbox 可写+段B secret 在役）与
    「缺 secret 不判活」安全缺省逐字未动；本守护仍**只报警不拉起**（不重复管理
    systemd 单元——拉起闸已由 systemd 承担，双勾起才叫双开）；报警文案的
    「恢复=主代理串行拉起」同步改为「拉起闸=af-trigger-inbox.service 常驻单元
    （Restart=always 自动拉起），持续失联时恢复指引=查 systemctl --user status
    af-trigger-inbox.service（env 缺 secret/bind 拒起等单元级故障）」。

旧 9 对象（main-sched/exp-sched/cb-run/image-feed/mcode-dispatch/ch-mes-local/
anolis-proxy-8124）的判活/拉起死码已随 2026-10-31 文件归档批（OBS-D6）清理
（改前备份 tools/factory-keepalive.py.20261031-pre-OBS.bak；三退役件移
参考/legacy/bench-infra-retired-20261029/）——登记链=计划/研究组/退役执行记录-20261026.md
+ 计划/30-遗产处置.md 删除记录表 + 计划/研究组/OBS回头批-20261031/OBS-D6-证据.md。
停机登记：8 对象 MES kind=retired（line_id=bench-retire，2026-10-26 01:03）。

背景（2026-10-21 复盘，技术债 D-3 韧性层）：tailnet 闪断把主/实验线调度器与 cb-run
杀了 50 分钟无人自动拉起（靠人工巡检发现）。下述 9 对象描述为 2026-10-21~10-24
历史形态（退役存档参考，现行看护对象以上表为准）：

  main-sched   python3 tools/factory-sched.py（无 AF_SCHED_*）
               判据=进程在 且 /tmp/factory-status.json mtime<300s；任一失效→杀残进程重启
  exp-sched    同脚本 + env AF_SCHED_GRAPH=/tmp/factory2-graph.json
                          AF_SCHED_STATUS=/tmp/factory2-status.json
                          AF_SCHED_LOG=/tmp/factory2.log
                          BIN=<WS>/af/target/debug/af-bench-fix2
               判据=进程 env 含 AF_SCHED 且 /tmp/factory2-status.json mtime<300s
  watch        python3 tools/factory-watch.py（env AF_WATCH_EXTRA_DIRS=实测现值）
               判据=进程在 且 状态观测/watch-state.json mtime<300s；
               拉起 watchdog 后连带检查看板 http.server 8790（死则一并拉起，绑 127.0.0.1）
  cb-run       python3 tools/cb-run.py run；判据=/tmp/cb-run.pid 指向活着的 cb-run 进程；
               拉起前清陈旧 pidfile（防其单实例守卫拒绝双开误判）
  image-feed   python3 tools/local-image-feed.py；判据=进程在；
               仅当 120 名单尚有缺镜像时才重启（缺=0 为正常完成退出，不重启只记一条）；
               docker 不可读则只报警不动手
  mcode-dispatch python3 tools/mcode-dispatch.py run（官方 harness 对照线，anolis 解题+本机判分）；
               判据=/tmp/mcode-dispatch/dispatch.pid 指向活进程（/proc 扫描兜底）
               且 /tmp/mcode-dispatch/heartbeat mtime<2400s（单题 solve 最长 30min，
               心跳按题相位刷新，阈值须大于单题时长）；QUOTA 熔断完成退出属正常，
               但 keepalive 无法区分熔断与崩溃——重启幂等（state 断点续跑+pidfile 单实例
               守卫拒绝双开），熔断态重启后 worker 立即跳完剩余队列自然退出
  ch-mes-local MES ClickHouse 探活（补丁② R2 + 补丁④查询级，2026-10-22；MES 迁
               mingda-website 后指向 mes-host.invalid:15221，本机 127.0.0.1:5221 旧实例只读
               48h 回滚锚不在此探活范围——见 计划/研究组/mes迁移mingda-交付.md）；
               判活=**一条极轻 SELECT 查询级探针**（补丁④：/ping 探不到查询级 500，
               10-21 两次 500 期间探针全程绿灯=mes500 根因报告 §4 C 组缺口 1）；
               失败分四类给不同告警码（conn/auth/query/timeout，见 ch_mes_probe）；
               失联处置=只报警不拉起——mingda 侧已有 systemd 单元 clickhouse-factory.service
               （Restart=always，2026-10-22 14:28 起在役）自动拉起，跨机自动拉起越权仍不做；
               klog + 状态观测/alarms.log 追加（类别码）
               + MES kind=ch_mes_down（写失败不致命），30min 去重用本进程自有状态键
               （watch 的 alarm_logged 在 watch 进程内，不可共享；类别翻转立即重报）。
               告警主通道是文件（klog/alarms.log）：CH 挂时照样可报，不落「用 MES 报
               MES 挂」悖论。anolis 侧 ch-mes 另有 guard.sh+用户级 crontab 保底
               （补丁②，定位=D-27 基建连续性，非产线告警面）。
  anolis-proxy-8124 anolis 8124=d36p-proxy 净化白名单代理（只放行 CONNECT
               agent.minimaxi.com:443 的模型网关，purified/containerized 跑批线共用
               出口；D-43 归还，2026-10-24 入监——曾静默死 13h 引发连锁误诊）。
               判活=ssh 端口探活（明文 GET 拿到任意 HTTP 码即活——本体对非 CONNECT
               一律 403=预期；000/空=死）；ssh 失联=判不准只报警不拉起（拉起也走
               ssh 必失败，30min 去重，klog+alarms.log）；恢复=ssh 调 anolis:~/
               mcode-swev/start-proxy-8124.sh（跑批组拉起方式固化：setsid+nohup+
               日志追加；本体自持 flock 单实例守卫，脚本幂等可重入）；失败上限/
               告警照抄既有对象（防抖 2 次/10min+MES keepalive_restart/suppressed）。
  gc-watch     anolis /data sweb.eval 镜像池 GC 看护（补丁③ R2，2026-10-22；非判活
               对象，是 one_round 内的额外步骤）。只做本地判断：latest.json 的
               anolis.disk['/data'].use_pct ≥85（watch 每轮 ssh 刷新，本地读；文件
               mtime>300s 视为 watch 断供不触发）且距上次成功 GC>6h（读耐久证据
               状态观测/img-gc-evidence.jsonl，不依赖 tmpfs）且距上次 spawn>1200s
               （内存防抖，重启复位由子进程 flock 兜底）→ spawn python3 tools/
               img-gc.py apply --host anolis（子命令在前——argparse 子解析器持
               --host，J3 实测旧序「--host 在前」100% 死于 argparse rc2 且零证据；
               setsid 脱离即返回，flock/ssh/prune 全在
               子进程，子进程 1200s 硬超时自杀）——严格非阻塞，绝不让自己成为 7 个
               看护对象的新单点。≥88% 时 img-gc 自行停手只回报（第二道）。A9：证据
               件有未告警的 apply 结果且距上次报警>30min → alarms.log 记一行
               （code=gc-watch），去重时间戳记回耐久证据件。

正确姿势要点（实测自今日现值，含手工巡检惯例）：
  · 全部 subprocess stdin=DEVNULL（mingda 教训）、cwd=WS、start_new_session（=setsid 脱离）、
    stdout/stderr 追加到各对象既有日志文件（/tmp/factory{,2}.log、/tmp/factory-watch.log、
    /tmp/factory-dash.log、/tmp/cb-run.log、/tmp/local-image-feed.log）。
  · 杀残进程用 /proc 扫描的精确 pid（argv0 basename + environ 判别主/实验线），
    不用 pgrep -f（防自匹配）。杀调度器后按厂内惯例清理其 af-bench/cnb-relay 孤儿
    （ppid==1 且 exe=该调度器 BIN，或 cmdline 含 cnb-relay.py）——防重启后同 --out 重复派发。
  · 防抖：同一对象 10 分钟内最多重启 2 次，超限只报警（本地日志 + MES kind=keepalive_suppressed）。
  · 每次拉起记 /tmp/factory-keepalive.log + MES 事件（kind=keepalive_restart，
    work_order_id=factory-keepalive-<对象>，直 INSERT af_mes.mes_event，写失败不致命）。
  · 刚拉起的对象有 150s 宽限期：宽限内只查进程在场、豁免状态文件新鲜度（旧文件 mtime
    是上一世的，避免刚重启即被判 stale 造成抖环；进程真死仍会触发重启→防抖兜底）。

控制文件韧性层（技术债 D-25，2026-10-21 立项当日归还）：/tmp 图与控制文件曾遭三连删
（factory-graph/factory2-graph/fix2ab-sample，10-21 13:00-14:04，凶手未明），彼时
keepalive 无存在性校验，删后产线盲跑（调度器 load_graph 读失败仅记日志、持旧内存继续
跑）。现每轮巡检最前面先过 graph_guard：两图缺失即从 工具状态备份/ 的最近备份原子
恢复（时间戳滚动件优先、平铺快照兜底；无可用备份只告警不凭空造图），恢复记高亮日志
行 ">>> RESTORED <file> from <backup> <<<" + MES 事件；心跳前再做新鲜滚动备份
backup_graphs（原子拷入 工具状态备份/，带时间戳、每图保留最近 5 份，防备份本身
被删/变旧）。

已知边界（自我认知）：本脚本自身崩溃没有任何进程拉它——单实例守卫 /tmp/factory-keepalive.pid；
自身死亡无法自愈，靠计划内 cron 人工/厂长巡检兜底（巡检 prompt 已存在，发现
/tmp/factory-keepalive.pid 失活即重启本脚本）。密钥零明文：本脚本不读不写任何令牌。

用法:
  factory-keepalive.py                 # 常驻（默认 30s 一轮）
  factory-keepalive.py --once          # 单轮真实巡检+处置
  factory-keepalive.py --dry-run       # 单轮干跑：只打印将执行的判活结论与命令，不动手
  factory-keepalive.py --print-commands  # 打印全部对象的拉起命令/env/日志路径（不动手不判活）
  factory-keepalive.py --interval N    # 自定义轮询秒数
"""
import argparse
import base64
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys, importlib.util
import time
import urllib.error
import urllib.parse
import urllib.request

WS = "/home/pan-ding/workspace/agent黑灯工厂"
# OTel MVP 埋点（2026-10-28）：工厂链路守护面关键事件 → OTLP（tools/otel/factory_otel）。
# 端点缺省（2026-11-02 起 AF_OTEL_ENDPOINT 未设落缺省 collector，此前=静默丢弃）；
# fail-open 绝不抛回主循环；
# 熔断文件 状态观测/OTEL-STOP 在位即静默（与 stream-tailer TAILER-STOP 同模式）。
sys.path.insert(0, os.path.join(WS, "tools", "otel"))
try:
    import factory_otel as _otel
except Exception:  # noqa: BLE001 —— 埋点缺失不影响看护主职
    _otel = None
PIDFILE = "/tmp/factory-keepalive.pid"; _ft_spec = importlib.util.spec_from_file_location("factory_thresholds", os.path.join(os.path.dirname(os.path.abspath(__file__)), "factory-thresholds.py")); _ft = importlib.util.module_from_spec(_ft_spec); _ft_spec.loader.exec_module(_ft)  # D-140（债 D-129）判活阈值单源：scheduler 判活线改由 tools/factory-thresholds.py 供值——本件行内形态为零净增行（bot-scrub 判据豁免行钉 1614/2082/2117 不漂移），逐行说明见 PR
KLOG = "/tmp/factory-keepalive.log"
def _mes_conn(url=None):
    """MES ClickHouse 连接 → (base_url, auth_header)。

    2026-10-22 MES 由 pandev-comp 本机迁至 mingda-website（tailnet mes-host.invalid:15221，
    迁移动机/对账/回滚见 计划/研究组/mes迁移mingda-交付.md；本机 127.0.0.1:5221 旧实例
    保留只读 48h 作回滚锚）。解析顺序：入参 url > 环境变量 MES_CH_URL > 0600 凭据文件
    ~/.config/mes-ch/url > 缺省新 MES 地址。凭据可写 user:pass@host 形式（urllib 不
    解析 URL 内嵌凭据，故在此拆出转 Basic 头）；口令明文按密钥纪律只存 0600 文件，
    不进任何文档/回报。缺文件且无 env 落到无凭据地址→401 显性失败，不静默写旧锚点。
    """
    if url is None:
        url = os.environ.get("MES_CH_URL")
    if not url:
        try:
            with open(os.path.expanduser("~/.config/mes-ch/url"), encoding="utf-8") as f:
                url = f.read().strip()
        except OSError:
            url = "http://mes-host.invalid:15221"
    auth = None
    if "@" in url:
        scheme, rest = url.split("://", 1)
        userinfo, hostpart = rest.split("@", 1)
        url = f"{scheme}://{hostpart}"
        auth = "Basic " + base64.b64encode(userinfo.encode()).decode()
    return url, auth


CH, CH_AUTH = _mes_conn()
ALARMS_LOG = f"{WS}/状态观测/alarms.log"   # 与 watch 同一告警文件（补丁②：ch-mes-local 主通道）
CHMES_DEDUP_S = 1800                       # ch-mes-local 失联报警去重窗（同 watch DEDUP_WINDOW）
LATEST_JSON = f"{WS}/状态观测/latest.json"  # watch 产物（anolis.disk['/data'].use_pct 在内）
GC_EVIDENCE = f"{WS}/状态观测/img-gc-evidence.jsonl"   # 耐久证据（补丁③：迟滞+A9 去重源）
GC_EVIDENCE_TMP = "/tmp/img-gc-evidence.jsonl"
GC_TRIGGER_PCT = 85      # /data use_pct 触发线（10-22 台账口径，巡检日志:157）
GC_MIN_INTERVAL = 6 * 3600   # 距上次成功 GC 迟滞
GC_SPAWN_SUPPRESS = 1200     # spawn 防抖（=子进程硬超时上界；重启复位由 flock 兜底）
GC_ALARM_DEDUP_S = 1800      # A9 结果报警去重（记回耐久证据件）
GC_DRILL_FLAG = f"{WS}/状态观测/img-gc-drill.flag"   # P0-2 drill 旗标（自毁；只读 plan 演练通道，方案 §3.3-a/§5）

INTERVAL = 30          # 轮询周期（s）
STALE_S = 300          # 状态/watch-state 文件新鲜度阈值（s）
RESTART_WINDOW = 600   # 防抖窗（s）
RESTART_MAX = 2        # 窗内最多重启次数
GRACE_S = 150          # 刚拉起后的判活宽限（s，豁免文件新鲜度）
HEARTBEAT_EVERY = 20   # 每 N 轮写一行全绿心跳（20×30s=10min）

# ---------- D-25 控制文件韧性：图存在性校验+自动恢复+滚动备份 ----------
BACKUP_DIR = f"{WS}/工具状态备份"
GRAPH_FILES = [("factory-graph", "/tmp/factory-graph.json"),
               ("factory2-graph", "/tmp/factory2-graph.json")]
BACKUP_KEEP = 5                    # 每图保留最近 N 份时间戳滚动备份
BACKUP_TS = "%Y%m%d-%H%M%S"        # 滚动备份时间戳（定长，字典序=时序）

WATCH_ENV = {"AF_WATCH_EXTRA_DIRS": "/tmp/bench-fix2-rerun-*,/tmp/factory2-status.json"}
DASH_PORT = "8790"
DASH_DIR = f"{WS}/状态/看板"
# self-improve-loop（循环产线批-20261029）：自改进循环产线守护的状态文件
# （判据=进程在+该文件 mtime<STALE_S，与 watch 同构；STOP 熔断轮守护仍记账，
# 故熔断不会误判失联；回写轮内守护 60s 心跳保新鲜度）
SIL_STATE = f"{WS}/状态观测/loop-state.json"
SIL_LOG = f"{WS}/状态观测/self-improve-loop.log"

# ---------- DEB-3（2026-10-30 产线续能批）：本机五守护入监表 ----------
# 判据：进程在（/proc argv basename 精确匹配，禁 pgrep -f 防自匹配）
#      +（状态文件 mtime<stale_s 或 日志尾 mtime<stale_s）——双信号 OR 判活。
# stale_s 逐守护按实测写盘节奏标定（校准全文见
# 计划/研究组/产线续能批-20261030/DEB3-判据校准.md）：
#   status-push 实测写盘 ≤119s → 300s（2.5× 余量）
#   emit-sidecar 实测 ≤41s → 300s（7× 余量）
#   self-improve-loop 60s 心跳 → 300s（5× 余量）
#   scheduler 实测单轮 p99=784s/max=1258s → 2400s
#   router 实测单轮 995–1226s（gov 报告目录增长则轮长随之变长）→ 3600s
# grace_s=拉起后的判活宽限（宽限内只看进程在不看新鲜度；进程不在仍判死）：
#   取各守护首轮写盘时间上界——router/scheduler 首轮 1800s、status-push 300s、
#   emit-sidecar 120s、self-improve-loop 150s（沿用既有 GRACE_S）。
LOCAL_GUARDS = [
    # 源码版本钉（2026-11-03 在役换码批，RT-E157/RT-E160/RT-E169 三批修复整批未在役
    # 30h+ 的根因面）：本守护判活追加「在役载入版本＝盘上源码」必要条件。此前判活只有
    # 「进程在 + state/log mtime<3600s」，盘上源码改了不重启＝修复不生效（2026-11-02
    # 实证：在役 17:54:51 起跑、盘上 18:45 已改，RT-E157 ARB_REJECT_RE 拒收回流腿、
    # RT-E160 「真上板才在飞」+88 条 skipped_newer 存量重武装、RT-E169 quote 契约三道
    # 机械门三批整批未在役；88 条冻结账被旧码防重放永久冻结、63 条原子永远停在非
    # verified，而变更日志却按「已生效」记账）。
    # 本条=「修复落盘自动生效」的耐久性门：版本不对齐⇒判死⇒fix_guard 拉起新码
    # （在役守护自 v1.x 起每次写盘登记 daemon_src.sha256＝载入时源码指纹；无该登记
    # = 在役码早于版本钉机制⇒同样判死换码，不放过假绿）。同 self-improve-loop 先例。
    {"name": "router", "script": "event-router.py",
     "state": f"{WS}/kb-seed/sandbox/.router-state.json",
     "log": f"{WS}/状态观测/event-router.log",
     "stale_s": 3600, "grace_s": 1800,
     "cmd": ["python3", "tools/event-router.py"],
     "log_target": f"{WS}/状态观测/event-router.log",
     "src_pin": "tools/event-router.py",
     "src_pin_state_key": "daemon_src"},
    {"name": "scheduler", "script": "factory-scheduler.py",
     "state": f"{WS}/状态观测/factory-scheduler-state.json",
     "log": f"{WS}/状态观测/factory-scheduler.log",
     "stale_s": _ft.LOCAL_GUARDS_STALE_S, "grace_s": _ft.LOCAL_GUARDS_GRACE_S,  # D-140 单源（原 2400/1800 字面；与 watch SCHED_STALE_S 同源同值）
     "cmd": ["python3", "tools/factory-scheduler.py"],
     "log_target": f"{WS}/状态观测/factory-scheduler.log"},
    {"name": "status-push", "script": "factory-status-push.py",
     "state": None,                      # 该守护无独立状态文件，日志即状态面
     "log": f"{WS}/状态观测/status-push.log",
     "stale_s": 300, "grace_s": 300,
     "cmd": ["python3", "tools/factory-status-push.py"],
     "log_target": f"{WS}/状态观测/status-push.log"},
    {"name": "emit-sidecar", "script": "emit-sidecar.py",
     "state": f"{WS}/状态观测/otel-sidecar.json",
     "log": f"{WS}/状态观测/otel-sidecar.log",
     "stale_s": 300, "grace_s": 120,
     "cmd": ["python3", "tools/otel/emit-sidecar.py"],
     "log_target": f"{WS}/状态观测/otel-sidecar.log"},
    {"name": "self-improve-loop", "script": "self-improve-loop.py",
     "state": SIL_STATE, "log": SIL_LOG,
     "stale_s": 300, "grace_s": GRACE_S,
     "cmd": ["python3", "tools/self-improve-loop.py"],
     "log_target": SIL_LOG,
     # 源码版本钉（2026-11-03 SIL 环修复批）：本守护判活追加「在役载入版本＝盘上
     # 源码」必要条件——此前判活只有「进程在 + state/log mtime<300s」，盘上源码改了
     # 不重启＝修复不生效（2026-11-03 实证：在役 06:53 起跑、盘上 17:53 已改、17h
     # 未重载＝轮4 SIL 修整体未在役；在役旧判据更宽松＝同一镜像面两套结论）。
     # 本条=「修复落盘自动生效」的耐久性门：版本不对齐⇒判死⇒fix_guard 拉起新码。
     "src_pin": "tools/self-improve-loop.py",
     "src_pin_state_key": "daemon_src"},
    # DEB-7（2026-10-31 义务批）：quota-governor 常驻化入 watch 清单（本机第六守护）
    # 判据=进程在（argv 含 quota-governor.py 且子命令=daemon）+ quota.json mtime<600s
    # argv_extra="daemon"：一次性 poll 与常驻 daemon 同脚本名，只认脚本名会让手动
    # poll 假阳性满足「进程在」（并被单实例收敛误杀）。
    # and_mode=True：quota.json 停写是本次要治的病（配额闸误判 stale），
    # OR 判据会让「进程活但读数停更」逃过判活——故 state 新鲜为必要条件。
    # stale_s=600 与配额闸 stale 阈（factory-scheduler QUOTA_STALE=600）同值；
    # 写盘密度=governor daemon 60s 一轮（远严于「≥300s 一轮」下界），恒满足。
    # grace_s=120：governor 首轮写盘含一次 ssh anolis 取 token（超时上限 60s）。
    # log_ok_token="poll ok"（DEB57 2026-11-01 误杀复盘）：启用「判读矛盾门」——and_mode
    # 下若 state 假死但日志尾恰是 poll ok（=poll() 已走完 os.replace(quota.json)，
    # quota-governor.py:125→206，mtime 必新鲜），判 stat 读数不可信：改判存活、只记疑
    # 不处置（01:25:50 实证 stat 读数与 61s 写盘节奏互斥，误杀在役 daemon 且烧掉防抖窗）。
    # 真病（进程活但停写）日志尾=poll error、不含该 token，判死拉起不变。
    {"name": "quota-governor", "script": "quota-governor.py",
     "state": f"{WS}/状态观测/quota.json",
     "log": f"{WS}/状态观测/quota-governor.log",
     "stale_s": 600, "grace_s": 120,
     "argv_extra": "daemon", "and_mode": True,
     "log_ok_token": "poll ok",
     "cmd": ["python3", "tools/quota-governor.py", "daemon"],
     "log_target": f"{WS}/状态观测/quota-governor.log"},
    # —— 账本一致批（2026-11-01）：otelcol（OTel collector）第七守护入 watch 清单 ——
    # 背景：collector 于 2026-10-31 断链（CH 末笔 span 12:36:56.347646382），26h+ 期间
    # 四处监督/账本面全零：欠账台账无行、变更日志无行、alarms.log/keepalive.log 无码、
    # 本清单不含 otelcol（仅红队终局轮 G8/V1 运行期另记）。本行补「告警面有码」。
    # argv0_is_bin=True：otelcol 是编译二进制（argv0=~/otelcol-build/build/otelcol），
    # 旧 scan_pids 只扫 argv0=python* 进程、match 只看 argv[1:]，两处都够不着它；
    # 放行 argv0 basename 精确==script 的二进制（其余守护缺省 False 零改动）。
    # 判据=进程在 + storage 发送队列文件新鲜（OR 日志尾）：
    #   state=exporter_clickhouse__metrics：端到端管线运动信号（OTLP 收数→batch→
    #   持久队列落盘），实测 30s 恒刷（2026-11-01 18:07–18:09 六采样 age=7–10s；
    #   emit-sidecar 每轮 emit(span=True metrics=13) 供数，exporter flush_timeout=2s）；
    #   collector.log 只记事件（启停/export retry），健康期恒静默（内部遥测已关）——
    #   只作 OR 副信号，不作判活主信号。
    #   stale_s=300：30s 写盘节奏 ×10 余量（emit-sidecar 同值）。
    #   grace_s=120：实测 run-collector.sh start → 队列文件首刷 ≤75s（18:04:48 起岗
    #   →≤18:06:03 首刷），120s=1.6× 余量（emit-sidecar 同值）。
    #   边界如实：①判据依赖 emit-sidecar 供数——sidecar 死则队列停刷，可能在
    #   sidecar 自身 30s 拉回前误判 collector 死而多拉起一次（collector 持久队列
    #   重启安全、不丢已收数据；防抖 600s/2 次封顶）；②「进程活但 hung」与
    #   router/scheduler 单轮长同旧例不可见，非本行新增缺口。
    # cmd=既有交付件 run-collector.sh start（凭据现取→派生配置→validate→验活四步
    # 自带，spawn Popen 即返回非阻塞；双启拒绝靠其 pidfile 守卫）。
    {"name": "otelcol", "script": "otelcol", "argv0_is_bin": True,
     "no_dedup": True,
     "state": os.path.expanduser("~/otelcol-runtime/storage/exporter_clickhouse__metrics"),
     "log": os.path.expanduser("~/otelcol-runtime/logs/collector.log"),
     "stale_s": 300, "grace_s": 120,
     "cmd": ["bash", "tools/otel/run-collector.sh", "start"],
     "log_target": f"{WS}/状态观测/otel-collector-restart.log"},
]

last_spawn = {}        # name -> epoch（最近一次本脚本拉起时刻，算宽限期）
last_chmes_alarm = 0.0  # ch-mes-local 上次报警时刻（30min 去重，本进程自有状态键）
last_chmes_alarm_cls = None  # 上次报警的失败类别（类别翻转立即重报，不被去重吞掉）
last_chmes_fail = None      # 最近一次查询探针失败 (cls, detail)（check→fix 传递）
last_gc_spawn = 0.0     # gc-watch 上次 spawn 时刻（1200s 防抖，内存态；重启复位由 flock 兜底）
last_hb_round = -1


def now_s():
    return time.strftime("%F %T")


def now_utc_s():
    """UTC 墙钟串（OBS-D4 2026-10-31 新增）：af_mes.mes_event.occurred_at 列为
    DateTime64(3,'UTC')，本地墙钟串按 UTC 解析 → 存储即时 +8h 漂移（2026-10-31
    实测：af-execline 等站最新行 epoch 比真值超前 ≈+8h；order-cli/af-mes 与
    factory-status-push _mes_occ_str 为正确口径）。MES 写入一律用本函数。"""
    return time.strftime("%F %T", time.gmtime())


def klog(name, msg):
    """日志单通道：只直接 append KLOG，不 print（红队 W2-C19 收口）。

    旧实现 print(stdout)+append KLOG 双通道，而上岗命令
    `nohup python3 tools/factory-keepalive.py >> /tmp/factory-keepalive.log`
    又把 stdout 重定向进同一文件——每行日志必写两次（2026-10-27 实测
    /tmp/factory-keepalive.log 逐字成对行，体积 950KB 双倍、轮次/告警读数
    翻倍易误判）。现只保留直接 append 单通道；stdout 不再承载日志，
    既有上岗命令的重定向退化为仅接崩溃 traceback（照旧落同一文件、恰好一次）。
    单通道性由 [`log_single_channel_selfcheck`] 启动断言兜底。"""
    line = f"[{now_s()}] [{name}] {msg}"
    try:
        with open(KLOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def log_single_channel_selfcheck():
    """日志单通道启动断言（红队 W2-C19：一行探针后 KLOG 必须恰 +1 行）。

    若 stdout 又被重定向到 KLOG 且 klog 的直接 append 通道并存（双写回归），
    探针会使行数 +2——即刻带原因退出拒跑，防日志体积/轮次计数再度翻倍。
    失败路径先清自身 pidfile（self_guard 已写过），不留指向死进程的陈旧锁。

    2026-10-30 DEB-3 重启实测：KLOG 里存在一段并发写撕裂的坏字节（两写者交错，
    落在 2026-10-30 03:46/03:55 两行之间），文本模式读会在解码处 UnicodeDecodeError
    把常驻进程直接掀翻——日志是只写证据，不该反过来弄死守护。故行数统计改按字节数
    '\\n' 计：判据（探针前后行数差 == 1）一字未改，只是不再解码正文。"""
    try:
        with open(KLOG, "rb") as f:
            before = f.read().count(b"\n")
    except OSError:
        before = 0
    klog("self", "日志单通道自检探针行（应恰出现一次）")
    try:
        with open(KLOG, "rb") as f:
            after = f.read().count(b"\n")
    except OSError as e:
        _fail_selfcheck(f"KLOG {KLOG} 不可读（{e}）")
        return
    if after - before != 1:
        _fail_selfcheck(
            f"日志双写回归：一条探针 klog 后 KLOG 行数 {before}→{after}"
            f"（增量 {after - before}≠1）。klog 只走直接 append 单通道，"
            f"stdout 不得再重定向到 {KLOG}"
        )


def _fail_selfcheck(reason: str):
    try:
        if open(PIDFILE).read().strip() == str(os.getpid()):
            os.remove(PIDFILE)
    except OSError:
        pass
    print(f"factory-keepalive 拒绝带病上岗：{reason}", file=sys.stderr)
    sys.exit(3)


# ---------- MES（直 INSERT，factory-sched ch_insert 同款；失败不致命） ----------

def mes_event(name, kind):
    body = json.dumps({
        "work_order_id": f"factory-keepalive-{name}",
        # OBS-D4（2026-10-31）：occurred_at 列 DateTime64(3,'UTC')——本地墙钟串
        # 会 +8h 漂移（J2 实测），改 UTC 墙钟串=写入侧修复，历史行零改动。
        "occurred_at": now_utc_s(),
        "event_id": f"factory-keepalive-{name}-{kind}-{int(time.time())}-{os.getpid()}",
        "line_id": "keepalive",
        "station_id": name,
        "kind": kind,
        "quantity": 1,
    }, ensure_ascii=False) + "\n"
    req = urllib.request.Request(
        CH + "/?query=" + urllib.parse.quote(
            "INSERT INTO af_mes.mes_event (work_order_id, occurred_at, event_id, "
            "line_id, station_id, kind, quantity) FORMAT JSONEachRow"),
        data=body.encode(), method="POST")
    if CH_AUTH:
        req.add_header("Authorization", CH_AUTH)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        return True
    except Exception as e:
        klog(name, f"MES 写入失败（不致命）: {e}")
        return False


# ---------- /proc 工具（不使用 pgrep -f，防自匹配） ----------

def scan_pids(match, argv0_ok=()):
    """扫 /proc：argv0 是 python* 且任一后续参数 basename 命中脚本名。match(argv)->bool。

    argv0_ok（账本一致批 2026-11-01）：额外的 argv0 basename 白名单——编译型二进制
    守护（otelcol，argv0=~/otelcol-build/build/otelcol 非 python*）按 basename 精确
    放行。缺省 () 时行为与旧版逐字节一致（既有调用方零改动）。"""
    out = []
    me = os.getpid()
    for ent in os.listdir("/proc"):
        if not ent.isdigit() or int(ent) == me:
            continue
        try:
            with open(f"/proc/{ent}/cmdline", "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if not argv:
            continue
        b0 = os.path.basename(argv[0])
        if not b0.startswith("python") and b0 not in argv0_ok:
            continue
        if match(argv):
            out.append(int(ent))
    return sorted(out)


def pid_argv(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
    except OSError:
        return None


def boot_time():
    """系统启动时刻（epoch 秒，/proc/stat btime）；读不到返回 None。

    2026-11-03 在役版本对账扩册批新增（RT-E194 拦截机制②读数原语），
    与 tools/live-daemon-version-probe.py 同口径。
    """
    try:
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("btime "):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def proc_start_epoch(pid, btime):
    """进程启动时刻（epoch 秒）：/proc/<pid>/stat 第 22 字段（clock tick）+ btime。

    同上＝扩册批新增，与探针同口径；读不到返回 None（调用方 fail-open，不据此动手）。
    """
    try:
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        ticks = int(fields[19])
    except (OSError, ValueError, IndexError):
        return None
    if btime is None:
        return None
    return btime + ticks / os.sysconf("SC_CLK_TCK")


def file_age(path):
    """文件 mtime 距今秒数；缺失/异常返回 None（视为 stale）。"""
    try:
        return time.time() - os.stat(path).st_mtime
    except OSError:
        return None


def kill_pid(pid, name):
    """精确 pid 杀残进程：SIGTERM → 最多 5s → SIGKILL。"""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(10):
        if not os.path.exists(f"/proc/{pid}"):
            return
        time.sleep(0.5)
    try:
        os.kill(pid, signal.SIGKILL)
        klog(name, f"SIGKILL 补刀 pid={pid}")
    except ProcessLookupError:
        pass
    time.sleep(0.5)


def spawn(name, cmd, logfile, extra_env=None, strip_env=()):
    """正确姿势拉起：stdin=DEVNULL、cwd=WS、setsid 脱离、日志追加。返回 pid 或 None。"""
    env = {k: v for k, v in os.environ.items() if k not in strip_env}
    env.update(extra_env or {})
    env["AF_KEEPALIVE_SPAWN"] = "1"   # 供事后辨认本脚本经手拉起的进程
    try:
        with open(logfile, "ab", 0) as lf:
            proc = subprocess.Popen(
                cmd, cwd=WS, env=env, stdin=subprocess.DEVNULL,
                stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
        klog(name, f"拉起 pid={proc.pid} cmd={' '.join(cmd)} "
                   f"env+={sorted(extra_env or {})} log={logfile}")
        return proc.pid
    except Exception as e:
        klog(name, f"拉起失败: {e}")
        return None


class Debounce:
    """同对象 10 分钟窗内最多 RESTART_MAX 次重启，超限只报警。"""

    def __init__(self):
        self.hist = {}       # name -> [epoch, ...]
        self.suppressed = {} # name -> epoch（上次"超限报警"记录时刻）

    def allow(self, name, t):
        wins = [x for x in self.hist.get(name, []) if t - x < RESTART_WINDOW]
        self.hist[name] = wins
        if len(wins) >= RESTART_MAX:
            last = self.suppressed.get(name, 0)
            if t - last > RESTART_WINDOW:  # 每窗只报一次
                klog(name, f"ALARM {RESTART_WINDOW}s 内已重启 {len(wins)} 次，超限停止拉起只报警"
                           f"（窗内不再自动拉起；若此后判活仍失败，需人工介入）")
                mes_event(name, "keepalive_suppressed")
                self.suppressed[name] = t
            return False
        return True

    def record(self, name, t):
        self.hist.setdefault(name, []).append(t)


# ---------- 控制文件韧性（D-25） ----------

def _json_ok(path):
    """文件存在且是合法 JSON（备份采纳/恢复候选的准入 sanity gate）。"""
    try:
        with open(path, "rb") as f:
            json.loads(f.read().decode("utf-8", "replace"))
        return True
    except (OSError, ValueError):
        return False


def _atomic_copy(src, dst):
    """原子拷贝：先写 dst 同目录临时名，再 os.replace（=mv）落位。
    图文件可能被调度器并发读写，绝不让半成品出现在目标名上。"""
    tmp = f"{dst}.tmp.{os.getpid()}"
    try:
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            while True:
                chunk = fi.read(1 << 20)
                if not chunk:
                    break
                fo.write(chunk)
            fo.flush()
            os.fsync(fo.fileno())
        os.replace(tmp, dst)
        return True
    except OSError as e:
        klog("graph", f"原子拷贝失败 {src} → {dst}: {e}")
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


def _stamped_backups(base):
    """某图的时间戳滚动备份（新→旧）。平铺旧件不归滚动管。"""
    ts_re = re.compile(rf"^{re.escape(base)}\.(\d{{8}}-\d{{6}})\.json$")
    stamped = []
    try:
        for fn in os.listdir(BACKUP_DIR):
            m = ts_re.match(fn)
            if m:
                stamped.append((m.group(1), fn))
    except OSError:
        pass
    stamped.sort(reverse=True)   # 定长时间戳，字典序=时序
    return [os.path.join(BACKUP_DIR, fn) for _, fn in stamped]


def graph_backup_candidates(base):
    """某图在 工具状态备份/ 下的备份候选（新→旧）：
    时间戳滚动件优先，2026-10-21 14:2x 平铺快照兜底。"""
    out = _stamped_backups(base)
    flat = os.path.join(BACKUP_DIR, f"{base}.json")
    if os.path.exists(flat):
        out.append(flat)
    return out


def prune_graph_backups(base):
    """滚动保留最近 BACKUP_KEEP 份时间戳备份（防备份本身堆积/变旧）。"""
    for old in _stamped_backups(base)[BACKUP_KEEP:]:
        try:
            os.unlink(old)
            klog("graph", f"滚动清理旧备份 {os.path.basename(old)}"
                          f"（每图保留最近 {BACKUP_KEEP} 份）")
        except OSError as e:
            klog("graph", f"清理旧备份失败 {old}: {e}")


def backup_graphs():
    """D-25 第二层：心跳前新鲜备份——两图原子拷入 工具状态备份/（时间戳滚动，
    每图保留最近 BACKUP_KEEP 份）。目录本身被删则重建；内容非法 JSON 不采纳。"""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
    except OSError as e:
        klog("graph", f"ALARM 备份目录不可用 {BACKUP_DIR}: {e}")
        return
    ts = time.strftime(BACKUP_TS)
    for base, path in GRAPH_FILES:
        if not os.path.exists(path):
            klog("graph", f"备份跳过：{path} 不存在（交由存在性校验流程处理）")
            continue
        dst = os.path.join(BACKUP_DIR, f"{base}.{ts}.json")
        if not _atomic_copy(path, dst) or not _json_ok(dst):
            klog("graph", f"ALARM 备份未采纳 {path} → {dst}（拷贝失败或内容非法）")
            try:
                os.unlink(dst)
            except OSError:
                pass
            continue
        klog("graph", f"备份 {path} → {os.path.relpath(dst, WS)}"
                      f"（{os.path.getsize(dst)}B）")
        prune_graph_backups(base)


def graph_guard(dry=False):
    """D-25 第一层：控制文件存在性校验+自动恢复。每轮巡检最前面跑，幂等
    （存在即跳过）。缺失→从最近备份（滚动件优先、平铺兜底）原子恢复；
    无可用备份只告警不恢复——绝不凭空造图。返回 (restored, missing)。"""
    restored, missing = [], []
    for base, path in GRAPH_FILES:
        if os.path.exists(path):
            continue
        cands = [p for p in graph_backup_candidates(base)
                 if os.path.exists(p) and _json_ok(p)]
        if not cands:
            klog("graph", f"ALARM 控制文件缺失且无可用备份：{path}"
                          f"（不凭空造图，只记不恢复，需人工介入）")
            missing.append(path)
            continue
        src = cands[0]
        if dry:
            klog("graph", f"[dry-run] {path} 缺失，将从 {src} 恢复（未动手）")
            missing.append(path)
            continue
        if _atomic_copy(src, path):
            klog("graph", f">>> RESTORED {path} from {src} <<<"
                          f"（D-25：控制文件曾被删/丢失，已从最近备份自动恢复）")
            mes_event("graph", "keepalive_graph_restored")
            restored.append(path)
        else:
            klog("graph", f"ALARM 恢复失败 {path} from {src}（需人工介入）")
            missing.append(path)
    return restored, missing


def watch_pids():
    return scan_pids(lambda argv: any(os.path.basename(a) == "factory-watch.py" for a in argv[1:]))


def dash_pids():
    return scan_pids(lambda argv: "http.server" in argv and DASH_PORT in argv)


WATCH_SRC = f"{WS}/tools/factory-watch.py"   # watch 判据源（常量＝夹具可覆写；路径改动须同步 LAUNCH_PLAN）


def watch_src_stale(pids):
    """「源 mtime>进程启动」版本对账腿（RT-E194 拦截机制②，2026-11-03 扩册批落码）。

    Python 在进程启动时加载源码 ⇒ 在役进程启动早于盘面源码 mtime 即正面证明在役
    载旧码（修复只落盘未在役＝两套真相并行——RT-E194/E202/E204 家族的病，DEB57-A0
    错根修复本体就是 watch，热改写后曾可带旧世界模型在役而全监测面读绿）。
    返回 (stale, detail)；stale=True ⇒ 判死 ⇒ 既有 fix_watch 杀残+拉起即自动换码。
    读数取不到（源码缺//proc 读不到）→ fail-open 不判死：自动重启是破坏性动作，
    不拿「读数缺失」当证据（与探针门的 rc=2 不猜绿是两面：门猜红、手不猜动）。
    1s slack 与探针 judge 同款（防 mtime/启动时刻秒级抖动假红；`touch` 空改会触发
    一次无谓换码——可接受，防抖窗 600s/2 次封顶，宁多重启一次不放过载旧码）。
    边界如实：本批只建 watch 腿（A0 被修本体）；其余对象版本对账归
    live-daemon-version-probe 旁证面，扩面待续。
    """
    try:
        src_mtime = os.stat(WATCH_SRC).st_mtime
    except OSError:
        return False, "版本腿：src_mtime 读不到（fail-open 不判死）"
    if not pids:
        return False, "版本腿：无进程（判活腿已判死，本腿不参与）"
    bt = boot_time()
    starts = [s for s in (proc_start_epoch(p, bt) for p in pids) if s is not None]
    if not starts:
        return False, "版本腿：proc_start 读不到（fail-open 不判死）"
    proc_start = min(starts)   # 取最早：任一实例载旧码即判死（fix 杀全部残再拉起）
    if proc_start + 1 < src_mtime:
        return True, (f"版本漂移：在役启动({time.strftime('%m-%d %H:%M:%S', time.localtime(proc_start))})"
                      f"<盘面源码落盘({time.strftime('%m-%d %H:%M:%S', time.localtime(src_mtime))})"
                      f"——载旧码，判死换码（RT-E194 机制②）")
    return False, (f"版本新鲜：在役启动({time.strftime('%m-%d %H:%M:%S', time.localtime(proc_start))})"
                   f"≥盘面源码落盘({time.strftime('%m-%d %H:%M:%S', time.localtime(src_mtime))})")


def check_watch(t):
    pids = watch_pids()
    age = file_age(f"{WS}/状态观测/watch-state.json")
    fresh = age is not None and age < STALE_S
    if t - last_spawn.get("watch", 0) < GRACE_S:
        return bool(pids), f"grace 宽限内：进程={pids or '无'}（豁免新鲜度）"
    ok = bool(pids) and fresh
    detail = f"进程={pids or '无'} watch-state_age={int(age) if age is not None else '缺失'}s fresh={fresh}"
    if ok:   # 版本腿只在判活已过后加判（进程不在时 fix_watch 拉起即换码，无须本腿）
        stale, vdetail = watch_src_stale(pids)
        ok = ok and not stale
        detail += f" {vdetail}"
    return ok, detail


def fix_watch(dry, t, deb):
    for p in watch_pids():
        if dry:
            klog("watch", f"[dry-run] 将 kill 残进程 pid={p}")
        else:
            klog("watch", f"杀残进程 pid={p}")
            kill_pid(p, "watch")
    cmd = ["python3", "tools/factory-watch.py"]
    if dry:
        klog("watch", f"[dry-run] 将拉起: cwd={WS} cmd={' '.join(cmd)} "
                      f"env+={WATCH_ENV} log=/tmp/factory-watch.log setsid")
        return
    if spawn("watch", cmd, "/tmp/factory-watch.log", extra_env=dict(WATCH_ENV)):
        last_spawn["watch"] = t
        deb.record("watch", t)
        mes_event("watch", "keepalive_restart")


# ---- 本机五守护（DEB-3 2026-10-30 产线续能批）：统一判据 + 统一拉起姿势 ----
# 判据：进程在（/proc argv basename 精确匹配，禁 pgrep -f 防自匹配）
#      +（状态文件 mtime<stale_s 或 日志尾 mtime<stale_s）——双信号 OR 判活。
# OR 而非 AND 的理由（实测，勿改回 AND）：本机五守护写盘节奏差 3 个数量级——
#   router 一轮 poll_verify_reports 要 ssh 遍历 gov 报告目录（实测单轮 995–1226s），
#   scheduler 单轮含 anolis/gov 多路 ssh（实测单轮 p99=784s/max=1258s），
#   status-push 单轮 ≤119s、emit-sidecar ≤41s、self-improve-loop 60s 心跳。
#   AND 判据会把 router/scheduler 系统性误杀（对活进程假阳性 >0，直接违反验收门 2）。
# stale_s 逐守护按实测标定（校准全文：计划/研究组/产线续能批-20261030/DEB3-判据校准.md）。
def guard_pids(spec):
    """某守护的在役进程（argv basename 精确匹配脚本名）。

    DEB-7：spec 带 argv_extra 时，额外要求该 token（子命令）出现在 argv 里——
    quota-governor 的一次性 poll 与常驻 daemon 同脚本名，只认脚本名会把手动 poll
    当成在役守护（假阳性满足「进程在」，并被单实例收敛误杀）。
    账本一致批 2026-11-01：spec 带 argv0_is_bin=True 时（otelcol 编译二进制，
    进程名只在 argv[0]），匹配候选扩为整个 argv 且 scan_pids 放行该 argv0 basename；
    缺省 False 时与旧语义逐字节一致（python 守护进程名都在 argv[1:]）。"""
    extra = spec.get("argv_extra")
    bin_match = bool(spec.get("argv0_is_bin"))
    cands = (lambda argv: argv) if bin_match else (lambda argv: argv[1:])

    def match(argv):
        if not any(os.path.basename(a) == spec["script"] for a in cands(argv)):
            return False
        if extra and not any(a == extra for a in argv[1:]):
            return False
        return True

    return scan_pids(match, (spec["script"],) if bin_match else ())


def _log_tail_has_token(path, token):
    """日志最后一条「完整行」是否含 token（DEB57 判读矛盾门的证据读取位）。

    只读末尾 4KB；文件末行可能正被写者追加（半行），不算完整行。文件缺失/不可读/
    空一律 False——判不准即不启用门，方向=维持原判（绝不因证据读取失败放行假死）。"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 4096))
            chunk = f.read().decode("utf-8", "replace")
    except OSError:
        return False
    if not chunk:
        return False
    lines = chunk.splitlines()
    if not chunk.endswith("\n"):
        lines = lines[:-1]
    return bool(lines) and token in lines[-1]


# DEB57：and_mode 判读矛盾的记疑去重键（name -> 上次记疑 epoch；30min 一条防刷屏）
_last_conflict_note = {}


def _sha256_file(path):
    """文件 sha256（读不到 → None）。"""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def src_pin_verdict(spec, rel):
    """源码版本钉判据（2026-11-03 SIL 环修复批）：(ok, 说明)。

    对账两端：①盘上源文件此刻的 sha256；②在役守护在状态面登记的**载入时**源码
    指纹（st[spec["src_pin_state_key"]]["sha256"]，守护 v1.3.11 起每次写盘登记）。

    判据（不可证即不放过假绿）：
      · 两端一致 → (True)：在役判据＝盘上判据；
      · 指纹不等 → (False)：在役跑的是另一份判据（两套真相并行——修复落盘却不在役，
        且在役旧判据可能更宽松）→ 判死换码；
      · 状态面无指纹读数 → (False)：在役码早于版本钉机制（旧码，其判据无从核对）
        → 判死换码（新码起跑即登记）；
      · 盘上源文件读不到 → (True, 说明)：环境异常，判不准**不处置**（保持原判，
        避免把「源文件临时读不到」变成杀拉循环）。
    """
    src = os.path.join(WS, rel)
    disk = _sha256_file(src)
    if disk is None:
        return True, f"源码版本钉：盘上源码不可读（{rel}）——判不准，保持原判不处置"
    key = spec.get("src_pin_state_key") or "daemon_src"
    rec = None
    try:
        with open(spec["state"], "rb") as f:
            st = json.loads(f.read().decode("utf-8", "replace"))
        rec = ((st.get(key) or {}) or {}).get("sha256")
    except (OSError, ValueError, AttributeError, TypeError):
        rec = None
    if not rec:
        return False, (f"源码版本钉：在役守护未登记载入版本（状态面无 {key}.sha256——"
                       f"在役码早于版本钉机制，其判据无从核对）")
    if rec != disk:
        return False, (f"源码版本钉：在役载入版本 {str(rec)[:12]}… ≠ 盘上源码 "
                       f"{disk[:12]}…（在役判据≠盘上判据＝两套真相并行，修复未在役）")
    return True, f"源码版本钉：对齐（{disk[:12]}…）"


def check_guard(t, spec):
    """统一判活：进程在 + （状态文件新鲜 或 日志尾新鲜）。

    DEB-7：spec["and_mode"]=True 时改为状态文件单信号判死——
    quota-governor 的两信号同源（每轮同写），OR 会让「进程活但 quota.json 停写」
    逃过判活（恰是 DEB-7 要治的病：读数老化→配额闸误判 fail-closed）。
    and_mode 下状态文件新鲜是唯一裁决信号，日志尾不参与判死（仅经下方 DEB57
    判读矛盾门在「state 假死读数撞上日志尾 ok token」时改判存活）。
    DEB57：and_mode 且配了 spec["log_ok_token"] 时启用「判读矛盾门」——state 假死
    读数撞上日志尾 ok token（=poll() 已走完 os.replace(STATE)，mtime 必新鲜）即 stat
    假读数实锤，改判存活、只记疑不处置（不杀在役 daemon、不烧防抖窗）。
    **源码版本钉（2026-11-03 SIL 环修复批）**：spec["src_pin"] 非空时追加一条
    **必要条件**——在役守护载入的源码指纹（守护在状态面登记的 daemon_src.sha256）
    必须等于盘上该源文件此刻的 sha256；不等 ⇒ 在役判据≠盘上判据（两套真相并行：
    修复落盘却不在役，且在役旧判据可能更宽松——2026-11-03 实证：SIL 守护 06:53
    起跑、盘上 17:53 已改、17h 未重载＝轮4 SIL 修整体未在役）⇒ 判死 → 走 fix_guard
    拉起**新码**（本条即「修复落盘自动生效」的耐久性门）。判不准（源文件不可读 /
    状态面无版本钉读数）时**不放行假绿**：无版本钉读数＝在役码早于版本钉机制（旧码）
    ⇒ 判死并换码；源文件不可读属环境异常 ⇒ 保持原判不处置。"""
    name = spec["name"]
    pids = guard_pids(spec)
    if not pids:
        return False, f"进程不在（{spec['script']}）"
    if t - last_spawn.get(name, 0) < spec["grace_s"]:
        return True, f"grace 宽限内：进程={pids}（豁免新鲜度）"
    parts, fresh = [], False
    state_fresh = False
    if spec["state"]:
        a = file_age(spec["state"])
        parts.append(f"state_age={int(a) if a is not None else '缺失'}s")
        state_fresh = a is not None and a < spec["stale_s"]
        fresh = fresh or state_fresh
    a = file_age(spec["log"])
    parts.append(f"log_age={int(a) if a is not None else '缺失'}s")
    log_fresh = a is not None and a < spec["stale_s"]
    fresh = fresh or log_fresh
    if spec.get("and_mode"):
        # AND 语义=状态文件新鲜为必要条件（OR 判据会让「进程活但读数停更」逃过判活）；
        # 日志尾只作参考不参与裁决（避免「日志写不进去」把在役守护误杀成杀拉循环）
        fresh = state_fresh
        # DEB57 判读矛盾门：state 假死读数与日志尾 ok token 互斥（token 在最后一条
        # 完整行=poll() 刚走完 os.replace(STATE)），此时 stat 读数不可信——改判存活
        # 只记疑不处置。真病（停写）日志尾是 poll error、不含 token，门不启用。
        if not fresh and log_fresh and spec.get("log_ok_token") \
                and _log_tail_has_token(spec["log"], spec["log_ok_token"]):
            fresh = True
            state_desc = parts[0] if (spec["state"] and parts) else "state缺失"
            log_desc = parts[-1] if parts else "log缺失"
            parts.append(f"判读矛盾门→改判存活（日志尾含 {spec['log_ok_token']!r}"
                         f"=状态面必已重写，state 读数不可信，本轮不处置）")
            if t - _last_conflict_note.get(name, 0) > 1800:
                _last_conflict_note[name] = t
                klog(name, f"判读矛盾（已改判存活、不处置）：{state_desc} 与 {log_desc} "
                           f"同轮并存，且日志尾含 {spec['log_ok_token']!r}——"
                           f"poll ok ⇒ poll() 已 os.replace 状态文件，mtime 必新鲜，"
                           f"本轮 stat 读数不可信；不杀在役 daemon，需人工核查 state 读数"
                           f"（1800s 内不重复记）")
    # 源码版本钉（2026-11-03 SIL 环修复批）：在役载入版本 ≠ 盘上源码 ⇒ 判死换码。
    pin = spec.get("src_pin")
    if pin:
        ok_pin, why_pin = src_pin_verdict(spec, pin)
        parts.append(why_pin)
        if not ok_pin:
            return False, (f"进程={pids} " + " ".join(parts) +
                           f" fresh={fresh} 版本钉未对齐（判死→拉起新码）")
    return fresh, f"进程={pids} " + " ".join(parts) + f" fresh={fresh}"


def fix_guard(dry, t, deb, spec):
    """统一拉起：先清该守护的残留进程（同 argv basename 精确匹配，不用 pgrep -f），
    再用该守护的「在役启动行」拉起（cwd=WS、setsid 脱离、stdout/stderr 追加其日志）。"""
    name = spec["name"]
    for p in guard_pids(spec):
        if dry:
            klog(name, f"[dry-run] 将 kill 残进程 pid={p}")
        else:
            klog(name, f"杀残进程 pid={p}")
            kill_pid(p, name)
    cmd = list(spec["cmd"])
    if dry:
        klog(name, f"[dry-run] 将拉起: cwd={WS} cmd={' '.join(cmd)} "
                   f"log={spec['log_target']} setsid")
        return
    if spawn(name, cmd, spec["log_target"]):
        last_spawn[name] = t
        deb.record(name, t)
        mes_event(name, "keepalive_restart")


def pid_starttime(pid):
    """进程启动时刻（/proc/<pid>/stat 第 22 字段，clock tick）——用于多实例收敛时
    保留在役最久的那一个（其余杀掉）。取不到返回 None。"""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[19])
    except Exception:
        return None


def dedup_guards():
    """单实例收敛（DEB-3）：本机五守护里只有 self-improve-loop 自带 pidfile 守卫，
    router/scheduler/status-push/emit-sidecar 无守卫——两个监督者（keepalive 与
    factory-scheduler 自身的 DAEMONS 表）同时拉起同一守护时会留下双实例并发写同一
    状态文件（router 的 .router-state.json 4.9MB，双写即损坏）。故每轮把同守护的
    多实例收敛到恰好一个：保留启动最久者（老实例在役更久、其状态进度更可信），
    杀掉其余。只在确认多实例时动手，且不触发重启（避免与 factory-scheduler 的
    拉起互相打架形成杀拉循环）。"""
    for spec in LOCAL_GUARDS:
        # 账本一致批 2026-11-01：otelcol 免收敛——tools/otel-e2e-check.py:186 每次
        # 自起同名临时 otelcol（门内夹具），按 argv basename 与在役 collector 不可
        # 区分，收敛会误杀门夹具；otelcol 单实例本就由 run-collector.sh pidfile
        # 双启拒绝 + 绑定地址冲突（第二常驻实例 bind 4317/4318 失败即死）兜底。
        if spec.get("no_dedup"):
            continue
        pids = guard_pids(spec)
        if len(pids) < 2:
            continue
        starts = [(pid_starttime(p) or 0, p) for p in pids]
        starts.sort()
        keep, extra = starts[0][1], [p for _, p in starts[1:]]
        for p in extra:
            klog(spec["name"], f"多实例收敛：保留最老 pid={keep}，杀多余实例 pid={p}")
            kill_pid(p, spec["name"])


# ---- self-improve-loop（循环产线批-20261029）：判据同 watch 同构（进程在+state<300s）----
# 2026-10-30 DEB-3：self-improve-loop 并入 LOCAL_GUARDS 统一判据（state 或 log 双信号），
# 原 check_self_improve/fix_self_improve 已并入 check_guard/fix_guard（去重，不留两份实现）。


def check_dash(t):
    pids = dash_pids()
    return bool(pids), f"看板8790进程={pids or '无'}"


def fix_dash(dry, t, deb):
    dcmd = ["python3", "-m", "http.server", DASH_PORT,
            "--bind", "127.0.0.1", "--directory", DASH_DIR]
    if dry:
        klog("dash", f"[dry-run] 将拉起看板: cmd={' '.join(dcmd)} "
                     f"log=/tmp/factory-dash.log setsid")
        return
    klog("dash", "看板 http.server 8790 不在（watchdog 的连带件），拉起（绑 127.0.0.1）")
    if spawn("dash", dcmd, "/tmp/factory-dash.log"):
        last_spawn["dash"] = t
        deb.record("dash", t)
        mes_event("dash", "keepalive_restart")


# 完成态分支登记表 DRAIN_PROBES 已于 2026-11-01 红队回头批移除：表自 2026-10-26
# §三-2 起恒空，OBS-D6 只清了配套 check/fix 函数，其声称「已清理」的最后两处消费点
# （one_round 防抖超限放行、心跳 done 标注——因表恒空/对象不在 TARGETS 而不可达）
# 本次随表一并清理（零在役引用复核后删，clearly-dead 口径同 OBS-D6 C3）。


# ---------- ch-mes-local（补丁④：查询级探针，2026-10-22；只报警不拉起） ----------
# 背景：mes500 根因报告（计划/研究组/mes500-根因报告.md §4 C 组缺口 1）——/ping 探不到
# 查询级 500（10-21 两次 500 期间探针全程绿灯）。判活从"进程在场"升级为"真查询"：
# 一条极轻 SELECT（occurred_at 是 ORDER BY 首列，分钟级谓词只扫尾部 granule，
# 毫秒级零重活）。失败分四类给不同告警码（alarms.log code + klog + 去重键）：
#   conn     连接拒绝（端口失/进程死/tailnet 断）
#   auth     HTTP 401/403（凭据缺失/错误——0600 cred 文件与 mingda .pw 不同步）
#   query    HTTP 5xx（CH 查询错误，含 mes500 的 MEMORY_LIMIT_EXCEEDED 形态）
#   timeout  超时无响应（挂起/深内存压力/网络黑洞）
# 告警主通道仍是文件（klog/alarms.log）：CH 挂时照样可报，不落「用 MES 报 MES 挂」
# 悖论；MES kind=ch_mes_down 不变（schema 零改动），类别只在告警文件与 klog 区分。
CHMES_PROBE_SQL = ("SELECT count() FROM af_mes.mes_event "
                   "WHERE occurred_at > now() - INTERVAL 1 MINUTE")
CHMES_PROBE_TIMEOUT = 3      # 秒：正常毫秒级返回；3s 足以区分"慢"与"挂"
CHMES_ALARM_CODES = {"conn": "ch-mes-conn-refused", "auth": "ch-mes-auth",
                     "query": "ch-mes-query", "timeout": "ch-mes-timeout"}
CHMES_RECOVERY = {
    "conn": "恢复=mingda systemd 单元 clickhouse-factory.service（enabled+Restart=always，"
            "2026-10-22 14:28 起在役）应自动拉起；持续失联→人工 ssh mingda-bench "
            "systemctl start clickhouse-factory.service 或跑 /root/ch-mes-factory/start.sh，"
            "并查 tailnet/端口",
    "auth": "恢复=核对 0600 凭据文件 ~/.config/mes-ch/url 与 mingda .pw 是否同步",
    "query": "恢复=查 mingda system.errors（mes500 形态=服务端限额塌陷/查询错误），人工介入",
    "timeout": "恢复=查 mingda 负载与 tailnet 连通性；持续超时按 conn 处置",
}


def ch_mes_probe(timeout=CHMES_PROBE_TIMEOUT, url=None, auth=None, sql=None):
    """查询级探活：GET {url}/?query=<极轻 SELECT>，期待纯数字计数。

    返回 (ok, fail_class, detail)：fail_class ∈ None/'conn'/'auth'/'query'/'timeout'。
    连接参数缺省走 CH/CH_AUTH（=0600 cred 文件/env 解析值，口令不落明文）；入参可
    覆盖——四类失败演练用（错端口/错凭据/错 SQL/黑洞超时）。分类（urllib 异常族）：
      HTTPError 401/403 → auth；其他 HTTP 错误（CH 查询错=500）→ query
      socket.timeout/TimeoutError（含 URLError.reason 包装）→ timeout
      ConnectionRefusedError（含 URLError.reason）→ conn；其他 URLError → conn
    2xx 但响应体非纯数字 → query（服务端回了但不是计数=查询语义异常）。
    """
    url = CH if url is None else url
    auth = CH_AUTH if auth is None else auth
    sql = CHMES_PROBE_SQL if sql is None else sql
    target = f"{url}/?query={urllib.parse.quote(sql)}"
    try:
        req = urllib.request.Request(target)
        if auth:
            req.add_header("Authorization", auth)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace").strip()
            if re.fullmatch(r"\d+", body):
                return True, None, f"查询 Ok（近1分钟事件 count={body}）"
            return False, "query", f"HTTP {r.status} 响应体非计数: {body[:60]!r}"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, "auth", f"HTTP {e.code}（凭据缺失/错误）"
        return False, "query", f"HTTP {e.code}（CH 查询错误；mes500 同形态）"
    except (socket.timeout, TimeoutError):
        return False, "timeout", f"{timeout}s 超时无响应"
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return False, "timeout", f"{timeout}s 超时（{reason}）"
        if isinstance(reason, ConnectionRefusedError):
            return False, "conn", f"连接拒绝: {reason}"
        return False, "conn", f"连接失败: {reason}"
    except ConnectionRefusedError as e:
        return False, "conn", f"连接拒绝: {e}"
    except Exception as e:            # 未分类连接异常，保守归 conn（方向安全）
        return False, "conn", f"未分类异常: {e!r}"


def check_mes_ch(t):
    """mes-ch（mingda MES 查询级探针，2026-10-26 §三-2 由 ch-mes-local 更名，探针不变）。"""
    global last_chmes_fail
    ok, cls, detail = ch_mes_probe()
    last_chmes_fail = None if ok else (cls, detail)
    return ok, detail


def fix_mes_ch(dry, t, deb):
    """失联处置=只报警不拉起（跨机自动拉起越权，不做；恢复手段见 CHMES_RECOVERY）。
    2026-10-26 §三-2：由 fix_ch_mes_local 更名 mes-ch（探针/告警码/kind 全不变）。
    告警码按失败类别四选一（补丁④）；30min 去重，类别翻转立即重报（同窗内 conn 翻
    query 是质变，不该被去重吞掉）。"""
    global last_chmes_alarm, last_chmes_alarm_cls
    cls, detail = last_chmes_fail or ("conn", "（无分类信息）")
    code = CHMES_ALARM_CODES.get(cls, CHMES_ALARM_CODES["conn"])
    rec = CHMES_RECOVERY.get(cls, CHMES_RECOVERY["conn"])
    if dry:
        klog("mes-ch", f"[dry-run] 查询探针失联（类别={cls} 码={code}：{detail}）"
                       f"——将报警（klog + {ALARMS_LOG} + MES kind=ch_mes_down，"
                       f"{CHMES_DEDUP_S}s 去重），不拉起；{rec}")
        return
    if t - last_chmes_alarm < CHMES_DEDUP_S and cls == last_chmes_alarm_cls:
        return
    last_chmes_alarm, last_chmes_alarm_cls = t, cls
    klog("mes-ch", f"ALARM MES({CH}) 查询探针失联（类别={cls} 码={code}）：{detail}"
                   f"——不自动重启；{rec}；af 线 MES 落账将失败，"
                   f"需人工介入（{CHMES_DEDUP_S}s 内同类别不重复报）")
    try:
        with open(ALARMS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": now_s(), "level": "red", "code": code,
                "message": f"MES({CH}) 查询探针失联（类别={cls}）：{detail}；{rec}",
                "since": time.strftime("%F %T", time.localtime(t)),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    mes_event("mes-ch", "ch_mes_down")


# ---------- af-execline（2026-10-26 §三-2 退役改造新增：af 统一执行面判活） ----------
# 背景：旧 bench 链退役（ADR-008，runbook §三-2）。af 执行面=订单驱动（af-order submit
# → af-execline 执行 → af-mes 记账），非守护进程——判活取双通道：①/proc 扫描 argv
# basename∈{af-order,af-execline}（释放件与 cargo run 形态同 basename；本机通道，
# 生产 af 进程在 anolis——OBS-D4 范围边界登记）；②生产真值根 anolis:/data/bench/
# af-p3-state/orders/ 最新订单目录 mtime（订单生命周期内落件即心跳；OBS-D4
# 2026-10-31 由本地 WS/af-state/orders 改读真值根，旧根冻结致产线在跑仍报空闲）。
# 心跳窗 72h=订单节奏日级+观察期跨天判据 3 天（=runbook §六-3 观察期权威定义的时长：
# 起算 2026-10-26 01:05:52、期满 2026-10-29 01:05:52；红队 W2-C17 统一 2026-10-27。
# 施工参数，登记 退役执行记录-20261026.md，可调——调整须同步 runbook 权威定义）。
# 失联处置=只报警不拉起（amber 级：订单驱动面空闲≠故障；30min 去重）——klog+
# alarms.log（code=af-execline-idle）+ MES kind=af_plane_idle（写失败不致命）。
AF_EXEC_NAME = "af-execline"
# OBS-D4（2026-10-31）判活读根对齐生产真值根：旧根 AF_STATE_ORDERS=本地
# WS/af-state/orders（15 单 F 系，2026-10-25 22:03 后冻结）与生产 ledger 根脱节
# （收口 20261029 §附-3：产线在跑仍报空闲，10-28 22:03 起持续 amber）。生产真值根
# =anolis /data/bench/af-p3-state/orders（2026-10-31 实测 1032 单、当日 10:50 仍在
# 落账；ssh 别名 anolis=pan-ding@anolis-host.invalid，~/.ssh/config）。
AF_PROD_ORDERS_HOST = "anolis"
AF_PROD_ORDERS_DIR = "/data/bench/af-p3-state/orders"
AF_PROD_SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
               AF_PROD_ORDERS_HOST]
AF_LEDGER_FRESH_S = 72 * 3600
AF_IDLE_ALARM_DEDUP_S = 1800
last_af_idle_alarm = 0.0
# OBS回头-RT 2026-11-01（OBS-D4 J3.3 报警面补齐）：one_round 同轮 CHECKS→FIXES 顺序
# 执行、单线程无交错——check 落下最近明细供 fix 按真实成因措辞（真值根不可达≠心跳
# 超窗，报警面不再对不可达分支写静态「超 72h」失实文案）。
last_af_exec_detail = ""


def af_plane_pids():
    """af-order/af-execline 进程扫描（不限 python——释放件是原生二进制）。"""
    out = []
    for ent in os.listdir("/proc"):
        if not ent.isdigit():
            continue
        argv = pid_argv(int(ent))
        if not argv:
            continue
        # 只认 argv[0] basename（释放件与 cargo run 产物形态同 basename，判活语义不变）；
        # 原 argv[1:] 任一参数 basename 宽匹配于 2026-11-01 红队回头批移除——
        # cp/grep 等以 af-order/af-execline 为参数的无关命令行会被误判「订单在飞」。
        if os.path.basename(argv[0]) in ("af-order", "af-execline"):
            out.append(int(ent))
    return sorted(out)


def latest_order_ledger_age():
    """生产真值根最新订单目录 mtime 距今秒数（OBS-D4 2026-10-31 由本地
    af-state/orders 改读 anolis:/data/bench/af-p3-state/orders——旧根与生产
    脱节致产线在跑仍报空闲）。ssh 单次往返 find -printf %T@ 取最大（生产根
    1000+ 目录量级）；ConnectTimeout=5+subprocess timeout=15+stdin=DEVNULL
    （同文件 proxy8124 ssh 探针姿势，DEB-1 超时纪律）。
    ssh 失败/根缺失/输出非法 → None（判不准 → 报警方向不变，不谎报在跑）。"""
    cmd = (f"find {AF_PROD_ORDERS_DIR} -mindepth 1 -maxdepth 1 -type d "
           f"-printf '%T@\\n' | sort -rn | head -1")
    try:
        r = subprocess.run(AF_PROD_SSH + [cmd], capture_output=True, text=True,
                           timeout=15, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    if not lines:
        return None
    try:
        newest = float(lines[0])
    except ValueError:
        return None
    return time.time() - newest


def check_af_execline(t):
    global last_af_exec_detail
    pids = af_plane_pids()
    if pids:
        last_af_exec_detail = f"进程={pids}（订单在飞）"
        return True, last_af_exec_detail
    age = latest_order_ledger_age()
    fresh = age is not None and age < AF_LEDGER_FRESH_S
    root_s = f"{AF_PROD_ORDERS_HOST}:{AF_PROD_ORDERS_DIR}"
    if age is None:
        last_af_exec_detail = f"生产订单 ledger 真值根不可达/读取失败（{root_s}）"
        return False, last_af_exec_detail
    last_af_exec_detail = (f"无本机 af 进程；生产订单 ledger 心跳 {int(age)}s 前"
                           f"（窗 {AF_LEDGER_FRESH_S}s，根={root_s}）")
    return fresh, last_af_exec_detail


def fix_af_execline(dry, t, deb):
    """订单驱动面空闲：只报警不拉起（amber，30min 去重）。恢复=经 af-order 正常下单。
    OBS回头-RT 2026-11-01（OBS-D4 J3.3 报警面补齐）：报文按 check 真实成因措辞——
    真值根不可达分支如实写「真值根不可达/读取失败」，不再一律写「心跳超 72h」。"""
    global last_af_idle_alarm
    unreachable = "真值根不可达" in last_af_exec_detail
    cause = ("生产订单 ledger 真值根不可达/读取失败" if unreachable else
             f"订单 ledger 心跳超 {AF_LEDGER_FRESH_S // 3600}h")
    if dry:
        klog(AF_EXEC_NAME, f"[dry-run] af 执行面无进程且{cause}——将报警"
                           f"（amber，{AF_IDLE_ALARM_DEDUP_S}s 去重），不拉起（订单驱动型非守护）")
        return
    if t - last_af_idle_alarm < AF_IDLE_ALARM_DEDUP_S:
        return
    last_af_idle_alarm = t
    klog(AF_EXEC_NAME, f"ALARM af 执行面空闲（无 af-order/af-execline 进程且{cause}）"
                       "——不自动拉起（订单驱动型，空闲≠故障）；"
                       "恢复=经 af-order 正常下单（下单即恢复心跳）")
    try:
        with open(ALARMS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": now_s(), "level": "amber", "code": "af-execline-idle",
                "message": f"af 执行面空闲：无 af-order/af-execline 进程且{cause}；"
                           "订单驱动型不自动拉起，恢复=经 af-order 正常下单",
                "since": time.strftime("%F %T", time.localtime(t)),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    mes_event(AF_EXEC_NAME, "af_plane_idle")


# ---------- gov 公网门户（RT 收口批 2026-11-02：第八看护对象，首个远程对象） ----------
# 判据/边界/处置的完整论证见文件头「RT 收口批」段。要点：三签名（healthz /
# tasks 信封 / 在役进程 env 含 AF_JOBS_DATA）；ssh 不可达不据未知动手；自愈经
# gov:/opt/company/af-jobs/start-portal.sh（11-02 事故修复物，AF_JOBS_DATA 内嵌）。
PORTAL_SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "root@gov-host.invalid"]
PORTAL_BASE = "http://gov-host.invalid:8090"
PORTAL_START_SH = "/opt/company/af-jobs/start-portal.sh"
PORTAL_PROBE_TIMEOUT = 8    # HTTP 探针单请求超时（s）
PORTAL_SSH_TIMEOUT = 15     # ssh 读 env 子进程帽（s，DEB-1 超时纪律同 latest_order_ledger_age）
PORTAL_RESTART_TIMEOUT = 60  # 重启动作子进程帽：杀旧 ≤10s + 验活环 ≤20s + ssh/余量
PORTAL_GRACE_S = 90         # 拉起后判活宽限（远端冷启动+首刷）
PORTAL_ALARM_DEDUP_S = 1800  # alarms.log 去重窗（同 mes-ch/af-execline）
# 与 factory-watch.py _portal_env_state 同口径双写（两文件互不 import——keepalive
# 顶层带 otel 装载副作用；watch 侧同款 smith 先例见其 PORTAL_ENV_SH 注释）。
# pid 遴选必须过 argv0==python3 过滤（实证见 watch 侧 PORTAL_ENV_SH 注释：
# pgrep [p] 括号法防不了重启命令的残留 bash 包装壳，head -1 会误选）。
PORTAL_ENV_SH = r'''
pid=""
for p in $(pgrep -f '[p]ython3 af-jobs-portal.py' 2>/dev/null); do
  a0="$(tr '\0' '\n' < "/proc/$p/cmdline" 2>/dev/null | head -1)"
  if [ "$a0" = "python3" ]; then pid="$p"; break; fi
done
if [ -z "$pid" ]; then
  echo "NOPROC"
elif tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep -q '^AF_JOBS_DATA='; then
  echo "OK pid=$pid"
else
  echo "MISSING pid=$pid"
fi
'''
# 拉起动作：杀旧（TERM→10s→SIGKILL 补刀，只杀 argv0==python3 的在役进程——
# 包装壳/无关进程不碰）→ start-portal.sh setsid 脱离拉起（stdout/stderr 追加
# portal-run.log、stdin=DEVNULL——ssh 会话退出不带走进程，等价于本地 spawn()
# 的 setsid 姿势）→ 远端 curl /healthz 验活环 ≤20s（healthz 为最终裁决）。
PORTAL_RESTART_SH = r'''
pids=""
for p in $(pgrep -f '[p]ython3 af-jobs-portal.py' 2>/dev/null); do
  a0="$(tr '\0' '\n' < "/proc/$p/cmdline" 2>/dev/null | head -1)"
  if [ "$a0" = "python3" ]; then pids="$pids $p"; fi
done
if [ -n "$pids" ]; then
  kill $pids 2>/dev/null
  left="$pids"
  for i in 1 2 3 4 5 6 7 8 9 10; do
    left=""
    for p in $(pgrep -f '[p]ython3 af-jobs-portal.py' 2>/dev/null); do
      a0="$(tr '\0' '\n' < "/proc/$p/cmdline" 2>/dev/null | head -1)"
      if [ "$a0" = "python3" ]; then left="$left $p"; fi
    done
    [ -z "$left" ] && break
    sleep 1
  done
  for p in $left; do kill -9 "$p" 2>/dev/null; done
  sleep 1
fi
setsid nohup bash /opt/company/af-jobs/start-portal.sh \
  >> /opt/company/af-jobs/portal-run.log 2>&1 < /dev/null &
hz="FAIL"
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  sleep 1
  c="$(curl -s -m 3 http://127.0.0.1:8090/healthz 2>/dev/null || true)"
  if printf '%s' "$c" | grep -q '"ok":true'; then hz="$c"; break; fi
done
echo "HEALTHZ=$hz"
'''

last_portal_restart = 0.0   # 最近一次拉起动作 epoch（宽限判据；重启复位只多探一轮）
last_portal_alarm = 0.0     # alarms.log portal-down 去重（本进程自有状态键）
last_portal_detail = ""     # check→fix 传递（one_round 单线程同轮有序，同 last_af_exec_detail）


def _portal_get(url):
    """门户 GET 探针原语。返回 (ok, code_desc, body)；异常分类同 ch_mes_probe
    （http/timeout/conn），不吞不谎报。"""
    try:
        with urllib.request.urlopen(url, timeout=PORTAL_PROBE_TIMEOUT) as r:
            return True, f"HTTP {r.status}", r.read(65536).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read(512).decode("utf-8", "replace")
        except Exception:
            body = ""
        return False, f"HTTP {e.code}", body
    except (socket.timeout, TimeoutError):
        return False, "timeout", f"{PORTAL_PROBE_TIMEOUT}s 超时无响应"
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return False, "timeout", f"{PORTAL_PROBE_TIMEOUT}s 超时（{reason}）"
        return False, "conn", f"连接失败: {reason}"
    except ConnectionRefusedError as e:
        return False, "conn", f"连接拒绝: {e}"
    except Exception as e:            # 未分类，保守归 conn（方向安全，同 ch_mes_probe）
        return False, "conn", f"未分类异常: {e!r}"


def portal_env_state():
    """③ 进程 env 签名（11-02 事故根因签名；wrong-data-dir 下 ①② 照样全绿的盲区
    由本读数收口）。返回 (st, why)：st ∈ {"ok","missing","unknown"}——ssh 不可达/
    读数不可识别=unknown（判不准不假报、不据未知动手）。"""
    try:
        r = subprocess.run(PORTAL_SSH + [PORTAL_ENV_SH], capture_output=True,
                           text=True, timeout=PORTAL_SSH_TIMEOUT,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return "unknown", f"ssh 读 env 失败（{type(e).__name__}）"
    if r.returncode != 0:
        return "unknown", f"ssh rc={r.returncode}"
    lines = [l for l in (r.stdout or "").splitlines() if l.strip()]
    line = lines[-1] if lines else ""
    if line.startswith("OK"):
        return "ok", line
    if line.startswith("MISSING"):
        return "missing", f"{line}（environ 无 AF_JOBS_DATA）"
    if line == "NOPROC":
        return "missing", "gov 在役进程不在（pgrep 'python3 af-jobs-portal.py' 空）"
    return "unknown", f"读数不可识别（{line[:60]!r}）"


def check_portal(t):
    """门户判活（三签名）。返回 (alive, detail)。拉起宽限内（PORTAL_GRACE_S）豁免
    三签名只看「刚被本脚本拉起」这一事实（同 check_guard 的 grace 语义）。"""
    global last_portal_detail
    if t - last_portal_restart < PORTAL_GRACE_S:
        last_portal_detail = f"拉起宽限内（{PORTAL_GRACE_S}s，豁免三签名）"
        return True, last_portal_detail
    reasons = []
    h_ok, h_code, h_body = _portal_get(f"{PORTAL_BASE}/healthz")
    healthz = False
    if h_ok:
        try:
            doc = json.loads(h_body.strip())
            healthz = isinstance(doc, dict) and doc.get("ok") is True
        except ValueError:
            healthz = False
    if not healthz:
        reasons.append(f"healthz 探针失败（{h_code}: {h_body[:60]!r}）" if not h_ok
                       else f"healthz 响应体非 ok:true（{h_body[:60]!r}）")
    t_ok, t_code, t_body = _portal_get(f"{PORTAL_BASE}/tasks.json?status=open&limit=1")
    open_total = None
    if t_ok:
        try:
            doc = json.loads(t_body)
            if isinstance(doc, dict) and isinstance(doc.get("total"), int):
                open_total = doc["total"]
            elif isinstance(doc, list):
                open_total = len(doc)   # 旧版门户裸数组（回滚形态）也算数据面在
        except ValueError:
            open_total = None
    if open_total is None:
        reasons.append(f"tasks.json 信封不可解析/非数据面形状（{t_code if not t_ok else '形状不符'}）")
    env_st, env_why = portal_env_state()
    if env_st == "missing":
        reasons.append(f"进程 env 缺 AF_JOBS_DATA（{env_why}）——11-02 板面全零事故同款根因签名")
    if reasons:
        if env_st == "unknown" and healthz and open_total is not None:
            reasons.append(f"env 未验证（{env_why}）——HTTP 面已过，仅注记不判死")
        last_portal_detail = "；".join(reasons)
        return False, last_portal_detail
    last_portal_detail = (f"healthz 200 ok:true｜tasks 信封 total={open_total}"
                          + ("｜env AF_JOBS_DATA 在位" if env_st == "ok"
                             else f"｜env 未验证（{env_why}）"))
    return True, last_portal_detail


def _portal_alarm(t, msg):
    """portal-down 红牌落三面：klog + alarms.log（1800s 去重）+ MES（写失败不致命）。"""
    global last_portal_alarm
    if t - last_portal_alarm < PORTAL_ALARM_DEDUP_S:
        return
    last_portal_alarm = t
    klog("portal", f"ALARM {msg}")
    try:
        with open(ALARMS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": now_s(), "level": "red", "code": "portal-down",
                "message": f"gov 公网门户（jobs.hkmingdajiaoyu.com 宿主）{msg}",
                "since": time.strftime("%F %T", time.localtime(t)),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    mes_event("portal", "portal_down")


def fix_portal(dry, t, deb):
    """门户失联处置（远程自愈，边界论证见文件头）：ssh gov 杀旧进程 → start-portal.sh
    setsid 拉起（AF_JOBS_DATA 内嵌）→ 远端 curl /healthz 验活环。ssh 不可达时
    （env 读数 unknown 且非 env 缺失型判死）不越权动手，只报警（mes-ch 同款纪律）。
    Debounce 由 one_round 统一把关（600s 窗 2 次，超限只报警）。"""
    global last_portal_restart
    if dry:
        klog("portal", f"[dry-run] 将 ssh {PORTAL_SSH[-1]} 杀旧进程并经 "
                       f"gov:{PORTAL_START_SH} setsid 拉起（远端 healthz 验活环 ≤20s）"
                       f"｜本轮判据：{last_portal_detail or '（无明细）'}")
        return
    env_st, env_why = portal_env_state()
    if env_st == "unknown" and "env 缺 AF_JOBS_DATA" not in last_portal_detail:
        _portal_alarm(t, f"判活失败且 gov ssh 不可达，无法自动拉起（越权纪律：不据未知动手）"
                         f"：{last_portal_detail}；{env_why}——需人工介入")
        return
    klog("portal", f"门户失联 → 处置（ssh gov 杀旧 + start-portal.sh 拉起 + 验活）："
                   f"{last_portal_detail}")
    try:
        r = subprocess.run(PORTAL_SSH + [PORTAL_RESTART_SH], capture_output=True,
                           text=True, timeout=PORTAL_RESTART_TIMEOUT,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        # 不设宽限：OSError=动作未发出（下一轮照常复判）；TimeoutExpired=动作可能
        # 半途——下轮复判交 Debounce 把关，报警去重窗防刷屏
        deb.record("portal", t)
        _portal_alarm(t, f"拉起动作子进程失败（{type(e).__name__}）需人工核实："
                         f"{last_portal_detail}")
        return
    last_portal_restart = time.time()
    deb.record("portal", t)
    mes_event("portal", "keepalive_restart")
    out = [l for l in (r.stdout or "").splitlines() if l.strip()]
    hz = out[-1] if out else ""
    if hz.startswith("HEALTHZ=") and '"ok":true' in hz:
        klog("portal", f"拉起完成，远端 healthz 验活过（{hz[:80]}）")
    else:
        _portal_alarm(t, f"已发拉起动作但远端 healthz 验活未过（{hz[:80] or '无输出'}）"
                         f"——需人工核实 portal-run.log；原判据：{last_portal_detail}")


# ---------- trigger-inbox（生产接线批 2026-11-03：第九看护对象，只判活不拉起） ----------
# 判据/边界/处置的完整论证见文件头「生产接线批」段。要点：进程在 + AF_TRIGGER_HOME
# 收件箱目录可写 + 在役 environ 含段B secret（缺 secret=安全缺省不判活）；
# 拉起闸=systemd --user 常驻单元 af-trigger-inbox.service（2026-11-05 常驻化批，
# Restart=always 自动拉起；见文件头「常驻化批」段），本守护失联只报警不动手。
TRIGGER_INBOX_SCRIPT = "trigger-inbox.py"
TRIGGER_INBOX_SECRET_ENV = "AF_TRIGGER_SECRET_GITEA_WEBHOOK"
TRIGGER_INBOX_ALARM_DEDUP_S = 1800
last_ti_alarm = 0.0
last_ti_detail = ""      # check→fix 传递（one_round 单线程同轮有序，同 last_af_exec_detail）

# ---------- 源断供安灯：判据④（v0.3-T5②/T6③ 常驻批 2026-11-04 新增，只加不改） ----------
# 本条安灯存在的**全部理由**＝把两种失联形态分家（既有码 vs 新码，物理隔离）：
#   形态A 收件箱进程不在        → 既有码 trigger-inbox-down（fix_trigger_inbox 既有报警行**逐字不动**）
#   形态B 收件箱进程在但源头断供  → 新码 trigger-inbox-source-silent（本段）
# 判据④ 只在①②③全过（进程在+目录可写+secret 在位）时评估 ⇒ 形态A 时新码**不出现**
# （新码永不覆盖既有 down 码）。
# 落面：①判据文件 状态观测/trigger-inbox-source-silent.json（原子写，机器可读，
#   与事件路由那份 trigger-inbox-liveness.json 同机制、不同文件、不互相覆盖）；
#   ②alarms.log 摘要行（1800s 去重，同既有失联报警节奏）+ MES 事件（同既有面口径）。
# 起算锚点 = max(最新投递 mtime, 在役进程启动时刻)——刚拉起还没来事件的收件箱不冤枉。
TRIGGER_INBOX_SILENT_CODE = "trigger-inbox-source-silent"
TRIGGER_INBOX_SILENT_ALARM_DEDUP_S = 1800
TRIGGER_INBOX_SILENT_DEFAULT_MIN = 240     # 注册表缺 liveness 时的回落阈（配方缺省）
TRIGGER_INBOX_SILENT_F = os.environ.get(
    "AF_TRIGGER_SILENT_F", f"{WS}/状态观测/trigger-inbox-source-silent.json")
TRIGGER_INBOX_ALARMS_LOG = os.environ.get("AF_TRIGGER_ALARMS_LOG", ALARMS_LOG)
last_ti_silent_alarm = 0.0


def trigger_inbox_pids():
    return scan_pids(lambda argv: any(os.path.basename(a) == TRIGGER_INBOX_SCRIPT
                                      for a in argv[1:]))


def _proc_environ_get(pid, key):
    """读 /proc/<pid>/environ 里的 key= 值；进程消失/读不到 → None（判不准不假绿）。"""
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            for kv in f.read().split(b"\0"):
                if kv.startswith(key.encode() + b"="):
                    return kv[len(key) + 1:].decode("utf-8", "replace")
    except OSError:
        return None
    return None


def _trigger_inbox_silent_threshold(home):
    """源断供阈值（**配方驱动**：读在役注册表运行位 <home>/registry.json 的
    liveness.inbox_silent_after_min）；缺 liveness/缺该项 → 回落 240
    （显式 None 判——0 是合法阈值，falsy 不吞）；注册表读不到/坏 → None（不可证）。
    秘密纪律：本函数**只读阈值**，注册表本身不含秘密（key_id 只作指向）。"""
    try:
        with open(os.path.join(home, "registry.json"), encoding="utf-8") as f:
            reg = json.load(f)
    except Exception:
        return None
    if not isinstance(reg, dict):
        return None
    thr = (reg.get("liveness") or {}).get("inbox_silent_after_min")
    if thr is None:
        return float(TRIGGER_INBOX_SILENT_DEFAULT_MIN)
    try:
        return float(thr)
    except (TypeError, ValueError):
        return None


def _trigger_inbox_newest_delivery(inbox_dir):
    """收件箱最新一投递的落盘时刻（epoch 秒）；无投递 → 0.0（只读扫描，不写面）。"""
    newest = 0.0
    try:
        for src_dir in os.scandir(inbox_dir):
            if not src_dir.is_dir():
                continue
            for f in os.scandir(src_dir.path):
                if not f.name.endswith(".json"):
                    continue
                try:
                    newest = max(newest, f.stat().st_mtime)
                except OSError:
                    pass
    except OSError:
        pass
    return newest


def _trigger_inbox_criterion_write(snap):
    """判据文件原子写（tmp+os.replace，事件路由安灯同款）；写失败不阻塞看护轮。"""
    try:
        os.makedirs(os.path.dirname(TRIGGER_INBOX_SILENT_F), exist_ok=True)
        tmp = TRIGGER_INBOX_SILENT_F + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)
        os.replace(tmp, TRIGGER_INBOX_SILENT_F)
    except OSError:
        pass


def _trigger_inbox_silent_state_raw(pids, home, t, process_alive, healthy, note):
    """形态判定 + 判据文件落盘 + 新码报警（形态A 不发新码 ⇒ 不覆盖既有 down 码）。

    返回 (status, alarm_code, silent_s, thr_min)：
      down     = 形态A（进程不在）——报警仍由既有 trigger-inbox-down 行负责
      degraded = 进程在但不健康（②③ 失败）——不判源断供
      unknown  = 不可证（阈值/锚点读不到）——**不报绿也不报琥珀**（fail-closed）
      amber    = 形态B（进程在 + 最新投递超阈）——新码 trigger-inbox-source-silent
      green    = 形态B 的健康侧
    """
    global last_ti_silent_alarm
    inbox_dir = os.path.join(home, "inbox")
    thr_min = _trigger_inbox_silent_threshold(home)
    newest = _trigger_inbox_newest_delivery(inbox_dir)
    proc_started = proc_start_epoch(pids[0], boot_time()) if pids else None
    # 起算锚点（**与路由侧那份 trigger-inbox-liveness 不同义**，此处按收件箱自身口径）：
    #   有投递 → 锚点=最新投递 mtime（投递只增不删 ⇒ 进程重启**不掩盖**既有断供；
    #           若用 max(投递, 进程启动) 则每次重启都会把断供时钟清零，源断供永报不出）
    #   无投递 → 锚点=在役进程启动时刻（刚部署还没事件，不冤枉）
    since = newest if newest else (proc_started or 0)
    silent_s = int(t - since) if since else None
    if not process_alive:
        status, code = "down", "trigger-inbox-down"
        msg = ((note or "进程不在") + "——形态A（收件箱进程不在）；本形态的报警由既有 "
               "trigger-inbox-down 报警行负责，本判据行**不覆盖既有码**")
    elif not healthy:
        status, code = "degraded", None
        msg = (note or "收件箱不健康") + "——第三形态（进程在但不健康）；不判源断供"
    elif thr_min is None or silent_s is None:
        status, code = "unknown", None
        msg = "不可证（阈值或起算锚点读不到）——不报绿也不报琥珀（fail-closed）"
    elif silent_s > thr_min * 60:
        status, code = "amber", TRIGGER_INBOX_SILENT_CODE
        msg = (f"trigger-inbox 源断供：收件箱进程在（pid={list(pids)} home={home}）但最新"
               f"投递距今 {silent_s // 60}min（>阈 {int(thr_min)}min）——形态B（源头无事件"
               f"可路由）；恢复=事件源重投/查 webhook 出口；与『进程不在』"
               f"（trigger-inbox-down）**分码**")
    else:
        status, code = "green", None
        msg = (f"收件箱活性正常（最新投递 {silent_s // 60}min 前，阈 {int(thr_min)}min）"
               "——形态B 的健康侧")
    # ---- D-114（factory-os#82，M5 收口）合成心跳读数（**只增**：状态/码判定逻辑
    # 零改动，消息注记+快照新键）——「源静默」与「收端侧坏」自此可分辨（探针
    # 写入方=trigger-inbox 端到端合成心跳，状态件=同 HOME 目录
    # synthetic-heartbeat.json；探针新鲜=last_ok 距今≤其自报 fresh_window_s）。
    probe = None
    try:
        with open(os.path.join(home, "synthetic-heartbeat.json"), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            probe = d
    except Exception:
        probe = None
    probe_fresh = None
    probe_ok_age_s = None
    if probe:
        ok_ep = probe.get("last_ok_epoch")
        fw = probe.get("fresh_window_s")
        if isinstance(ok_ep, (int, float)) and ok_ep > 0 \
                and isinstance(fw, (int, float)) and fw > 0:
            probe_ok_age_s = max(0, int(t - ok_ep))
            probe_fresh = probe_ok_age_s <= fw
    if status in ("amber", "green"):
        if probe_fresh is True:
            msg += (f"；合成心跳新鲜（收端自证活，last_ok {probe_ok_age_s}s 前）"
                    "→ 静默归**上游侧**（Gitea 无事件/发射腿断——发射腿探针属 "
                    "night-sentinel 哨兵域，卡面交接夜轨B）")
        elif probe_fresh is False:
            msg += ("；合成心跳过期/连败（**收端接收链可疑**——比源静默更严重一档，"
                    "查收件箱 HTTP 面/secret/落盘链；写入方=trigger-inbox 合成心跳）")
        else:
            msg += ("；合成心跳读数不可证（探针未在役或状态件缺/坏——"
                    "收端自证缺失，fail-closed 不当活）")
    snap = {"ts": now_s(), "ts_epoch": int(t), "tool": "factory-keepalive/trigger-inbox",
            "status": status, "alarm_code": code, "message": msg,
            "process_alive": bool(process_alive), "healthy": bool(healthy),
            "silent_s": silent_s,
            "threshold_min": (int(thr_min) if thr_min is not None else None),
            "inbox_dir": inbox_dir, "pids": list(pids or []),
            # D-114 合成心跳读数（只增键；旧消费方未知键不崩）
            "probe_status": (probe or {}).get("status"),
            "probe_fresh": probe_fresh,
            "probe_ok_age_s": probe_ok_age_s,
            "probe_consecutive_fail": (probe or {}).get("consecutive_fail"),
            "newest_delivery_epoch": (int(newest) if newest else None),
            "process_started_epoch": (int(proc_started) if proc_started else None),
            "since_epoch": (int(since) if since else None),
            "note": "写入方=factory-keepalive 判据行④；形态A 的真实报警仍由既有 "
                    "trigger-inbox-down 报警行发出（既有码/既有行零改动）"}
    _trigger_inbox_criterion_write(snap)
    if status == "amber" and (t - last_ti_silent_alarm) >= TRIGGER_INBOX_SILENT_ALARM_DEDUP_S:
        last_ti_silent_alarm = t
        try:
            with open(TRIGGER_INBOX_ALARMS_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": now_s(), "level": "amber", "code": TRIGGER_INBOX_SILENT_CODE,
                    "message": msg + "；不自动拉起（拉起闸=systemd --user 常驻单元 "
                                   "af-trigger-inbox.service，Restart=always）",
                    "since": time.strftime("%F %T", time.localtime(since)),
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass
        mes_event("trigger-inbox", "trigger_inbox_source_silent")
    return status, code, silent_s, thr_min


def _trigger_inbox_silent_state(pids, home, t, process_alive, healthy, note):
    """判据④ 入口（**永不抛异常**：本判据行不得带崩看护轮，既有护栏口径）。"""
    try:
        return _trigger_inbox_silent_state_raw(pids, home, t, process_alive, healthy, note)
    except Exception as e:
        klog("trigger-inbox", f"源断供判据行异常（不阻塞看护轮）: "
                              f"{type(e).__name__}: {str(e)[:120]}")
        return "unknown", None, None, None


def check_trigger_inbox(t):
    """trigger-inbox 判活（进程在 + inbox 目录可写 + 段B secret 在役）。返回 (alive, detail)。"""
    global last_ti_detail
    pids = trigger_inbox_pids()
    if not pids:
        last_ti_detail = ("进程不在（trigger-inbox.py；拉起闸=systemd --user 常驻单元 "
                          "af-trigger-inbox.service，Restart=always 应由 systemd 自动拉起；"
                          "本守护只报警不重复拉起）")
        # 判据④（新增）：形态A 只镜像状态到判据文件，**不发新码**
        # （既有 trigger-inbox-down 报警行仍由 fix_trigger_inbox 负责，逐字不动）
        _trigger_inbox_silent_state([], f"{WS}/af-state/triggers", t,
                                    process_alive=False, healthy=False,
                                    note=last_ti_detail)
        return False, last_ti_detail
    home = _proc_environ_get(pids[0], "AF_TRIGGER_HOME") or f"{WS}/af-state/triggers"
    inbox_dir = os.path.join(home, "inbox")
    try:
        os.makedirs(inbox_dir, exist_ok=True)
    except OSError as e:
        last_ti_detail = f"收件箱目录不可建/不可写（{inbox_dir}: {e}）"
        _trigger_inbox_silent_state(pids, home, t, process_alive=True, healthy=False,
                                    note=last_ti_detail)
        return False, last_ti_detail
    if not os.access(inbox_dir, os.W_OK):
        last_ti_detail = f"收件箱目录不可写（{inbox_dir}）"
        _trigger_inbox_silent_state(pids, home, t, process_alive=True, healthy=False,
                                    note=last_ti_detail)
        return False, last_ti_detail
    if not _proc_environ_get(pids[0], TRIGGER_INBOX_SECRET_ENV):
        last_ti_detail = (f"进程={pids} 在役缺段B secret（{TRIGGER_INBOX_SECRET_ENV}）"
                          "——收件箱 fail-closed 必 401，缺 secret 不判活（安全缺省）")
        _trigger_inbox_silent_state(pids, home, t, process_alive=True, healthy=False,
                                    note=last_ti_detail)
        return False, last_ti_detail
    # 判据④（新增）：形态B 判定（源断供）——只在①②③全过时评估
    _trigger_inbox_silent_state(pids, home, t, process_alive=True, healthy=True, note="")
    last_ti_detail = f"进程={pids} home={home} inbox 可写 secret 在位"
    return True, last_ti_detail


def fix_trigger_inbox(dry, t, deb):
    """失联处置=只报警不拉起（amber，1800s 去重）。

    拉起闸=systemd --user 常驻单元 af-trigger-inbox.service（2026-11-05 常驻化批，
    B清单§三-1：Restart=always+KillMode=process，EnvironmentFile 解绑人工串行）：
    进程死由 systemd 10s 内自动拉起，本守护**不重复拉起**（双勾起才叫双开）。
    持续失联（进程反复不在）=单元级故障（env 缺 secret/bind 拒起/单元未 enable），
    报警恢复指引=systemctl --user status af-trigger-inbox.service。
    """
    global last_ti_alarm
    if dry:
        klog("trigger-inbox", f"[dry-run] 判据：{last_ti_detail or '（无明细）'}"
                              "——将报警（amber，1800s 去重），不拉起（拉起闸=af-trigger-inbox.service 常驻单元）")
        return
    if t - last_ti_alarm < TRIGGER_INBOX_ALARM_DEDUP_S:
        return
    last_ti_alarm = t
    klog("trigger-inbox", f"ALARM trigger-inbox 失联：{last_ti_detail}"
                          "——不自动拉起（拉起闸=af-trigger-inbox.service 常驻单元自动拉起）；"
                          "恢复=systemctl --user status af-trigger-inbox.service 查单元级故障")
    try:
        with open(ALARMS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": now_s(), "level": "amber", "code": "trigger-inbox-down",
                "message": f"trigger-inbox 失联：{last_ti_detail}；不自动拉起"
                           "（拉起闸=af-trigger-inbox.service 常驻单元，Restart=always）；"
                           "持续失联恢复=systemctl --user status af-trigger-inbox.service",
                "since": time.strftime("%F %T", time.localtime(t)),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    mes_event("trigger-inbox", "trigger_inbox_down")


# ---------- higress LLM 网关判活（D-114/factory-os#82 · 夜轨C2 红队分诊 M8 收口批） ----------
# 病灶（分诊 M8 实测，2026-11-07 重跑留证）：higress:8080 TCP 可达（/dev/tcp 实测）
# 但 keepalive TARGETS（时为 11 对象）/两哨兵/factory-watch 全不含（grep higress=0）
# ——生产 LLM 网关零判活探针。
# 判活签名：HTTP GET / → 200 欢迎页（2026-11-08 本机实测 200/0.06s；/healthz 404、
# /v1/models 404=网关不暴露通用探针端点，欢迎页 200 是唯一稳定活签名——网关路由
# 配置变动致 200 消失也该被看见，故判据钉 200 不放宽）。
# 处置：**只报警不拉起**——higress 是 gov 保留资产（AGENT.md 纪律 2：未经
# 30-遗产处置.md 清单授权不得改动/重启/删除），amber 1800s 去重 + MES 事件；
# 恢复=运营者按授权面处置。目标地址 env 可覆（AF_HIGRESS_TARGET，沙箱/换址用），
# 缺省=登记面主机名（仓内面洗名纪律，与 mes-host.invalid 同款）。
HIGRESS_BASE = os.environ.get("AF_HIGRESS_TARGET", "http://higress-host.invalid:8080")
HIGRESS_ALARM_DEDUP_S = 1800
last_higress_alarm = 0.0
last_higress_detail = ""


def _higress_get(url, timeout=6):
    """GET → (http_ok, status_or_None, detail)。HTTPError=网关应答了非 2xx（探针
    本身通，但活签名不成立）→ http_ok=True 带 status；连接层异常 → False。"""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, r.status, "HTTP 200"
    except urllib.error.HTTPError as e:
        return True, e.code, f"HTTP {e.code}（非 2xx）"
    except Exception as e:
        return False, None, f"{type(e).__name__}: {e}"


def check_higress(t):
    """higress 判活（HTTP 欢迎页签名）。返回 (alive, detail)。"""
    global last_higress_detail
    http_ok, status, detail = _higress_get(HIGRESS_BASE + "/")
    if http_ok and status == 200:
        last_higress_detail = f"HTTP 200（{HIGRESS_BASE} 欢迎页活签名）"
        return True, last_higress_detail
    last_higress_detail = (f"GET / 活签名不成立（{detail}）" if http_ok
                           else f"不可达（{detail}）")
    return False, last_higress_detail


def fix_higress(dry, t, deb):
    """失联处置=只报警不拉起（amber higress-down，1800s 去重 + MES）。

    gov 保留资产（AGENT.md 纪律 2）——本守护**不碰远程容器**（不 ssh 不重启），
    重启/改动须经 30-遗产处置.md 清单授权由运营者执行；LLM 网关流量面中断时
    本行保证「有人知道」。"""
    global last_higress_alarm
    if dry:
        klog("higress", f"[dry-run] 判活失败：{last_higress_detail}——将报警"
                        f"（amber higress-down，{HIGRESS_ALARM_DEDUP_S}s 去重），"
                        "不拉起（gov 保留资产，授权面处置）")
        return
    if t - last_higress_alarm < HIGRESS_ALARM_DEDUP_S:
        return
    last_higress_alarm = t
    klog("higress", f"ALARM higress 判活失败：{last_higress_detail}——不自动处置"
                    "（gov 保留资产，AGENT.md 纪律 2：重启/改动须 30-遗产处置.md "
                    "授权面）；LLM 网关流量面可能中断，需人工介入")
    try:
        with open(ALARMS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": now_s(), "level": "amber", "code": "higress-down",
                "message": f"higress LLM 网关判活失败：{last_higress_detail}；"
                           "不自动处置（gov 保留资产，重启/改动须 30-遗产处置.md "
                           "授权面）",
                "since": time.strftime("%F %T", time.localtime(t)),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    mes_event("higress", "higress_down")


# ---------- gc-watch（补丁③ R2：anolis 镜像池 GC 看护，本地判断+spawn 即返回） ----------

def read_gc_evidence():
    """耐久证据末态。容忍缺文件/坏行（无 GC 历史=全 0，方向安全：只多评估一轮）。"""
    last_apply_epoch, last_apply_ok, last_apply_note = 0.0, None, ""
    last_success_epoch, last_alarm_epoch = 0.0, 0.0
    try:
        with open(GC_EVIDENCE, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                ep = r.get("epoch") or 0
                if r.get("kind") == "apply":
                    if ep >= last_apply_epoch:
                        last_apply_epoch, last_apply_ok = ep, bool(r.get("ok"))
                        last_apply_note = (f"删 {r.get('deleted', 0)} 张/rmi-fail "
                                           f"{r.get('rmi_fail', 0)}，/data "
                                           f"{r.get('use_pct')}%→{r.get('use_pct_after')}%"
                                           f"，reason={r.get('reason')}" if not r.get("ok")
                                           else f"删 {r.get('deleted', 0)} 张/rmi-fail "
                                                f"{r.get('rmi_fail', 0)}，/data "
                                                f"{r.get('use_pct')}%→{r.get('use_pct_after')}%")
                    if r.get("ok"):
                        last_success_epoch = max(last_success_epoch, ep)
                elif r.get("kind") == "gc-alarm-sent":
                    last_alarm_epoch = max(last_alarm_epoch, ep)
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return {"last_apply_epoch": last_apply_epoch, "last_apply_ok": last_apply_ok,
            "last_apply_note": last_apply_note, "last_success_epoch": last_success_epoch,
            "last_alarm_epoch": last_alarm_epoch}


def append_gc_evidence(rec):
    """证据双写（tmp 现场 + 耐久）。失败不致命（只影响下轮去重/迟滞精度，方向安全）。"""
    for path in (GC_EVIDENCE_TMP, GC_EVIDENCE):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass


def gc_watch(dry=False):
    """anolis 镜像池 GC 看护（补丁③ R2）。严格非阻塞：本函数只读本地文件做判断，
    需要跑则 spawn tools/img-gc.py apply --host anolis 即返回——flock/ssh/prune 全在
    子进程，绝不阻塞 30s 一轮的主循环（否则 7 个看护对象集体失明）。"""
    global last_gc_spawn
    t = time.time()
    ev = read_gc_evidence()
    # A9：有未告警的 GC 结果 → alarms.log（去重时间戳记回耐久件，30min 窗）
    if ev["last_apply_epoch"] > ev["last_alarm_epoch"] and \
            t - ev["last_alarm_epoch"] > GC_ALARM_DEDUP_S:
        lvl = "amber" if ev["last_apply_ok"] else "red"
        if dry:
            klog("gc-watch", f"[dry-run] 将报警（level={lvl}）：{ev['last_apply_note']}")
        else:
            try:
                with open(ALARMS_LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "ts": now_s(), "level": lvl, "code": "gc-watch",
                        "message": f"anolis /data 镜像GC结果：{ev['last_apply_note']}",
                        "since": time.strftime("%F %T", time.localtime(ev["last_apply_epoch"])),
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
            append_gc_evidence({"kind": "gc-alarm-sent", "ts": now_s(),
                                "epoch": int(t), "level": lvl})
            klog("gc-watch", f"GC 结果已入 alarms.log（level={lvl}）：{ev['last_apply_note']}")
    # 触发判断（全部本地读；判不准一律不动）
    if t - last_gc_spawn < GC_SPAWN_SUPPRESS:
        return
    # P0-2 drill 旗标（方案 §3.3-a）：只读演练通道——旗标存在则跳过水位/迟滞判断，
    # spawn 一次 argv=plan（只读不删）的子进程后自毁旗标。1200s 防抖仍适用。
    if os.path.exists(GC_DRILL_FLAG):
        if dry:
            klog("gc-watch", "[dry-run] drill 旗标存在——将 spawn "
                         "tools/img-gc.py plan --host anolis（只读不删；不删旗标）")
            return
        last_gc_spawn = t
        argv = ["python3", "tools/img-gc.py", "plan", "--host", "anolis"]
        klog("gc-watch", f"[drill] 旗标命中 → spawn tools/img-gc.py plan --host anolis"
                         f"（argv={' '.join(argv)}，只读不删；spawn 后旗标自毁）")
        spawn("gc-watch", argv, "/tmp/img-gc.log")
        try:
            os.remove(GC_DRILL_FLAG)
        except OSError:
            pass
        return
    try:
        with open(LATEST_JSON, encoding="utf-8") as f:
            an = (json.load(f).get("anolis") or {})
        pct = (an.get("disk") or {}).get("/data", {}).get("use_pct")
    except Exception:
        return
    age = file_age(LATEST_JSON)
    if pct is None or age is None or age > STALE_S:
        return  # watch 断供/字段缺失：宁可不 GC（fail-safe，不阻塞）
    if pct < GC_TRIGGER_PCT:
        return
    if t - ev["last_success_epoch"] < GC_MIN_INTERVAL:
        return
    if dry:
        klog("gc-watch", f"[dry-run] 将 spawn tools/img-gc.py apply --host anolis"
                         f"（/data {pct}%≥{GC_TRIGGER_PCT}%，距上次成功GC "
                         f"{(t - ev['last_success_epoch']) / 3600:.1f}h）")
        return
    last_gc_spawn = t
    klog("gc-watch", f"触发（/data {pct}%≥{GC_TRIGGER_PCT}%，距上次成功GC "
                     f"{(t - ev['last_success_epoch']) / 3600:.1f}h）→ spawn apply 子进程"
                     f"（非阻塞；≥88% 子进程内自停手只回报）")
    # J3 修复（补丁③R2-fix1）：子命令必须在前——--host 归 apply 子解析器，
    # 旧序「--host anolis apply」100% 死于 argparse rc2 且死前零证据、A9 无从告警。
    spawn("gc-watch", ["python3", "tools/img-gc.py", "apply", "--host", "anolis"],
          "/tmp/img-gc.log")


LAUNCH_PLAN = [
    ("watch", ["python3", "tools/factory-watch.py"], "/tmp/factory-watch.log",
     f"env+={WATCH_ENV}；判据=进程+watch-state.json<300s"),
    ("dash", ["python3", "-m", "http.server", DASH_PORT,
              "--bind", "127.0.0.1", "--directory", DASH_DIR], "/tmp/factory-dash.log",
     "看板：判据=8790 进程在；死则拉起（绑 127.0.0.1）"),
    ("af-execline",
     ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "anolis",
      "find /data/bench/af-p3-state/orders -mindepth 1 -maxdepth 1 -type d "
      "-printf '%T@\\n' | sort -rn | head -1"],
     "（不拉起，报警面）",
     "af 统一执行面判活（2026-10-26 §三-2 新增，订单驱动非守护；OBS-D4 20261031 "
     "心跳根改生产真值根）：判活=af-order/af-execline 进程在场 或 生产真值根 "
     "anolis:/data/bench/af-p3-state/orders 最新订单目录 mtime<72h（cmd 列=心跳等价"
     "查看命令）；空闲=amber 报警不拉起（klog+alarms.log code=af-execline-idle+MES "
     "kind=af_plane_idle，30min 去重）；恢复=经 af-order 正常下单"),
    ("mes-ch", ["curl", "-s", "-m", "5", "-u", "default:<0600凭据文件>",
                "http://mes-host.invalid:15221/?query=SELECT%20count()%20FROM%20af_mes.mes_event%20WHERE%20occurred_at%20%3E%20now()%20-%20INTERVAL%201%20MINUTE"],
     str(ALARMS_LOG),
     "mingda MES 查询级连通探活（2026-10-26 §三-2 由 ch-mes-local 更名，探针原样）："
     "判活=极轻 SELECT（/ping 探不到查询级 500=mes500 缺口）；失联=30min 去重报警"
     "（klog+alarms.log 类别码 ch-mes-conn-refused/auth/query/timeout+MES kind=ch_mes_down）；"
     "恢复=mingda systemd 单元 clickhouse-factory.service（Restart=always）自动拉起，持续失联"
     "人工 ssh mingda-bench systemctl start；实现走 urllib（cmd 列的是等价判据命令，"
     "凭据从 0600 文件解析）"),
    ("self-improve-loop", ["python3", "tools/self-improve-loop.py"], SIL_LOG,
     "自改进循环产线守护（2026-10-29 循环产线批新增，600s 周期四段增量流水）："
     "判据同 watch 同构=进程在+状态观测/loop-state.json mtime<300s；守护带全寿命 60s "
     "心跳重写 state（轮周期 600s>300s 判据，无心跳会被反复误判拉起——实测后加）；"
     "STOP 熔断轮守护仍记账（不会因熔断误判失联）；死则按 event-router 同款 nohup "
     "姿势拉起（setsid 脱离、日志追加）；工单 tools/self-improve-loop.py"),
    # ---- DEB-3（2026-10-30 产线续能批）：本机五守护入 watch 清单 ----
    # 拉起命令=各守护「在役启动行」（与在役进程 cwd/stdout 落点逐字一致，见 /proc 实测）：
    ("router", ["python3", "tools/event-router.py"], f"{WS}/状态观测/event-router.log",
     "事件路由器（2026-10-30 DEB-3 入监）：判据=进程在 +（状态文件 "
     "kb-seed/sandbox/.router-state.json mtime<3600s 或 日志尾 状态观测/event-router.log "
     "mtime<3600s）双信号 OR；阈值 3600s 按实测单轮 995–1226s 标定（router 每轮 "
     "poll_verify_reports 要 ssh 遍历 gov 报告目录，轮长随报告数增长）；"
     "在役启动行=nohup python3 tools/event-router.py >> 状态观测/event-router.log 2>&1 &"),
    ("scheduler", ["python3", "tools/factory-scheduler.py"],
     f"{WS}/状态观测/factory-scheduler.log",
     "调度中枢（2026-10-30 DEB-3 入监）：判据=进程在 +（状态文件 "
     "状态观测/factory-scheduler-state.json mtime<2400s 或 日志尾 "
     "状态观测/factory-scheduler.log mtime<2400s）双信号 OR；阈值 2400s 按实测单轮 "
     "p99=784s/max=1258s 标定（单轮含 anolis/gov 多路 ssh）；"
     "在役启动行=nohup python3 tools/factory-scheduler.py >> 状态观测/factory-scheduler.log 2>&1 &"),
    ("status-push", ["python3", "tools/factory-status-push.py"],
     f"{WS}/状态观测/status-push.log",
     "工厂快况推送器（2026-10-30 DEB-3 入监）：判据=进程在 + 日志尾 "
     "状态观测/status-push.log mtime<300s（该守护无独立状态文件，日志即其状态面）；"
     "阈值 300s 按实测单轮 ≤119s 标定；"
     "在役启动行=nohup python3 tools/factory-status-push.py >> 状态观测/status-push.log 2>&1 &"),
    ("emit-sidecar", ["python3", "tools/otel/emit-sidecar.py"],
     f"{WS}/状态观测/otel-sidecar.log",
     "OTel 观测边车（2026-10-30 DEB-3 入监）：判据=进程在 +（状态文件 "
     "状态观测/otel-sidecar.json mtime<300s 或 日志尾 状态观测/otel-sidecar.log "
     "mtime<300s）双信号 OR；阈值 300s 按实测单轮 ≤41s 标定；"
     "在役启动行=setsid nohup python3 tools/otel/emit-sidecar.py >> 状态观测/otel-sidecar.log 2>&1 &"),
    ("quota-governor", ["python3", "tools/quota-governor.py", "daemon"],
     f"{WS}/状态观测/quota-governor.log",
     "配额治理器（2026-10-31 DEB-7 入监，本机第六守护）：判据=进程在（/proc argv 含 "
     "tools/quota-governor.py 且子命令=daemon，一次性 poll 不算在役）+ 状态文件 "
     "状态观测/quota.json mtime<600s（AND 模式：状态新鲜为必要条件，日志尾仅参考；"
     "OR 判据会让「进程活但读数停更」逃过判活——正是 DEB-7 要治的病；DEB57 判读矛盾门："
     "state 假死读数撞上日志尾 poll ok=os.replace 已完成时改判存活只记疑不处置）；"
     "阈值 600s 与配额闸 stale 阈（factory-scheduler QUOTA_STALE=600）同值，"
     "写盘密度=daemon 60s 一轮（远严于「≥300s 一轮」下界）；"
     "单实例=governor 自带 pidfile 守卫（tools/.quota-governor.pid）+ keepalive 多实例收敛；"
     "在役启动行=setsid nohup python3 tools/quota-governor.py daemon >> 状态观测/quota-governor.log 2>&1 &"),
    ("otelcol", ["bash", "tools/otel/run-collector.sh", "start"],
     f"{WS}/状态观测/otel-collector-restart.log",
     "OTel collector（2026-11-01 账本一致批入监，本机第七守护）：判据=进程在（编译"
     "二进制 argv0 basename=otelcol，argv0_is_bin 放行）+ storage 发送队列文件 "
     "~/otelcol-runtime/storage/exporter_clickhouse__metrics mtime<300s（端到端管线"
     "运动信号：收数→batch→持久队列落盘，实测 30s 恒刷；collector.log 健康期恒静默"
     "只作 OR 副信号）OR 日志尾 mtime<300s；阈值 300s=30s 写盘节奏 ×10 余量、grace 120s"
     "（start→首刷实测 ≤75s）；在役启动行=既有交付件 run-collector.sh start（凭据现取→"
     "派生配置→validate→验活四步自带，双启拒绝靠 pidfile）——2026-10-31 断链 26h+ "
     "四处账本/监督面全零（红队终局轮 G8/V1 另记）后补的告警码面"),
    # ---- RT 收口批（2026-11-02）：gov 公网门户（第八看护对象，首个远程对象） ----
    # 拉起在 gov 宿主侧执行（ssh 杀旧 → start-portal.sh setsid → healthz 验活环），
    # 全文见本文件 PORTAL_RESTART_SH；此处登记操作员可读摘要行。
    ("portal", ["ssh", "root@gov-host.invalid", "bash /opt/company/af-jobs/start-portal.sh"],
     "gov:/opt/company/af-jobs/portal-run.log",
     "gov 公网门户（RT 收口批 2026-11-02 入监，jobs.hkmingdajiaoyu.com 宿主，监听 8090）："
     "判据三签名=①/healthz 返回 ok:true ②/tasks.json?status=open&limit=1 信封可解析"
     "（total:int 或旧版裸数组）③gov 在役进程 environ 含 AF_JOBS_DATA（11-02 板面全零"
     "事故根因签名，该形态下 ①② 照样全绿）；ssh 不可达只按 ①② 裁决不据未知动手；"
     "处置=ssh gov 杀旧进程→start-portal.sh setsid 拉起（AF_JOBS_DATA 导出内嵌）→"
     "远端 curl /healthz 验活环 ≤20s；拉起后 90s 判活宽限；Debounce 600s 窗 2 次；"
     "与 all-gates L5 deploy-consistency-probe 同宿主同对账域，自动拉起非越权"),
    ("trigger-inbox", ["curl", "-s", "-m", "5", "http://127.0.0.1:8765/healthz"],
     f"{WS}/状态观测/alarms.log",
     "af.trigger.v1 收件箱（生产接线批 2026-11-03 入监，第九看护对象；**只判活不拉起**）："
     "判据三件=①进程在（argv basename=trigger-inbox.py）②AF_TRIGGER_HOME（读在役进程 "
     "environ，缺省=WS/af-state/triggers）的 inbox/ 目录可写 ③在役 environ 含段B secret "
     "AF_TRIGGER_SECRET_GITEA_WEBHOOK（缺 secret=安全缺省不判活——收件箱自身 fail-closed "
     "无 secret 一律 401，进程在而无 secret 时「判活」是假绿）；cmd 列=等价判据查看命令"
     "（实现走 /proc 扫描+environ 读数，curl 那条仅作人工核对）；失联处置=只报警"
     "（amber code=trigger-inbox-down，1800s 去重）不拉起——2026-11-05 常驻化批"
     "（B清单§三-1）拉起闸已移交 systemd --user 常驻单元 af-trigger-inbox.service"
     "（EnvironmentFile=~/.config/af-trigger/gitea-webhook.env 解绑人工串行、"
     "Restart=always+KillMode=process 自动拉起，与在役 factory-keepalive.service 同型，"
     "RT-E169② 先例口径），本守护不重复管理该单元；持续失联=单元级故障，"
     "恢复=systemctl --user status af-trigger-inbox.service"),
]


def print_commands():
    print("factory-keepalive 拉起命令台账（均 cwd=WS、stdin=DEVNULL、setsid 脱离、stdout/stderr 追加）：")
    for name, cmd, logf, note in LAUNCH_PLAN:
        print(f"\n[{name}]\n  cmd : {' '.join(cmd)}\n  log : {logf}\n  姿势: {note}")


# 2026-10-26 §三-2 退役改造：旧 9 对象收敛为观察期 5 对象（runbook §三-2；
# 2026-10-29 循环产线批新增 self-improve-loop，判据同 watch 同构）。
# 旧对象的 check/fix 函数死码已随 2026-10-31 文件归档批（OBS-D6）清理；不在本表=不判活不拉起。
TARGETS = ["watch", "dash", "af-execline", "mes-ch",
            # DEB-3（2026-10-30 产线续能批）：本机五守护入 watch 清单
            "router", "scheduler", "status-push", "emit-sidecar", "self-improve-loop",
            # DEB-7（2026-10-31 义务批）：quota-governor 常驻化入 watch 清单
            "quota-governor",
            # 账本一致批（2026-11-01）：otelcol（OTel collector）入 watch 清单
            "otelcol",
            # RT 收口批（2026-11-02）：gov 公网门户入 watch 清单（第八看护对象，
            # 首个远程对象；三签名判活 + ssh gov 经 start-portal.sh 自愈拉起，
            # 完整论证见文件头「RT 收口批」段）
            "portal",
            # 生产接线批（2026-11-03）：trigger-inbox 入 watch 清单（第九看护对象，
            # 只判活**不拉起**——2026-11-05 常驻化批（B清单§三-1）起拉起闸=systemd --user
            # 常驻单元 af-trigger-inbox.service（Restart=always 自动拉起，本守护不重复管理）；
            # 判据=进程在+inbox 目录可写+段B secret 在役，缺 secret=安全缺省不判活；
            # 失联 amber 报警 1800s 去重，完整论证见文件头「生产接线批」「常驻化批」段）
            "trigger-inbox",
            # 观测补遗批（D-114/factory-os#82，2026-11-08）：higress LLM 网关入 watch
            # 清单（远程对象；HTTP GET / 欢迎页 200=活签名——分诊 M8 实测 TCP 可达但
            # keepalive TARGETS/两哨兵/factory-watch 全不含，grep higress=0；只报警
            # **不拉起**：gov 保留资产，AGENT.md 纪律 2，重启/改动须经
            # 30-遗产处置.md 授权面；amber 1800s 去重+MES，论证见
            # check_higress/fix_higress 段头注）
            "higress"]

# DEB-3：名字 → 守护规格表（供 CHECKS/FIXES 的 lambda 取用，避免重复字面量）
GUARD_BY_NAME = {g["name"]: g for g in LOCAL_GUARDS}


def otel_guardian_round(states, dry):
    """守护面埋点发射（fail-open + 失败可见）：返回记账 dict（factory_otel.guard 口径）。

    2026-11-02 RT 修复（OTel 链·守护/收割发射面可见性）：此前调用点
    `except Exception: pass` 且**丢弃 guardian_round 的 ok 返回值**——发射面坏了
    （collector 不可达）进程内 errors 计数在涨，无人读、无人比对、无人告警。
    现失败落守护日志（KLOG=/tmp/factory-keepalive.log，守护自身的状态面）。
    熔断（OTEL-STOP 在场）/禁用（AF_OTEL_DISABLE=1）是有意静默，不算失败、不刷屏。
    """
    if _otel is None:
        return {"ok": False, "errors": 0, "skipped": 0, "exc": None, "disabled": True}
    up = sum(1 for v in states.values() if v[0])
    rep = _otel.guard(_otel.guardian_round, up=up, down=len(states) - up,
                      mode="dry-run" if dry else "live", service="factory-keepalive")
    vis = _otel.visible_failure(rep, "守护面")
    if vis:
        klog("otel", vis)
    return rep


def one_round(dry=False):
    t = time.time()
    deb = one_round.deb
    states = {}
    graph_guard(dry)   # D-25：先保图（存在性校验+自动恢复），再判各对象活
    for name in TARGETS:
        alive, detail = CHECKS[name](t)
        states[name] = (alive, detail)
        if alive:
            continue
        if not dry and not deb.allow(name, t):
            # 防抖超限态：压制处置（continue，不拉起不记 deb）。原完成态放行分支
            # （组合补丁③ queue_drained）于 2026-11-01 红队回头批移除——其登记表
            # DRAIN_PROBES 自 2026-10-26 §三-2 起恒空，在役 TARGETS 无可放行对象。
            continue  # 防抖超限已报警
        if name not in ("af-execline", "mes-ch", "portal", "trigger-inbox", "higress"):
            # af-execline/mes-ch/portal/trigger-inbox/higress 的 fix 自带分支日志（空闲报警/
            # 去重报警/恢复指引/门户处置明细/收件箱失联报警/higress 判活失败报警），通用「失联 → 处置」行
            # 会每轮刷屏，豁免
            klog(name, f"失联 → 处置（{detail}）")
        FIXES[name](dry, t, deb)
    if not dry:
        # DEB-3：单实例收敛（多实例时保留最老者，杀多余）——放在处置之后，
        # 使「处置拉起」与「收敛」顺序确定：先处置后收敛，本轮结束时恰好一实例。
        dedup_guards()
    gc_watch(dry)   # 补丁③：anolis 镜像池 GC 看护（纯本地判断+spawn 即返回，非阻塞）
    if dry:
        print(f"--- dry-run 判活结论 {now_s()} ---")
        for name in TARGETS:
            alive, detail = states[name]
            print(f"  {name:<11} {'存活' if alive else '失联'}  {detail}")
    # OTel MVP 埋点：守护面看护轮次（dry/live 两路同点覆盖；判活/防抖/拉起语义不变）
    # 2026-11-02 RT：ok 不再被丢弃——失败记账落守护日志（见 otel_guardian_round）
    otel_guardian_round(states, dry)
    return states


# 让 one_round 携带防抖状态（免全局乱飘）
one_round.deb = Debounce()

CHECKS = {
    "watch": check_watch,
    "dash": check_dash,
    "af-execline": check_af_execline,
    "mes-ch": check_mes_ch,
    # DEB-3：五本机守护统一判据（check_guard）
    "router": lambda t: check_guard(t, GUARD_BY_NAME["router"]),
    "scheduler": lambda t: check_guard(t, GUARD_BY_NAME["scheduler"]),
    "status-push": lambda t: check_guard(t, GUARD_BY_NAME["status-push"]),
    "emit-sidecar": lambda t: check_guard(t, GUARD_BY_NAME["emit-sidecar"]),
    "self-improve-loop": lambda t: check_guard(t, GUARD_BY_NAME["self-improve-loop"]),
    # DEB-7：quota-governor 统一判据（check_guard，and_mode=状态新鲜必要）
    "quota-governor": lambda t: check_guard(t, GUARD_BY_NAME["quota-governor"]),
    # 账本一致批：otelcol 统一判据（check_guard，OR 模式=进程在+队列文件新鲜）
    "otelcol": lambda t: check_guard(t, GUARD_BY_NAME["otelcol"]),
    # RT 收口批：gov 公网门户三签名判活（远程对象，不走 LOCAL_GUARDS/check_guard
    # ——guard_pids 是 /proc 本机扫描，门户在 gov 宿主）
    "portal": check_portal,
    # 生产接线批：trigger-inbox 三件判据（只判活不拉起，fix 只报警——见函数头注释）
    "trigger-inbox": check_trigger_inbox,
    # 观测补遗批（D-114/#82 M8）：higress 欢迎页签名判活（远程对象，不走
    # LOCAL_GUARDS/check_guard——guard_pids 是 /proc 本机扫描，网关在 gov 宿主）
    "higress": check_higress,
}
FIXES = {
    "watch": fix_watch,
    "dash": fix_dash,
    "af-execline": fix_af_execline,
    "mes-ch": fix_mes_ch,
    # DEB-3：五本机守护统一拉起（fix_guard，用各自在役启动行）
    "router": lambda dry, t, deb: fix_guard(dry, t, deb, GUARD_BY_NAME["router"]),
    "scheduler": lambda dry, t, deb: fix_guard(dry, t, deb, GUARD_BY_NAME["scheduler"]),
    "status-push": lambda dry, t, deb: fix_guard(dry, t, deb, GUARD_BY_NAME["status-push"]),
    "emit-sidecar": lambda dry, t, deb: fix_guard(dry, t, deb, GUARD_BY_NAME["emit-sidecar"]),
    "self-improve-loop": lambda dry, t, deb: fix_guard(dry, t, deb, GUARD_BY_NAME["self-improve-loop"]),
    # DEB-7：quota-governor 统一拉起（fix_guard，在役启动行）
    "quota-governor": lambda dry, t, deb: fix_guard(dry, t, deb, GUARD_BY_NAME["quota-governor"]),
    # 账本一致批：otelcol 统一拉起（fix_guard，run-collector.sh start 四步自带验活）
    "otelcol": lambda dry, t, deb: fix_guard(dry, t, deb, GUARD_BY_NAME["otelcol"]),
    # RT 收口批：门户自愈拉起（fix_portal：ssh gov 杀旧 + start-portal.sh + 验活环）
    "portal": fix_portal,
    # 生产接线批：trigger-inbox 失联只报警不拉起（拉起闸=systemd 常驻单元
    # af-trigger-inbox.service，Restart=always 自动拉起；见函数头注释）
    "trigger-inbox": fix_trigger_inbox,
    # 观测补遗批（D-114/#82 M8）：higress 失联只报警不拉起（gov 保留资产，
    # AGENT.md 纪律 2——本守护不碰远程容器，授权面处置）
    "higress": fix_higress,
}


# ---------------------------------------------------------------- 自身源码变更自我重载
# 2026-11-03 SIL 环修复批：监督面自身也有同一类「旧码在役」缺陷——本脚本跑的是
# 启动时载入的源码，盘上改了不重启＝监督面判据不生效（本次 SIL 守护 17h 未换码的
# 上游成因之一：看护面本可自动换码却没有该机制）。故：盘上源码变更且**稳定**、
# 且新码**可编译**时，用 os.execv 把本进程换成新码（pid 不变、systemd 单元不受
# 影响、无双实例窗口）。三道护栏（任一不满足即本轮不换、保持旧码在役）：
#   ① 二次读指纹一致（排除「正写到一半的半成品」）；② 新码 compile() 通过（排除
#      语法坏件把监督面换死）；③ execv 失败只记日志不退出（旧码继续在役）。
KEEPALIVE_SRC = os.path.abspath(__file__)
KEEPALIVE_SRC_SHA = _sha256_file(KEEPALIVE_SRC) or "unreadable"


def _self_refresh_verdict():
    """自身源码是否需要重载 → (need, 说明)。"""
    cur = _sha256_file(KEEPALIVE_SRC)
    if not cur or cur == KEEPALIVE_SRC_SHA:
        return False, ""
    time.sleep(1.0)                                  # 护栏①：二次读，指纹须稳定
    cur2 = _sha256_file(KEEPALIVE_SRC)
    if cur2 != cur:
        return False, f"盘上源码正在变更（指纹不稳定 {cur[:8]}≠{str(cur2)[:8]}）——本轮不重载"
    try:                                             # 护栏②：新码须可编译
        with open(KEEPALIVE_SRC, encoding="utf-8") as f:
            compile(f.read(), KEEPALIVE_SRC, "exec")
    except (OSError, SyntaxError, ValueError) as e:
        return False, f"盘上源码不可编译（{type(e).__name__}: {e}）——本轮不重载（旧码在役）"
    return True, cur


def _self_refresh(t):
    """执行自我重载（os.execv 换新码，pid 不变）。返回 True=已重载（进程已被替换）。"""
    need, why = _self_refresh_verdict()
    if not need:
        if why:
            klog("self", f"自身源码变更待重载但本轮跳过：{why}")
        return False
    klog("self", f"自身源码变更（sha {KEEPALIVE_SRC_SHA[:12]}→{why[:12]}）→ 自我重载"
                 f"（os.execv 载入新码，pid 不变={os.getpid()}）")
    os.environ["KEEPALIVE_RELOAD_PID"] = str(os.getpid())
    try:
        os.execv(sys.executable, [sys.executable, KEEPALIVE_SRC] + sys.argv[1:])
    except OSError as e:                             # 护栏③：换失败不退出（旧码继续在役）
        klog("self", f"自我重载失败（{e}）——继续以旧码在役")
        return False
    return True


def self_guard():
    """单实例守卫：pidfile 指向活着的 factory-keepalive 进程即拒绝。

    自我重载豁免（2026-11-03 SIL 环修复批）：os.execv 换新码时 pid 不变、pidfile 仍
    指向自己——若不做豁免，重载后的新码会把自己认成「另一个实例」而 exit(3)（监督
    面当场自杀）。故环境变量 KEEPALIVE_RELOAD_PID == 自己 pid 时跳过双实例拒绝
    （该变量只由本进程在 execv 前自设，见 _self_refresh）。"""
    if os.environ.get("KEEPALIVE_RELOAD_PID") == str(os.getpid()):
        klog("self", f"自我重载续跑（pid={os.getpid()}）——跳过双实例拒绝")
        with open(PIDFILE, "w") as f:
            f.write(str(os.getpid()))
        return
    try:
        old = open(PIDFILE).read().strip()
        if old and old.isdigit() and os.path.exists(f"/proc/{old}"):
            argv = pid_argv(int(old)) or []
            if any("factory-keepalive.py" in a for a in argv[1:]):
                print(f"factory-keepalive 已在跑 pid={old}，拒绝双实例", file=sys.stderr)
                sys.exit(3)
        klog("self", f"清陈旧自身 pidfile（pid={old} 失活）")
    except FileNotFoundError:
        pass
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))


# ---------- J2 内存防线三读数（2026-11-03 内存防线批；v0.3 §二 J2 / T4 终裁 #3） ----------
# 防线三线=df /tmp(tmpfs) + MemAvailable + SwapUsed（T4 实测修正：tmpfs 多数已换出到
# swap，/tmp 名义用量≠常驻内存）。每轮巡检追加一行 mem 三值摘要 JSONL 到
# 状态观测/memory-readings.jsonl（全量版含守护 RSS 面由 tools/mem-readings.sh 手动/巡检跑，
# 两者同文件同字段口径，本函数只摘三值保持轮内开销最小）。
# 计量先行（宪法9，显式降级声明）：本函数**只读不处置**——不报警、不拉起、不改任何
# 守护限额；任何失败只记本日志一行，绝不影响判活/处置/心跳语义。
MEM_READINGS_JSONL = f"{WS}/状态观测/memory-readings.jsonl"


def mem_readings_append():
    """每轮追加 mem 三值摘要行（J2 观测面在役增长腿）。失败不致命。"""
    try:
        def _kb(key):
            with open("/proc/meminfo", encoding="ascii") as f:
                for ln in f:
                    if ln.startswith(key + ":"):
                        return int(ln.split()[1])
            return 0
        df_line = subprocess.run(["df", "-B1", "-P", "/tmp"], capture_output=True,
                                 text=True, check=True).stdout.splitlines()[1].split()
        sw_total, sw_free = _kb("SwapTotal"), _kb("SwapFree")
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "epoch": int(time.time()),
               "src": "factory-keepalive",
               "tmpfs_used_b": int(df_line[2]),          # 三读数①：tmpfs 已用（字节）
               "mem_available_kb": _kb("MemAvailable"),  # 三读数②：可用内存
               "swap_used_kb": sw_total - sw_free}       # 三读数③：swap 已用
        with open(MEM_READINGS_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False,
                               separators=(",", ":")) + "\n")  # 紧凑分隔=与 mem-readings.sh 同口径
    except Exception as e:   # 计量失败≠守护失败：只记日志，不烧轮次不误报 DOWN
        klog("self", f"mem 三读数摘要采集失败（不致命，J2 观测面该轮缺行）: {e}")


def main():
    global INTERVAL
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="单轮干跑，只打印将执行的命令")
    ap.add_argument("--print-commands", action="store_true",
                    help="打印全部对象拉起命令/env/日志路径后退出（不判活不动手）")
    ap.add_argument("--interval", type=int, default=INTERVAL)
    a = ap.parse_args()
    if a.print_commands:
        print_commands()
        return
    INTERVAL = max(5, a.interval)
    if a.dry_run:
        one_round(dry=True)
        return
    self_guard()
    log_single_channel_selfcheck()   # 红队 W2-C19：双写回归拒跑（探针 +1 断言）
    klog("self", f"keepalive 常驻启动 pid={os.getpid()} 周期 {INTERVAL}s "
                 f"看护 {len(TARGETS)} 对象：{', '.join(TARGETS)}")
    stop = {"flag": False}

    def on_term(_sig, _frm):
        stop["flag"] = True
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    rnd = 0
    try:
        while not stop["flag"]:
            rnd += 1
            # 自身源码变更→自我重载（2026-11-03 SIL 环修复批）：换码在本轮判活**之前**
            # （新码跑这一轮），且 execv 成功即本进程被替换（后续代码不执行）。
            _self_refresh(t=time.time())
            try:
                states = one_round()
                mem_readings_append()   # J2 内存防线：每轮 mem 三值摘要行（只读不处置，失败不致命）
                if rnd - last_hb_round >= HEARTBEAT_EVERY:
                    globals()["last_hb_round"] = rnd
                    backup_graphs()   # D-25：心跳前先做新鲜滚动备份
                    parts = []
                    for name, (ok, detail) in states.items():
                        if ok:
                            parts.append(f"{name}:ok")
                        else:
                            parts.append(f"{name}:DOWN({detail})")
                    klog("self", f"心跳：第 {rnd} 轮 " + "  ".join(parts))
            except Exception as e:
                klog("self", f"轮异常（不退出）: {e}")
            for _ in range(INTERVAL):
                if stop["flag"]:
                    break
                time.sleep(1)
    finally:
        try:
            if open(PIDFILE).read().strip() == str(os.getpid()):
                os.remove(PIDFILE)
        except OSError:
            pass
        klog("self", "keepalive 退出")


if __name__ == "__main__":
    main()
