"""Short-lived, opt-in handoff of a validated preflight IR to execution.

Only /translator/test requests with cache_for_execution=true prepare entries.
Keys include query, LLM configuration, active policy, prompts and registry state.
"""
from collections import OrderedDict
import copy
import hashlib
import json
from pathlib import Path
import threading
import time


# 校验通过的预检 IR 的短时缓存（opt-in）。
# 仅 /translator/test 且 cache_for_execution=true 的请求会准备条目；
# 键含 query、LLM 配置、当前策略库、提示词与注册表状态。
class PreparedTranslations:
# 容量与 TTL：容量满时按 LRU 淘汰最旧条目
    def __init__(self, ttl=300, capacity=64, clock=time.monotonic):
        self.ttl = ttl
        self.capacity = capacity
        self.clock = clock
        self.entries = OrderedDict()
        self.lock = threading.RLock()

# 键生成：query+config+scope 稳定序列化后哈希
    @staticmethod
# 键：三元组（查询/配置/生效范围）
    def key(query, config, scope):
# 稳定序列化：键排序，避免字段顺序影响哈希
        value = json.dumps([query, config, scope], sort_keys=True, ensure_ascii=False, default=str)
# sha256 摘要作为缓存键
        return hashlib.sha256(value.encode()).hexdigest()

# 写入：仅接受「校验通过且 query 一致」的结果
    def put(self, query, config, scope, result):
# 拒绝非本轮结果（防串号）
        if result.get('query') != query or (result.get('validation') or {}).get('ok') is not True:
            return False
# 拒绝空 IR：无 policies 视为未通过预检
        if not result.get('level1') or not (result.get('level2') or {}).get('policies'):
            return False
        key = self.key(query, config, scope)
        with self.lock:
# 深拷贝入缓存：隔离后续对结果的修改
            self.entries[key] = (self.clock(), copy.deepcopy(result))
            self.entries.move_to_end(key)
# 超容量：淘汰最旧（LRU）
            while len(self.entries) > self.capacity:
# LRU 淘汰最旧条目
                self.entries.popitem(last=False)
        return True

# 读取：TTL 内命中并回填预检来源元信息
    def get(self, query, config, scope):
        key = self.key(query, config, scope)
        with self.lock:
# 未命中返回 None
            entry = self.entries.get(key)
            if entry is None:
                return None
            created, value = entry
# 条目年龄（单调钟）
            age = self.clock() - created
# 过期：删除并视为未命中
            if age > self.ttl:
# 过期条目移除
                self.entries.pop(key, None)
                return None
            self.entries.move_to_end(key)
# 深拷贝出缓存：调用方修改不影响缓存
            result = copy.deepcopy(value)
# 回填执行预检元信息（来源/年龄/TTL）
        result.setdefault('meta', {})['execution_preflight_cache'] = {
            'source': '/api/translator/test', 'age_seconds': round(age, 3),
            'ttl_seconds': self.ttl, 'scope_verified': True,
        }
        return result


# 全局单例
PREPARED = PreparedTranslations()


# 计算「生效范围」指纹：策略库文件集 + 两级提示词 + 注册表状态
def current_scope():
    import db
    from . import core
# 注册表目录全文件集合
    files = set(Path(core.REGISTRY_DIR).rglob('*'))
# 引导文档注册表并入指纹（文档变更即失效）
    advice_registry = core._load_advice_registry()
# 逐条目把引导文档并入文件集合
    for entry in advice_registry:
        if isinstance(entry, dict) and entry.get('path'):
            files.add(core._resolve_advice_path(entry['path']))
# 文件版本：路径 + mtime(ns) + 大小
    versions = []
# 排序保证指纹稳定
    for path in sorted(files):
        if not path.is_file():
            continue
# 取 mtime/size 作为文件版本
        stat = path.stat()
# 版本三元组：路径/mtime(ns)/大小
        versions.append((str(path), stat.st_mtime_ns, stat.st_size))
# 生效范围快照：策略/路径/场景/工具/提示词/格式/引导注册表/文件版本
    return {'policy': db.get_config('ir_translator.current_policy'),
            'registry_path': str(core.REGISTRY_DIR),
            'scenes': core.SCENE_REGISTRY, 'tools': core.TOOL_REGISTRY,
            'prompt_level1': db.get_config('ir_translator.prompt_level1'),
            'prompt_level2': db.get_config('ir_translator.prompt_level2'),
            'registry_prompt_format': db.get_config('ir_translator.registry_prompt_format'),
            'advice_registry': advice_registry,
            'files': versions}


# 准备：写入前校验 scope 未漂移（并发变更拒绝）
def prepare(query, config, result, expected_scope=None):
    scope = current_scope()
# scope 不一致：策略库在预检后变更，拒绝缓存
    if expected_scope is not None and PREPARED.key(query, config, scope) != PREPARED.key(query, config, expected_scope):
        return False
    return PREPARED.put(query, config, scope, result)


# 消费：按当前生效范围读取一次，命中即视为同 scope
def consume(query, config):
# 读取入口（执行前调用）
    return PREPARED.get(query, config, current_scope())
