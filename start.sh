#!/bin/bash
# ╔══════════════════════════════════════════════════════════════╗
# ║  ClawAVC - Claw Access-View Compliance                      ║
# ╚══════════════════════════════════════════════════════════════╝

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$DIR/logs"
mkdir -p "$LOG_DIR"

# ─── Colors ───────────────────────────────────────────────────
R='\033[0m'
B='\033[1m'
D='\033[2m'
# ClawAVC brand colors
BLU='\033[38;5;33m'    # 腾讯蓝 #0052D9
ORG='\033[38;5;208m'   # 虾爪橙 #ED7B2F
WHT='\033[38;5;255m'   # white
GRN='\033[38;5;48m'    # mint green
GRY='\033[38;5;245m'   # gray
DKG='\033[38;5;238m'   # dark gray

# ─── Banner ──────────────────────────────────────────────────
clear 2>/dev/null
echo ""
echo -e "${ORG}${B}"
cat << 'ASCIIEOF'
      ██████╗██╗      █████╗ ██╗    ██╗
     ██╔════╝██║     ██╔══██╗██║    ██║
     ██║     ██║     ███████║██║ █╗ ██║
     ██║     ██║     ██╔══██║██║███╗██║
     ╚██████╗███████╗██║  ██║╚███╔███╔╝
      ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝
ASCIIEOF
echo -e "${BLU}${B}"
cat << 'ASCIIEOF'
              █████╗ ██╗   ██╗ ██████╗
             ██╔══██╗██║   ██║██╔════╝
             ███████║██║   ██║██║     
             ██╔══██║╚██╗ ██╔╝██║     
             ██║  ██║ ╚████╔╝ ╚██████╗
             ╚═╝  ╚═╝  ╚═══╝   ╚═════╝
ASCIIEOF
echo -e "${R}"

echo -e "  ${BLU}┌─────────────────────────────────────────────────────────┐${R}"
echo -e "  ${BLU}│${R}                                                           ${BLU}│${R}"
echo -e "  ${BLU}│${R}  ${ORG}🦀${R} ${B}${WHT}Claw${R} ${BLU}${B}Access${R}${DKG}-${R}${BLU}${B}View${R}${DKG}-${R}${ORG}${B}Compliance${R}                    ${BLU}│${R}"
echo -e "  ${BLU}│${R}  ${GRY}   透视访问行为意图 · 校验合规性${R}                     ${BLU}│${R}"
echo -e "  ${BLU}│${R}                                                           ${BLU}│${R}"
echo -e "  ${BLU}│${R}  ${BLU}🔒${R} ${GRY}AI Agent 行为合规审计可视化平台${R}                     ${BLU}│${R}"
echo -e "  ${BLU}│${R}  ${ORG}👥${R} ${GRY}by @jjq0425 & @xiaoxuan668${R}                          ${BLU}│${R}"
echo -e "  ${BLU}│${R}                                                           ${BLU}│${R}"
echo -e "  ${BLU}└─────────────────────────────────────────────────────────┘${R}"
echo ""

# ─── Loading Animation ────────────────────────────────────────
loading_bar() {
  local msg="$1"
  local icon="$2"
  local width=35
  for ((i=0; i<=width; i++)); do
    local pct=$((i * 100 / width))
    local bar=""
    for ((j=0; j<i; j++)); do bar+="━"; done
    for ((j=i; j<width; j++)); do bar+="┄"; done
    if [ $pct -lt 50 ]; then
      printf "\r  ${BLU}${icon}${R}  ${WHT}${msg}${R} ${BLU}${bar}${R} ${GRY}${pct}%%${R}"
    else
      printf "\r  ${ORG}${icon}${R}  ${WHT}${msg}${R} ${ORG}${bar}${R} ${GRY}${pct}%%${R}"
    fi
    sleep 0.015
  done
  printf "\r  ${GRN}✓${R}  ${WHT}${msg}${R} ${GRN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${R} ${GRN}done${R}\n"
}

# ─── Kill existing ────────────────────────────────────────────
fuser -k 15100/tcp 2>/dev/null
fuser -k 15101/tcp 2>/dev/null
sleep 1

DAEMON=false
if [ "$1" = "-d" ] || [ "$1" = "--daemon" ]; then
  DAEMON=true
fi

if [ "$DAEMON" = true ]; then
  echo -e "  ${ORG}⚡${R} ${B}Mode:${R} ${ORG}${B}DAEMON${R} ${GRY}(background)${R}"
  echo ""

  loading_bar "Loading core engine   " "🔧"
  cd "$DIR/backend" && nohup uv run python3 app.py >> "$LOG_DIR/backend.log" 2>&1 &
  BACKEND_PID=$!
  sleep 3

  loading_bar "Starting web server  " "🌐"
  cd "$DIR/frontend" && nohup npx vite --host 0.0.0.0 --port 15101 >> "$LOG_DIR/frontend.log" 2>&1 &
  FRONTEND_PID=$!
  sleep 1

  loading_bar "Arming audit shield  " "🛡️"
  echo ""

  echo -e "  ${BLU}╭──────────────────────────────────────────────────╮${R}"
  echo -e "  ${BLU}│${R}  ${GRN}🟢${R} Backend   ${B}http://0.0.0.0:${ORG}15100${R}  ${DKG}pid:${BACKEND_PID}${R}  ${BLU}│${R}"
  echo -e "  ${BLU}│${R}  ${GRN}🟢${R} Frontend  ${B}http://0.0.0.0:${ORG}15101${R}  ${DKG}pid:${FRONTEND_PID}${R}  ${BLU}│${R}"
  echo -e "  ${BLU}│${R}  ${GRY}📁 Logs: ${LOG_DIR}/${R}           ${BLU}│${R}"
  echo -e "  ${BLU}╰──────────────────────────────────────────────────╯${R}"
  echo ""
  echo -e "  ${ORG}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${R}"
  echo -e "  ${GRN}${B}  🫴 SYSTEM ONLINE${R}  ${GRY}— 你的 Agent 跑得再快，我也接得住${R}"
  echo -e "  ${ORG}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${R}"
  echo ""
  echo -e "  ${GRY}🛑 Stop: ${BLU}fuser -k 15100/tcp; fuser -k 15101/tcp${R}"
  echo ""
else
  echo -e "  ${ORG}⚡${R} ${B}Mode:${R} ${BLU}${B}FOREGROUND${R} ${GRY}(Ctrl+C to stop)${R}"
  echo ""

  loading_bar "Loading core engine   " "🔧"
  cd "$DIR/backend" && uv run python3 app.py 2>&1 | tee -a "$LOG_DIR/backend.log" &
  BACKEND_PID=$!
  sleep 3

  loading_bar "Starting web server  " "🌐"
  cd "$DIR/frontend" && npx vite --host 0.0.0.0 --port 15101 2>&1 | tee -a "$LOG_DIR/frontend.log" &
  FRONTEND_PID=$!
  sleep 1

  loading_bar "Arming audit shield  " "🛡️"
  echo ""

  echo -e "  ${BLU}╭──────────────────────────────────────────────────╮${R}"
  echo -e "  ${BLU}│${R}  ${GRN}🟢${R} Backend   ${B}:${ORG}15100${R}                           ${BLU}│${R}"
  echo -e "  ${BLU}│${R}  ${GRN}🟢${R} Frontend  ${B}:${ORG}15101${R}                           ${BLU}│${R}"
  echo -e "  ${BLU}╰──────────────────────────────────────────────────╯${R}"
  echo ""
  echo -e "  ${ORG}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${R}"
  echo -e "  ${GRN}${B}  🫴 SYSTEM ONLINE${R}  ${GRY}— 爪到擒来，合规无忧${R}"
  echo -e "  ${ORG}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${R}"
  echo ""

  trap "echo ''; echo -e '  ${ORG}🛑 ${B}SHUTDOWN${R}'; echo -e '  ${GRY}Terminating processes...${R}'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo -e '  ${DKG}SYSTEM OFFLINE${R}'; echo ''; exit" INT TERM
  wait
fi
