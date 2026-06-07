<template>
  <t-dialog 
    :visible="dialogVisible" 
    header="LSM Hook 结果分析"
    width="800px" 
    :footer="false"
    @close="onClose"
    top="5vh"
  >
    <div class="lsm-dialog-content">
      <div v-if="loading" class="detail-loading">
        <t-loading size="large" />
        <p>加载中...</p>
      </div>
      <div v-else-if="error" class="detail-error">
        <t-icon name="error-circle" size="48px" />
        <p>{{ error }}</p>
      </div>
      <div v-else-if="!hookData.length" class="detail-empty">
        <t-icon name="folder-open" size="48px" />
        <p>无 LSM Hook 数据</p>
      </div>
      <div v-else class="lsm-analysis">
        <!-- 统计概览 -->
        <div class="stats-overview">
          <div class="stat-card primary">
            <div class="stat-value">{{ hookData.length }}</div>
            <div class="stat-label">总 Hook 次数</div>
          </div>
          <div class="stat-card success">
            <div class="stat-value">{{ allowCount }}</div>
            <div class="stat-label">允许 (Allow)</div>
          </div>
          <div class="stat-card danger">
            <div class="stat-value">{{ denyCount }}</div>
            <div class="stat-label">拒绝 (Deny)</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ uniqueHookTypes.length }}</div>
            <div class="stat-label">Hook 类型数</div>
          </div>
        </div>

        <!-- Hook 结果分布 -->
        <div class="section-block">
          <div class="section-header" @click="toggleSection('resultDist')">
            <t-icon :name="expandedSections.resultDist ? 'chevron-down' : 'chevron-right'" size="16px" />
            <span>Hook 结果分布</span>
          </div>
          <div v-show="expandedSections.resultDist" class="section-content">
            <div class="result-distribution">
              <div class="result-item allow">
                <div class="result-label">允许 (Allow)</div>
                <div class="result-bar">
                  <div class="result-fill" :style="{ width: allowPercentage + '%' }"></div>
                </div>
                <div class="result-count">{{ allowCount }}</div>
              </div>
              <div class="result-item deny">
                <div class="result-label">拒绝 (Deny)</div>
                <div class="result-bar">
                  <div class="result-fill" :style="{ width: denyPercentage + '%' }"></div>
                </div>
                <div class="result-count">{{ denyCount }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Hook 类型分布 -->
        <div class="section-block">
          <div class="section-header" @click="toggleSection('hookTypeDist')">
            <t-icon :name="expandedSections.hookTypeDist ? 'chevron-down' : 'chevron-right'" size="16px" />
            <span>Hook 类型分布</span>
          </div>
          <div v-show="expandedSections.hookTypeDist" class="section-content">
            <div class="hook-type-distribution">
              <div v-for="item in hookTypeDistribution" :key="item.name" class="dist-item">
                <div class="dist-info">
                  <span class="dist-name">{{ item.name }}</span>
                  <span class="dist-count">{{ item.count }}次</span>
                </div>
                <div class="dist-bar">
                  <div class="dist-fill" :style="{ width: (item.count / maxHookTypeCount * 100) + '%' }"></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 文件访问分析 -->
        <div class="section-block">
          <div class="section-header" @click="toggleSection('fileAccess')">
            <t-icon :name="expandedSections.fileAccess ? 'chevron-down' : 'chevron-right'" size="16px" />
            <span>文件访问路径 (Top 15)</span>
            <t-tag size="small" variant="light">{{ uniquePaths.length }} 个不同路径</t-tag>
          </div>
          <div v-show="expandedSections.fileAccess" class="section-content">
            <div class="path-list">
              <div v-for="item in pathDistribution" :key="item.path" class="path-item">
                <t-tag theme="primary" variant="light" size="small">{{ item.count }}次</t-tag>
                <span class="path-text" :title="item.path">{{ item.path }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 进程活动 -->
        <div class="section-block">
          <div class="section-header" @click="toggleSection('processActivity')">
            <t-icon :name="expandedSections.processActivity ? 'chevron-down' : 'chevron-right'" size="16px" />
            <span>进程活动分析</span>
          </div>
          <div v-show="expandedSections.processActivity" class="section-content">
            <div class="process-list">
              <div v-for="item in processActivity" :key="item.pid" class="process-item">
                <div class="process-info">
                  <span class="pid-badge">PID: {{ item.pid }}</span>
                  <span class="hook-badge">{{ item.count }} 次 Hook</span>
                </div>
                <div class="process-hooks">
                  <t-tag v-for="ht in item.hookTypes.slice(0, 5)" :key="ht" size="small" variant="outline">{{ ht }}</t-tag>
                  <t-tag v-if="item.hookTypes.length > 5" size="small" variant="light">+{{ item.hookTypes.length - 5 }}</t-tag>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 详细 Hook 列表 -->
        <div class="section-block">
          <div class="section-header" @click="toggleSection('detailedHooks')">
            <t-icon :name="expandedSections.detailedHooks ? 'chevron-down' : 'chevron-right'" size="16px" />
            <span>详细 Hook 列表</span>
            <t-tag size="small" variant="light">{{ hookData.length }} 条</t-tag>
          </div>
          <div v-show="expandedSections.detailedHooks" class="section-content">
            <div class="hooks-table-wrapper">
              <table class="hooks-table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>Hook 类型</th>
                    <th>结果</th>
                    <th>PID/TID</th>
                    <th>目标路径</th>
                    <th>返回值</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(hook, index) in pagedHooks" :key="index" :class="{ 'deny-row': getHookResult(hook) === 'deny' }">
                    <td class="time-cell">{{ formatTime(hook.timestamp_mono_ns) }}</td>
                    <td class="hook-type-cell">
                      <span class="hook-type-name">{{ getHookName(hook) }}</span>
                    </td>
                    <td class="result-cell">
                      <t-tag :theme="getHookResult(hook) === 'allow' ? 'success' : 'danger'" size="small">
                        {{ getHookResult(hook) }}
                      </t-tag>
                    </td>
                    <td class="pid-cell">{{ hook.pid }}/{{ hook.tid }}</td>
                    <td class="path-cell" :title="getHookPath(hook)">{{ getHookPath(hook) }}</td>
                    <td class="return-cell">{{ hook.return_value }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="pagination-mini" v-if="totalPages > 1">
              <t-button size="small" variant="text" @click="currentPage--" :disabled="currentPage === 1">上一页</t-button>
              <span>{{ currentPage }} / {{ totalPages }}</span>
              <t-button size="small" variant="text" @click="currentPage++" :disabled="currentPage === totalPages">下一页</t-button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </t-dialog>
</template>

<script setup>
import { ref, watch, computed } from "vue"

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false
  },
  filePath: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['update:modelValue'])

// 使用 ref 和 watch 实现双向绑定
const dialogVisible = ref(false)

// 同步父组件的值
watch(() => props.modelValue, (val) => {
  dialogVisible.value = val
  if (val) {
    loadContent()
  }
})

// 通知父组件关闭
function onClose() {
  emit('update:modelValue', false)
}

const loading = ref(false)
const error = ref('')
const content = ref('')
const hookData = ref([])

// 展开/折叠状态
const expandedSections = ref({
  resultDist: true,
  hookTypeDist: true,
  fileAccess: true,
  processActivity: false,
  detailedHooks: false
})

const currentPage = ref(1)
const PAGE_SIZE = 20

async function loadContent() {
  if (!props.filePath) return
  
  loading.value = true
  error.value = ''
  
  try {
    const response = await fetch(`/api/kernel/file?path=${encodeURIComponent(props.filePath)}`)
    if (response.ok) {
      const data = await response.json()
      if (data.ok) {
        content.value = data.data
        parseHookData()
      } else {
        throw new Error(data.error || '无法读取文件内容')
      }
    } else {
      throw new Error('无法读取文件内容')
    }
  } catch (err) {
    error.value = err.message || '加载失败'
    content.value = ''
  } finally {
    loading.value = false
  }
}

function parseHookData() {
  if (!content.value) {
    hookData.value = []
    return
  }
  
  const lines = content.value.trim().split('\n')
  hookData.value = lines.map(line => {
    try {
      return JSON.parse(line)
    } catch {
      return null
    }
  }).filter(Boolean)
  
  currentPage.value = 1
}

function toggleSection(section) {
  expandedSections.value[section] = !expandedSections.value[section]
}

// 统计计算
const allowCount = computed(() => hookData.value.filter(h => getHookResult(h) === 'allow').length)
const denyCount = computed(() => hookData.value.filter(h => getHookResult(h) === 'deny').length)
const allowPercentage = computed(() => hookData.value.length ? (allowCount.value / hookData.value.length * 100) : 0)
const denyPercentage = computed(() => hookData.value.length ? (denyCount.value / hookData.value.length * 100) : 0)

const uniqueHookTypes = computed(() => {
  const set = new Set(hookData.value.map(h => getHookName(h)))
  return Array.from(set)
})

const hookTypeDistribution = computed(() => {
  const counts = {}
  hookData.value.forEach(h => {
    const name = getHookName(h)
    counts[name] = (counts[name] || 0) + 1
  })
  return Object.entries(counts)
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count)
})

const maxHookTypeCount = computed(() => {
  if (hookTypeDistribution.value.length === 0) return 1
  return hookTypeDistribution.value[0].count
})

const uniquePaths = computed(() => {
  const set = new Set()
  hookData.value.forEach(h => {
    const path = getHookPath(h)
    if (path) set.add(path)
  })
  return Array.from(set)
})

const pathDistribution = computed(() => {
  const counts = {}
  hookData.value.forEach(h => {
    const path = getHookPath(h)
    if (path) {
      counts[path] = (counts[path] || 0) + 1
    }
  })
  return Object.entries(counts)
    .map(([path, count]) => ({ path, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 15)
})

const processActivity = computed(() => {
  const pids = {}
  hookData.value.forEach(h => {
    const pid = h.pid || 0
    const hookName = getHookName(h)
    if (!pids[pid]) {
      pids[pid] = { pid, count: 0, hookTypes: new Set() }
    }
    pids[pid].count++
    pids[pid].hookTypes.add(hookName)
  })
  return Object.values(pids)
    .map(p => ({
      pid: p.pid,
      count: p.count,
      hookTypes: Array.from(p.hookTypes).sort()
    }))
    .sort((a, b) => b.count - a.count)
})

const totalPages = computed(() => Math.ceil(hookData.value.length / PAGE_SIZE))

const pagedHooks = computed(() => {
  const start = (currentPage.value - 1) * PAGE_SIZE
  return hookData.value.slice(start, start + PAGE_SIZE)
})

// 兼容两种格式的辅助函数
function getHookName(h) {
  // 新格式: hook_name, 旧格式: hook_name (相同)
  return h.hook_name || 'unknown'
}

function getHookResult(h) {
  // 新格式: result, 旧格式: hook_result
  return h.result || h.hook_result || 'unknown'
}

function getHookPath(h) {
  // 新格式: path 在顶层, 旧格式: path 在 target.path
  if (h.path) return h.path
  if (h.target && h.target.path) return h.target.path
  return ''
}

function getRelatedEventId(h) {
  // 新格式: related_event_id, 旧格式: related_syscall_event_id
  return h.related_event_id || h.related_syscall_event_id || ''
}

function formatTime(timestampNs) {
  if (!timestampNs) return ''
  const ns = String(timestampNs)
  if (ns.length >= 10) {
    return ns.slice(-9)
  }
  return ns
}

// 分页切换
watch(currentPage, (val) => {
  if (val < 1) currentPage.value = 1
  if (val > totalPages.value) currentPage.value = totalPages.value
})
</script>

<style scoped>
.lsm-dialog-content {
  min-height: 300px;
  max-height: 700px;
  overflow-y: auto;
}

.detail-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.detail-loading p {
  margin-top: 16px;
  color: #999;
  font-size: 14px;
}

.detail-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.detail-error p {
  margin-top: 16px;
  color: #e34d59;
  font-size: 14px;
}

.detail-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.detail-empty p {
  margin-top: 16px;
  color: #999;
  font-size: 14px;
}

/* 统计概览 */
.stats-overview {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.stat-card {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 8px;
  padding: 16px;
  text-align: center;
  color: white;
}

.stat-card.primary {
  background: linear-gradient(135deg, #0052d9 0%, #0066ff 100%);
}

.stat-card.success {
  background: linear-gradient(135deg, #00a870 0%, #00c48f 100%);
}

.stat-card.danger {
  background: linear-gradient(135deg, #e34d59 0%, #ed7b2f 100%);
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.2;
}

.stat-label {
  font-size: 12px;
  opacity: 0.9;
  margin-top: 4px;
}

/* 区块样式 */
.section-block {
  background: #f8f9fa;
  border-radius: 8px;
  margin-bottom: 12px;
  border: 1px solid #e8ecf0;
  overflow: hidden;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: #fff;
  cursor: pointer;
  user-select: none;
  font-weight: 500;
  font-size: 13px;
  color: #333;
}

.section-header:hover {
  background: #f5f7fa;
}

.section-content {
  padding: 12px 16px;
}

/* 结果分布 */
.result-distribution {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.result-item {
  display: flex;
  align-items: center;
  gap: 12px;
}

.result-label {
  min-width: 100px;
  font-size: 13px;
  font-weight: 500;
}

.result-item.allow .result-label {
  color: #00a870;
}

.result-item.deny .result-label {
  color: #e34d59;
}

.result-bar {
  flex: 1;
  height: 8px;
  background: #e8ecf0;
  border-radius: 4px;
  overflow: hidden;
}

.result-item.allow .result-fill {
  height: 100%;
  background: linear-gradient(90deg, #00a870, #00c48f);
  border-radius: 4px;
}

.result-item.deny .result-fill {
  height: 100%;
  background: linear-gradient(90deg, #e34d59, #ed7b2f);
  border-radius: 4px;
}

.result-count {
  min-width: 40px;
  text-align: right;
  font-weight: 600;
  font-size: 13px;
}

.result-item.allow .result-count {
  color: #00a870;
}

.result-item.deny .result-count {
  color: #e34d59;
}

/* Hook 类型分布 */
.hook-type-distribution {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dist-item {
  display: flex;
  align-items: center;
  gap: 12px;
}

.dist-info {
  display: flex;
  flex-direction: column;
  min-width: 140px;
}

.dist-name {
  font-size: 12px;
  color: #333;
  font-family: "SF Mono", monospace;
}

.dist-count {
  font-size: 11px;
  color: #666;
}

.dist-bar {
  flex: 1;
  height: 6px;
  background: #e8ecf0;
  border-radius: 3px;
  overflow: hidden;
}

.dist-fill {
  height: 100%;
  background: linear-gradient(90deg, #ed7b2f, #f5a623);
  border-radius: 3px;
}

/* 文件路径列表 */
.path-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 200px;
  overflow-y: auto;
}

.path-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  background: #fff;
  border-radius: 4px;
  font-size: 12px;
}

.path-text {
  flex: 1;
  color: #666;
  font-family: "SF Mono", monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 进程活动 */
.process-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 250px;
  overflow-y: auto;
}

.process-item {
  background: #fff;
  border-radius: 6px;
  padding: 10px 12px;
}

.process-info {
  display: flex;
  gap: 12px;
  margin-bottom: 6px;
}

.pid-badge {
  font-weight: 600;
  color: #0052d9;
  font-size: 12px;
}

.hook-badge {
  color: #666;
  font-size: 12px;
}

.process-hooks {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

/* 详细 Hook 列表 */
.hooks-table-wrapper {
  max-height: 300px;
  overflow-y: auto;
  border: 1px solid #e8ecf0;
  border-radius: 6px;
}

.hooks-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.hooks-table thead {
  position: sticky;
  top: 0;
  background: #f0f2f5;
  z-index: 1;
}

.hooks-table th {
  padding: 8px 10px;
  text-align: left;
  font-weight: 600;
  color: #666;
  border-bottom: 1px solid #e8ecf0;
  font-size: 11px;
  text-transform: uppercase;
}

.hooks-table td {
  padding: 6px 10px;
  border-bottom: 1px solid #f0f0f0;
}

.hooks-table tbody tr:hover {
  background: #f8f9fa;
}

.hooks-table tbody tr.deny-row {
  background: #fff0f0;
}

.hooks-table tbody tr.deny-row:hover {
  background: #ffe0e0;
}

.time-cell {
  font-family: "SF Mono", monospace;
  color: #999;
}

.hook-type-cell {
  font-family: "SF Mono", monospace;
  font-weight: 500;
}

.hook-type-name {
  color: #ed7b2f;
}

.pid-cell {
  font-family: "SF Mono", monospace;
  color: #666;
}

.path-cell {
  color: #333;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
  font-family: "SF Mono", monospace;
  font-size: 11px;
}

.return-cell {
  font-family: "SF Mono", monospace;
  color: #666;
}

.result-cell {
  text-align: center;
}

/* 分页 */
.pagination-mini {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-top: 12px;
  font-size: 12px;
  color: #666;
}

/* 响应式 */
@media (max-width: 768px) {
  .stats-overview {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .hooks-table {
    font-size: 11px;
  }
  
  .path-cell {
    max-width: 100px;
  }
}
</style>
