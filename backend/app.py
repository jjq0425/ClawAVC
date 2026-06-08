#!/usr/bin/env python3
from gevent import monkey; monkey.patch_all()
"""
Claw Access-View Compliance - Backend Server

Flask + Flask-SocketIO providing:
- REST API for rounds data
- WebSocket for real-time push
- SQLite persistence
"""

import json
import os
import sys
import threading
from pathlib import Path
from api_docs import api_doc, generate_docs

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO

sys.path.insert(0, str(Path(__file__).parent))
import db

app = Flask(__name__)
app.config["SECRET_KEY"] = "clawAVC-secret-2026"
CORS(app, resources={r"/api/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent", path="/wss")

# Import historical data on first startup
JSONL_PATH = os.environ.get(
    "ROUNDS_JSONL",
    "/home/hx/jjq/auditor/openclaw_orchestrator.rounds.jsonl"
)


@api_doc(summary="分页查询 Rounds", category="数据查询与更新", params=[{"name":"limit","type":"int","default":"20","desc":"每页条数"},{"name":"offset","type":"int","default":"0","desc":"偏移量"},{"name":"query","type":"str","desc":"模糊搜索 user_query"},{"name":"round_id","type":"str","desc":"模糊搜索 round_id"},{"name":"time_from","type":"str","desc":"开始时间"},{"name":"time_to","type":"str","desc":"结束时间"}], response={"ok":True,"data":[],"total":0}, public=True)
@app.route("/api/rounds", methods=["GET"])
def list_rounds():
    """List rounds with pagination and filters."""
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    abnormal_only = request.args.get("abnormal", "false").lower() == "true"
    query = request.args.get("query", "").strip()
    round_id = request.args.get("round_id", "").strip()
    time_from = request.args.get("time_from", "").strip()
    time_to = request.args.get("time_to", "").strip()
    result = db.get_rounds(limit=limit, offset=offset, abnormal_only=abnormal_only,
                           query=query, round_id=round_id, time_from=time_from, time_to=time_to)
    return jsonify({"ok": True, "data": result["data"], "total": result["total"]})

@api_doc(summary="查询单个 Round", category="数据查询与更新", params=[{"name":"round_id","type":"query","desc":"Round ID"}], response={"ok":True,"data":{}}, public=True)
@app.route("/api/rounds/query", methods=["GET"])
def get_round():
    """根据 round_id 获取单条 round 详情。"""
    round_id = request.args.get("round_id", "").strip()
    if not round_id:
        return jsonify({"ok": False, "error": "round_id is required"}), 400
    record = db.get_round_by_id(round_id)
    if not record:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "data": record})

@api_doc(summary="更新单个 Round", category="数据查询与更新", params=[{"name":"round_id","type":"body","desc":"Round ID"}, {"name":"field","type":"body","desc":"列名"}, {"name":"value","type":"body","desc":"值（字符串）"}], response={"ok":True}, public=True)
@app.route("/api/rounds/update", methods=["PUT"])
def update_round():
    """更新指定 round 的字段值（对外接口）。
    
    Body: {"round_id": "xxx", "field": "列名", "value": "值（字符串）"}
    支持的列名配置在 backend/db.py 的 UPDATABLE_FIELDS 数组中
    15分钟限制可通过平台管理页面的开关控制
    """
    data = request.get_json(force=True)
    if not data:
        return jsonify({"ok": False, "error": "empty body"}), 400
    round_id = (data.get("round_id") or "").strip()
    field = (data.get("field") or "").strip()
    value = str(data.get("value", "") or "")
    if not round_id:
        return jsonify({"ok": False, "error": "round_id is required"}), 400
    if not field:
        return jsonify({"ok": False, "error": "field is required"}), 400
    
    # 获取15分钟限制开关状态
    time_limit_enabled = db.get_config("round_update_time_limit_enabled", "True")
    time_limit_enabled = time_limit_enabled.lower() == "true"
    
    result = db.update_round_field(round_id, field, value, time_limit_enabled)
    if result == "not_found":
        return jsonify({"ok": False, "error": f"更新失败: 未找到对应的 round_id: {round_id}"}), 404
    if result == "too_old":
        return jsonify({"ok": False, "error": "更新失败: 数据创建时间超过 15 分钟，不支持API修改，请前往数据运维页面修改"}), 400
    if result == "unsupported":
        return jsonify({"ok": False, "error": f"更新失败: 不支持这个字段的修改: {field}"}), 400
    if result == "error":
        return jsonify({"ok": False, "error": f"更新失败: {field}"}), 500
    
    # 推送更新到前端
    record = db.get_round_by_id(round_id)
    if record:
        socketio.emit("new_round_info", record)
    
    return jsonify({"ok": True})


@api_doc(summary="内核态信息上报", category="数据查询与更新", params=[{"name":"round_id","type":"body","desc":"Round ID"}, {"name":"kernel_syscall_seq_path","type":"body","desc":"内核态系统调用序列文件路径"}, {"name":"kernel_lsm_hook_result_path","type":"body","desc":"内核态LSM hook检查结果文件路径"}, {"name":"kernel_resource_facts_path","type":"body","desc":"内核资源事实信息文件路径"}], response={"ok":True}, public=True)
@app.route("/api/rounds/kernel", methods=["POST"])
def report_kernel_info():
    """上报内核态信息（对外接口）。
    
    Body: {
        "round_id": "xxx",
        "kernel_syscall_seq_path": "/path/to/syscall_seq.json",
        "kernel_lsm_hook_result_path": "/path/to/lsm_hook_result.json",
        "kernel_resource_facts_path": "/path/to/kernel_resource_facts.json"
    }
    
    文件处理逻辑：
    - kernel_syscall_seq_path 和 kernel_lsm_hook_result_path 会被复制到 infos/kernel_infos/<round_id>/ 目录（JSONL格式）
    - kernel_resource_facts_path 的内容会被读取并存入数据库
    
    15分钟限制受平台管理页面的开关控制
    """
    data = request.get_json(force=True)
    if not data:
        return jsonify({"ok": False, "error": "empty body"}), 400
    
    round_id = (data.get("round_id") or "").strip()
    if not round_id:
        return jsonify({"ok": False, "error": "round_id is required"}), 400
    
    kernel_syscall_seq_path = data.get("kernel_syscall_seq_path", "")
    kernel_lsm_hook_result_path = data.get("kernel_lsm_hook_result_path", "")
    kernel_resource_facts_path = data.get("kernel_resource_facts_path", "")
    
    # 获取15分钟限制开关状态
    time_limit_enabled = db.get_config("round_update_time_limit_enabled", "True")
    time_limit_enabled = time_limit_enabled.lower() == "true"
    
    # 检查round_id是否存在及时间限制
    result = db.update_kernel_info(round_id, kernel_syscall_seq_path, kernel_lsm_hook_result_path, kernel_resource_facts_path, time_limit_enabled)
    if result == "not_found":
        return jsonify({"ok": False, "error": f"未找到对应的 round_id: {round_id}"}), 404
    if result == "too_old":
        return jsonify({"ok": False, "error": "数据创建时间超过 15 分钟，不支持API修改，请前往数据运维页面修改"}), 400
    if result == "error":
        return jsonify({"ok": False, "error": "文件处理或更新失败"}), 500
    
    # 推送更新到前端
    record = db.get_round_by_id(round_id)
    if record:
        # 推送1: 向本平台推送
        socketio.emit("new_round_info", record)
        
        # 推送 round_kernel 阶段到 WebSocket
        from datetime import datetime
        push_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "+0800"
        
        kernel_syscall_seq = record.get("kernel_syscall_seq", "")
        kernel_lsm_hook_result = record.get("kernel_lsm_hook_result", "")
        kernel_resource_facts = record.get("kernel_resource_facts", "")
        
        # 推送2: 向监控平台推送
        socketio.emit("push", {
            "push_type": "round_kernel",
            "round_id": round_id,
            "kernel_syscall_seq": kernel_syscall_seq,
            "kernel_lsm_hook_result": kernel_lsm_hook_result,
            "kernel_resource_facts": kernel_resource_facts,
            "push_time": push_time
        }, namespace="/wss/monitor")
    
    return jsonify({"ok": True})


@app.route("/api/rounds/detection/kernel", methods=["POST"])
def report_kernel_judge_result():
    """上报内核态判断结果（对外接口）。
    
    Body: {
        "round_id": "xxx",
        "judge_result_kernel_md_path": "/path/to/judge_result.md"
    }
    
    15分钟限制受平台管理页面的开关控制
    """
    data = request.get_json(force=True)
    if not data:
        return jsonify({"ok": False, "error": "empty body"}), 400
    
    round_id = (data.get("round_id") or "").strip()
    if not round_id:
        return jsonify({"ok": False, "error": "round_id is required"}), 400
    
    judge_result_kernel_md_path = data.get("judge_result_kernel_md_path", "")
    if not judge_result_kernel_md_path:
        return jsonify({"ok": False, "error": "judge_result_kernel_md_path is required"}), 400
    
    # 获取15分钟限制开关状态
    time_limit_enabled = db.get_config("round_update_time_limit_enabled", "True")
    time_limit_enabled = time_limit_enabled.lower() == "true"
    
    # 检查round_id是否存在及时间限制
    result = db.update_judge_result_kernel(round_id, judge_result_kernel_md_path, time_limit_enabled)
    if result == "not_found":
        return jsonify({"ok": False, "error": f"未找到对应的 round_id: {round_id}"}), 404
    if result == "too_old":
        return jsonify({"ok": False, "error": "数据创建时间超过 15 分钟，不支持API修改，请前往数据运维页面修改"}), 400
    if result == "error":
        return jsonify({"ok": False, "error": "文件处理或更新失败"}), 500
    
    # 推送更新到前端
    record = db.get_round_by_id(round_id)
    if record:
        # 推送1: 向本平台推送
        socketio.emit("new_round_info", record)
        
        # 推送2: 向监控平台推送
        from datetime import datetime
        push_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "+0800"
        
        socketio.emit("push", {
            "push_type": "round_kernel_judge",
            "round_id": round_id,
            "judge_result_kernel": record.get("judge_result_kernel", ""),
            "push_time": push_time
        }, namespace="/wss/monitor")
    
    return jsonify({"ok": True})


@app.route("/api/rounds", methods=["POST"])
def report_round():
    """Receive round data from monitor/orchestrator.
    
    Supports two modes:
      event=start: Insert partial record at round start, push to frontend
      event=end (or no event): Update record with full data, push to frontend
      Legacy (from old orchestrator): field "round" instead of "round_id"
    """
    data = request.get_json(force=True)
    if not data:
        return jsonify({"ok": False, "error": "empty body"}), 400

    event = data.get("event", "end")
    round_id = data.get("round_id") or data.get("round", "")

    if event == "start":
        # ROUND_STARTED: insert partial record。
        # attack_config 由上报方（monitor）通过 /api/attack/tool-config 接口读取后随 body 带入；
        # 若未携带则本地直读兜底，结构统一为 {"tool_injection": {...}}。
        attack_config = data.get("attack_config")
        if attack_config is None:
            attack_config = json.dumps(_read_all_attack_config(), ensure_ascii=False)
        # pid_info 由 monitor 在 ROUND_START 时通过扫描 /proc 采集（OpenClaw 进程 PID、
        # SELinux/AppArmor 标签、capabilities、namespaces、cgroup、ancestors 等），
        # 直接以已编码的 JSON 字符串透传；缺省存空串。
        pid_info = data.get("pid_info") or ""
        row_id = db.insert_round_start(
            round_id=round_id,
            time_start=data.get("time_start", ""),
            session_key=data.get("session_key") or data.get("sessionKey", ""),
            session_id=data.get("session_id") or data.get("sessionID", ""),
            attack_config=attack_config,
            pid_info=pid_info,
        )
        if row_id:
            record = db.get_round_by_id(round_id)
            if record:
                socketio.emit("new_round_info", record)
                socketio.emit("push", {"push_type": "round_start", "round_id": round_id, "time_start": data.get("time_start", ""), "session_key": data.get("session_key", ""), "push_time": data.get("time_start", "")}, namespace="/wss/monitor")
        return jsonify({"ok": True, "inserted": row_id is not None})

    else:
        # ROUND_ENDED: update existing or insert full record
        # Try update first (if start was already inserted)
        updated = db.update_round_end(round_id, data)
        if not updated:
            # Fallback: insert full record (legacy orchestrator format)
            legacy_data = {
                "round": round_id,
                "time_start": data.get("time_start", ""),
                "time_end": data.get("time_end", ""),
                "sessionKey": data.get("session_key") or data.get("sessionKey", ""),
                "sessionID": data.get("session_id") or data.get("sessionID", ""),
                "user_query": data.get("user_query", ""),
                "last_llm_message": data.get("last_llm_message", ""),
                "action": data.get("action") or [],
                "IR": data.get("IR") or {},
                "abnormal_judge": data.get("judge_result") or data.get("abnormal_judge", ""),
            }
            # If action_json is already a string, parse it
            if isinstance(data.get("action_json"), str):
                try:
                    legacy_data["action"] = json.loads(data["action_json"])
                except Exception:
                    legacy_data["action"] = []
            if isinstance(data.get("ir_json"), str):
                try:
                    legacy_data["IR"] = json.loads(data["ir_json"])
                except Exception:
                    legacy_data["IR"] = {}
            db.insert_round(legacy_data)

        # Push updated record to frontend
        record = db.get_round_by_id(round_id)
        if record:
            socketio.emit("new_round_info", record)
            # Emit fine-grained WSS events
            ir_json = data.get("ir_json", "")
            if ir_json and ir_json != "__loading__" and data.get("overall_score", -1) < 0:
                # IR ready but not yet judged
                socketio.emit("push", {"push_type": "round_ir_ready", "round_id": round_id, "ir_json": ir_json, "push_time": data.get("time_end") or data.get("time_start", "")}, namespace="/wss/monitor")
            elif data.get("overall_score", -1) >= 0:
                # Full round end with judge
                socketio.emit("push", {"push_type": "round_end", "round_id": round_id, "time_start": data.get("time_start", ""), "time_end": data.get("time_end", ""), "action_json": data.get("action_json", "[]"), "ir_json": ir_json, "overall_score": data.get("overall_score", 1.0), "judge_result": data.get("judge_result", ""), "push_time": data.get("time_end", "")}, namespace="/wss/monitor")

        return jsonify({"ok": True})


@api_doc(summary="统计概览", category="数据查询与更新", response={"ok":True,"data":{"total":0,"abnormal":0,"normal":0,"avg_score":0}}, public=True)
@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Get overview statistics."""
    stats = db.get_stats()
    return jsonify({"ok": True, "data": stats})


@app.route("/api/import", methods=["POST"])
def import_history():
    """Manually trigger JSONL import."""
    count = db.import_from_jsonl(JSONL_PATH)
    return jsonify({"ok": True, "imported": count})



@app.route("/api/auth", methods=["POST"])
def auth_verify():
    """Verify secret key for access."""
    data = request.get_json(force=True)
    secret = data.get("secret", "")
    if db.verify_secret(secret):
        return jsonify({"ok": True, "token": secret})
    return jsonify({"ok": False, "error": "invalid secret"}), 401


@app.route("/api/config", methods=["GET"])
def get_config():
    """Get public config (subdomain, etc)."""
    return jsonify({
        "ok": True,
        "data": {
            
        }
    })


@app.route("/api/config", methods=["PUT"])
def update_config():
    """Update config. Privileged keys require admin auth."""
    data = request.get_json(force=True)
    admin_key = request.headers.get("X-Admin-Key", "")
    auth_token = request.headers.get("X-Auth-Token", "")

    # Privileged config keys that require admin
    privileged_keys = {"secret_key", "subdomain"}

    for key, value in data.items():
        if key == "admin_key":
            # Admin key cannot be modified
            return jsonify({"ok": False, "error": "特权密钥不可修改"}), 403
        if key in privileged_keys:
            if not db.verify_admin(admin_key):
                return jsonify({"ok": False, "error": "需要特权密钥"}), 403
            db.set_config(key, value)
        else:
            # Non-privileged config just needs normal auth
            if not db.verify_secret(auth_token):
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            db.set_config(key, value)
    return jsonify({"ok": True})






# --- Admin session with expiry ---
import time as _time
_admin_sessions = {}  # token -> expiry_timestamp
ADMIN_SESSION_TTL = int(os.environ.get("ADMIN_SESSION_TTL", "1200"))  # 20 min default

def _check_admin_session(token: str) -> bool:
    """Check if admin session is still valid."""
    if token in _admin_sessions:
        if _time.time() < _admin_sessions[token]:
            return True
        else:
            del _admin_sessions[token]
    return False

def _create_admin_session(token: str):
    _admin_sessions[token] = _time.time() + ADMIN_SESSION_TTL


@app.route("/api/admin/verify", methods=["POST"])
def admin_verify_v2():
    """Verify admin key and create session."""
    data = request.get_json(force=True)
    key = data.get("admin_key", "")
    if db.verify_admin(key):
        import hashlib
        session_token = hashlib.sha256(f"{key}{_time.time()}".encode()).hexdigest()[:32]
        _create_admin_session(session_token)
        return jsonify({"ok": True, "session_token": session_token, "ttl": ADMIN_SESSION_TTL})
    return jsonify({"ok": False, "error": "特权密钥错误"}), 401


@app.route("/api/admin/session", methods=["GET"])
def admin_session_check():
    """Check if admin session is still active."""
    token = request.headers.get("X-Admin-Session", "")
    valid = _check_admin_session(token)
    return jsonify({"ok": True, "valid": valid})


@app.route("/api/db/query", methods=["POST"])
def db_query():
    """Execute SELECT query on database."""
    data = request.get_json(force=True)
    sql = data.get("sql", "").strip()
    if not sql:
        return jsonify({"ok": False, "error": "empty sql"}), 400
    # Protect write operations and config table
    sql_upper = sql.upper()
    token = request.headers.get("X-Admin-Session", "")
    is_admin = _check_admin_session(token)
    is_write = not sql_upper.startswith("SELECT")
    touches_config = "CONFIG" in sql_upper
    touches_sqlite_sequence = "SQLITE_SEQUENCE" in sql_upper

    if touches_config and not is_admin:
        return jsonify({"ok": False, "error": "需要特权验证才能访问 config 表"}), 403
    
    if touches_sqlite_sequence and not is_admin:
        return jsonify({"ok": False, "error": "需要特权验证才能访问 sqlite_sequence 表"}), 403

    if is_write and not is_admin:
        return jsonify({"ok": False, "error": "需要特权验证才能执行写操作"}), 403
    try:
        import sqlite3
        conn = db.get_conn()
        cursor = conn.execute(sql)
        if sql.upper().startswith("SELECT"):
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            conn.close()
            return jsonify({"ok": True, "columns": columns, "rows": rows, "count": len(rows)})
        else:
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            return jsonify({"ok": True, "affected": affected})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/db/tables", methods=["GET"])
def db_tables():
    """List all tables."""
    conn = db.get_conn()
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    tables = []
    for row in rows:
        name = row[0]
        count = conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
        tables.append({"name": name, "count": count})
    conn.close()
    return jsonify({"ok": True, "tables": tables})


@app.route("/api/config/admin_ttl", methods=["GET"])
def get_admin_ttl():
    return jsonify({"ok": True, "ttl": ADMIN_SESSION_TTL})


@app.route("/api/config/admin_ttl", methods=["PUT"])
def set_admin_ttl():
    global ADMIN_SESSION_TTL
    data = request.get_json(force=True)
    token = request.headers.get("X-Admin-Session", "")
    if not _check_admin_session(token):
        return jsonify({"ok": False, "error": "需要特权验证"}), 403
    ADMIN_SESSION_TTL = int(data.get("ttl", 1200))
    return jsonify({"ok": True, "ttl": ADMIN_SESSION_TTL})



# --- IR Translator API ---
@app.route("/api/translator/config", methods=["GET"])
def get_translator_config():
    """Get current IR translator LLM config."""
    keys = ["api_base_url", "api_key", "model", "temperature", "timeout", "json_mode"]
    config = {}
    for k in keys:
        val = db.get_config(f"ir_translator.{k}")
        if k == "api_key" and val:
            # Mask API key
            config[k] = val[:6] + "***" + val[-4:] if len(val) > 10 else "***"
        else:
            config[k] = val or ""
    return jsonify({"ok": True, "data": config})


@app.route("/api/translator/config", methods=["PUT"])
def set_translator_config():
    """Update IR translator LLM config. Requires admin."""
    token = request.headers.get("X-Admin-Session", "")
    if not _check_admin_session(token):
        return jsonify({"ok": False, "error": "需要特权验证"}), 403
    data = request.get_json(force=True)
    allowed_keys = ["api_base_url", "api_key", "model", "temperature", "timeout", "json_mode", "prompt_level1", "prompt_level2"]
    for k, v in data.items():
        if k in allowed_keys:
            db.set_config(f"ir_translator.{k}", str(v))
    return jsonify({"ok": True})


@app.route("/api/translator/test", methods=["POST"])
def test_translator():
    """Test IR translation with a query. Returns full pipeline result."""
    data = request.get_json(force=True)
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"ok": False, "error": "query is required"}), 400

    try:
        from auditor.translator.core import translate, get_llm_config
        config = get_llm_config()
        # Allow override config from request for testing
        if data.get("config"):
            config.update(data["config"])
        result = translate(query, config=config, is_ui_test=True)
        return jsonify({"ok": True, "data": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
@api_doc(summary="IR 翻译", category="策略翻译", description="将用户自然语言意图翻译为结构化权限策略", params=[{"name":"query","type":"str","desc":"用户查询文本 (body JSON)"}], public=True)
@app.route("/api/translator/translate", methods=["POST"])
def run_translate():
    """Internal translate endpoint for monitor. Not UI test."""
    data = request.get_json(force=True)
    query = data.get("query", "").strip()
    round_id = data.get("round_id", "")
    if not query:
        return jsonify({"ok": False, "error": "query is required"}), 400
    try:
        from auditor.translator.core import translate, get_llm_config
        config = get_llm_config()
        result = translate(query, config=config, is_ui_test=False, round_id=round_id)
        return jsonify({"ok": True, "data": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500



@app.route("/api/translator/level1", methods=["POST"])
def test_level1():
    """Test Level-1 classification only."""
    data = request.get_json(force=True)
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"ok": False, "error": "query is required"}), 400
    try:
        from auditor.translator.core import level1_classify, get_llm_config
        scenes, meta = level1_classify(query, config=get_llm_config())
        return jsonify({"ok": True, "data": {"scenes": scenes, "meta": meta}})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/translator/level2", methods=["POST"])
def test_level2():
    """Test Level-2 generation only."""
    data = request.get_json(force=True)
    query = data.get("query", "").strip()
    scenes = data.get("scenes", [])
    if not query or not scenes:
        return jsonify({"ok": False, "error": "query and scenes are required"}), 400
    try:
        from auditor.translator.core import level2_generate, get_llm_config
        ir, meta = level2_generate(query, scenes, config=get_llm_config())
        return jsonify({"ok": True, "data": {"ir": ir, "meta": meta}})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500







@app.route("/api/translator/scene/<scene_name>", methods=["GET"])
def get_scene_detail(scene_name):
    """Get full scene detail: desc from scenes.json + functions from tools/<scene>.json."""
    from auditor.translator.core import REGISTRY_DIR, SCENE_REGISTRY, TOOL_REGISTRY
    if scene_name not in SCENE_REGISTRY:
        return jsonify({"ok": False, "error": f"场景 {scene_name} 不存在"}), 404
    scene_meta = SCENE_REGISTRY[scene_name]
    tool_data = TOOL_REGISTRY.get(scene_name, {})
    return jsonify({"ok": True, "data": {
        "scene": scene_name,
        "desc": scene_meta.get("desc", ""),
        "resource_type": scene_meta.get("resource_type", ""),
        "functions_list": scene_meta.get("functions", []),
        "functions_detail": tool_data.get("functions", {}),
    }})


@app.route("/api/translator/scene/<scene_name>/desc", methods=["PUT"])
def update_scene_desc(scene_name):
    """Update scene description in scenes.json. Requires admin."""
    token = request.headers.get("X-Admin-Session", "")
    if not _check_admin_session(token):
        return jsonify({"ok": False, "error": "需要特权验证"}), 403
    from auditor.translator.core import REGISTRY_DIR, reload_registry
    data = request.get_json(force=True)
    new_desc = data.get("desc", "")
    # Read scenes.json
    scenes_path = REGISTRY_DIR / "scenes.json"
    with open(scenes_path, "r", encoding="utf-8") as f:
        scenes = json.load(f)
    if scene_name not in scenes:
        return jsonify({"ok": False, "error": f"场景 {scene_name} 不存在"}), 404
    scenes[scene_name]["desc"] = new_desc
    with open(scenes_path, "w", encoding="utf-8") as f:
        json.dump(scenes, f, ensure_ascii=False, indent=2)
    reload_registry()
    return jsonify({"ok": True})


@app.route("/api/translator/scene/<scene_name>/functions", methods=["PUT"])
def update_scene_functions(scene_name):
    """Add a function to scene. Updates both scenes.json and tools/<scene>.json. Requires admin."""
    token = request.headers.get("X-Admin-Session", "")
    if not _check_admin_session(token):
        return jsonify({"ok": False, "error": "需要特权验证"}), 403
    from auditor.translator.core import REGISTRY_DIR, reload_registry
    data = request.get_json(force=True)
    action = data.get("action")  # "add" or "remove"
    func_name = data.get("name", "").strip()
    func_def = data.get("definition", {})

    if not func_name:
        return jsonify({"ok": False, "error": "函数名不能为空"}), 400

    scenes_path = REGISTRY_DIR / "scenes.json"
    tool_path = REGISTRY_DIR / "tools" / f"{scene_name}.json"

    with open(scenes_path, "r", encoding="utf-8") as f:
        scenes = json.load(f)
    if scene_name not in scenes:
        return jsonify({"ok": False, "error": f"场景 {scene_name} 不存在"}), 404

    if not tool_path.exists():
        return jsonify({"ok": False, "error": f"工具文件 tools/{scene_name}.json 不存在"}), 404
    with open(tool_path, "r", encoding="utf-8") as f:
        tool_data = json.load(f)

    if action == "add":
        # Add to scenes.json functions list
        if func_name not in scenes[scene_name].get("functions", []):
            scenes[scene_name].setdefault("functions", []).append(func_name)
        # Add to tools/<scene>.json functions dict
        if func_name not in tool_data.get("functions", {}):
            tool_data.setdefault("functions", {})[func_name] = func_def or {"type": "function", "params": {}, "desc": ""}
    elif action == "remove":
        # Remove from scenes.json
        funcs = scenes[scene_name].get("functions", [])
        if func_name in funcs:
            funcs.remove(func_name)
        # Remove from tools/<scene>.json
        tool_data.get("functions", {}).pop(func_name, None)
    else:
        return jsonify({"ok": False, "error": "action 必须为 add 或 remove"}), 400

    with open(scenes_path, "w", encoding="utf-8") as f:
        json.dump(scenes, f, ensure_ascii=False, indent=2)
    with open(tool_path, "w", encoding="utf-8") as f:
        json.dump(tool_data, f, ensure_ascii=False, indent=2)
    reload_registry()
    return jsonify({"ok": True})


@app.route("/api/translator/scene/<scene_name>/function/<func_name>", methods=["PUT"])
def update_function_detail(scene_name, func_name):
    """Update a function definition in tools/<scene>.json. Requires admin."""
    token = request.headers.get("X-Admin-Session", "")
    if not _check_admin_session(token):
        return jsonify({"ok": False, "error": "需要特权验证"}), 403
    from auditor.translator.core import REGISTRY_DIR, reload_registry
    data = request.get_json(force=True)
    definition = data.get("definition", {})

    tool_path = REGISTRY_DIR / "tools" / f"{scene_name}.json"
    if not tool_path.exists():
        return jsonify({"ok": False, "error": f"工具文件不存在"}), 404
    with open(tool_path, "r", encoding="utf-8") as f:
        tool_data = json.load(f)
    if func_name not in tool_data.get("functions", {}):
        return jsonify({"ok": False, "error": f"函数 {func_name} 不存在"}), 404
    tool_data["functions"][func_name] = definition
    with open(tool_path, "w", encoding="utf-8") as f:
        json.dump(tool_data, f, ensure_ascii=False, indent=2)
    reload_registry()
    return jsonify({"ok": True})

@app.route("/api/translator/registry-health", methods=["GET"])
def registry_health():
    """Check if registry path is valid and accessible."""
    import os
    path = db.get_config("ir_translator.registry_path") or ""
    if not path.strip():
        return jsonify({"ok": False, "error": "策略库路径未配置,提示词变量和策略无法读取", "path": ""})
    if not path.endswith("policy_registry"):
        return jsonify({"ok": False, "error": "路径必须以 policy_registry 结尾", "path": path})
    if not os.path.isdir(path):
        return jsonify({"ok": False, "error": f"目录不存在: {path}", "path": path})
    if not os.path.isfile(os.path.join(path, "scenes.json")):
        return jsonify({"ok": False, "error": "目录中缺少 scenes.json", "path": path})
    if not os.path.isdir(os.path.join(path, "tools")):
        return jsonify({"ok": False, "error": "目录中缺少 tools 文件夹", "path": path})
    return jsonify({"ok": True, "path": path})

@app.route("/api/translator/registry-path", methods=["GET"])
def get_registry_path():
    """Get current registry path."""
    path = db.get_config("ir_translator.registry_path") or ""
    return jsonify({"ok": True, "data": {"path": path}})


@app.route("/api/translator/registry-path", methods=["PUT"])
def set_registry_path():
    """Set registry path. Requires admin. Validates path."""
    token = request.headers.get("X-Admin-Session", "")
    if not _check_admin_session(token):
        return jsonify({"ok": False, "error": "需要特权验证"}), 403
    data = request.get_json(force=True)
    path = data.get("path", "").strip()
    if not path:
        return jsonify({"ok": False, "error": "路径不能为空"}), 400
    if not path.endswith("policy_registry"):
        return jsonify({"ok": False, "error": "路径必须以 policy_registry 结尾"}), 400
    import os
    if not os.path.isdir(path):
        return jsonify({"ok": False, "error": f"目录不存在: {path}"}), 400
    if not os.path.isfile(os.path.join(path, "scenes.json")):
        return jsonify({"ok": False, "error": "目录中缺少 scenes.json"}), 400
    if not os.path.isdir(os.path.join(path, "tools")):
        return jsonify({"ok": False, "error": "目录中缺少 tools 文件夹"}), 400
    db.set_config("ir_translator.registry_path", path)
    # Reload registry
    try:
        from auditor.translator.core import reload_registry
        reload_registry()
    except Exception:
        pass
    return jsonify({"ok": True})

@app.route("/api/translator/registry", methods=["GET"])
def get_registry():
    """Get current policy registry (scenes + tools summary)."""
    try:
        from auditor.translator.core import SCENE_REGISTRY, TOOL_REGISTRY
        scenes_summary = {}
        for name, meta in SCENE_REGISTRY.items():
            scenes_summary[name] = {
                "desc": meta.get("desc", ""),
                "functions": meta.get("functions", []),
            }
        return jsonify({"ok": True, "data": {"scenes": scenes_summary, "tool_count": sum(len(v.get("functions", {})) for v in TOOL_REGISTRY.values())}})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/translator/prompts", methods=["GET"])
def get_translator_prompts():
    """Get current prompts from config."""
    from auditor.translator.core import LEVEL1_SYS, LEVEL2_SYS
    l1 = db.get_config("ir_translator.prompt_level1") or ""
    l2 = db.get_config("ir_translator.prompt_level2") or ""
    # If empty, initialize with built-in
    if not l1.strip():
        l1 = LEVEL1_SYS.strip()
        db.set_config("ir_translator.prompt_level1", l1)
    if not l2.strip():
        l2 = LEVEL2_SYS.strip()
        db.set_config("ir_translator.prompt_level2", l2)
    return jsonify({"ok": True, "data": {
        "level1": {"value": l1},
        "level2": {"value": l2},
    }})


@app.route("/api/translator/prompts", methods=["PUT"])
def set_translator_prompts():
    """Update prompts. No privilege required."""
    data = request.get_json(force=True)
    if "level1" in data:
        db.set_config("ir_translator.prompt_level1", data["level1"])
    if "level2" in data:
        db.set_config("ir_translator.prompt_level2", data["level2"])
    return jsonify({"ok": True})




@app.route("/api/translator/prompts/preview", methods=["POST"])
def preview_prompt():
    """Preview prompt with variables replaced."""
    data = request.get_json(force=True)
    level = data.get("level", "level1")
    prompt_text = data.get("prompt", "")
    try:
        from auditor.translator.core import _scene_list_for_prompt, _selected_registry_for_prompt, SCENE_REGISTRY
        if level == "level1":
            replaced = prompt_text.replace("{SCENE_LIST}", _scene_list_for_prompt())
        else:
            # Use all scenes for preview
            all_scenes = list(SCENE_REGISTRY.keys())
            replaced = prompt_text.replace("{SELECTED_REGISTRY}", _selected_registry_for_prompt(all_scenes))
        return jsonify({"ok": True, "data": {"preview": replaced}})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/translator/prompts/reset", methods=["POST"])
def reset_translator_prompts():
    """Reset prompts to built-in defaults. No privilege required."""
    data = request.get_json(force=True)
    level = data.get("level", "all")
    if level in ("level1", "all"):
        db.set_config("ir_translator.prompt_level1", "")
    if level in ("level2", "all"):
        db.set_config("ir_translator.prompt_level2", "")
    return jsonify({"ok": True})






@app.route("/api/translator/logs", methods=["GET"])
def get_translation_logs():
    """Get translation log entries."""
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    ui_only = request.args.get("ui_only", "false").lower() == "true"
    logs = db.get_translation_logs(limit=limit, offset=offset, ui_only=ui_only)
    return jsonify({"ok": True, "data": logs})


@app.route("/api/translator/default-policy", methods=["GET"])
def get_default_policy():
    """Get the default fallback policy."""
    raw = db.get_config("ir_translator.default_policy") or "{}"
    try:
        policy = json.loads(raw)
    except Exception:
        policy = {}
    return jsonify({"ok": True, "data": policy})


@app.route("/api/translator/default-policy", methods=["PUT"])
def set_default_policy():
    """Save default policy after normalize + validate."""
    data = request.get_json(force=True)
    policy = data.get("policy", {})
    try:
        from auditor.translator.core import normalize_and_validate
        result = normalize_and_validate(policy)
        if not result["validation"]["ok"]:
            return jsonify({"ok": False, "error": "校验失败", "validation": result["validation"]}), 400
        db.set_config("ir_translator.default_policy", json.dumps(result["ir"], ensure_ascii=False))
        return jsonify({"ok": True, "validation": result["validation"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@socketio.on("connect")
def handle_connect():
    print(f"[ws] client connected: {request.sid}")


@socketio.on("disconnect")
def handle_disconnect():
    print(f"[ws] client disconnected: {request.sid}")


# ─── /monitor namespace (运行消息组) ────────────────────────
@socketio.on("connect", namespace="/wss/monitor")
def handle_monitor_connect():
    print(f"[ws/monitor] client connected: {request.sid}")


@socketio.on("disconnect", namespace="/wss/monitor")
def handle_monitor_disconnect():
    print(f"[ws/monitor] client disconnected: {request.sid}")


# ─── Monitor Config API ───────────────────────────────
MONITOR_CONF_KEYS = ["gateway_log_path", "openclaw_root", "use_gateway"]

@app.route("/api/monitor/config", methods=["GET"])
def get_monitor_config():
    data = {}
    path_status = {}
    for key in MONITOR_CONF_KEYS:
        val = db.get_config(f"monitor_conf.{key}")
        data[key] = val or ""
    # Check path validity
    for pk in ["gateway_log_path", "openclaw_root"]:
        p = data[pk]
        if p:
            path_status[pk] = "ok" if os.path.exists(p) else "invalid"
    data["_path_status"] = path_status
    return jsonify({"ok": True, "data": data})

@app.route("/api/monitor/config", methods=["PUT"])
def put_monitor_config():
    body = request.get_json(force=True)
    key = body.get("key", "")
    value = body.get("value", "")
    if key not in MONITOR_CONF_KEYS:
        return jsonify({"ok": False, "error": f"无效的配置项: {key}"}), 400
    db.set_config(f"monitor_conf.{key}", value)
    result = {"ok": True}
    # Check path validity for path fields
    if key in ["gateway_log_path", "openclaw_root"] and value:
        result["data"] = {"path_valid": os.path.exists(value)}
    return jsonify(result)

# ─── Monitor Control API ──────────────────────────────
_monitor_thread = None
_monitor_instance = None
@api_doc(summary="启动安全监控", category="运行监控", description="启动前需配置网关日志路径和OpenClaw根文件夹", public=True)
@app.route("/api/monitor/start", methods=["POST"])
def start_monitor_api():
    global _monitor_thread, _monitor_instance
    if _monitor_thread and _monitor_thread.is_alive():
        return jsonify({"ok": True, "message": "监控已在运行中"})

    from auditor.monitor.watcher import MonitorOrchestrator, get_config_from_db
    config = get_config_from_db()
    openclaw_logs = config.get("openclaw_root", "").strip()
    gateway_logs = config.get("gateway_log_path", "").strip()
    use_gateway = config.get("use_gateway", "false").lower() == "true"

    if not openclaw_logs:
        return jsonify({"ok": False, "error": "请先配置 OpenClaw 根文件夹路径"}), 400
    if not os.path.exists(openclaw_logs):
        return jsonify({"ok": False, "error": f"OpenClaw 根文件夹路径不存在: {openclaw_logs}"}), 400
    if use_gateway:
        if not gateway_logs:
            return jsonify({"ok": False, "error": "启用网关数据源时需配置网关日志路径"}), 400
        if not os.path.exists(gateway_logs):
            return jsonify({"ok": False, "error": f"网关日志路径不存在: {gateway_logs}"}), 400

    _monitor_instance = MonitorOrchestrator(
        openclaw_log_root=openclaw_logs,
        gateway_log_path=gateway_logs,
    )

    def _run():
        try:
            _monitor_instance.run()
        except Exception as e:
            print(f"[monitor] Error: {e}", flush=True)

    _monitor_thread = threading.Thread(target=_run, daemon=True)
    _monitor_thread.start()
    return jsonify({"ok": True, "message": "监控已启动"})

@api_doc(summary="停止安全监控", category="运行监控", public=True)
@app.route("/api/monitor/stop", methods=["POST"])
def stop_monitor_api():
    global _monitor_instance
    if _monitor_instance:
        _monitor_instance.running = False
        _monitor_instance = None
        return jsonify({"ok": True, "message": "监控已停止"})
    return jsonify({"ok": True, "message": "监控未在运行"})

@api_doc(summary="监控运行状态", category="运行监控", response={"ok":True,"data":{"running":False}}, public=True)
@app.route("/api/monitor/status", methods=["GET"])
def monitor_status_api():
    global _monitor_thread
    running = _monitor_thread is not None and _monitor_thread.is_alive()
    return jsonify({"ok": True, "data": {"running": running}})


@api_doc(summary="读取内核态文件内容", category="运行监控", description="读取内核态信息文件内容（JSONL格式）", params=[{"name":"path","type":"query","desc":"文件路径"}], response={"ok":True,"data":"文件内容"}, public=True)
@app.route("/api/kernel/file", methods=["GET"])
def read_kernel_file():
    """读取内核态信息文件内容。"""
    file_path = request.args.get("path", "").strip()
    if not file_path:
        return jsonify({"ok": False, "error": "path is required"}), 400
    
    from pathlib import Path
    
    path = Path(file_path)
    if not path.exists():
        return jsonify({"ok": False, "error": f"文件不存在: {file_path}"}), 404
    
    if not path.is_file():
        return jsonify({"ok": False, "error": f"路径不是文件: {file_path}"}), 400
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({"ok": True, "data": content})
    except Exception as e:
        return jsonify({"ok": False, "error": f"读取文件失败: {str(e)}"}), 500


@api_doc(summary="发送模拟/回放 WSS 消息", category="运行监控", description="向 /wss/monitor 推送消息，自动添加 is_mock=true 标记", params=[{"name":"data","type":"body","desc":"消息内容 JSON，需包含 push_type 字段"}], public=True)
@app.route("/api/monitor/send-test", methods=["POST"])
def send_test_wss():
    """发送模拟消息到 /wss/monitor，自动设置 is_mock=True 和当前时间。"""
    from datetime import datetime
    
    data = request.get_json(force=True)
    if not data:
        return jsonify({"ok": False, "error": "empty body"}), 400
    
    push_type = data.get("push_type", "")
    if not push_type:
        return jsonify({"ok": False, "error": "push_type is required"}), 400
    
    # 确保 is_mock 字段为 True
    data["is_mock"] = True
    
    # 替换 push_time 为当前时间
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "+0800"
    data["push_time"] = now
    
    # 通过 Socket.IO 向 /wss/monitor 推送消息
    socketio.emit("push", data, namespace="/wss/monitor")
    
    return jsonify({"ok": True, "data": {"push_type": push_type, "is_mock": True}})


# ─── Navigator Config ──────────────────────────────────
@app.route("/api/config/navigator", methods=["GET"])
def get_navigator_config():
    """获取快捷导航配置。"""
    val = db.get_config("navigator.conf")
    return jsonify({"ok": True, "data": val or ""})

@app.route("/api/config/navigator", methods=["PUT"])
def set_navigator_config():
    """保存快捷导航配置。"""
    """保存快捷导航配置（需特权）。"""
    token = request.headers.get("X-Admin-Session", "")
    if not _check_admin_session(token):
        return jsonify({"ok": False, "error": "需要特权验证"}), 403
    data = request.get_json(force=True)
    value = data.get("value", "")
    db.set_config("navigator.conf", value)
    return jsonify({"ok": True})

# ─── Attack Config API ─────────────────────────────────
# 模拟攻击配置，统一存储于 config 表，键名形如 attack.<group>.<item>.<field>。
# 对外 JSON 分类名 → config 表内部 group 前缀的映射：
ATTACK_GROUPS = {
    "tool_injection": "inject",   # 工具注入：固定访问网络 / 文件路径
    "runtime_tamper": "tamper",   # 运行时篡改：替换工具 / 插入工具
}

def _read_attack_group(group: str) -> dict:
    """读取某攻击分类下的全部配置项（开启状态 + 内容），动态来自 config 表。"""
    prefix = f"attack.{group}."
    data = {}
    for key, val in db.get_configs_by_prefix(prefix).items():
        # key 形如 attack.<group>.<item>.<field>
        rest = key[len(prefix):]
        parts = rest.rsplit(".", 1)
        if len(parts) != 2:
            continue
        item, field = parts
        cfg = data.setdefault(item, {"enabled": False, "value": ""})
        if field == "enabled":
            cfg["enabled"] = (val or "false").lower() == "true"
        elif field == "value":
            cfg["value"] = val or ""
    return data

def _read_all_attack_config() -> dict:
    """读取全部攻击配置，按对外分类名组织。"""
    return {pub: _read_attack_group(grp) for pub, grp in ATTACK_GROUPS.items()}

# 兼容旧调用：仅工具注入配置
def _read_attack_inject_config():
    return _read_attack_group("inject")

@app.route("/api/attack/config", methods=["GET"])
def get_attack_config():
    """获取模拟攻击配置（工具注入 + 运行时篡改）。"""
    return jsonify({"ok": True, "data": _read_all_attack_config()})

@app.route("/api/attack/config", methods=["PUT"])
def put_attack_config():
    """保存模拟攻击配置（各分类的开启状态 + 攻击内容）。

    body 形如 {"tool_injection": {...}, "runtime_tamper": {...}}，
    仅携带的分类会被写入，未携带的分类保持不变。
    """
    body = request.get_json(force=True)
    for pub, grp in ATTACK_GROUPS.items():
        section = body.get(pub)
        if not isinstance(section, dict):
            continue
        for item, cfg in section.items():
            if not isinstance(cfg, dict):
                continue
            enabled = bool(cfg.get("enabled", False))
            value = str(cfg.get("value", "") or "")
            db.set_config(f"attack.{grp}.{item}.enabled", "true" if enabled else "false")
            db.set_config(f"attack.{grp}.{item}.value", value)
    return jsonify({"ok": True, "data": _read_all_attack_config()})

@app.route("/api/attack/tool-config", methods=["GET"])
def get_attack_tool_config_external():
    """对外接口：根据配置项 key 获取对应攻击配置的开启状态与具体内容。

    key 形如 tool_injection.network / tool_injection.filepath /
    runtime_tamper.replace / runtime_tamper.insert。
    不传 key 时返回全部攻击配置。
    """
    key = (request.args.get("key", "") or "").strip()
    all_cfg = _read_all_attack_config()

    # 不传 key：返回全部
    if not key:
        return jsonify({"ok": True, "data": all_cfg})

    if "." not in key:
        return jsonify({"ok": False, "error": f"unknown key: {key}"}), 404
    group, item = key.split(".", 1)
    section = all_cfg.get(group)
    if section is None or item not in section:
        return jsonify({"ok": False, "error": f"unknown key: {key}"}), 404

    return jsonify({"ok": True, "data": {"key": key, **section[item]}})


# ─── API Documentation ─────────────────────────────────
@app.route("/api/docs", methods=["GET"])
def get_api_docs():
    """获取全部 API 接口文档。"""
    endpoints = generate_docs(app)
    return jsonify({"ok": True, "data": endpoints})

@app.route("/api/docs/public", methods=["GET"])
def get_public_api_docs():
    """获取对外公开的 API 接口文档。"""
    public_list_str = db.get_config("api_docs.public_endpoints") or "[]"
    try:
        public_list = json.loads(public_list_str)
    except Exception:
        public_list = []
    endpoints = generate_docs(app, public_only=True, public_list=public_list)
    return jsonify({"ok": True, "data": endpoints})

@app.route("/api/docs/public", methods=["PUT"])
def set_public_api_docs():
    """设置对外公开的接口列表（需特权）。"""
    token = request.headers.get("X-Admin-Session", "")
    if not _check_admin_session(token):
        return jsonify({"ok": False, "error": "需要特权验证"}), 403
    data = request.get_json(force=True)
    endpoints = data.get("endpoints", [])
    db.set_config("api_docs.public_endpoints", json.dumps(endpoints, ensure_ascii=False))
    return jsonify({"ok": True})


# ─── Round Update Time Limit Config ─────────────────────────
@api_doc(summary="获取Round更新时间限制开关状态", category="平台配置", public=False)
@app.route("/api/config/round_update_time_limit", methods=["GET"])
def get_round_update_time_limit():
    """获取Round更新15分钟时间限制的开关状态。"""
    enabled = db.get_config("round_update_time_limit_enabled", "True")
    return jsonify({"ok": True, "data": {"enabled": enabled.lower() == "true"}})


@api_doc(summary="设置Round更新时间限制开关状态", category="平台配置", public=False)
@app.route("/api/config/round_update_time_limit", methods=["PUT"])
def set_round_update_time_limit():
    """设置Round更新15分钟时间限制的开关状态（需特权）。"""
    token = request.headers.get("X-Admin-Session", "")
    if not _check_admin_session(token):
        return jsonify({"ok": False, "error": "需要特权验证"}), 403
    data = request.get_json(force=True)
    enabled = data.get("enabled", True)
    db.set_config("round_update_time_limit_enabled", str(enabled))
    return jsonify({"ok": True, "data": {"enabled": enabled}})


def main():
    # Auto-import on first run if DB is empty
    stats = db.get_stats()
    if stats["total"] == 0 and os.path.exists(JSONL_PATH):
        count = db.import_from_jsonl(JSONL_PATH)
        print(f"[init] Imported {count} historical rounds from JSONL")

    print("[clawAVC] Starting backend on http://0.0.0.0:15100")
    socketio.run(app, host="0.0.0.0", port=15100, debug=False, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
