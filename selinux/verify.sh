#!/bin/bash
# 验证：① SELinux 处于 permissive ② 模块与 permissive 域 ③ 标签生效 ④ 审计可捕获
D=$(cd "$(dirname "$0")" && pwd)
NAME=openclaw_agent
pass=0; fail=0
ck(){ if [ "$1" = "0" ]; then echo "  [OK]   $2"; pass=$((pass+1)); else echo "  [FAIL] $2"; fail=$((fail+1)); fi }

echo "=== ① 运行模式 ==="
MODE=$(getenforce)
[ "$MODE" = "Permissive" ] && ck 0 "SELinux 当前模式 = $MODE（日志模式，不阻断）" \
                           || ck 1 "SELinux 模式为 $MODE，期望 Permissive"

echo "=== ② 模块与域 ==="
semodule -l | grep -qw "$NAME"; ck $? "策略模块 $NAME 已加载"
semanage permissive -l 2>/dev/null | grep -qw "^agent_t$" || semanage permissive -l 2>/dev/null | grep -qw "agent_t"
ck $? "agent_t 已登记为 permissive 域"
seinfo -t 2>/dev/null | grep -qw "agent_t";      ck $? "类型 agent_t 存在"
seinfo -t 2>/dev/null | grep -qw "agent_tool_t"; ck $? "类型 agent_tool_t 存在"

echo "=== ③ 标签生效（实际上下文 vs 策略期望）==="
for p in /usr/bin/openclaw \
         /usr/lib/node_modules/openclaw/openclaw.mjs \
         /usr/lib/node_modules/openclaw/dist/index.js \
         /usr/local/bin/openclaw-tool-e2e \
         /usr/local/libexec/openclaw-round-id-listener.py \
         /usr/local/libexec/run-openclaw-tracee-collector-service \
         /home/hx/jjq/agent_perm_audit/tools \
         /home/hx/jjq/agent_perm_audit/tools/safe_file_reader/server.py \
         /root/.openclaw/skills \
         /var/lib/openclaw-kernel-collector ; do
  if [ -e "$p" ]; then
    ctx=$(stat -c '%C' "$p" 2>/dev/null)
    case "$p" in
      *kernel-collector*)                           exp="agent_log_t"  ;;
      *agent_perm_audit/tools*|*\.openclaw/skills*) exp="agent_tool_t" ;;
      *openclaw*|*index.js*)                        exp="agent_exec_t" ;;
    esac
    echo "$ctx" | grep -q "$exp" && ck 0 "$(basename $p) → $ctx" || ck 1 "$(basename $p) → $ctx（期望含 $exp）"
  fi
done
echo "  --- matchpathcon 一致性（有输出表示不符合策略）---"
mism=$(for p in /home/hx/jjq/agent_perm_audit/tools /usr/lib/node_modules/openclaw/openclaw.mjs /root/.openclaw/skills; do matchpathcon -V "$p" 2>/dev/null; done | grep -c "verified" || true)
[ "${mism:-0}" -ge 1 ] && ck 0 "matchpathcon 校验通过（$mism 项符合策略）" || ck 1 "matchpathcon 未报告符合项"

echo "=== ④ 审计捕获（以 agent_t 身份触发访问）==="
BEFORE=$(ausearch -m AVC,USER_AVC -ts recent 2>/dev/null | grep -c "agent_t" || true)
TOOL=$(ls /home/hx/jjq/agent_perm_audit/tools/*/server.py 2>/dev/null | head -1)
runcon system_u:system_r:agent_t:s0 head -n1 "$TOOL" >/dev/null 2>&1
runcon system_u:system_r:agent_t:s0 head -n1 /etc/hostname >/dev/null 2>&1
runcon system_u:system_r:agent_t:s0 sh -c 'echo probe > /tmp/.agent_t_probe' >/dev/null 2>&1
rm -f /tmp/.agent_t_probe
sleep 2
AFTER=$(ausearch -m AVC,USER_AVC -ts recent 2>/dev/null | grep -c "agent_t" || true)
echo "  触发前 agent_t 审计记录: $BEFORE / 触发后: $AFTER"
[ "${AFTER:-0}" -gt "${BEFORE:-0}" ]; ck $? "agent_t 的访问已写入审计日志（AVC 记录新增 $((AFTER-BEFORE)) 条）"

echo "  --- 最近 3 条 agent_t 审计样例 ---"
ausearch -m AVC,USER_AVC -ts recent 2>/dev/null | grep "agent_t" | tail -3 | cut -c1-150

echo "=== ⑤ 进程域现状（提示：已有进程需重启后才进入 agent_t）==="
ps -eZ 2>/dev/null | grep -E "openclaw|node.*openclaw" | grep -v grep | awk '{print "  " $1}' | sort | uniq -c

echo "=== ⑥ 域自动切换（直接执行 agent_exec_t 二进制）==="
PROBE=/tmp/.agent_transition_probe
cp /bin/bash "$PROBE" 2>/dev/null && chcon -t agent_exec_t "$PROBE" && chcon -u system_u "$PROBE"
if [ -x "$PROBE" ]; then
  got=$("$PROBE" -c 'id -Z' 2>/dev/null | awk -F: '{print $3}')
  [ "$got" = "agent_t" ] && ck 0 "执行 agent_exec_t 二进制后进程域 = $got" \
                          || ck 1 "进程域 = ${got:-未知}（期望 agent_t）"
  rm -f "$PROBE"
fi

echo "=== ⑦ 托管进程域（systemd 服务 + user-level gateway）==="
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
dom_of(){ tr -d '\0' < /proc/$1/attr/current 2>/dev/null | awk -F: '{print $3}'; }
check_unit(){
  local mgr="$1" u="$2"
  pid=$([ "$mgr" = user ] && systemctl --user show "$u" -p MainPID --value 2>/dev/null \
                          || systemctl show "$u" -p MainPID --value 2>/dev/null)
  if [ -z "${pid:-}" ] || [ "$pid" = "0" ]; then echo "  [SKIP] $u 未运行"; return; fi
  d=$(dom_of "$pid")
  [ "$d" = "agent_t" ] && ck 0 "$u (pid=$pid) 进程域 = $d" \
                       || ck 1 "$u (pid=$pid) 进程域 = ${d:-未知}（期望 agent_t）"
}
for u in openclaw-round-listener.service openclaw-kernel-collector.service; do
  systemctl list-unit-files 2>/dev/null | grep -qw "$u" && check_unit system "$u" || echo "  [SKIP] $u 不存在"
done
systemctl --user list-unit-files 2>/dev/null | grep -qw openclaw-gateway.service \
  && check_unit user openclaw-gateway.service || echo "  [SKIP] openclaw-gateway.service (user) 不存在"

echo
echo "结果：PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ] || exit 1
