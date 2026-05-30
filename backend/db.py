"""SQLite data layer for Claw Access-View Compliance."""

import json
import sqlite3
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent / "clawAVC.db"


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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
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



def insert_round_start(round_id: str, time_start: str, session_key: str, session_id: str) -> Optional[int]:
    """Insert a round record at ROUND_START (partial data, no score yet)."""
    conn = get_conn()
    try:
        cursor = conn.execute("""
            INSERT OR IGNORE INTO rounds
            (round_id, time_start, time_end, session_key, session_id,
             user_query, last_llm_message, action_json, ir_json,
             judge_result, is_abnormal, overall_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            round_id, time_start, "", session_key, session_id,
            "", "", "[]", "{}", "", 0, -1.0,
        ))
        conn.commit()
        return cursor.lastrowid if cursor.rowcount > 0 else None
    except Exception as e:
        print(f"[db] insert_round_start error: {e}")
        return None
    finally:
        conn.close()


def update_round_end(round_id: str, data: Dict[str, Any]) -> bool:
    """Update a round record at ROUND_END with full data."""
    conn = get_conn()
    try:
        conn.execute("""
            UPDATE rounds SET
                time_end = ?,
                user_query = ?,
                last_llm_message = ?,
                action_json = ?,
                ir_json = ?,
                judge_result = ?,
                is_abnormal = ?,
                overall_score = ?
            WHERE round_id = ?
        """, (
            data.get("time_end", ""),
            data.get("user_query", ""),
            data.get("last_llm_message", ""),
            data.get("action_json", "[]"),
            data.get("ir_json", "{}"),
            data.get("judge_result", ""),
            1 if data.get("is_abnormal") else 0,
            data.get("overall_score", 1.0),
            round_id,
        ))
        conn.commit()
        return True
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
    conn.commit()
    conn.close()


def get_config(key: str) -> Optional[str]:
    conn = get_conn()
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None


def set_config(key: str, value: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


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
