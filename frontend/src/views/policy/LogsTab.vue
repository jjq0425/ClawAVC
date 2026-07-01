<template>
  <div class="logs-tab">
    <div class="log-card">
      <div class="card-title">翻译日志 <t-button size="small" variant="outline" @click="loadLogs">刷新</t-button></div>
      <div class="log-filters">
        <t-select v-model="filter.type" size="small" style="width: 120px;" @change="loadLogs" clearable placeholder="类型">
          <t-option value="ui" label="UI 测试" />
          <t-option value="live" label="线上" />
        </t-select>
        <t-input v-model="filter.roundId" size="small" style="width: 150px;" placeholder="round_id" clearable @clear="loadLogs" @enter="loadLogs" />
        <t-input v-model="filter.scene" size="small" style="width: 150px;" placeholder="场景标签" clearable @clear="loadLogs" @enter="loadLogs" />
      </div>
      <div v-if="filtered.length === 0" class="empty-hint">暂无翻译记录</div>
      <div v-else class="log-list">
        <div v-for="log in filtered" :key="log.id" class="log-item" @click="openDetail(log)">
          <div class="log-header">
            <t-tag v-if="log.is_ui_test" theme="primary" variant="light" size="small">测试</t-tag>
            <t-tag v-else theme="success" variant="light" size="small">线上</t-tag>
            <t-tag v-if="isComplete(log)" theme="success" variant="light" size="small">完整</t-tag>
            <t-tag v-else theme="warning" variant="light" size="small">进行中</t-tag>
            <span class="log-query">{{ log.query }}</span>
            <span class="log-time">{{ log.created_at }}</span>
            <t-tag v-if="log.round_id" size="small" variant="outline">{{ log.round_id }}</t-tag>
          </div>
          <div class="log-body">
            <t-tag v-for="s in parseScenes(log.level1_json)" :key="s" size="small" theme="primary" variant="outline" style="margin-right:4px;">{{ s }}</t-tag>
            <span v-if="!parseScenes(log.level1_json).length" style="color:#ccc;">(无场景)</span>
          </div>
        </div>
      </div>
    </div>
    <t-drawer v-model:visible="drawerVisible" header="翻译详情" size="560px" :footer="false">
      <div v-if="detail" class="log-detail">
        <div class="d-field"><div class="d-label">查询</div><div class="d-value">{{ detail.query }}</div></div>
        <div class="d-field"><div class="d-label">时间</div><div class="d-value">{{ detail.created_at }}</div></div>
        <div class="d-field" v-if="detail.round_id"><div class="d-label">Round ID</div><div class="d-value">{{ detail.round_id }}</div></div>
        <div class="d-field"><div class="d-label">Level-1 场景</div><div class="d-value"><t-tag v-for="s in parseScenes(detail.level1_json)" :key="s" theme="primary" variant="light" style="margin-right:4px;">{{ s }}</t-tag></div></div>
        <div class="d-field"><div class="d-label">Level-2 IR</div><pre class="d-json">{{ fmtJson(detail.level2_json) }}</pre></div>
        <div class="d-field"><div class="d-label">校验结果</div><pre class="d-json small">{{ fmtJson(detail.validation_json) }}</pre></div>
        <div class="d-field"><div class="d-label">调用元信息</div><pre class="d-json small">{{ fmtJson(detail.meta_json) }}</pre></div>
      </div>
    </t-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
const logs = ref([])
const filter = ref({ type: "", roundId: "", scene: "" })
const drawerVisible = ref(false)
const detail = ref(null)

const filtered = computed(() => logs.value.filter(l => {
  if (filter.value.type === "ui" && !l.is_ui_test) return false
  if (filter.value.type === "live" && l.is_ui_test) return false
  if (filter.value.roundId && !(l.round_id || "").includes(filter.value.roundId)) return false
  if (filter.value.scene) { const ss = parseScenes(l.level1_json); if (!ss.some(s => s.includes(filter.value.scene))) return false }
  return true
}))

function parseScenes(j) { try { return JSON.parse(j || "[]") } catch { return [] } }
function fmtJson(j) { try { return JSON.stringify(JSON.parse(j || "{}"), null, 2) } catch { return j || "" } }
function openDetail(log) { detail.value = log; drawerVisible.value = true }
function isComplete(log) {
  // level1 为空算完整（可能是空场景）
  // level2 非空才算完整
  const level1 = parseScenes(log.level1_json)
  const level2 = fmtJson(log.level2_json)
  const level2Obj = log.level2_json ? (typeof log.level2_json === 'string' ? JSON.parse(log.level2_json) : log.level2_json) : null
  // level1 为空（无场景）或有场景时，level2 有内容则算完整
  return (level1.length === 0 || level1.length > 0) && level2Obj && Object.keys(level2Obj).length > 0 && level2Obj.policies && level2Obj.policies.length > 0
}
async function loadLogs() { try { const r = await fetch("/api/translator/logs?limit=100"); const j = await r.json(); if (j.ok) logs.value = j.data } catch {} }
onMounted(loadLogs)
</script>

<style scoped>
.log-card { background: #fff; border-radius: 12px; padding: 24px; border: 1px solid #eee; }
.card-title { font-size: 15px; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
.log-filters { display: flex; gap: 8px; margin-bottom: 12px; }
.empty-hint { font-size: 13px; color: #ccc; text-align: center; padding: 24px; }
.log-list { display: flex; flex-direction: column; gap: 8px; max-height: 500px; overflow-y: auto; }
.log-item { padding: 10px 14px; background: #f9fafb; border-radius: 8px; border: 1px solid #eee; cursor: pointer; transition: border-color 0.2s; }
.log-item:hover { border-color: #0052D9; }
.log-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.log-query { font-size: 13px; font-weight: 500; color: #333; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.log-time { font-size: 11px; color: #999; }
.log-body { font-size: 12px; }
.d-field { margin-bottom: 14px; padding-bottom: 12px; border-bottom: 1px solid #f3f3f3; }
.d-label { font-size: 12px; font-weight: 600; color: #0052D9; margin-bottom: 6px; text-transform: uppercase; }
.d-value { font-size: 13px; color: #333; }
.d-json { background: #f8f9fa; border-radius: 6px; padding: 12px; font-size: 11px; line-height: 1.6; overflow-x: auto; max-height: 300px; white-space: pre-wrap; word-break: break-all; font-family: "SF Mono", monospace; margin: 0; }
.d-json.small { max-height: 150px; font-size: 10px; }
</style>
