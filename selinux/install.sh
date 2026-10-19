#!/bin/bash
# 安装 openclaw_agent SELinux 模块：策略 + 标签 + permissive + 审计规则 + systemd 上下文
set -e
D=$(cd "$(dirname "$0")" && pwd)
NAME=openclaw_agent

echo "== [1/7] 编译策略模块 =="
cd "$D"
make -f /usr/share/selinux/devel/Makefile ${NAME}.pp

echo "== [2/7] 载入模块（幂等：已存在则升级）=="
if semodule -l | grep -qw "${NAME}"; then
  semodule -i ${NAME}.pp && echo "  已升级 ${NAME}"
else
  semodule -i ${NAME}.pp && echo "  已安装 ${NAME}"
fi

echo "== [3/7] 确认 agent_t 为 permissive（日志模式，不阻断）=="
semanage permissive -a agent_t 2>/dev/null || echo "  agent_t 已是 permissive"

echo "== [4/7] 应用文件标签 =="
# /home、/root 下的路径会被 file_contexts.homedirs 的 /home/[^/]+/.+ 覆盖，
# 必须额外登记到 file_contexts.local（优先级高于 homedirs）才能稳定生效
fc_add(){ semanage fcontext -a -t "$2" "$1" 2>/dev/null || semanage fcontext -m -t "$2" "$1" 2>/dev/null || true; }
fc_add '/home/hx/jjq/agent_perm_audit/tools(/.*)?' agent_tool_t
fc_add '/root/\.openclaw/skills(/.*)?' agent_tool_t
fc_add '/root/\.openclaw/exec-approvals\.json' agent_conf_t
echo "  已登记 file_contexts.local 规则"

for p in /usr/bin/openclaw \
         /usr/lib/node_modules/openclaw \
         /usr/local/bin/openclaw-tool-e2e \
         /usr/local/bin/openclaw-selinux-file-search-read \
         /usr/local/libexec/openclaw-round-id-listener.py \
         /usr/local/libexec/run-openclaw-tracee-collector-service \
         /usr/local/libexec/openclaw-selinux \
         /home/hx/jjq/agent_perm_audit/tools \
         /root/.openclaw/skills \
         /root/.openclaw/exec-approvals.json \
         /var/lib/openclaw-kernel-collector ; do
  if [ -e "$p" ]; then
    # setfiles 直接按 file_contexts 落标签（对 /home 下路径比 restorecon 更确定）
    setfiles -F /etc/selinux/targeted/contexts/files/file_contexts "$p" >/dev/null 2>&1 \
      || restorecon -RvF "$p" >/dev/null 2>&1
    echo "  已打标签: $p"
  else
    echo "  跳过(不存在): $p"
  fi
done
# 目录自身（不递归，避免对海量会话日志重打标签）
[ -d /root/.openclaw ] && restorecon -vF /root/.openclaw >/dev/null 2>&1; echo "  已打标签: /root/.openclaw (目录)"

echo "== [5/7] 安装 auditd 规则 =="
install -m 640 "$D/audit/${NAME}.rules" /etc/audit/rules.d/${NAME}.rules
augenrules --load >/dev/null 2>&1 || auditctl -R "$D/audit/${NAME}.rules" || true
echo "  当前 agent 相关规则数: $(auditctl -l 2>/dev/null | grep -c 'agent_\|openclaw_')"

echo "== [6/7] 安装 systemd 域上下文（不重启服务）=="
# 6a. 已有服务：装 drop-in
for svc in openclaw-kernel-collector.service openclaw-round-listener.service; do
  if systemctl list-unit-files 2>/dev/null | grep -qw "$svc"; then
    mkdir -p /etc/systemd/system/${svc}.d
    install -m 644 "$D/systemd/openclaw-agent-context.conf" /etc/systemd/system/${svc}.d/10-agent-context.conf
    echo "  已配置: $svc → SELinuxContext=agent_t"
  fi
done
# 6b. gateway：由 openclaw 自带的 user-level unit 托管（/root/.config/systemd/user/），
#     只能用 --user 的 drop-in；进程域只能在启动时确定，切换需重启该 unit。
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if systemctl --user list-unit-files 2>/dev/null | grep -qw openclaw-gateway.service; then
  mkdir -p /root/.config/systemd/user/openclaw-gateway.service.d
  install -m 644 "$D/systemd/openclaw-agent-context.conf" \
    /root/.config/systemd/user/openclaw-gateway.service.d/10-agent-context.conf
  systemctl --user daemon-reload
  echo "  已配置: openclaw-gateway.service (user) → SELinuxContext=agent_t"
  if [ "${AUTO_RESTART_GATEWAY:-0}" = "1" ]; then
    systemctl --user restart openclaw-gateway.service
    echo "  已重启 gateway（注：会短暂中断会话，且 kernel-collector 会因 gateway PID 变化重建容器）"
  else
    echo "  未重启。生效命令: systemctl --user daemon-reload && systemctl --user restart openclaw-gateway.service"
  fi
else
  echo "  跳过: 未发现 user-level openclaw-gateway.service"
fi
systemctl daemon-reload 2>/dev/null || true

echo "== [7/7] 验证 =="
bash "$D/verify.sh"
