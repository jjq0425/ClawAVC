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


@api_doc(summary="分页查询 Rounds", category="数据查询", params=[{"name":"limit","type":"int","default":"20","desc":"每页条数"},{"name":"offset","type":"int","default":"0","desc":"偏移量"},{"name":"query","type":"str","desc":"模糊搜索 user_query"},{"name":"round_id","type":"str","desc":"模糊搜索 round_id"},{"name":"time_from","type":"str","desc":"开始时间"},{"name":"time_to","type":"str","desc":"结束时间"}], response={"ok":True,"data":[],"total":0}, public=True)
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


@app.route("/api/rounds/<round_id>", methods=["GET"])
def get_round(round_id):
    """Get single round detail."""
    record = db.get_round_by_id(round_id)
    if not record:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "data": record})


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
        # ROUND_STARTED: insert partial record
        row_id = db.insert_round_start(
            round_id=round_id,
            time_start=data.get("time_start", ""),
            session_key=data.get("session_key") or data.get("sessionKey", ""),
            session_id=data.get("session_id") or data.get("sessionID", ""),
        )
        if row_id:
            record = db.get_round_by_id(round_id)
            if record:
                socketio.emit("new_round", record)
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
            socketio.emit("new_round", record)
            # Emit fine-grained WSS events
            ir_json = data.get("ir_json", "")
            if ir_json and ir_json != "__loading__" and data.get("overall_score", -1) < 0:
                # IR ready but not yet judged
                socketio.emit("push", {"push_type": "round_ir_ready", "round_id": round_id, "ir_json": ir_json, "push_time": data.get("time_end") or data.get("time_start", "")}, namespace="/wss/monitor")
            elif data.get("overall_score", -1) >= 0:
                # Full round end with judge
                socketio.emit("push", {"push_type": "round_end", "round_id": round_id, "time_start": data.get("time_start", ""), "time_end": data.get("time_end", ""), "action_json": data.get("action_json", "[]"), "ir_json": ir_json, "overall_score": data.get("overall_score", 1.0), "judge_result": data.get("judge_result", ""), "push_time": data.get("time_end", "")}, namespace="/wss/monitor")

        return jsonify({"ok": True})


@api_doc(summary="统计概览", category="数据查询", response={"ok":True,"data":{"total":0,"abnormal":0,"normal":0,"avg_score":0}}, public=True)
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

    if touches_config and not is_admin:
        return jsonify({"ok": False, "error": "需要特权验证才能访问 config 表"}), 403
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
        result = translate(query, config=config, is_ui_test=False)
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

# ─── /monitor namespace (运行消息组) ────────────────────────
@socketio.on("connect", namespace="/wss/monitor")
def handle_monitor_connect():
    print(f"[ws/monitor] client connected: {request.sid}")

@socketio.on("disconnect", namespace="/wss/monitor")
def handle_monitor_disconnect():
    print(f"[ws/monitor] client disconnected: {request.sid}")

def handle_disconnect():
    print(f"[ws] client disconnected: {request.sid}")


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
