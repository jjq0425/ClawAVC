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
from typing import Any, Dict, List
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
        
        
    return jsonify({"ok": True})


@app.route("/api/rounds/detection/syscall", methods=["POST"])
def report_syscall_judge_result():
    """上报系统调用判断结果（对外接口）。
    
    Body: {
        "round_id": "xxx",
        "syscall_judge": { ... }  // 直接传入 JSON 数据
    }
    
    15分钟限制受平台管理页面的开关控制
    """
    data = request.get_json(force=True)
    if not data:
        return jsonify({"ok": False, "error": "empty body"}), 400
    
    round_id = (data.get("round_id") or "").strip()
    if not round_id:
        return jsonify({"ok": False, "error": "round_id is required"}), 400
    
    syscall_judge = data.get("syscall_judge")
    if syscall_judge is None:
        return jsonify({"ok": False, "error": "syscall_judge is required"}), 400
    
    # 获取15分钟限制开关状态
    time_limit_enabled = db.get_config("round_update_time_limit_enabled", "True")
    time_limit_enabled = time_limit_enabled.lower() == "true"
    
    # 检查round_id是否存在及时间限制
    result = db.update_syscall_judge_json(round_id, syscall_judge, time_limit_enabled)
    if result == "not_found":
        return jsonify({"ok": False, "error": f"未找到对应的 round_id: {round_id}"}), 404
    if result == "too_old":
        return jsonify({"ok": False, "error": "数据创建时间超过 15 分钟，不支持API修改，请前往数据运维页面修改"}), 400
    if result == "error":
        return jsonify({"ok": False, "error": "更新失败"}), 500
    
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
        # history: 对话历史，包含之前的 user/assistant/tool 消息
        history = data.get("history") or ""
        row_id = db.insert_round_start(
            round_id=round_id,
            time_start=data.get("time_start", ""),
            session_key=data.get("session_key") or data.get("sessionKey", ""),
            session_id=data.get("session_id") or data.get("sessionID", ""),
            attack_config=attack_config,
            pid_info=pid_info,
            history=history,
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
        ir_v = data.get("ir_json", "")
        ir_brief = ir_v if (isinstance(ir_v, str) and len(ir_v) <= 32) else (
            (ir_v[:29] + "...") if isinstance(ir_v, str) else type(ir_v).__name__
        )
        print(
            f"[/api/rounds end] round_id={round_id} update_ok={updated} "
            f"ir_json_brief={ir_brief!r}",
            flush=True,
        )
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
            inserted = db.insert_round(legacy_data)
            print(
                f"[/api/rounds end] fallback insert_round round_id={round_id} "
                f"rowid={inserted}",
                flush=True,
            )

        # Push updated record to frontend
        record = db.get_round_by_id(round_id)
        if record:
            socketio.emit("new_round_info", record)
            # Emit fine-grained WSS events
            # 关键：精细化 push 的 ir_json / action_json 一律取 DB 当前真实值
            # （record），而不是请求体里的 data——因为 update_round_end 对
            # 空/占位的 ir_json/action_json 已做防覆盖，DB 里可能保存着
            # portkey 早先回填的真实 IR，请求体那个版本反而是空的。
            ir_json = (record or {}).get("ir_json") or ""
            action_json = (record or {}).get("action_json") or "[]"
            if ir_json and ir_json != "__loading__" and data.get("overall_score", -1) < 0:
                # IR ready but not yet judged
                socketio.emit("push", {"push_type": "round_ir_ready", "round_id": round_id, "ir_json": ir_json, "push_time": data.get("time_end") or data.get("time_start", "")}, namespace="/wss/monitor")
            elif data.get("overall_score", -1) >= 0:
                # Full round end with judge
                socketio.emit("push", {"push_type": "round_end", "round_id": round_id, "time_start": data.get("time_start", ""), "time_end": data.get("time_end", ""), "action_json": action_json, "ir_json": ir_json, "overall_score": data.get("overall_score", 1.0), "judge_result": data.get("judge_result", ""), "push_time": data.get("time_end", "")}, namespace="/wss/monitor")

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
    # admin_key = request.headers.get("X-Admin-Key", "")
    auth_token = request.headers.get("X-Auth-Token", "")
    token = request.headers.get("X-Admin-Session", "")
    is_admin = _check_admin_session(token)
    # Privileged config keys that require admin
    privileged_keys = {"secret_key", "subdomain"}

    for key, value in data.items():
        if key == "admin_key":
            # Admin key cannot be modified
            return jsonify({"ok": False, "error": "特权密钥不可修改"}), 403
        if key in privileged_keys:
            if not is_admin:
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
MONITOR_CONF_KEYS = ["gateway_log_path", "openclaw_root", "use_gateway", "tool_trace_enabled"]

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
    "tool_injection": "inject",   # 工具注入：固定网络外发 / 文件路径
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


# ─── Attack Messages API ─────────────────────────────────
@api_doc(summary="伪装的 Webhook 端点（实际用于攻击消息记录）", category="模拟攻击", public=True)
@app.route("/api/webhook", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
def receive_attack():
    """伪装的 Webhook 端点。表面上是用于接收外部回调，实际上会记录所有请求信息用于攻击检测。
    
    支持的方法：GET、POST、PUT、DELETE、PATCH、HEAD、OPTIONS 等
    记录的信息：
    - 请求方法 (GET/POST/PUT/DELETE 等)
    - 来源 IP、Host、User-Agent、Referer
    - Content-Type、Content-Length
    - 完整请求体内容
    - 所有请求头
    """
    from flask import request as flask_request
    import time
    
    # 收集请求信息
    data = {
        "received_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "request_method": flask_request.method,
        "source_ip": flask_request.remote_addr or "unknown",
        "source_host": flask_request.host or "unknown",
        "user_agent": flask_request.user_agent.string if flask_request.user_agent else "",
        "referrer": flask_request.referrer or "",
        "content_type": flask_request.content_type or "",
        "content_length": flask_request.content_length or 0,
        "message_content": flask_request.get_data(as_text=True) or "",
        "headers": dict(flask_request.headers),
        "payload": flask_request.get_json(silent=True) or {},
        "attack_type": "attack_request",
    }
    
    row_id = db.insert_attack_message(data)
    if row_id:
        return jsonify({
            "ok": True, 
            "data": {"id": row_id, "method": flask_request.method, "message": "攻击请求已记录"},
            "attack_success": True
        })
    else:
        return jsonify({"ok": False, "error": "存储失败"}), 500


@api_doc(summary="获取攻击消息列表", category="模拟攻击", public=True, 
          params=[{"name":"limit","type":"query","default":"20","desc":"每页条数，最大100"}, 
                  {"name":"offset","type":"query","default":"0","desc":"偏移量"}],
          response={"ok": True, "total": 100, "data": [{"id":1,"request_method":"GET","received_at":"2026-06-19 10:00:00","source_ip":"127.0.0.1","source_host":"localhost:15100"}]})
@app.route("/api/attack/messages", methods=["GET"])
def get_attack_messages():
    """获取已记录的攻击消息列表。"""
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    result = db.get_attack_messages(limit=limit, offset=offset)
    return jsonify({"ok": True, **result})


@api_doc(summary="清空攻击消息", category="模拟攻击", public=False,
          response={"ok": True, "data": {"deleted": 50}})
@app.route("/api/attack/messages", methods=["DELETE"])
def clear_attack_messages():
    """清空所有攻击消息记录。"""
    count = db.clear_attack_messages()
    return jsonify({"ok": True, "data": {"deleted": count}})


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


# ─── Intercept Non-IR Tools Config ─────────────────────────
# 是否拦截 IR 外工具：开启后，portkey 网关在收到 LLM 响应中的 tool_calls 时，
# 会先通过 turn-ir 接口同步获取该轮的 IR，仅放行 IR 白名单内的工具调用；
# 其它工具会被替换为系统提示，建议 Agent 使用 IR 内允许的工具。
@api_doc(summary="获取 IR 外工具拦截开关状态", category="平台配置", public=False)
@app.route("/api/config/intercept_non_ir_tools", methods=["GET"])
def get_intercept_non_ir_tools():
    enabled = db.get_config("intercept.non_ir_tools_enabled", "false")
    return jsonify({"ok": True, "data": {"enabled": (enabled or "false").lower() == "true"}})


@api_doc(summary="设置 IR 外工具拦截开关状态", category="平台配置", public=False)
@app.route("/api/config/intercept_non_ir_tools", methods=["PUT"])
def set_intercept_non_ir_tools():
    """开关需特权验证。开启后 portkey 网关会根据 IR 拦截 tool_calls。"""
    token = request.headers.get("X-Admin-Session", "")
    if not _check_admin_session(token):
        return jsonify({"ok": False, "error": "需要特权验证"}), 403
    data = request.get_json(force=True)
    enabled = bool(data.get("enabled", False))
    db.set_config("intercept.non_ir_tools_enabled", "true" if enabled else "false")
    # 切换开关时清空 turn-ir 缓存
    try:
        _TURN_IR_CACHE.clear()
    except Exception:
        pass
    return jsonify({"ok": True, "data": {"enabled": enabled}})


# ─── Loop-Breaker（死循环熔断）配置 ─────────────────────────
# Agent 在 IR 白名单极窄且唯一工具"看似返回成功但内容不达预期"时，会反复重试
# 同一工具调用陷入死循环（典型：safe_file_reader__read_directory）。
# 该开关开启后，portkey 网关会在 turn 粒度对 (tool_name, arguments_hash) 计数，
# 一旦阈值（默认 3 次，含本次）触达，跳过 retry 直接合成"loop break"拒绝文本，
# 强制 Agent 改用自然语言回答用户原始问题，结束死循环。
@api_doc(summary="获取死循环熔断配置", category="平台配置", public=False)
@app.route("/api/config/loop_breaker", methods=["GET"])
def get_loop_breaker():
    enabled = (db.get_config("intercept.loop_breaker_enabled", "true") or "true").lower() == "true"
    try:
        threshold = int(db.get_config("intercept.loop_breaker_threshold", "3") or "3")
    except Exception:
        threshold = 3
    if threshold < 2:
        threshold = 2
    return jsonify({"ok": True, "data": {"enabled": enabled, "threshold": threshold}})


@api_doc(summary="设置死循环熔断配置", category="平台配置", public=False)
@app.route("/api/config/loop_breaker", methods=["PUT"])
def set_loop_breaker():
    """开关需特权验证。enabled: bool；threshold: int >=2，默认 3。"""
    token = request.headers.get("X-Admin-Session", "")
    if not _check_admin_session(token):
        return jsonify({"ok": False, "error": "需要特权验证"}), 403
    data = request.get_json(force=True) or {}
    enabled = bool(data.get("enabled", True))
    try:
        threshold = int(data.get("threshold", 3))
    except Exception:
        threshold = 3
    if threshold < 2:
        threshold = 2
    if threshold > 50:
        threshold = 50
    db.set_config("intercept.loop_breaker_enabled", "true" if enabled else "false")
    db.set_config("intercept.loop_breaker_threshold", str(threshold))
    # 切换熔断配置时清空 turn-ir 缓存（让 portkey 拿到新值）
    try:
        _TURN_IR_CACHE.clear()
    except Exception:
        pass
    return jsonify({"ok": True, "data": {"enabled": enabled, "threshold": threshold}})


# ─── Turn IR 长轮询超时配置 ──────────────────────────────────────────────
# 单位毫秒；下限 5_000（5s）避免请求秒回，上限 1_800_000（30 分钟）兼顾极慢翻译。
TURN_IR_WAIT_MS_DEFAULT = 300_000
TURN_IR_WAIT_MS_MIN = 5_000
TURN_IR_WAIT_MS_MAX = 1_800_000


def _get_turn_ir_wait_ms_config() -> int:
    """读取 DB 中配置的长轮询超时（毫秒），自动 clamp 到 [MIN, MAX]。"""
    try:
        v = int(db.get_config("intercept.turn_ir_wait_ms", str(TURN_IR_WAIT_MS_DEFAULT)) or TURN_IR_WAIT_MS_DEFAULT)
    except Exception:
        v = TURN_IR_WAIT_MS_DEFAULT
    return max(TURN_IR_WAIT_MS_MIN, min(v, TURN_IR_WAIT_MS_MAX))


@api_doc(summary="获取 IR 长轮询超时配置", category="平台配置", public=False)
@app.route("/api/config/turn_ir_wait_ms", methods=["GET"])
def get_turn_ir_wait_ms():
    wait_ms = _get_turn_ir_wait_ms_config()
    return jsonify({"ok": True, "data": {
        "wait_ms": wait_ms,
        "min_ms": TURN_IR_WAIT_MS_MIN,
        "max_ms": TURN_IR_WAIT_MS_MAX,
        "default_ms": TURN_IR_WAIT_MS_DEFAULT,
    }})


@api_doc(summary="设置 IR 长轮询超时配置", category="平台配置", public=False)
@app.route("/api/config/turn_ir_wait_ms", methods=["PUT"])
def set_turn_ir_wait_ms():
    """超时调整需特权验证。wait_ms: 5_000~1_800_000 毫秒，默认 300_000（5 分钟）。"""
    token = request.headers.get("X-Admin-Session", "")
    if not _check_admin_session(token):
        return jsonify({"ok": False, "error": "需要特权验证"}), 403
    data = request.get_json(force=True) or {}
    try:
        wait_ms = int(data.get("wait_ms", TURN_IR_WAIT_MS_DEFAULT))
    except Exception:
        wait_ms = TURN_IR_WAIT_MS_DEFAULT
    wait_ms = max(TURN_IR_WAIT_MS_MIN, min(wait_ms, TURN_IR_WAIT_MS_MAX))
    db.set_config("intercept.turn_ir_wait_ms", str(wait_ms))
    return jsonify({"ok": True, "data": {"wait_ms": wait_ms}})


# ─── Turn IR (供 portkey 网关同步调用) ─────────────────────
# 同一 turn（user_query）共享一个 IR。portkey 在拦截 LLM 响应时调用本接口：
#   - 传入 turn_key 与 user_query
#   - 若该 turn 已翻译过则直接返回缓存
#   - 否则同步调用现有翻译流水线，缓存并返回
import threading as _threading
import re as _re_turn
_TURN_IR_LOCK = _threading.Lock()
# cache key：**normalize 后的 user_query**（不再用 portkey 的 hash turn_key）
# 这样 watcher 翻译完成后只要用同一份 user_query 算 key，就能命中
# portkey 长轮询线程；portkey 端的 turn_key 仅作为 round 绑定/事件去重等用途。
_TURN_IR_CACHE: Dict[str, Dict[str, Any]] = {}
_TURN_IR_MAX_ENTRIES = 256
# normalized_user_query -> threading.Event，watcher 翻译完成后 set；
# portkey 长轮询线程 wait 在这个 Event 上，超时或被 round_start 清掉时返回。
_TURN_IR_EVENTS: Dict[str, _threading.Event] = {}
# 当前正在等待翻译完成的 normalized user_query 集合（用于 round_start 清理）
_TURN_IR_PENDING: set = set()
# turn_key -> round_id 绑定（首次回填成功后记住，后续 turn 命中缓存也能复用）
_TURN_IR_ROUND_BIND: Dict[str, str] = {}

# ─── normalize user_query ─────────────────────────────────────────────────
# 与 portkey 端 `sanitizeUserQuery` 规则完全一致，必须保持同步！否则 portkey
# 算出来的 turn_key 命中 user_query 与 watcher 算出来的 cache key 不一致，
# 长轮询会永远 wait 到超时。
_SENDER_META_RE = _re_turn.compile(
    r"Sender\s*\(untrusted metadata\)\s*:\s*```json\s*\{[\s\S]*?\}\s*```\s*"
)
_TS_PREFIX_RE = _re_turn.compile(r"^\[[^\]]*\]\s*")


def _normalize_user_query(raw: str) -> str:
    """剥离 Sender 元信息块 + 行首时间戳前缀，取最后一行非空文本。

    必须与 portkey/src/middlewares/irIntercept.ts:sanitizeUserQuery 保持一致。
    """
    if not isinstance(raw, str) or not raw:
        return ""
    cleaned = _SENDER_META_RE.sub("", raw).strip()
    if not cleaned:
        return ""
    lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
    if not lines:
        return cleaned
    last = _TS_PREFIX_RE.sub("", lines[-1]).strip()
    return last or cleaned


def _turn_ir_get_or_create_event(key: str) -> _threading.Event:
    """返回 normalized_user_query 对应的 Event，不存在则创建。必须在 LOCK 内调用。"""
    ev = _TURN_IR_EVENTS.get(key)
    if ev is None:
        ev = _threading.Event()
        _TURN_IR_EVENTS[key] = ev
    return ev


def _turn_ir_publish_translation(user_query: str, ir_result: Dict[str, Any]) -> None:
    """watcher 翻译完成后调用：写 cache + set Event 唤醒所有长轮询线程。

    幂等：同一个 normalized user_query 多次发布只保留最新 IR，但 Event 始终 set。
    """
    key = _normalize_user_query(user_query)
    if not key:
        print("[turn-ir.publish] skip: empty normalized key", flush=True)
        return
    allowed_tools = _extract_allowed_tools_from_ir(ir_result or {})
    entry = {
        "allowed_tools": allowed_tools,
        "ir": ir_result or {},
        "user_query": user_query,
    }
    with _TURN_IR_LOCK:
        # 简单 LRU：超过容量先丢首条
        if key not in _TURN_IR_CACHE and len(_TURN_IR_CACHE) >= _TURN_IR_MAX_ENTRIES:
            try:
                _TURN_IR_CACHE.pop(next(iter(_TURN_IR_CACHE)))
            except Exception:
                pass
        _TURN_IR_CACHE[key] = entry
        ev = _turn_ir_get_or_create_event(key)
        _TURN_IR_PENDING.discard(key)
    ev.set()
    print(
        f"[turn-ir.publish] cached key={key[:40]!r} allowed_tools={allowed_tools} "
        f"event_set=1",
        flush=True,
    )


def _turn_ir_reset_for_new_round() -> None:
    """round_start 时清掉旧 turn 的 pending Event。

    旧 IR 仍保留在 cache 中（短期内同 user_query 复用），但 pending 状态被清空，
    避免上一轮没等到翻译的长轮询线程一直 hang 到 5 分钟。
    """
    with _TURN_IR_LOCK:
        # 把 pending 集合里仍未完成的 Event 全部 set（让对应长轮询返回 pending），
        # 然后丢掉 pending 标记。已经发布成功的 Event 不动。
        stale_keys = list(_TURN_IR_PENDING)
        _TURN_IR_PENDING.clear()
        # 清掉对应的 Event 对象本身，避免下一轮误命中
        for k in stale_keys:
            ev = _TURN_IR_EVENTS.pop(k, None)
            if ev is not None:
                try:
                    ev.set()  # 唤醒老的长轮询线程，让它返回 pending
                except Exception:
                    pass
    if stale_keys:
        print(
            f"[turn-ir.reset] round_start cleared {len(stale_keys)} stale pending keys",
            flush=True,
        )


def _extract_allowed_tools_from_ir(ir_result: Dict[str, Any]) -> List[str]:
    """从翻译结果中抽取所有允许调用的 tool identifier。"""
    tools: set = set()
    level2 = (ir_result or {}).get("level2") or {}
    for pol in level2.get("policies", []) or []:
        if not isinstance(pol, dict):
            continue
        if pol.get("effect") and pol.get("effect") != "allow":
            continue
        for obj in pol.get("objects", []) or []:
            if isinstance(obj, dict) and obj.get("type") == "tool":
                ident = obj.get("identifier")
                if isinstance(ident, str) and ident:
                    tools.add(ident)
    return sorted(tools)


@api_doc(summary="获取/翻译指定 turn 的 IR（portkey 网关同步调用，long-poll）",
         category="策略翻译",
         description=(
             "按 normalized user_query 缓存：同一 turn 多次调用复用首个 IR。\n"
             "**Long-Poll 语义**：\n"
             "  - cache 命中 → 立即返回 cached=true；\n"
             "  - cache 未命中 → 等待 watcher 翻译完成（_query_and_ir_worker 写 cache + set Event）；\n"
             "  - 超时仍未完成 → **本端自行 fallback 调一次 translate**，成功则正常返回；"
             "失败再上报 ir_timeout 拦截事件并返回 pending=true，由 portkey 端降级放行。\n"
             "默认翻译均由 watcher 在 round_start 后异步完成，仅在 watcher 漏触发等异常时走 fallback。\n"
             "wait_ms 由 DB 配置 `intercept.turn_ir_wait_ms` 控制（默认 300_000ms，可在前端调整）。"
         ),
         params=[{"name": "turn_key", "type": "body", "desc": "turn 标识（portkey 计算）"},
                 {"name": "user_query", "type": "body", "desc": "用户原始 query（必填，作为 cache key）"},
                 {"name": "round_id", "type": "body", "desc": "可选 round_id"},
                 {"name": "wait_ms", "type": "body", "desc": "可选；缺省读取 DB 配置；范围 5_000 ~ 1_800_000 ms"}],
         response={"ok": True, "data": {"allowed_tools": [], "ir": {}, "cached": False, "pending": False, "intercept_enabled": False}},
         public=True)
@app.route("/api/translator/turn-ir", methods=["POST"])
def get_turn_ir():
    """portkey 同步调用：根据 normalized user_query 长轮询返回 IR + 允许的 tool 白名单。"""
    data = request.get_json(force=True) or {}
    turn_key = (data.get("turn_key") or "").strip()
    user_query = (data.get("user_query") or "").strip()
    round_id = (data.get("round_id") or "").strip()
    # wait_ms 优先级：请求体显式传入 > DB 配置 > 默认值
    cfg_wait_ms = _get_turn_ir_wait_ms_config()
    if "wait_ms" in data and data.get("wait_ms") is not None:
        try:
            wait_ms = int(data.get("wait_ms"))
        except Exception:
            wait_ms = cfg_wait_ms
    else:
        wait_ms = cfg_wait_ms
    # 0 仍允许（前端"立即探测"）；其它值 clamp 到 [MIN, MAX]
    if wait_ms > 0:
        wait_ms = max(TURN_IR_WAIT_MS_MIN, min(wait_ms, TURN_IR_WAIT_MS_MAX))
    else:
        wait_ms = 0

    print(
        f"[turn-ir] hit endpoint turn_key={turn_key[:12]}... "
        f"uq_len={len(user_query)} round_id={round_id} wait_ms={wait_ms}",
        flush=True,
    )

    # 总开关：未启用时直接返回 disabled，让网关跳过拦截逻辑
    enabled = (db.get_config("intercept.non_ir_tools_enabled", "false") or "false").lower() == "true"

    # [loop-breaker] 死循环熔断配置：随每次响应回吐给 portkey
    lb_enabled = (db.get_config("intercept.loop_breaker_enabled", "true") or "true").lower() == "true"
    try:
        lb_threshold = int(db.get_config("intercept.loop_breaker_threshold", "3") or "3")
    except Exception:
        lb_threshold = 3
    if lb_threshold < 2:
        lb_threshold = 2

    if not enabled:
        print(f"[turn-ir] switch disabled, return intercept_enabled=False", flush=True)
        return jsonify({"ok": True, "data": {
            "intercept_enabled": False,
            "allowed_tools": [],
            "ir": {},
            "cached": False,
            "pending": False,
            "loop_breaker_enabled": lb_enabled,
            "loop_breaker_threshold": lb_threshold,
        }})

    if not user_query:
        return jsonify({"ok": False, "error": "user_query is required"}), 400

    norm_key = _normalize_user_query(user_query)
    if not norm_key:
        return jsonify({"ok": False, "error": "user_query normalized to empty"}), 400

    def _make_response_from_entry(entry: Dict[str, Any], cached: bool, pending: bool = False):
        # turn_key 已绑定的话仍执行一次 backfill（用 portkey 的 turn_key 做 round 关联）
        if entry and turn_key:
            try:
                _backfill_round_ir(
                    user_query or entry.get("user_query", ""),
                    entry.get("ir", {}),
                    turn_key=turn_key,
                )
            except Exception as e:
                print(f"[turn-ir] backfill failed: {e}", flush=True)
        return jsonify({"ok": True, "data": {
            "intercept_enabled": True,
            "allowed_tools": (entry or {}).get("allowed_tools", []),
            "ir": (entry or {}).get("ir", {}),
            "cached": cached,
            "pending": pending,
            "loop_breaker_enabled": lb_enabled,
            "loop_breaker_threshold": lb_threshold,
        }})

    # 1) 命中缓存：立即返回
    with _TURN_IR_LOCK:
        cached = _TURN_IR_CACHE.get(norm_key)
    if cached:
        print(
            f"[turn-ir] CACHE HIT key={norm_key[:40]!r} "
            f"allowed_tools={cached.get('allowed_tools', [])}",
            flush=True,
        )
        return _make_response_from_entry(cached, cached=True)

    # 2) 未命中且 wait_ms == 0：直接返回 pending（portkey 可选用此模式快速探测）
    if wait_ms <= 0:
        return _make_response_from_entry({}, cached=False, pending=True)

    # 3) 长轮询：等待 watcher 翻译完成（_turn_ir_publish_translation 会 set Event）
    with _TURN_IR_LOCK:
        ev = _turn_ir_get_or_create_event(norm_key)
        _TURN_IR_PENDING.add(norm_key)
        # 二次检查：可能在拿锁前 watcher 已 publish 完了
        cached2 = _TURN_IR_CACHE.get(norm_key)
    if cached2:
        return _make_response_from_entry(cached2, cached=True)

    print(
        f"[turn-ir] LONG-POLL waiting key={norm_key[:40]!r} timeout={wait_ms}ms",
        flush=True,
    )
    # 改用轮询 + 短 sleep 替代 Event.wait()：
    # gevent monkey-patched 下 threading.Event 跨执行体唤醒在某些路径上不稳定
    # （观测到 watcher 已 set 但 wait 未返回），改成主动轮询 cache 最稳：
    #   - 每 100ms 检查一次 cache，watcher publish 后最多 100ms 内被发现；
    #   - time.sleep 也被 gevent patch，每次都会让出 hub，不占 CPU；
    #   - 通过 time.monotonic 控制超时上限，行为与 Event.wait 一致。
    import time as _time_lp
    poll_interval = 0.1
    deadline = _time_lp.monotonic() + (wait_ms / 1000.0)
    entry = None
    while _time_lp.monotonic() < deadline:
        with _TURN_IR_LOCK:
            entry = _TURN_IR_CACHE.get(norm_key)
        if entry:
            break
        _time_lp.sleep(poll_interval)

    if entry:
        print(
            f"[turn-ir] LONG-POLL got key={norm_key[:40]!r} "
            f"after_polling=True allowed_tools={entry.get('allowed_tools', [])}",
            flush=True,
        )
        return _make_response_from_entry(entry, cached=False)

    # 4) 超时仍无 IR：**fallback 主动 translate 一次**作为兜底
    #    （watcher 可能漏触发、user_query 提取失败等异常场景）
    print(
        f"[turn-ir] LONG-POLL TIMEOUT key={norm_key[:40]!r} "
        f"after {wait_ms/1000:.0f}s, fallback to local translate",
        flush=True,
    )
    fallback_err = ""
    try:
        from auditor.translator.core import translate, get_llm_config
        cfg = get_llm_config()
        result = translate(user_query, config=cfg, is_ui_test=False, round_id=round_id)
        # 复用 publish 流水线（写 cache + set Event + 唤醒同时在 wait 的其它请求）
        _turn_ir_publish_translation(user_query, result or {})
        with _TURN_IR_LOCK:
            entry = _TURN_IR_CACHE.get(norm_key)
        if entry:
            print(
                f"[turn-ir] FALLBACK translate OK key={norm_key[:40]!r} "
                f"allowed_tools={entry.get('allowed_tools', [])}",
                flush=True,
            )
            return _make_response_from_entry(entry, cached=False)
    except Exception as e:
        fallback_err = f"{type(e).__name__}: {e}"
        print(f"[turn-ir] FALLBACK translate FAILED: {fallback_err}", flush=True)

    # 5) fallback 也失败：上报 ir_timeout 拦截事件，返回 pending
    try:
        _record_turn_ir_timeout_event(
            turn_key=turn_key,
            user_query=user_query,
            round_id=round_id,
            wait_ms=wait_ms,
            fallback_err=fallback_err,
        )
    except Exception as e:
        print(f"[turn-ir] timeout event report failed: {e}", flush=True)
    return _make_response_from_entry({}, cached=False, pending=True)


def _record_turn_ir_timeout_event(
    turn_key: str,
    user_query: str,
    round_id: str,
    wait_ms: int,
    fallback_err: str = "",
) -> None:
    """超时且 fallback translate 也失败时，向 intercept_events 写一条 'ir_timeout' 事件。

    note 字段记录人类可读的说明（前端 SecurityPage 备注列直接展示）。
    """
    try:
        conn = db.get_conn()
        note_parts = [
            f"IR 长轮询超时（{wait_ms/1000:.0f}s）且 fallback translate 失败",
            "可能原因：watcher 未触发 round_start / user_query 抓取失败 / LLM 不可用",
        ]
        if fallback_err:
            note_parts.append(f"fallback 错误：{fallback_err[:300]}")
        note = "；".join(note_parts)
        extra = {
            "round_id": round_id,
            "wait_ms": wait_ms,
            "reason": "long_poll_timeout_and_fallback_failed",
            "fallback_err": fallback_err,
        }
        conn.execute(
            "INSERT INTO intercept_events (event_type, protocol, turn_key, user_query, "
            "violations_json, allowed_tools_json, source, extra_json, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "ir_timeout",
                "",
                turn_key,
                (user_query or "")[:4000],
                json.dumps([], ensure_ascii=False),
                json.dumps([], ensure_ascii=False),
                "clawavc-long-poll",
                json.dumps(extra, ensure_ascii=False),
                note,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, received_at, event_type, protocol, turn_key, user_query, "
            "violations_json, allowed_tools_json, source, extra_json, note "
            "FROM intercept_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            payload = _row_to_intercept_event(row)
            try:
                socketio.emit("intercept_event", payload)
            except Exception:
                pass
            try:
                socketio.emit(
                    "push",
                    {"push_type": "intercept_event",
                     "push_time": payload.get("received_at"),
                     "data": payload},
                    namespace="/wss/monitor",
                )
            except Exception:
                pass
            print(f"[turn-ir.timeout] event recorded id={row['id']}", flush=True)
    except Exception as e:
        print(f"[turn-ir.timeout] record failed: {e}", flush=True)


def _backfill_round_ir(
    user_query: str,
    ir_result: Dict[str, Any],
    turn_key: str = "",
) -> None:
    """把 portkey 触发的 IR 翻译结果，回填到对应的 round.ir_json 上。

    匹配策略（按优先级）：
      0) 若 turn_key 已与某个 round_id 绑定，且该 round 仍处于"未填 IR"状态，
         直接命中该 round（避免错误关联到别的 round）。
      1) user_query 精确匹配最近 30 分钟内、ir_json 仍为空/占位/__loading__ 的最新 round；
      2) 都没匹配上则退化：取最近 30 分钟内、ir_json 仍为空/占位/__loading__ 的最新 round
         （portkey 调 turn-ir 时 round.user_query 通常还没写入，需要这一层兜底）；
      3) 仍未命中：什么都不做，等下一次 turn-ir 调用再试。

    成功回填后：
      - UPDATE rounds.ir_json
      - 记住 turn_key -> round_id 绑定，便于后续 turn（命中缓存）二次确认
      - socketio emit "new_round_info" + "push{round_ir_ready}"，前端实时刷新
    """
    ir_json_str = json.dumps(ir_result, ensure_ascii=False)
    loading = "__loading__"

    conn = db.get_conn()
    try:
        row = None
        match_strategy = ""
        # 0) 已绑定 turn_key → round_id：优先复用
        bound_round_id = _TURN_IR_ROUND_BIND.get(turn_key) if turn_key else None
        if bound_round_id:
            row = conn.execute(
                """
                SELECT round_id FROM rounds
                WHERE round_id = ?
                  AND (ir_json IS NULL OR ir_json = '' OR ir_json = '{}' OR ir_json = ?)
                """,
                (bound_round_id, loading),
            ).fetchone()
            if row:
                match_strategy = f"bound({bound_round_id})"

        # 1) user_query 精确匹配（仅在 user_query 非空时尝试）
        if not row and user_query:
            row = conn.execute(
                """
                SELECT round_id FROM rounds
                WHERE user_query = ?
                  AND (ir_json IS NULL OR ir_json = '' OR ir_json = '{}' OR ir_json = ?)
                  AND created_at >= datetime('now', '-30 minutes')
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_query, loading),
            ).fetchone()
            if row:
                match_strategy = "user_query_exact"

        # 2) 兜底：最近 30 分钟 ir_json 还没填的最新 round
        #    （portkey 调 turn-ir 早于 round_end 写入 user_query 时走这里）
        if not row:
            row = conn.execute(
                """
                SELECT round_id FROM rounds
                WHERE (ir_json IS NULL OR ir_json = '' OR ir_json = '{}' OR ir_json = ?)
                  AND created_at >= datetime('now', '-30 minutes')
                ORDER BY id DESC
                LIMIT 1
                """,
                (loading,),
            ).fetchone()
            if row:
                match_strategy = "fallback_latest_empty"

        if not row:
            # 进一步诊断：看看最近的 rounds 都长什么样
            diag = conn.execute(
                """
                SELECT round_id, substr(user_query,1,40) as uq,
                       substr(ir_json,1,30) as ir, created_at
                FROM rounds
                ORDER BY id DESC LIMIT 3
                """
            ).fetchall()
            diag_str = "; ".join(
                f"{r['round_id'][:16]}|uq={r['uq']!r}|ir={r['ir']!r}|ct={r['created_at']}"
                for r in diag
            ) if diag else "(empty rounds table)"
            print(
                f"[turn-ir] backfill SKIP: no round to update "
                f"(uq_len={len(user_query) if user_query else 0}, "
                f"turn_key={turn_key[:12]}...) recent_rounds=[{diag_str}]",
                flush=True,
            )
            return
        round_id = row["round_id"]
        cursor = conn.execute(
            "UPDATE rounds SET ir_json = ? WHERE round_id = ?",
            (ir_json_str, round_id),
        )
        conn.commit()
        print(
            f"[turn-ir] backfill UPDATE strategy={match_strategy} "
            f"round_id={round_id} affected={cursor.rowcount} "
            f"ir_len={len(ir_json_str)}",
            flush=True,
        )
    finally:
        conn.close()

    # 绑定 turn_key → round_id，方便后续 turn 命中缓存时直接定位
    if turn_key:
        _TURN_IR_ROUND_BIND[turn_key] = round_id
        # 防膨胀：超出阈值清理一半
        if len(_TURN_IR_ROUND_BIND) > _TURN_IR_MAX_ENTRIES * 2:
            try:
                keys = list(_TURN_IR_ROUND_BIND.keys())
                for k in keys[: len(keys) // 2]:
                    _TURN_IR_ROUND_BIND.pop(k, None)
            except Exception:
                pass

    # 推送给前端实时刷新（运行日志页订阅了 new_round_info）
    try:
        record = db.get_round_by_id(round_id)
        if record:
            socketio.emit("new_round_info", record)
            socketio.emit(
                "push",
                {
                    "push_type": "round_ir_ready",
                    "round_id": round_id,
                    "ir_json": ir_json_str,
                    "push_time": record.get("time_end") or record.get("time_start", ""),
                },
                namespace="/wss/monitor",
            )
            print(
                f"[turn-ir] socketio emit new_round_info + round_ir_ready: round_id={round_id}",
                flush=True,
            )
    except Exception as e:
        print(f"[turn-ir] socketio emit failed: {e}", flush=True)


# ─── Intercept Events (portkey 网关上报 / 前端查询 / 实时推送) ─────────────
# portkey 网关在命中 IR 重写时通过 POST /api/intercept/events 上报，
# 前端"安全拦截"页通过 GET 拉取列表 + 监听 socketio "intercept_event" 实时刷新。
@api_doc(summary="网关上报一次拦截事件", category="安全拦截",
         description="portkey 网关在命中 IR 重写后调用，记录被拒绝的工具调用，便于审计与前端可视化。",
         params=[
             {"name": "event_type", "type": "body", "desc": "事件类型，默认 ir_tool_block"},
             {"name": "protocol", "type": "body", "desc": "openai | anthropic"},
             {"name": "turn_key", "type": "body", "desc": "网关计算的 turn 标识"},
             {"name": "user_query", "type": "body", "desc": "本轮 user_query 摘要"},
             {"name": "violations", "type": "body", "desc": "被拦截的 tool 名称数组"},
             {"name": "allowed_tools", "type": "body", "desc": "本轮 IR 白名单"},
             {"name": "source", "type": "body", "desc": "上报来源，例如 portkey-gateway"},
             {"name": "extra", "type": "body", "desc": "附加 JSON，可放上游 model、url 等"},
         ],
         response={"ok": True, "data": {"id": 1}},
         public=True)
@app.route("/api/intercept/events", methods=["POST"])
def post_intercept_event():
    data = request.get_json(force=True) or {}
    event_type = (data.get("event_type") or "ir_tool_block").strip() or "ir_tool_block"
    protocol = (data.get("protocol") or "").strip()
    turn_key = (data.get("turn_key") or "").strip()
    user_query = data.get("user_query") or ""
    if isinstance(user_query, str) and len(user_query) > 4000:
        user_query = user_query[:4000]
    violations = data.get("violations") or []
    allowed_tools = data.get("allowed_tools") or []
    source = (data.get("source") or "portkey-gateway").strip()
    extra = data.get("extra") or {}
    note = data.get("note") or ""
    if isinstance(note, str) and len(note) > 2000:
        note = note[:2000]

    # 去重：portkey 在同一 user_query 下因 Agent 重试会多次触发拦截上报。
    # 即便 turn_key 已稳定（基于 user_query 内容），同 turn_key + 同 violations
    # 集合 + 短时间窗口内的事件视为同一个"逻辑事件"，不重复入库，避免前端
    # 拦截事件列表被刷屏（典型表现：同一 user_query 30 秒内出现 N 条相同条目）。
    # 窗口设为 120 秒，足够覆盖 Agent 多轮 retry；超过窗口的新事件视为"用户又一次
    # 触发同样的违规调用"，允许独立记录。
    DEDUP_WINDOW_SECONDS = 120
    violations_canon = json.dumps(
        sorted([str(v) for v in violations]),
        ensure_ascii=False,
    )

    try:
        conn = db.get_conn()
        # 先查最近窗口内有没有"同 turn_key + 同 violations 集合"的事件
        dedup_row = None
        if turn_key:
            dedup_row = conn.execute(
                """
                SELECT id, received_at FROM intercept_events
                WHERE turn_key = ?
                  AND event_type = ?
                  AND received_at >= datetime('now', ?)
                ORDER BY id DESC
                LIMIT 1
                """,
                (turn_key, event_type, f"-{DEDUP_WINDOW_SECONDS} seconds"),
            ).fetchone()

        if dedup_row:
            # 比对 violations 集合是否一致：完全相同才认定为重复
            existing = conn.execute(
                "SELECT violations_json FROM intercept_events WHERE id = ?",
                (dedup_row["id"],),
            ).fetchone()
            existing_canon = ""
            if existing and existing["violations_json"]:
                try:
                    existing_canon = json.dumps(
                        sorted([str(v) for v in json.loads(existing["violations_json"])]),
                        ensure_ascii=False,
                    )
                except Exception:
                    existing_canon = ""

            if existing_canon == violations_canon:
                conn.close()
                print(
                    f"[intercept] DEDUP hit: turn_key={turn_key[:12]}... "
                    f"violations={violations_canon} -> reuse id={dedup_row['id']}",
                    flush=True,
                )
                # 复用已有行作为返回，前端的本地去重（按 id）自然不会重复展示
                conn = db.get_conn()
                row = conn.execute(
                    "SELECT id, received_at, event_type, protocol, turn_key, user_query, "
                    "violations_json, allowed_tools_json, source, extra_json, note "
                    "FROM intercept_events WHERE id = ?",
                    (dedup_row["id"],),
                ).fetchone()
                conn.close()
                payload = _row_to_intercept_event(row) if row else {"id": dedup_row["id"]}
                # 不再 emit socketio 事件（前端已有该 id），仅返回
                return jsonify({"ok": True, "data": payload, "dedup": True})

        cur = conn.execute(
            "INSERT INTO intercept_events (event_type, protocol, turn_key, user_query, "
            "violations_json, allowed_tools_json, source, extra_json, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_type,
                protocol,
                turn_key,
                user_query,
                json.dumps(violations, ensure_ascii=False),
                json.dumps(allowed_tools, ensure_ascii=False),
                source,
                json.dumps(extra, ensure_ascii=False),
                note,
            ),
        )
        event_id = cur.lastrowid
        conn.commit()
        row = conn.execute(
            "SELECT id, received_at, event_type, protocol, turn_key, user_query, "
            "violations_json, allowed_tools_json, source, extra_json, note "
            "FROM intercept_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": f"db insert failed: {e}"}), 500

    payload = _row_to_intercept_event(row) if row else {"id": event_id}
    # 同时向根 namespace（前端默认订阅）和 /wss/monitor（对外 push）推送
    try:
        socketio.emit("intercept_event", payload)
    except Exception:
        pass
    try:
        socketio.emit(
            "push",
            {"push_type": "intercept_event", "push_time": payload.get("received_at"), "data": payload},
            namespace="/wss/monitor",
        )
    except Exception:
        pass
    return jsonify({"ok": True, "data": payload})


def _row_to_intercept_event(row) -> Dict[str, Any]:
    """统一把一行 intercept_events 行转成前端友好结构。"""
    def _loads(s):
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            return s
    # 兼容旧库：sqlite3.Row 没有 .get，但 keys() 可用
    try:
        keys = row.keys()
    except Exception:
        keys = []
    note_val = row["note"] if "note" in keys else ""
    return {
        "id": row["id"],
        "received_at": row["received_at"],
        "event_type": row["event_type"],
        "protocol": row["protocol"],
        "turn_key": row["turn_key"],
        "user_query": row["user_query"],
        "violations": _loads(row["violations_json"]) or [],
        "allowed_tools": _loads(row["allowed_tools_json"]) or [],
        "source": row["source"],
        "extra": _loads(row["extra_json"]) or {},
        "note": note_val or "",
    }


@api_doc(summary="拉取拦截事件列表", category="安全拦截",
         params=[
             {"name": "limit", "type": "query", "desc": "返回条数上限，默认 100，最大 500"},
             {"name": "offset", "type": "query", "desc": "偏移，默认 0"},
             {"name": "event_type", "type": "query", "desc": "按类型过滤"},
         ],
         response={"ok": True, "data": {"items": [], "total": 0}},
         public=False)
@app.route("/api/intercept/events", methods=["GET"])
def list_intercept_events():
    try:
        limit = int(request.args.get("limit", 100))
    except Exception:
        limit = 100
    limit = max(1, min(limit, 500))
    try:
        offset = int(request.args.get("offset", 0))
    except Exception:
        offset = 0
    offset = max(0, offset)
    event_type = (request.args.get("event_type") or "").strip()

    conn = db.get_conn()
    where = ""
    params: List[Any] = []
    if event_type:
        where = "WHERE event_type = ?"
        params.append(event_type)
    total = conn.execute(
        f"SELECT COUNT(*) AS c FROM intercept_events {where}", params
    ).fetchone()["c"]
    rows = conn.execute(
        f"SELECT id, received_at, event_type, protocol, turn_key, user_query, "
        f"violations_json, allowed_tools_json, source, extra_json, note "
        f"FROM intercept_events {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    items = [_row_to_intercept_event(r) for r in rows]
    return jsonify({"ok": True, "data": {"items": items, "total": total}})


@api_doc(summary="清空拦截事件", category="安全拦截",
         description="特权操作，清空 intercept_events 表。",
         public=False)
@app.route("/api/intercept/events", methods=["DELETE"])
def clear_intercept_events():
    token = request.headers.get("X-Admin-Session", "")
    if not _check_admin_session(token):
        return jsonify({"ok": False, "error": "需要特权验证"}), 403
    conn = db.get_conn()
    conn.execute("DELETE FROM intercept_events")
    conn.commit()
    conn.close()
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
