<template>
  <div class="logs-tab">
    <!-- Filter Bar -->
    <div class="filter-bar">
      <t-input v-model="filters.query" placeholder="搜索 user_query" clearable size="small" style="width: 200px;" />
      <t-input v-model="filters.round_id" placeholder="搜索 round_id" clearable size="small" style="width: 160px;" />
      <t-date-range-picker v-model="filters.dateRange" enable-time-picker size="small" style="width: 320px;" />
      <t-button theme="primary" size="small" @click="fetchRounds" :loading="loading">查询</t-button>
      <t-button size="small" variant="outline" @click="resetFilters">重置</t-button>
      <div class="filter-right">
        <span class="status-dot" :class="connected ? 'online' : 'offline'" />
        <span class="status-text">{{ connected ? '实时接收中' : '等待连接' }}</span>
        <span class="total-text">共 {{ total }} 条</span>
      </div>
    </div>

    <!-- Empty -->
    <div v-if="!loading && rounds.length === 0" class="empty-state">
      <t-icon name="time" size="56px" style="color: #ccc;" />
      <p>暂无数据</p>
    </div>

    <!-- Cards -->
    <transition-group name="card-slide" tag="div" class="rounds-list">
      <div v-for="r in rounds" :key="r.round_id" class="round-card" :class="{ abnormal: (r.overall_score ?? -1) <= 0.5 && (r.overall_score ?? -1) >= 0, pending: (r.overall_score ?? -1) < 0 }">
        <div class="card-header" @click="toggleExpand(r.round_id)">
          <div class="score-badge" :class="(r.overall_score ?? -1) < 0 ? 'pending' : (r.overall_score ?? 0) > 0.5 ? 'pass' : 'fail'">
            {{ (r.overall_score ?? -1) < 0 ? '...' : ((r.overall_score ?? 0) * 100).toFixed(0) }}
          </div>
          <div class="card-info">
            <div class="query-text">{{ r.user_query || '(无查询)' }}</div>
            <div class="card-meta">
              <t-tag size="small" variant="outline">{{ r.round_id }}</t-tag>
              <span class="meta-time">{{ fmtTime(r.time_start) }} → {{ fmtTime(r.time_end) }}</span>
            </div>
          </div>
          <t-tag :theme="(r.overall_score ?? -1) < 0 ? 'primary' : (r.overall_score ?? 0) > 0.5 ? 'success' : 'danger'" variant="light" size="medium">
            {{ (r.overall_score ?? -1) < 0 ? '检测中' : (r.overall_score ?? 0) > 0.5 ? '合规' : '异常' }}
          </t-tag>
        </div>

        <div v-if="expandedId === r.round_id" class="card-expand">
          <details class="group-box access-group" open>
            <summary class="group-title"><t-icon name="play-circle" size="18px" /><span>Access · 行为轨迹</span></summary>
            <div class="group-blocks">
              <div class="sub-block">
                <div class="sub-block-header user">用户态行为</div>
                <div v-if="parseJSON(r.action_json).length" class="action-cards">
                  <div v-for="(act, i) in parseJSON(r.action_json)" :key="i" class="action-chip">
                    <div class="action-tool"><span class="tool-field">工具：</span><t-tag theme="warning" variant="light" size="small">{{ act.tool }}</t-tag></div>
                    <div v-if="act.arguments" class="action-detail"><span class="tool-field">参数：</span><code>{{ JSON.stringify(act.arguments) }}</code></div>
                    <div v-if="act.resources && act.resources.length" class="action-detail"><span class="tool-field">资源：</span><span v-for="(res, j) in act.resources" :key="j" class="resource-tag">{{ res.path }} ({{ res.access }})</span></div>
                  </div>
                </div>
                <div v-else class="integrating-hint">（本轮无行为记录）</div>
              </div>
              <div class="sub-block">
                <div class="sub-block-header kernel">内核态轨迹</div>
                <div class="kernel-sections">
                  <!-- 系统调用序列 -->
                  <div class="kernel-item" v-if="r.kernel_syscall_seq">
                    <div class="kernel-item-header">
                      <span class="kernel-item-label">系统调用序列</span>
                      <span class="kernel-item-path">{{ r.kernel_syscall_seq }}</span>
                      <t-button size="small" variant="text" theme="primary" @click="currentSyscallSeqPath = r.kernel_syscall_seq; syscallSeqVisible = true">
                        <t-icon name="browse" size="14px" />
                        查看详情
                      </t-button>
                    </div>
                  </div>
                  
                  <!-- LSM Hook结果 -->
                  <div class="kernel-item" v-if="r.kernel_lsm_hook_result">
                    <div class="kernel-item-header">
                      <span class="kernel-item-label">LSM Hook结果</span>
                      <span class="kernel-item-path">{{ r.kernel_lsm_hook_result }}</span>
                      <t-button size="small" variant="text" theme="primary" @click="currentLsmHookPath = r.kernel_lsm_hook_result; lsmHookVisible = true">
                        <t-icon name="browse" size="14px" />
                        查看详情
                      </t-button>
                    </div>
                  </div>
                  
                  <!-- 资源事实 -->
                  <div class="kernel-item" v-if="r.kernel_resource_facts">
                    <div class="kernel-item-header resource-facts">
                      <span class="kernel-item-label">资源事实</span>
                      <t-button size="small" variant="text" theme="primary" @click="openResourceFactsDialog(r.kernel_resource_facts)">
                        <t-icon name="browse" size="14px" />
                        查看详情
                      </t-button>
                    </div>
                    <div class="kernel-item-preview" v-if="getKernelPreview(r.kernel_resource_facts)">
                      {{ getKernelPreview(r.kernel_resource_facts) }}
                    </div>
                  </div>
                  
                  <!-- 无数据提示 -->
                  <div v-if="!r.kernel_syscall_seq && !r.kernel_lsm_hook_result && !r.kernel_resource_facts" class="integrating-hint">（本轮无行为记录）</div>
                </div>
              </div>
            </div>
          </details>

          <details class="group-box view-group" open>
            <summary class="group-title"><t-icon name="file-paste" size="18px" /><span>View · 意图 - IR 策略</span></summary>
            <div class="group-blocks">
              <div v-if="r.ir_json === '__loading__'" class="integrating-hint"><t-loading size="small" /> IR 翻译中...</div>
              <div v-else-if="getIRPolicies(r.ir_json).length" class="ir-policies">
                <div v-for="(policy, i) in getIRPolicies(r.ir_json)" :key="i" class="sub-block">
                  <div class="sub-block-header user">{{ policy.subject || 'policy ' + i }}</div>
                  <div class="ir-objects-list">
                    <div v-for="(obj, j) in (policy.objects || [])" :key="j" class="ir-obj-row">
                      <t-tag :theme="obj.type === 'tool' ? 'primary' : 'success'" variant="light" size="small">{{ obj.type }}</t-tag>
                      <span class="ir-ident">{{ obj.identifier }}</span>
                      <span v-if="obj.actions" class="ir-act">[{{ obj.actions.join(', ') }}]</span>
                      <div v-if="obj.params && obj.params.length" class="ir-params">
                        <span v-for="(p, k) in obj.params" :key="k" class="ir-param-chip">{{ p.name }}={{ p.identifier }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else class="integrating-hint">（无 IR 策略数据）</div>
            </div>
          </details>

          <details class="group-box compliance-group" open>
            <summary class="group-title"><t-icon name="check-circle" size="18px" /><span>Compliance · 合规判定</span></summary>
            <div class="group-blocks">
              <div class="sub-block">
                <div class="sub-block-header user">用户态意图行为一致性检测</div>
                <div v-if="r.judge_result" class="judge-box">{{ r.judge_result }}</div>
                <div v-else class="judge-box empty">（无检测数据）</div>
              </div>
              <div class="sub-block">
                <div class="sub-block-header kernel">内核态行为意图一致性检测</div>
                <div v-if="r.judge_result_kernel" class="kernel-item">
                  <div class="kernel-item-header kernel-judge">
                    <span class="kernel-item-label">判断结果文档</span>
                    <t-button size="small" variant="text" theme="primary" @click="openKernelJudgeDialog(r.judge_result_kernel)">
                      <t-icon name="browse" size="14px" />
                      查看详情
                    </t-button>
                  </div>
                  <div class="kernel-item-preview" v-if="getKernelJudgePreview(r.judge_result_kernel)">
                    {{ getKernelJudgePreview(r.judge_result_kernel) }}
                  </div>
                </div>
                <div v-else class="integrating-hint">（本轮无行为记录）</div>
              </div>
              <div class="sub-block">
                <div class="sub-block-header ai">多维行为轨迹综合研判（大模型）</div>
                <div class="integrating-hint">正在集成中...</div>
              </div>
            </div>
          </details>
        </div>
      </div>
    </transition-group>

    <!-- 内核态详情弹窗组件 -->
    <SyscallSeqDialog v-model="syscallSeqVisible" :file-path="currentSyscallSeqPath" />
    <LsmHookDialog v-model="lsmHookVisible" :file-path="currentLsmHookPath" />
    <ResourceFactsDialog v-model="resourceFactsVisible" :content="currentResourceFacts" />
    <MarkdownDialog v-model="kernelJudgeVisible" :file-path="currentKernelJudgePath" />

    <!-- Pagination -->
    <div class="pagination-bar" v-if="total > 0">
      <t-pagination v-model:current="currentPage" v-model:pageSize="pageSize" :total="total" :page-size-options="[10, 20, 50]" show-page-size show-jumper @current-change="fetchRounds" @page-size-change="onPageSizeChange" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue"
import socket, { connected } from "../../utils/socket.js"
import { NotifyPlugin } from "tdesign-vue-next"
import SyscallSeqDialog from "../../components/dialogs/SyscallSeqDialog.vue"
import LsmHookDialog from "../../components/dialogs/LsmHookDialog.vue"
import ResourceFactsDialog from "../../components/dialogs/ResourceFactsDialog.vue"
import MarkdownDialog from "../../components/dialogs/MarkdownDialog.vue"

const rounds = ref([])
const total = ref(0)
const loading = ref(false)
const expandedId = ref(null)
const currentPage = ref(1)
const pageSize = ref(20)
const filters = ref({ query: "", round_id: "", dateRange: [] })
let notificationInstance = null

// 内核态详情弹窗控制
const syscallSeqVisible = ref(false)
const currentSyscallSeqPath = ref('')

const lsmHookVisible = ref(false)
const currentLsmHookPath = ref('')

const resourceFactsVisible = ref(false)
const currentResourceFacts = ref('')

const kernelJudgeVisible = ref(false)
const currentKernelJudgePath = ref('')

// 打开内核态判断结果弹窗
function openKernelJudgeDialog(filePath) {
  currentKernelJudgePath.value = filePath
  kernelJudgeVisible.value = true
}

// 获取内核态判断结果预览
function getKernelJudgePreview(filePath) {
  if (!filePath) return ''
  // 显示完整路径
  return filePath
}

// 通用筛选函数
function matchesFilter(data) {
  if (!data) return false
  const { query, round_id: roundIdFilter, dateRange } = filters.value
  const matchQuery = !query || (data.user_query || '').toLowerCase().includes(query.toLowerCase())
  const matchRoundId = !roundIdFilter || data.round_id?.includes(roundIdFilter)
  const matchDateRange = !dateRange?.length || 
    (!dateRange[0] || data.time_start >= dateRange[0]) && 
    (!dateRange[1] || data.time_end <= dateRange[1])
  return matchQuery && matchRoundId && matchDateRange
}

onMounted(() => {
  fetchRounds()
  socket.on("new_round_info", (data) => {
    const idx = rounds.value.findIndex(r => r.round_id === data.round_id)
    if (idx >= 0) { rounds.value[idx] = data }
    else if (matchesFilter(data)) { rounds.value.unshift(data); total.value++ }
    
    // 有新消息且处于筛选状态时显示通知
    const { query, round_id: roundIdFilter, dateRange } = filters.value
    const hasFilter = !!(query || roundIdFilter || dateRange?.length === 2)
    if (hasFilter) {
      notificationInstance = NotifyPlugin.warning({
        title: '温馨提示',
        content: '有更新消息到达，当前处于筛选状态，建议刷新搜索条件查看最新数据',
        duration: 3000,
      })
    }
  })
})

async function fetchRounds() {
  loading.value = true
  const offset = (currentPage.value - 1) * pageSize.value
  const params = new URLSearchParams({ limit: pageSize.value, offset })
  if (filters.value.query) params.set("query", filters.value.query)
  if (filters.value.round_id) params.set("round_id", filters.value.round_id)
  if (filters.value.dateRange && filters.value.dateRange.length === 2) {
    params.set("time_from", filters.value.dateRange[0])
    params.set("time_to", filters.value.dateRange[1])
  }
  try {
    const r = await fetch("/api/rounds?" + params.toString())
    const j = await r.json()
    if (j.ok) { rounds.value = j.data; total.value = j.total }
  } catch {}
  loading.value = false
}

function resetFilters() { filters.value = { query: "", round_id: "", dateRange: [] }; currentPage.value = 1; fetchRounds() }
function onPageSizeChange() { currentPage.value = 1; fetchRounds() }
function toggleExpand(id) { expandedId.value = expandedId.value === id ? null : id }
function fmtTime(t) { if (!t) return ""; return t.replace(/\+\d{4}\s*$/, "").trim() }
function parseJSON(str) { try { return JSON.parse(str || "[]") } catch { return [] } }
function getIRPolicies(irStr) { try { const ir = JSON.parse(irStr || "{}"); const level2 = ir.level2 || ir; return level2.policies || [] } catch { return [] } }

// 内核态详情查看
function getKernelPreview(content) {
  if (!content) return ''
  // 如果是文件路径，不显示预览
  if (content.includes('/')) return ''
  // 如果内容太长，截取前100个字符
  if (content.length > 100) {
    return content.substring(0, 100) + '...'
  }
  return content
}

// 打开资源事实弹窗
function openResourceFactsDialog(content) {
  console.log('openResourceFactsDialog called, content type:', typeof content)
  console.log('openResourceFactsDialog content preview:', content?.substring(0, 300))
  currentResourceFacts.value = content || ''
  resourceFactsVisible.value = true
}
</script>

<style scoped>
.logs-tab { max-width: 1000px; margin: 0 auto; padding-top: 20px; }
.filter-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; background: #fff; border-radius: 12px; padding: 14px 18px; margin-bottom: 16px; border: 1px solid #e8ecf0; box-shadow: 0 1px 4px rgba(0,0,0,0.03); }
.filter-right { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; }
.status-dot.online { background: #00a870; box-shadow: 0 0 4px #00a870; }
.status-dot.offline { background: #ccc; }
.status-text { font-size: 12px; color: #999; }
.total-text { font-size: 12px; color: #666; font-weight: 500; }
.empty-state { text-align: center; padding: 80px 0; color: #999; }
.rounds-list { display: flex; flex-direction: column; gap: 12px; }
.round-card { background: #fff; border-radius: 14px; border: 1px solid #e8ecf0; overflow: hidden; transition: all 0.25s; box-shadow: 0 1px 4px rgba(0,0,0,0.03); }
.round-card:hover { box-shadow: 0 4px 16px rgba(0,82,217,0.08); border-color: #c8dcff; transform: translateY(-1px); }
.round-card.abnormal { border-left: 4px solid #ED7B2F; }
.round-card.pending { border-left: 4px solid #0052D9; }
.card-header { display: flex; align-items: center; gap: 16px; padding: 18px 24px; cursor: pointer; }
.score-badge { width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 700; color: #fff; flex-shrink: 0; }
.score-badge.pass { background: linear-gradient(135deg, #00c48f, #00a870); box-shadow: 0 2px 8px rgba(0,168,112,0.3); }
.score-badge.fail { background: linear-gradient(135deg, #ff9f43, #ED7B2F); box-shadow: 0 2px 8px rgba(237,123,47,0.3); }
.score-badge.pending { background: linear-gradient(135deg, #a0aec0, #718096); animation: pulse-badge 1.5s ease-in-out infinite; }
@keyframes pulse-badge { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
.card-info { flex: 1; min-width: 0; }
.query-text { font-size: 14px; font-weight: 500; color: #333; margin-bottom: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-meta { display: flex; align-items: center; gap: 8px; }
.meta-time { font-size: 12px; color: #999; }
.card-expand { padding: 16px 20px 20px; background: #fafbfc; border-top: 1px solid #f0f0f0; }
.group-box { border-radius: 12px; padding: 0; margin-bottom: 14px; overflow: hidden; border: none; }
.group-box.access-group { background: linear-gradient(135deg, #f0f5ff 0%, #fff 100%); box-shadow: 0 2px 8px rgba(0,82,217,0.06); }
.group-box.view-group { background: linear-gradient(135deg, #f0fff8 0%, #fff 100%); box-shadow: 0 2px 8px rgba(0,168,112,0.06); }
.group-box.compliance-group { background: linear-gradient(135deg, #fffbf5 0%, #fff 100%); box-shadow: 0 2px 8px rgba(237,123,47,0.06); }
.group-title { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600; padding: 14px 18px; cursor: pointer; user-select: none; list-style: none; }
.group-title::-webkit-details-marker { display: none; }
.group-title span { flex: 1; }
.group-box.access-group .group-title { color: #0052D9; }
.group-box.view-group .group-title { color: #00a870; }
.group-box.compliance-group .group-title { color: #ED7B2F; }
.group-blocks { display: flex; flex-direction: column; gap: 10px; padding: 0 18px 18px; }
.sub-block { background: rgba(255,255,255,0.7); border-radius: 8px; padding: 14px 16px; border: 1px solid rgba(0,0,0,0.04); }
.sub-block-header { font-size: 12px; font-weight: 600; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid #eee; }
.sub-block-header.user { color: #0052D9; }
.sub-block-header.kernel { color: #722ed1; }
.sub-block-header.ai { color: #ED7B2F; }
.integrating-hint { background: #f8f9fa; border: 1px dashed #ddd; border-radius: 6px; padding: 12px; font-size: 12px; color: #bbb; text-align: center; font-style: italic; }
.action-cards { display: flex; flex-direction: column; gap: 8px; }
.action-chip { background: #fafbfc; border: 1px solid #eee; border-radius: 8px; padding: 10px 14px; }
.action-tool { margin-bottom: 4px; }
.tool-field { font-size: 11px; color: #888; margin-right: 4px; }
.action-detail { margin-top: 4px; display: flex; align-items: flex-start; gap: 4px; }
.action-detail code { font-size: 11px; color: #666; word-break: break-all; }
.resource-tag { font-size: 11px; color: #0052D9; background: #f0f5ff; padding: 2px 6px; border-radius: 4px; margin-right: 4px; }
.ir-policies { display: flex; flex-direction: column; gap: 10px; }
.ir-objects-list { display: flex; flex-direction: column; gap: 6px; }
.ir-obj-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; padding: 4px 0; }
.ir-ident { font-family: "SF Mono", monospace; font-size: 12px; color: #333; font-weight: 500; }
.ir-act { font-size: 11px; color: #999; }
.ir-params { display: flex; flex-wrap: wrap; gap: 4px; margin-left: 4px; }
.ir-param-chip { font-size: 11px; background: #f0f5ff; color: #0052D9; padding: 1px 6px; border-radius: 4px; }
.judge-box { background: #f8f9fa; border-radius: 8px; padding: 14px; font-size: 12px; line-height: 1.8; color: #555; white-space: pre-wrap; font-family: "SF Mono", "Fira Code", monospace; }
.judge-box.empty { color: #ccc; font-style: italic; }
.pagination-bar { margin-top: 20px; display: flex; justify-content: center; padding-bottom: 20px; }
.card-slide-enter-active { transition: all 0.4s ease-out; }
.card-slide-enter-from { opacity: 0; transform: translateY(-16px); }

/* 内核态轨迹样式 */
.kernel-sections { display: flex; flex-direction: column; gap: 12px; }
.kernel-item { background: #f8f9fa; border-radius: 8px; padding: 12px 14px; border: 1px solid #e8ecf0; }
.kernel-item-header { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.kernel-item-label { font-size: 12px; font-weight: 600; color: #333; min-width: 100px; }
.kernel-item-path { font-size: 11px; color: #0052D9; font-family: "SF Mono", monospace; word-break: break-all; flex: 1; }
.kernel-item-preview { font-size: 11px; color: #666; margin-top: 8px; padding-top: 8px; border-top: 1px dashed #e8ecf0; max-height: 60px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }
.kernel-item.resource-facts .kernel-item-label { min-width: 80px; }

</style>
