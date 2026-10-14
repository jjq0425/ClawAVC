#!/bin/bash
# 以 agent_t 域运行 openclaw / MCP 工具（用于带 shebang 的脚本）
# 说明：内核对 #!/usr/bin/env xxx 脚本按「解释器」计算域，不会自动切到 agent_t，
#       因此脚本类入口（openclaw.mjs、*.py、*.sh）需用 runcon 显式指定域。
# 用法：
#   ./run_as_agent.sh openclaw gateway --port 18790
#   ./run_as_agent.sh python3 /home/hx/jjq/agent_perm_audit/tools/http_fetch/server.py
set -euo pipefail
CTX="${AGENT_CTX:-system_u:system_r:agent_t:s0}"
if [ $# -eq 0 ]; then
  echo "usage: $0 <command> [args...]  (默认域: $CTX)" >&2
  exit 2
fi
exec runcon "$CTX" "$@"
