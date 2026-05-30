#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$DIR/logs"
mkdir -p "$LOG_DIR"

echo "=== ClawAVC ==="
echo "  Claw Access-View Compliance"
echo ""

# Kill existing processes on these ports
fuser -k 15100/tcp 2>/dev/null
fuser -k 15101/tcp 2>/dev/null
sleep 1

DAEMON=false
if [ "$1" = "-d" ] || [ "$1" = "--daemon" ]; then
  DAEMON=true
fi

if [ "$DAEMON" = true ]; then
  echo "[daemon] Running in background..."
  cd "$DIR/backend" && nohup uv run python3 app.py >> "$LOG_DIR/backend.log" 2>&1 &
  BACKEND_PID=$!
  sleep 3
  cd "$DIR/frontend" && nohup npx vite --host 0.0.0.0 --port 15101 >> "$LOG_DIR/frontend.log" 2>&1 &
  FRONTEND_PID=$!
  echo "✓ Backend:  http://0.0.0.0:15100 (pid: $BACKEND_PID)"
  echo "✓ Frontend: http://0.0.0.0:15101 (pid: $FRONTEND_PID)"
  echo "Logs: $LOG_DIR/"
  echo "Stop: fuser -k 15100/tcp; fuser -k 15101/tcp"
else
  # Foreground mode: output to terminal + log file
  echo "[1/2] Backend :15100 ..."
  cd "$DIR/backend" && uv run python3 app.py 2>&1 | tee -a "$LOG_DIR/backend.log" &
  BACKEND_PID=$!
  sleep 3

  echo "[2/2] Frontend :15101 ..."
  cd "$DIR/frontend" && npx vite --host 0.0.0.0 --port 15101 2>&1 | tee -a "$LOG_DIR/frontend.log" &
  FRONTEND_PID=$!

  echo ""
  echo "✓ Backend:  http://0.0.0.0:15100"
  echo "✓ Frontend: http://0.0.0.0:15101"
  echo "Logs: $LOG_DIR/"
  echo "Press Ctrl+C to stop"

  trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
  wait
fi
