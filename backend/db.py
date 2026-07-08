"""SQLite data layer for Claw Access-View Compliance."""

import json
import sqlite3
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent.parent / "infos" / "db" / "clawAVC.db"

# ─── 可更新字段配置 ─────────────────────────────────────
# rounds 表中支持通过 API 修改的字段列表
UPDATABLE_FIELDS = [
    "action_json",
    "ir_json",
    "judge_result",
    "judge_result_kernel",
    "syscall_judge",
]


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id TEXT UNIQUE,
            time_start TEXT,
            time_end TEXT,
            session_key TEXT,
            session_id TEXT,
            user_query TEXT,
            last_llm_message TEXT,
            action_json TEXT,
            ir_json TEXT,
            judge_result TEXT,
            is_abnormal INTEGER DEFAULT 0,
            overall_score REAL DEFAULT 1.0,
            attack_config TEXT DEFAULT '',
            pid_info TEXT DEFAULT '',
            kernel_syscall_seq TEXT DEFAULT '',
            kernel_lsm_hook_result TEXT DEFAULT '',
            kernel_resource_facts TEXT DEFAULT '',
            judge_result_kernel TEXT DEFAULT '',
            syscall_judge TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migration: add columns added after initial release
    cols = [r[1] for r in conn.execute("PRAGMA table_info(rounds)").fetchall()]
    if "attack_config" not in cols:
        conn.execute("ALTER TABLE rounds ADD COLUMN attack_config TEXT DEFAULT ''")
    if "pid_info" not in cols:
        conn.execute("ALTER TABLE rounds ADD COLUMN pid_info TEXT DEFAULT ''")
    if "kernel_syscall_seq" not in cols:
        conn.execute("ALTER TABLE rounds ADD COLUMN kernel_syscall_seq TEXT DEFAULT ''")
    if "kernel_lsm_hook_result" not in cols:
        conn.execute("ALTER TABLE rounds ADD COLUMN kernel_lsm_hook_result TEXT DEFAULT ''")
    if "kernel_resource_facts" not in cols:
        conn.execute("ALTER TABLE rounds ADD COLUMN kernel_resource_facts TEXT DEFAULT ''")
    if "judge_result_kernel" not in cols:
        conn.execute("ALTER TABLE rounds ADD COLUMN judge_result_kernel TEXT DEFAULT ''")
    if "syscall_judge" not in cols:
        conn.execute("ALTER TABLE rounds ADD COLUMN syscall_judge TEXT DEFAULT ''")
    if "history" not in cols:
        conn.execute("ALTER TABLE rounds ADD COLUMN history TEXT DEFAULT ''")
    if "anomaly_llm_v2_judge_res" not in cols:
        conn.execute("ALTER TABLE rounds ADD COLUMN anomaly_llm_v2_judge_res TEXT DEFAULT ''")
    # 迁移：将旧的 resource_facts 列重命名为 kernel_resource_facts（如果存在）
    if "resource_facts" in cols and "kernel_resource_facts" not in cols:
        try:
            # SQLite 不支持直接重命名列，需要特殊处理
            conn.execute("""
                CREATE TABLE rounds_new AS SELECT *, '' as kernel_resource_facts FROM rounds
            """)
            conn.execute("DROP TABLE rounds")
            conn.execute("ALTER TABLE rounds_new RENAME TO rounds")
        except Exception as e:
            print(f"[db] Migration resource_facts to kernel_resource_facts failed: {e}")
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rounds_time ON rounds(time_start DESC)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rounds_abnormal ON rounds(is_abnormal)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS translation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id TEXT,
            query TEXT,
            level1_json TEXT,
            level2_json TEXT,
            validation_json TEXT,
            meta_json TEXT,
            is_ui_test INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 攻击消息表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attack_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            request_method TEXT,
            source_ip TEXT,
            source_host TEXT,
            user_agent TEXT,
            referrer TEXT,
            content_type TEXT,
            content_length INTEGER,
            message_content TEXT,
            headers_json TEXT,
            payload_json TEXT,
            attack_type TEXT DEFAULT 'unknown'
        )
    """)
    # 迁移：添加 request_method 列（如果不存在）
    cols = [r[1] for r in conn.execute("PRAGMA table_info(attack_messages)").fetchall()]
    if "request_method" not in cols:
        conn.execute("ALTER TABLE attack_messages ADD COLUMN request_method TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_attack_messages_time ON attack_messages(received_at DESC)")
    # 安全拦截事件表（IR 外工具拦截 / 后续可扩展更多拦截类型）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS intercept_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            event_type TEXT DEFAULT 'ir_tool_block',
            protocol TEXT,
            turn_key TEXT,
            user_query TEXT,  -- 已废弃，保留兼容旧数据
            round_id TEXT,   -- 新字段：本轮 round_id
            violations_json TEXT,
            allowed_tools_json TEXT,
            source TEXT,
            extra_json TEXT,
            note TEXT
        )
    """)
    # 迁移：为已存在的旧库补 round_id 列
    ie_cols = [r[1] for r in conn.execute("PRAGMA table_info(intercept_events)").fetchall()]
    if "round_id" not in ie_cols:
        try:
            conn.execute("ALTER TABLE intercept_events ADD COLUMN round_id TEXT")
            print("[db] migrate intercept_events.round_id success", flush=True)
        except Exception as e:
            print(f"[db] migrate intercept_events.round_id failed: {e}", flush=True)
    # 迁移：为已存在的旧库补 note 列（IR 长轮询超时上报等场景使用）
    if "note" not in ie_cols:
        try:
            conn.execute("ALTER TABLE intercept_events ADD COLUMN note TEXT")
        except Exception as e:
            print(f"[db] migrate intercept_events.note failed: {e}", flush=True)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_intercept_events_time ON intercept_events(received_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_intercept_events_turn ON intercept_events(turn_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_intercept_events_round ON intercept_events(round_id)")
    # API 请求追踪表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_trace (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            method TEXT,
            path TEXT,
            query_string TEXT,
            request_body TEXT,
            response_body TEXT,
            status_code INTEGER,
            duration_ms REAL,
            source_ip TEXT,
            user_agent TEXT,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_api_trace_time ON api_trace(received_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_api_trace_path ON api_trace(path)")
    # 初始化默认配置
    conn.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('round_update_time_limit_enabled', 'True')")
    conn.commit()
    conn.close()


def insert_round(data: Dict[str, Any]) -> Optional[int]:
    """Insert a round record. Returns row id or None if duplicate."""
    conn = get_conn()
    try:
        judge_result = data.get("abnormal_judge", "")
        is_abnormal = 0
        overall_score = 1.0

        if isinstance(judge_result, str):
            if overall_score < 0.5:
                is_abnormal = 1
            # Extract score from text like "整体得分: 0.3333"
            import re
            score_match = re.search(r"整体得分:\s*([\d.]+)", judge_result)
            if score_match:
                overall_score = float(score_match.group(1))

        cursor = conn.execute("""
            INSERT OR IGNORE INTO rounds
            (round_id, time_start, time_end, session_key, session_id,
             user_query, last_llm_message, action_json, ir_json,
             judge_result, is_abnormal, overall_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("round", ""),
            data.get("time_start", "").strip(),
            data.get("time_end", "").strip(),
            data.get("sessionKey", ""),
            data.get("sessionID", ""),
            data.get("user_query", ""),
            data.get("last_llm_message", ""),
            json.dumps(data.get("action", []), ensure_ascii=False),
            json.dumps(data.get("IR", {}), ensure_ascii=False),
            judge_result,
            is_abnormal,
            overall_score,
        ))
        conn.commit()
        return cursor.lastrowid if cursor.rowcount > 0 else None
    except Exception as e:
        print(f"[db] insert error: {e}")
        return None
    finally:
        conn.close()



def insert_round_start(round_id: str, time_start: str, session_key: str, session_id: str,
                       attack_config: str = "", pid_info: str = "", history: str = "") -> Optional[int]:
    """Insert a round record at ROUND_START (partial data, no score yet).

    attack_config: 当前攻击配置的完整 JSON 快照，在 round 开始时固化保存。
    pid_info: OpenClaw 进程及其安全/隔离上下文（PID、SELinux/AppArmor、capabilities、
              namespaces、cgroup、ancestors 等）的 JSON 快照。
    history: 对话历史 JSON，包含之前的 user/assistant/tool 消息。
    """
    conn = get_conn()
    try:
        cursor = conn.execute("""
            INSERT OR IGNORE INTO rounds
            (round_id, time_start, time_end, session_key, session_id,
             user_query, last_llm_message, action_json, ir_json,
             judge_result, is_abnormal, overall_score, attack_config, pid_info, history)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            round_id, time_start, "", session_key, session_id,
            "", "", "[]", "{}", "", 0, -1.0, attack_config, pid_info, history,
        ))
        conn.commit()
        return cursor.lastrowid if cursor.rowcount > 0 else None
    except Exception as e:
        print(f"[db] insert_round_start error: {e}")
        return None
    finally:
        conn.close()


def update_round_end(round_id: str, data: Dict[str, Any]) -> bool:
    """Update a round record at ROUND_END with full data.

    动态拼接 SET 子句，只更新 data 中有值的字段，避免 None/空字符串覆盖已有数据。
    
    防覆盖规则：
      - 所有字段：若入参为 None 或空字符串，跳过。
      - ir_json：额外保护——若入参为 `'{}'`/`'__loading__'` 且 DB 已有真实 IR，也跳过。
      - 其它字段：只更新 data 中存在的、非空的字段。
    """
    conn = get_conn()
    try:
        set_parts: list = []
        params: list = []
        skipped: list = []

        # user_query
        v = data.get("user_query")
        if v is not None and v != "":
            set_parts.append("user_query = ?")
            params.append(v)
        else:
            skipped.append(f"user_query({v!r})")

        # judge_result
        v = data.get("judge_result")
        if v is not None and v != "":
            set_parts.append("judge_result = ?")
            params.append(v)
        else:
            skipped.append(f"judge_result({v!r})")

        # is_abnormal
        v = data.get("is_abnormal")
        if v is not None:
            set_parts.append("is_abnormal = ?")
            params.append(1 if v else 0)
        else:
            skipped.append(f"is_abnormal({v!r})")

        # overall_score
        v = data.get("overall_score")
        if v is not None:
            set_parts.append("overall_score = ?")
            params.append(v)
        else:
            skipped.append(f"overall_score({v!r})")

        # time_end
        v = data.get("time_end")
        if v is not None and v != "":
            set_parts.append("time_end = ?")
            params.append(v)
        else:
            skipped.append(f"time_end({v!r})")

        # last_llm_message
        v = data.get("last_llm_message")
        if v is not None and v != "":
            set_parts.append("last_llm_message = ?")
            params.append(v)
        else:
            skipped.append(f"last_llm_message({v!r})")

        # history
        v = data.get("history")
        if v is not None and v != "":
            set_parts.append("history = ?")
            params.append(v)
        else:
            skipped.append(f"history({v!r})")

        # action_json: 拒绝 None、空字符串、'[]'占位值
        # 如果 DB 中已有真实的 actions（非 '[]'），且入参是 '[]'，则跳过保护已有数据
        v = data.get("action_json")
        action_keep_reason = ""
        if v is None or v == "":
            action_keep_reason = "empty"
        elif v == "[]":
            # 入参是占位值，检查 DB 是否已有真实 actions
            try:
                cur_row = conn.execute(
                    "SELECT action_json FROM rounds WHERE round_id = ?",
                    (round_id,),
                ).fetchone()
                cur_actions = (cur_row[0] if cur_row else "") or ""
                if cur_actions and cur_actions != "[]":
                    action_keep_reason = f"placeholder_db_has_real(len={len(cur_actions)})"
            except Exception:
                pass

        if not action_keep_reason:
            set_parts.append("action_json = ?")
            params.append(v)
        else:
            skipped.append(f"action_json[{action_keep_reason}]({v!r})")

        # ir_json: 拒绝 None 和空字符串，且保护 DB 中已有真实 IR
        v = data.get("ir_json")
        ir_keep_reason = ""
        if v is None or v == "":
            ir_keep_reason = "empty"
        elif v in ("{}", "__loading__"):
            # 入参是占位值，检查 DB 是否已有真实 IR
            try:
                cur_row = conn.execute(
                    "SELECT ir_json FROM rounds WHERE round_id = ?",
                    (round_id,),
                ).fetchone()
                cur_ir = (cur_row[0] if cur_row else "") or ""
                if cur_ir and cur_ir not in ("{}", "__loading__"):
                    ir_keep_reason = f"placeholder_db_has_real(len={len(cur_ir)})"
            except Exception:
                pass

        if not ir_keep_reason:
            set_parts.append("ir_json = ?")
            params.append(v)
        else:
            skipped.append(f"ir_json[{ir_keep_reason}]({v!r})")

        if not set_parts:
            print(f"[db.update_round_end] round_id={round_id} no fields to update, skipped={skipped}", flush=True)
            return False

        params.append(round_id)
        sql = f"UPDATE rounds SET {', '.join(set_parts)} WHERE round_id = ?"
        cursor = conn.execute(sql, params)
        conn.commit()
        affected = cursor.rowcount

        print(
            f"[db.update_round_end] round_id={round_id} affected={affected} "
            f"updated={set_parts} skipped={skipped}",
            flush=True,
        )
        return affected > 0
    except Exception as e:
        print(f"[db] update_round_end error: {e}")
        return False
    finally:
        conn.close()

def get_rounds(limit: int = 50, offset: int = 0, abnormal_only: bool = False,
             query: str = "", round_id: str = "",
             time_from: str = "", time_to: str = "") -> Dict[str, Any]:
    """Get rounds with filters. Returns {total, data}."""
    conn = get_conn()
    conditions = []
    params = []
    if abnormal_only:
        conditions.append("is_abnormal = 1")
    if query:
        conditions.append("user_query LIKE ?")
        params.append(f"%{query}%")
    if round_id:
        conditions.append("round_id LIKE ?")
        params.append(f"%{round_id}%")
    if time_from:
        conditions.append("time_start >= ?")
        params.append(time_from)
    if time_to:
        conditions.append("time_start <= ?")
        params.append(time_to)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    total = conn.execute(f"SELECT COUNT(*) FROM rounds {where}", params).fetchone()[0]
    rows = conn.execute(f"SELECT * FROM rounds {where} ORDER BY time_start DESC LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
    conn.close()
    return {"total": total, "data": [dict(r) for r in rows]}


def get_round_by_id(round_id: str) -> Optional[Dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM rounds WHERE round_id = ?", (round_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_round_field(round_id: str, field: str, value: str, time_limit_enabled: bool = True) -> str:
    """更新 rounds 表中指定字段的值。field 为列名，value 为字符串。
    
    Args:
        round_id: Round ID
        field: 要更新的字段名
        value: 新值
        time_limit_enabled: 是否启用15分钟时间限制
    
    Returns:
        "ok" - 更新成功
        "not_found" - round_id 不存在
        "too_old" - 数据超过 15 分钟，需前往数据运维页面修改
        "unsupported" - 不支持该字段
        "error" - 其他错误
    """
    if field not in UPDATABLE_FIELDS:
        return "unsupported"
    conn = get_conn()
    try:
        # 先检查 round_id 是否存在，并获取创建时间
        existing = conn.execute(
            "SELECT created_at FROM rounds WHERE round_id = ?", (round_id,)
        ).fetchone()
        if not existing:
            return "not_found"
        # 检查创建时间是否超过 15 分钟（仅当开关启用时）
        if time_limit_enabled:
            created_at = existing[0]
            if created_at:
                from datetime import datetime, timedelta
                created_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                now = datetime.now()
                if now - created_dt > timedelta(minutes=15):
                    return "too_old"
        # is_abnormal 需要转为整数
        if field == "is_abnormal":
            conn.execute("UPDATE rounds SET is_abnormal = ? WHERE round_id = ?", (1 if value else 0, round_id))
        else:
            conn.execute(f"UPDATE rounds SET {field} = ? WHERE round_id = ?", (value, round_id))
        conn.commit()
        return "ok"
    except Exception as e:
        print(f"[db] update_round_field error: {e}")
        return "error"
    finally:
        conn.close()


def update_kernel_info(round_id: str, kernel_syscall_seq_path: str, kernel_lsm_hook_result_path: str, kernel_resource_facts_path: str, time_limit_enabled: bool = True) -> str:
    """更新内核态信息。
    
    Args:
        round_id: Round ID
        kernel_syscall_seq_path: 内核态系统调用序列文件路径
        kernel_lsm_hook_result_path: 内核态LSM hook检查结果文件路径
        kernel_resource_facts_path: 内核资源事实信息文件路径
        time_limit_enabled: 是否启用15分钟时间限制
    
    Returns:
        "ok" - 更新成功
        "not_found" - round_id 不存在
        "too_old" - 数据超过 15 分钟
        "error" - 其他错误
    """
    import os
    import shutil
    from pathlib import Path
    
    # 获取 infos 目录路径
    infos_dir = Path(__file__).parent.parent / "infos" / "kernel_infos" / round_id
    infos_dir.mkdir(parents=True, exist_ok=True)
    
    # 处理 kernel_syscall_seq：复制文件并获取新路径（覆盖已存在的文件）
    kernel_syscall_seq = ""
    if kernel_syscall_seq_path:
        try:
            src_path = Path(kernel_syscall_seq_path)
            if src_path.exists():
                dest_path = infos_dir / f"{round_id}_syscall_seq.jsonl"
                if dest_path.exists():
                    print(f"[db] Overwriting existing kernel_syscall_seq file: {dest_path}")
                shutil.copy2(src_path, dest_path)
                kernel_syscall_seq = str(dest_path)
            else:
                return "error"
        except Exception as e:
            print(f"[db] Copy kernel_syscall_seq failed: {e}")
            return "error"
    
    # 处理 kernel_lsm_hook_result：复制文件并获取新路径（覆盖已存在的文件）
    kernel_lsm_hook_result = ""
    if kernel_lsm_hook_result_path:
        try:
            src_path = Path(kernel_lsm_hook_result_path)
            if src_path.exists():
                dest_path = infos_dir / f"{round_id}_lsm_hook_result.jsonl"
                if dest_path.exists():
                    print(f"[db] Overwriting existing kernel_lsm_hook_result file: {dest_path}")
                shutil.copy2(src_path, dest_path)
                kernel_lsm_hook_result = str(dest_path)
            else:
                return "error"
        except Exception as e:
            print(f"[db] Copy kernel_lsm_hook_result failed: {e}")
            return "error"
    
    # 处理 kernel_resource_facts：读取文件内容
    kernel_resource_facts = ""
    if kernel_resource_facts_path:
        try:
            src_path = Path(kernel_resource_facts_path)
            if src_path.exists():
                with open(src_path, 'r', encoding='utf-8') as f:
                    kernel_resource_facts = f.read()
            else:
                return "error"
        except Exception as e:
            print(f"[db] Read resource_facts failed: {e}")
            return "error"
    
    conn = get_conn()
    try:
        # 先检查 round_id 是否存在，并获取创建时间
        existing = conn.execute(
            "SELECT created_at FROM rounds WHERE round_id = ?", (round_id,)
        ).fetchone()
        if not existing:
            return "not_found"
        
        # 检查创建时间是否超过 15 分钟（仅当开关启用时）
        if time_limit_enabled:
            created_at = existing[0]
            if created_at:
                from datetime import datetime, timedelta
                created_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                now = datetime.now()
                if now - created_dt > timedelta(minutes=15):
                    return "too_old"
        
        # 更新内核态信息
        conn.execute("""
            UPDATE rounds 
            SET kernel_syscall_seq = ?, 
                kernel_lsm_hook_result = ?,
                kernel_resource_facts = ?
            WHERE round_id = ?
        """, (kernel_syscall_seq, kernel_lsm_hook_result, kernel_resource_facts, round_id))
        conn.commit()
        return "ok"
    except Exception as e:
        print(f"[db] update_kernel_info error: {e}")
        return "error"
    finally:
        conn.close()


def update_anomaly_llm_v2_judge(round_id: str, value: str) -> str:
    """写入二阶段异常判断大模型（v2）的返回结果，不走 15 分钟时间限制。

    Args:
        round_id: Round ID
        value: 待写入的结果文本（通常为 request_anomaly_llm_url_v2 返回的 JSON 字符串）

    Returns:
        "ok" - 写入成功
        "not_found" - 对应 round_id 不存在（调用方据此忽略）
        "error" - 写入异常
    """
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT round_id FROM rounds WHERE round_id = ?", (round_id,)
        ).fetchone()
        if not existing:
            return "not_found"
        conn.execute(
            "UPDATE rounds SET anomaly_llm_v2_judge_res = ? WHERE round_id = ?",
            (value, round_id),
        )
        conn.commit()
        return "ok"
    except Exception as e:
        print(f"[db] update_anomaly_llm_v2_judge error: {e}")
        return "error"
    finally:
        conn.close()


def update_judge_result_kernel(round_id: str, judge_result_kernel_md_path: str, time_limit_enabled: bool = True) -> str:
    """更新内核态判断结果。
    
    Args:
        round_id: Round ID
        judge_result_kernel_md_path: 内核态判断结果 Markdown 文件路径
        time_limit_enabled: 是否启用15分钟时间限制
    
    Returns:
        "ok" - 更新成功
        "not_found" - round_id 不存在
        "too_old" - 数据超过 15 分钟，需前往数据运维页面修改
        "error" - 其他错误
    """
    import os
    import shutil
    from pathlib import Path
    
    # 获取 kernel_judge 目录路径
    kernel_judge_dir = Path(__file__).parent.parent / "infos" / "kernel_judge"
    kernel_judge_dir.mkdir(parents=True, exist_ok=True)
    
    # 处理 judge_result_kernel_md：复制文件并获取新路径（覆盖已存在的文件）
    judge_result_kernel = ""
    if judge_result_kernel_md_path:
        try:
            src_path = Path(judge_result_kernel_md_path)
            if src_path.exists():
                dest_path = kernel_judge_dir / f"{round_id}_judge_result.md"
                if dest_path.exists():
                    print(f"[db] Overwriting existing judge_result_kernel file: {dest_path}")
                shutil.copy2(src_path, dest_path)
                # 存储绝对路径
                judge_result_kernel = str(dest_path.absolute())
            else:
                return "error"
        except Exception as e:
            print(f"[db] Copy judge_result_kernel_md failed: {e}")
            return "error"
    
    conn = get_conn()
    try:
        # 检查 round_id 是否存在，并获取创建时间
        existing = conn.execute(
            "SELECT created_at FROM rounds WHERE round_id = ?", (round_id,)
        ).fetchone()
        if not existing:
            return "not_found"
        # 检查创建时间是否超过 15 分钟（仅当开关启用时）
        if time_limit_enabled:
            created_at = existing[0]
            if created_at:
                from datetime import datetime, timedelta
                created_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                now = datetime.now()
                if now - created_dt > timedelta(minutes=15):
                    return "too_old"
        # 更新 judge_result_kernel 字段
        conn.execute(
            "UPDATE rounds SET judge_result_kernel = ? WHERE round_id = ?",
            (judge_result_kernel, round_id)
        )
        conn.commit()
        return "ok"
    except Exception as e:
        print(f"[db] update_judge_result_kernel error: {e}")
        return "error"
    finally:
        conn.close()


def parse_json_input(data) -> dict:
    """解析各种格式的 JSON 输入，返回 dict 对象。
    
    支持的格式：
    1. 已经是 dict 对象
    2. 标准 JSON 字符串
    3. 带转义的 JSON 字符串 (如 \\" -> \")
    4. 多重转义的 JSON 字符串
    5. 压缩的 JSON 字符串
    6. 格式的 JSON 字符串（带换行、缩进）
    """
    import json
    import re
    
    # 如果已经是 dict，直接返回
    if isinstance(data, dict):
        return data
    
    # 如果是 bytes，先转为字符串
    if isinstance(data, bytes):
        data = data.decode('utf-8')
    
    # 如果不是字符串，尝试转为字符串
    if not isinstance(data, str):
        return dict(data) if data else {}
    
    s = data.strip()
    if not s:
        return {}
    
    # 递归解析函数
    def try_parse(text, depth=0):
        if depth > 5:
            raise ValueError("JSON 嵌套过深")
        
        # 尝试直接解析
        try:
            result = json.loads(text)
            # 如果结果还是字符串，可能是双重编码，继续解析
            if isinstance(result, str):
                return try_parse(result, depth + 1)
            return result
        except json.JSONDecodeError:
            pass
        
        # 尝试修复转义后解析
        try:
            # 处理 \\" -> \"
            fixed = text.replace('\\"', '"')
            result = json.loads(fixed)
            if isinstance(result, str):
                return try_parse(result, depth + 1)
            return result
        except json.JSONDecodeError:
            pass
        
        # 尝试处理 \\n -> \n
        try:
            fixed = text.replace('\\n', '\n')
            fixed = fixed.replace('\\r', '\r')
            fixed = fixed.replace('\\t', '\t')
            result = json.loads(fixed)
            if isinstance(result, str):
                return try_parse(result, depth + 1)
            return result
        except json.JSONDecodeError:
            pass
        
        # 尝试处理 \\\\ -> \\
        try:
            fixed = text.replace('\\\\', '\\')
            result = json.loads(fixed)
            if isinstance(result, str):
                return try_parse(result, depth + 1)
            return result
        except json.JSONDecodeError:
            pass
        
        # 尝试使用 ast.literal_eval (处理 Python 字面量)
        try:
            import ast
            result = ast.literal_eval(text)
            if isinstance(result, str):
                return try_parse(result, depth + 1)
            return result
        except (ValueError, SyntaxError):
            pass
        
        raise ValueError(f"无法解析 JSON: {text[:100]}...")
    
    result = try_parse(s)
    
    # 确保返回 dict
    if isinstance(result, dict):
        return result
    elif isinstance(result, list):
        return {"data": result}
    else:
        return {"value": result}


def update_syscall_judge_json(round_id: str, syscall_judge_data, time_limit_enabled: bool = True) -> str:
    """更新系统调用判断结果（直接存储 JSON）。
    
    Args:
        round_id: Round ID
        syscall_judge_data: 系统调用判断结果 JSON 数据（支持各种格式）
        time_limit_enabled: 是否启用15分钟时间限制
    
    Returns:
        "ok" - 更新成功
        "not_found" - round_id 不存在
        "too_old" - 数据超过 15 分钟，需前往数据运维页面修改
        "error" - 其他错误
    """
    import json
    
    # 解析输入的 JSON 数据
    try:
        data_dict = parse_json_input(syscall_judge_data)
    except ValueError as e:
        print(f"[db] parse_json_input error: {e}")
        return "error"
    
    # 将 dict 压缩后转为 JSON 字符串存储（ensure_ascii=True 确保纯 ASCII）
    syscall_judge_json = json.dumps(data_dict, ensure_ascii=True, separators=(',', ':'))
    
    conn = get_conn()
    try:
        # 检查 round_id 是否存在，并获取创建时间
        existing = conn.execute(
            "SELECT created_at FROM rounds WHERE round_id = ?", (round_id,)
        ).fetchone()
        if not existing:
            return "not_found"
        # 检查创建时间是否超过 15 分钟（仅当开关启用时）
        if time_limit_enabled:
            created_at = existing[0]
            if created_at:
                from datetime import datetime, timedelta
                created_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                now = datetime.now()
                if now - created_dt > timedelta(minutes=15):
                    return "too_old"
        # 更新 syscall_judge 字段
        conn.execute(
            "UPDATE rounds SET syscall_judge = ? WHERE round_id = ?",
            (syscall_judge_json, round_id)
        )
        conn.commit()
        return "ok"
    except Exception as e:
        print(f"[db] update_syscall_judge error: {e}")
        return "error"


def get_config(key: str, default_value: str = None) -> str:
    """获取配置项值
    
    Args:
        key: 配置项键名
        default_value: 默认值
    
    Returns:
        配置项的值，如果不存在则返回默认值
    """
    conn = get_conn()
    try:
        result = conn.execute(
            "SELECT value FROM config WHERE key = ?", (key,)
        ).fetchone()
        return result[0] if result else default_value
    except Exception as e:
        print(f"[db] get_config error: {e}")
        return default_value
    finally:
        conn.close()


def set_config(key: str, value: str) -> bool:
    """设置配置项值
    
    Args:
        key: 配置项键名
        value: 配置项值
    
    Returns:
        是否成功
    """
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO config (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
        """, (key, value, value))
        conn.commit()
        return True
    except Exception as e:
        print(f"[db] set_config error: {e}")
        return False
    finally:
        conn.close()


def get_stats() -> Dict[str, Any]:
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM rounds").fetchone()[0]
    abnormal = conn.execute("SELECT COUNT(*) FROM rounds WHERE is_abnormal = 1").fetchone()[0]
    avg_score = conn.execute("SELECT AVG(overall_score) FROM rounds").fetchone()[0] or 1.0
    conn.close()
    return {
        "total": total,
        "abnormal": abnormal,
        "normal": total - abnormal,
        "avg_score": round(avg_score, 4),
    }


def import_from_jsonl(jsonl_path: str):
    """Import historical data from JSONL file."""
    if not os.path.exists(jsonl_path):
        return 0
    count = 0
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("when") != "end":
                    continue
                result = insert_round(data)
                if result:
                    count += 1
            except Exception:
                continue
    return count



# ============================================================
# Attack Messages
# ============================================================

def insert_attack_message(data: Dict[str, Any]) -> Optional[int]:
    """Insert an attack message record. Returns row id or None on error."""
    conn = get_conn()
    try:
        cursor = conn.execute("""
            INSERT INTO attack_messages
            (received_at, request_method, source_ip, source_host, user_agent, referrer, 
             content_type, content_length, message_content, headers_json, 
             payload_json, attack_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("received_at", ""),
            data.get("request_method", ""),
            data.get("source_ip", ""),
            data.get("source_host", ""),
            data.get("user_agent", ""),
            data.get("referrer", ""),
            data.get("content_type", ""),
            data.get("content_length", 0),
            data.get("message_content", ""),
            json.dumps(data.get("headers", {}), ensure_ascii=False),
            json.dumps(data.get("payload", {}), ensure_ascii=False),
            data.get("attack_type", "unknown"),
        ))
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        print(f"[db] insert_attack_message error: {e}")
        return None
    finally:
        conn.close()


def get_attack_messages(limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """Get attack messages with pagination. Returns {total, data}."""
    conn = get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM attack_messages").fetchone()[0]
        rows = conn.execute(
            """SELECT id, received_at, request_method, source_ip, source_host, user_agent,
                      referrer, content_type, content_length, message_content,
                      headers_json, payload_json, attack_type
               FROM attack_messages 
               ORDER BY received_at DESC 
               LIMIT ? OFFSET ?""",
            (limit, offset)
        ).fetchall()
        data = []
        for row in rows:
            d = dict(row)
            # 解析 JSON 字段
            if d.get("headers_json"):
                try:
                    d["headers"] = json.loads(d.pop("headers_json"))
                except:
                    d["headers"] = {}
            else:
                d["headers"] = {}
            if d.get("payload_json"):
                try:
                    d["payload"] = json.loads(d.pop("payload_json"))
                except:
                    d["payload"] = {}
            else:
                d["payload"] = {}
            data.append(d)
        conn.close()
        return {"total": total, "data": data}
    except Exception as e:
        print(f"[db] get_attack_messages error: {e}")
        return {"total": 0, "data": []}


def clear_attack_messages() -> int:
    """Clear all attack messages. Returns deleted count."""
    conn = get_conn()
    try:
        cursor = conn.execute("DELETE FROM attack_messages")
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        print(f"[db] clear_attack_messages error: {e}")
        return 0
    finally:
        conn.close()


# ============================================================
# API Trace
# ============================================================

def insert_api_trace(trace_data: Dict[str, Any]) -> None:
    """异步写入 API 请求追踪记录。"""
    import threading
    
    def _do_insert():
        try:
            conn = get_conn()
            conn.execute("""
                INSERT INTO api_trace 
                (received_at, method, path, query_string, request_body, response_body,
                 status_code, duration_ms, source_ip, user_agent, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trace_data.get("received_at"),
                trace_data.get("method"),
                trace_data.get("path"),
                trace_data.get("query_string"),
                trace_data.get("request_body"),
                trace_data.get("response_body"),
                trace_data.get("status_code"),
                trace_data.get("duration_ms"),
                trace_data.get("source_ip"),
                trace_data.get("user_agent"),
                trace_data.get("error_message"),
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[db] insert_api_trace error: {e}", flush=True)
    
    threading.Thread(target=_do_insert, daemon=True).start()


def get_api_trace(limit: int = 100, offset: int = 0, path: str = "") -> Dict[str, Any]:
    """查询 API 请求追踪记录。"""
    conn = get_conn()
    try:
        conditions = []
        params = []
        if path:
            conditions.append("path LIKE ?")
            params.append(f"%{path}%")
        
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        
        total = conn.execute(f"SELECT COUNT(*) FROM api_trace{where}", params).fetchone()[0]
        rows = conn.execute(f"""
            SELECT id, received_at, method, path, query_string, 
                   substr(request_body, 1, 200) as request_body,
                   substr(response_body, 1, 200) as response_body,
                   status_code, duration_ms, source_ip, error_message
            FROM api_trace{where}
            ORDER BY id DESC LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()
        conn.close()
        return {"total": total, "data": [dict(r) for r in rows]}
    except Exception as e:
        print(f"[db] get_api_trace error: {e}", flush=True)
        return {"total": 0, "data": []}


def clear_api_trace() -> int:
    """清空 api_trace 表，返回删除的记录数。"""
    conn = get_conn()
    try:
        cursor = conn.execute("DELETE FROM api_trace")
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        print(f"[db] clear_api_trace error: {e}", flush=True)
        return 0


# ============================================================
# Config / Auth
# ============================================================

def init_config_table():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    # Default secret key
    conn.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('secret_key', 'abc')")
    # Default subdomain (二级域名密钥)
    conn.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('admin_key', 'admin')")
    conn.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('monitor_conf.use_gateway', 'false')")

    conn.commit()
    conn.close()


def set_config(key: str, value: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def get_configs_by_prefix(prefix: str) -> dict:
    """返回所有 key 以 prefix 开头的配置项，{key: value}。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT key, value FROM config WHERE key LIKE ?", (prefix + "%",)
    ).fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}


def verify_secret(secret: str) -> bool:
    """Verify if the provided secret matches the stored key."""
    stored = get_config("secret_key")
    return stored is not None and secret == stored




def verify_admin(key: str) -> bool:
    """Verify admin key. Admin key is hardcoded and cannot be changed."""
    stored = get_config("admin_key")
    return stored is not None and key == stored




def insert_translation_log(result: Dict[str, Any], is_ui_test: bool = False, round_id: Optional[str] = None) -> Optional[int]:
    """Store a translation result in the log."""
    conn = get_conn()
    try:
        cursor = conn.execute("""
            INSERT INTO translation_log (round_id, query, level1_json, level2_json, validation_json, meta_json, is_ui_test)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            round_id,
            result.get("query", ""),
            json.dumps(result.get("level1", []), ensure_ascii=False),
            json.dumps(result.get("level2", {}), ensure_ascii=False),
            json.dumps(result.get("validation", {}), ensure_ascii=False),
            json.dumps(result.get("meta", {}), ensure_ascii=False),
            1 if is_ui_test else 0,
        ))
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        print(f"[db] translation log insert error: {e}")
        return None
    finally:
        conn.close()


def insert_or_update_translation_log(result: Dict[str, Any], is_ui_test: bool = False, round_id: Optional[str] = None) -> bool:
    """Insert or update translation log. If round_id exists, update; otherwise insert."""
    conn = get_conn()
    try:
        if round_id:
            # Check if record exists
            existing = conn.execute(
                "SELECT id FROM translation_log WHERE round_id = ?", (round_id,)
            ).fetchone()
            
            if existing:
                # Update existing record
                conn.execute("""
                    UPDATE translation_log 
                    SET query = ?, level1_json = ?, level2_json = ?, 
                        validation_json = ?, meta_json = ?
                    WHERE round_id = ?
                """, (
                    result.get("query", ""),
                    json.dumps(result.get("level1", []), ensure_ascii=False),
                    json.dumps(result.get("level2", {}), ensure_ascii=False),
                    json.dumps(result.get("validation", {}), ensure_ascii=False),
                    json.dumps(result.get("meta", {}), ensure_ascii=False),
                    round_id,
                ))
            else:
                # Insert new record
                conn.execute("""
                    INSERT INTO translation_log (round_id, query, level1_json, level2_json, validation_json, meta_json, is_ui_test)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    round_id,
                    result.get("query", ""),
                    json.dumps(result.get("level1", []), ensure_ascii=False),
                    json.dumps(result.get("level2", {}), ensure_ascii=False),
                    json.dumps(result.get("validation", {}), ensure_ascii=False),
                    json.dumps(result.get("meta", {}), ensure_ascii=False),
                    1 if is_ui_test else 0,
                ))
        else:
            # No round_id, just insert
            conn.execute("""
                INSERT INTO translation_log (round_id, query, level1_json, level2_json, validation_json, meta_json, is_ui_test)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                round_id,
                result.get("query", ""),
                json.dumps(result.get("level1", []), ensure_ascii=False),
                json.dumps(result.get("level2", {}), ensure_ascii=False),
                json.dumps(result.get("validation", {}), ensure_ascii=False),
                json.dumps(result.get("meta", {}), ensure_ascii=False),
                1 if is_ui_test else 0,
            ))
        conn.commit()
        return True
    except Exception as e:
        print(f"[db] insert_or_update_translation_log error: {e}")
        return False
    finally:
        conn.close()


def insert_translation_log_pending(round_id: str, query: str, is_ui_test: bool = False) -> bool:
    """Insert a pending translation log entry when translation starts."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO translation_log (round_id, query, level1_json, level2_json, validation_json, meta_json, is_ui_test)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            round_id,
            query,
            "[]",  # empty level1
            "{}",  # empty level2
            "{}",  # empty validation
            "{}",  # empty meta
            1 if is_ui_test else 0,
        ))
        conn.commit()
        return True
    except Exception as e:
        print(f"[db] insert_translation_log_pending error: {e}")
        return False
    finally:
        conn.close()


def update_translation_log_level1(round_id: str, scenes: List[str], meta: Dict[str, Any]) -> bool:
    """Update translation log with level1 result."""
    conn = get_conn()
    try:
        conn.execute("""
            UPDATE translation_log 
            SET level1_json = ?, meta_json = json_set(meta_json, '$.level1', json(?))
            WHERE round_id = ?
        """, (
            json.dumps(scenes, ensure_ascii=False),
            json.dumps(meta, ensure_ascii=False),
            round_id,
        ))
        conn.commit()
        return True
    except Exception as e:
        print(f"[db] update_translation_log_level1 error: {e}")
        return False
    finally:
        conn.close()


def get_translation_logs(limit: int = 50, offset: int = 0, ui_only: bool = False) -> List[Dict]:
    conn = get_conn()
    where = "WHERE is_ui_test = 1" if ui_only else ""
    rows = conn.execute(f"""
        SELECT * FROM translation_log {where}
        ORDER BY created_at DESC LIMIT ? OFFSET ?
    """, (limit, offset)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _init_translator_prompts():
    """Initialize translator prompts in config if not present."""
    conn = get_conn()
    # Check if already initialized
    existing = conn.execute("SELECT value FROM config WHERE key = 'ir_translator.prompt_level1'").fetchone()
    if existing and existing[0]:
        conn.close()
        return

    LEVEL1_PROMPT = """你是一个「Agent 权限场景分类器」。

任务：根据用户自然语言请求，选择完成任务"必须授权"的最小场景集合。

只允许从下面的封闭集合中选择，不得创造新标签：

{SCENE_LIST}

输出格式：
{
  "scenes": ["<scene1>", "<scene2>"]
}

判定原则：
1. 只选择用户请求中明确需要、或完成任务不可避免需要的 scene；不要因为模型"可能会用到"就扩大授权。
2. scenes 顺序必须按用户任务的实际执行顺序排列，例如"搜索并保存"应为 ["search", "file_ops"]。
3. 如果请求需要最新信息、联网核验、来源链接、网页内容读取，选择 search；如果只是一般常识回答，不要选择 search。
4. 如果请求需要真实浏览器渲染、点击、输入、截图、登录态页面或 DOM 交互，选择 browser；普通信息检索不要用 browser。
5. 如果请求涉及读取、写入、编辑、保存、导出、生成文件、打补丁或整理文件，选择 file_ops。
6. 如果请求涉及执行命令、运行脚本、测试、构建、安装、启动服务、查看环境或查看进程，选择 shell_exec；如果是长期/交互式会话再选择 terminal_session。
7. 如果请求涉及进程状态、停止、重启、kill、PID、后台服务控制，选择 process_control 或 runtime_exec 中更贴近语义的 scene。
8. 如果请求涉及对外发送消息、通知、邮件、日历、媒体播放、锁屏、提权等，只在用户明确要求时选择对应 scene。
9. 不能输出封闭集合之外的 scene。不能输出解释、注释、Markdown 代码块。"""

    LEVEL2_PROMPT = """你是一个「OpenClaw function-level 权限 IR 生成器」。

输入：
1. 用户 query
2. 第一阶段得到的 scenes
3. 每个 scene 对应的 function 定义 JSON

任务：基于输入，输出完成该 query 所需的权限 IR（subject/objects 格式）。你的输出是权限授权计划，不是执行计划。

重要：对于每个 scene，你必须列出该场景下所有可能被 Agent 用来完成任务的 function（不要只列一个），并为每个 function 都生成完整的参数约束。Agent 的实际行为可能使用同一场景下的多种工具组合，你需要预判并覆盖所有合理的执行路径。

输出格式要求（严格遵守）：
- 只输出一个 JSON 对象，顶层必须包含 `policies` 数组。
- 每个 policy 必须包含：`subject`（场景名）、`objects`（数组）、`effect`（值为 "allow"）。
- objects 数组中每个对象必须包含：`type`（"tool" 或 "file"）、`identifier`（工具函数名或文件路径）。
- 对于 type="tool" 的对象：
  - `identifier` 必须逐字等于 function 定义 JSON 中的 key（如 "read"、"safe_file_reader__read_text"）。
  - `actions` 固定为 ["invoke"]。
  - `params` 为数组格式：[{"name": "参数名", "identifier": "参数值"}]，只能使用 function 定义中声明过的参数名。
- 对于 type="file" 的对象：
  - `identifier` 为文件路径（来自用户 query 或工具参数中的路径）。
  - `actions` 为允许的文件操作列表，如 ["read"]、["write", "create"] 等。
- 不得输出任何额外解释、注释或 Markdown。

关键规则：
1. 场景内全覆盖：对于每个已选 scene，必须列出所有可能被 Agent 调用的 function 作为 tool 对象。不要只输出一个——Agent 可能通过多种工具路径完成同一任务。
2. 文件资源必须显式声明：如果某个工具的参数中包含文件路径，除了 tool 对象外，还必须额外生成一个对应的 type="file" 对象，声明允许的文件操作。
3. identifier 必须逐字等于 function 定义 JSON 中的 key；不得使用别名或自然语言。
4. params 值来源优先级：用户 query 明确给出 > 已验证上下文 > constraint_spec.static.default。对模棱两可的输入可留空字符串，但能从 query 明确提取的值不要留空。
5. 必须遵守 function 的 desc、constraint_spec.dynamic_ai_hint、static.allowlist/denylist 等约束。
6. 对于 allowed_values 非空的参数，值必须从中选择。
7. 对于高风险能力（shell、privilege 等），优先生成只读/查询权限。
8. 如果同一 scene 中多个 function 都能完成任务，必须全部列出——无法预知 Agent 选哪个。
9. 任何 required=true 的参数无法安全确定时，不生成该 function 对象。
10. 严禁输出密钥、隐私数据、敏感目录路径。

当前可用 function 定义 JSON：
{SELECTED_REGISTRY}"""

    conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                ("ir_translator.prompt_level1", LEVEL1_PROMPT.strip()))
    conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                ("ir_translator.prompt_level2", LEVEL2_PROMPT.strip()))
    conn.commit()
    conn.close()


# Auto-init on import
init_db()
init_config_table()
_init_translator_prompts()
