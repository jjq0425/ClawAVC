<template>
  <t-dialog 
    :visible="dialogVisible" 
    header="系统调用序列分析"
    width="800px" 
    :footer="false"
    @close="onClose"
  >
    <div class="syscall-dialog-content">
      <div v-if="loading" class="detail-loading">
        <t-loading size="large" />
        <p>加载中...</p>
      </div>
      <div v-else-if="error" class="detail-error">
        <t-icon name="error-circle" size="48px" />
        <p>{{ error }}</p>
      </div>
      <div v-else-if="!syscallData.length" class="detail-empty">
        <t-icon name="folder-open" size="48px" />
        <p>无系统调用数据</p>
      </div>
      <div v-else class="syscall-analysis">
        <!-- 统计概览 -->
        <div class="stats-overview">
          <div class="stat-card">
            <div class="stat-value">{{ syscallData.length }}</div>
            <div class="stat-label">总调用次数</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ uniqueSyscalls.length }}</div>
            <div class="stat-label">系统调用种类</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ uniquePids.length }}</div>
            <div class="stat-label">涉及进程数</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ failedCalls }}</div>
            <div class="stat-label">失败调用</div>
          </div>
        </div>

        <!-- 系统调用分布 -->
        <div class="section-block">
          <div class="section-header" @click="toggleSection('syscallDist')">
            <t-icon :name="expandedSections.syscallDist ? 'chevron-down' : 'chevron-right'" size="16px" />
            <span>系统调用分布 (Top 10)</span>
          </div>
          <div v-show="expandedSections.syscallDist" class="section-content">
            <div class="syscall-distribution">
              <div v-for="item in syscallDistribution" :key="item.name" class="dist-item">
                <div class="dist-info">
                  <span class="dist-name">{{ item.name }}</span>
                  <span class="dist-count">{{ item.count }}次</span>
                </div>
                <div class="dist-bar">
                  <div class="dist-fill" :style="{ width: (item.count / maxSyscallCount * 100) + '%' }"></div>
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
                  <span class="syscall-badge">{{ item.count }} 次调用</span>
                </div>
                <div class="process-syscalls">
                  <t-tag v-for="sc in item.syscalls.slice(0, 5)" :key="sc" size="small" variant="outline">{{ sc }}</t-tag>
                  <t-tag v-if="item.syscalls.length > 5" size="small" variant="light">+{{ item.syscalls.length - 5 }}</t-tag>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 详细调用列表 -->
        <div class="section-block">
          <div class="section-header" @click="toggleSection('detailedCalls')">
            <t-icon :name="expandedSections.detailedCalls ? 'chevron-down' : 'chevron-right'" size="16px" />
            <span>详细调用列表</span>
            <t-tag size="small" variant="light">{{ syscallData.length }} 条</t-tag>
          </div>
          <div v-show="expandedSections.detailedCalls" class="section-content">
            <div class="calls-table-wrapper">
              <table class="calls-table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>系统调用</th>
                    <th>PID/TID</th>
                    <th>路径/参数</th>
                    <th>返回值</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(call, index) in pagedCalls" :key="index" :class="{ 'failed-row': call.return_value < 0 }">
                    <td class="time-cell">{{ formatTime(call.timestamp_mono_ns) }}</td>
                    <td class="syscall-cell">
                      <span class="syscall-name">{{ call.syscall_name }}</span>
                    </td>
                    <td class="pid-cell">{{ call.pid }}/{{ call.tid }}</td>
                    <td class="path-cell" :title="getPathFromArgs(call.args)">{{ getPathFromArgs(call.args) }}</td>
                    <td class="return-cell">{{ call.return_value }}</td>
                    <td class="status-cell">
                      <t-tag :theme="call.return_value >= 0 ? 'success' : 'danger'" size="small">
                        {{ call.return_value >= 0 ? '成功' : '失败' }}
                      </t-tag>
                    </td>
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
const syscallData = ref([])

// 展开/折叠状态
const expandedSections = ref({
  syscallDist: true,
  fileAccess: true,
  processActivity: false,
  detailedCalls: false
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
        parseSyscallData()
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

function parseSyscallData() {
  if (!content.value) {
    syscallData.value = []
    return
  }
  
  const lines = content.value.trim().split('\n')
  syscallData.value = lines.map(line => {
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
const uniqueSyscalls = computed(() => {
  const set = new Set(syscallData.value.map(d => d.syscall_name))
  return Array.from(set)
})

const uniquePids = computed(() => {
  const set = new Set(syscallData.value.map(d => d.pid))
  return Array.from(set)
})

const failedCalls = computed(() => {
  return syscallData.value.filter(d => d.return_value < 0).length
})

const syscallDistribution = computed(() => {
  const counts = {}
  syscallData.value.forEach(d => {
    counts[d.syscall_name] = (counts[d.syscall_name] || 0) + 1
  })
  return Object.entries(counts)
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 10)
})

const maxSyscallCount = computed(() => {
  if (syscallDistribution.value.length === 0) return 1
  return syscallDistribution.value[0].count
})

const uniquePaths = computed(() => {
  const set = new Set()
  syscallData.value.forEach(d => {
    const path = getPathFromArgs(d.args)
    if (path) set.add(path)
  })
  return Array.from(set)
})

const pathDistribution = computed(() => {
  const counts = {}
  syscallData.value.forEach(d => {
    const path = getPathFromArgs(d.args)
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
  syscallData.value.forEach(d => {
    if (!pids[d.pid]) {
      pids[d.pid] = { pid: d.pid, count: 0, syscalls: new Set() }
    }
    pids[d.pid].count++
    pids[d.pid].syscalls.add(d.syscall_name)
  })
  return Object.values(pids)
    .map(p => ({
      pid: p.pid,
      count: p.count,
      syscalls: Array.from(p.syscalls).sort()
    }))
    .sort((a, b) => b.count - a.count)
})

const totalPages = computed(() => Math.ceil(syscallData.value.length / PAGE_SIZE))

const pagedCalls = computed(() => {
  const start = (currentPage.value - 1) * PAGE_SIZE
  return syscallData.value.slice(start, start + PAGE_SIZE)
})

function getPathFromArgs(args) {
  if (!args) return ''
  if (args.path) return args.path
  return ''
}

function formatTime(timestampNs) {
  if (!timestampNs) return ''
  // 简化时间显示，只显示后9位（微秒级）
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
.syscall-dialog-content {
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

/* 系统调用分布 */
.syscall-distribution {
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
  min-width: 120px;
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
  background: linear-gradient(90deg, #0052d9, #00a870);
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

.syscall-badge {
  color: #666;
  font-size: 12px;
}

.process-syscalls {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

/* 详细调用列表 */
.calls-table-wrapper {
  max-height: 300px;
  overflow-y: auto;
  border: 1px solid #e8ecf0;
  border-radius: 6px;
}

.calls-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.calls-table thead {
  position: sticky;
  top: 0;
  background: #f0f2f5;
  z-index: 1;
}

.calls-table th {
  padding: 8px 10px;
  text-align: left;
  font-weight: 600;
  color: #666;
  border-bottom: 1px solid #e8ecf0;
  font-size: 11px;
  text-transform: uppercase;
}

.calls-table td {
  padding: 6px 10px;
  border-bottom: 1px solid #f0f0f0;
}

.calls-table tbody tr:hover {
  background: #f8f9fa;
}

.calls-table tbody tr.failed-row {
  background: #fff0f0;
}

.calls-table tbody tr.failed-row:hover {
  background: #ffe0e0;
}

.time-cell {
  font-family: "SF Mono", monospace;
  color: #999;
}

.syscall-cell {
  font-family: "SF Mono", monospace;
  font-weight: 500;
}

.syscall-name {
  color: #0052d9;
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

.status-cell {
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
  
  .calls-table {
    font-size: 11px;
  }
  
  .path-cell {
    max-width: 100px;
  }
}
</style>
