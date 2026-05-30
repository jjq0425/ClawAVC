"""ClawAVC Monitor module.

Provides:
  - watcher: OpenClaw + Gateway log monitoring, round detection, action parsing
  - ir_client: Calls the existing translator API for IR translation
  - judge: User-state abnormal judging (from abnormal_judge_userState.py)
"""

from .watcher import start_monitor, MonitorOrchestrator

__all__ = ["start_monitor", "MonitorOrchestrator"]
