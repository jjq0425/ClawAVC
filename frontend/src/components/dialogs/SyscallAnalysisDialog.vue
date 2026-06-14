<template>
  <t-dialog 
    :visible="dialogVisible" 
    header="系统调用分析判断结果"
    width="900px" 
    :footer="false"
    @close="onClose"
    top="5vh"
  >
    <div class="syscall-analysis-dialog-content">
      <div v-if="loading" class="analysis-loading">
        <t-loading size="small" />
        <span>加载中...</span>
      </div>
      <div v-else-if="error" class="analysis-error">
        <t-icon name="error-circle" size="24px" />
        <span>{{ error }}</span>
      </div>
      <div v-else-if="analysisData" class="analysis-content">
        <!-- 基本信息 -->
        <div class="info-section">
          <div class="info-grid">
            <div class="info-item">
              <span class="info-label">Round ID:</span>
              <span class="info-value">{{ analysisData.round_id || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">工具调用 ID:</span>
              <span class="info-value mono">{{ toolCallId || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">授权状态:</span>
              <t-tag :theme="isAuthorized ? 'success' : 'danger'" variant="light">
                {{ isAuthorized ? '已授权' : '未授权' }}
              </t-tag>
            </div>
            <div class="info-item">
              <span class="info-label">风险判定:</span>
              <t-tag :theme="getVerdictTheme()" variant="light">
                {{ getVerdictText() }}
              </t-tag>
            </div>
            <div class="info-item">
              <span class="info-label">期望工具:</span>
              <span class="info-value">{{ expectedTool }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">实际工具:</span>
              <span class="info-value" :class="{ 'text-error': !isAuthorized }">
                {{ actualTool }}
              </span>
            </div>
            <div class="info-item">
              <span class="info-label">风险分数:</span>
              <span class="info-value">{{ riskScore !== null && riskScore !== undefined ? riskScore : '-' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">处理事件数:</span>
              <span class="info-value">{{ eventCount }}</span>
            </div>
          </div>
          <div class="summary-section">
            <span class="summary-label">摘要:</span>
            <span class="summary-text">{{ analysisData.summary || '-' }}</span>
          </div>
        </div>

        <!-- 检测器信息 (仅旧格式) -->
        <div v-if="detectorInfo" class="analysis-section">
          <div class="section-header">检测器信息</div>
          <div class="detector-grid">
            <div class="detector-item">
              <span class="info-label">名称:</span>
              <span class="info-value">{{ detectorInfo.name }}</span>
            </div>
            <div class="detector-item">
              <span class="info-label">版本:</span>
              <span class="info-value">{{ detectorInfo.version }}</span>
            </div>
          </div>
        </div>

        <!-- 工具调用参数 -->
        <div v-if="toolArgs" class="analysis-section">
          <div class="section-header">工具调用参数</div>
          <pre class="arguments-json">{{ JSON.stringify(toolArgs, null, 2) }}</pre>
        </div>

        <!-- 系统调用统计 -->
        <div v-if="hasSyscallAnalysis" class="analysis-section">
          <div class="section-header">系统调用统计</div>
          <div class="stats-grid">
            <div class="stat-item">
              <span class="stat-label">处理事件数:</span>
              <span class="stat-value">{{ syscallAnalysis.processed_event_count }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">告警数:</span>
              <span class="stat-value" :class="{ 'text-warning': (syscallAnalysis.alert_count || 0) > 0 }">
                {{ syscallAnalysis.alert_count || 0 }}
              </span>
            </div>
          </div>
        </div>

        <!-- 告警列表 -->
        <div v-if="analysisData.alerts && analysisData.alerts.length > 0" class="analysis-section">
          <div class="section-header">告警详情 ({{ analysisData.alerts.length }} 条)</div>
          <div class="alerts-list">
            <div v-for="(alert, idx) in analysisData.alerts" :key="idx" class="alert-item">
              <div class="alert-header">
                <t-tag :theme="getSeverityTheme(alert)" variant="light" size="small">
                  {{ getSeverity(alert) }}
                </t-tag>
                <span class="alert-id">{{ getAlertId(alert) }}</span>
              </div>
              <div class="alert-rule">规则 ID: {{ getRuleId(alert) }}</div>
              <div class="alert-message">{{ getAlertMessage(alert) }}</div>
              <div class="alert-meta">
                <span>PID: {{ getPid(alert) }}</span>
                <span v-if="getSourceEventId(alert)" class="meta-item">事件ID: {{ getSourceEventId(alert) }}</span>
                <span v-if="getSourceLine(alert) !== undefined" class="meta-item">行号: {{ getSourceLine(alert) }}</span>
                <span v-if="getRoundId(alert)" class="meta-item">Round: {{ getRoundId(alert) }}</span>
                <span v-if="getExpectedTool(alert)" class="meta-item">期望: {{ getExpectedTool(alert) }}</span>
                <span v-if="getActualTool(alert)" class="meta-item">实际: {{ getActualTool(alert) }}</span>
                <span v-if="getAuthorized(alert) !== null" class="meta-item">
                  授权: <t-tag :theme="getAuthorized(alert) ? 'success' : 'danger'" size="small" variant="light">
                    {{ getAuthorized(alert) ? '是' : '否' }}
                  </t-tag>
                </span>
              </div>
              <div v-if="getResource(alert)" class="alert-resource">
                <span class="resource-label">资源:</span>
                <span class="resource-type">{{ getResource(alert).type }}</span>
                <code class="resource-path">{{ getResource(alert).path }}</code>
              </div>
              <div v-if="getEvidence(alert)" class="alert-evidence">
                <span class="evidence-label">证据链:</span>
                <pre class="evidence-json">{{ JSON.stringify(getEvidence(alert), null, 2) }}</pre>
              </div>
              <div v-if="getContext(alert)" class="alert-context">
                <span class="context-label">上下文:</span>
                <pre class="context-json">{{ JSON.stringify(getContext(alert), null, 2) }}</pre>
              </div>
            </div>
          </div>
        </div>

        <!-- 错误信息 -->
        <div v-if="analysisData.error" class="analysis-section error-section">
          <div class="section-header">错误信息</div>
          <t-alert theme="error" :message="analysisData.error.message">
            <template #operation>
              <span class="error-code">{{ analysisData.error.code }}</span>
            </template>
          </t-alert>
        </div>

        <!-- 其他未展示的字段 -->
        <div v-if="otherFields.length > 0" class="analysis-section">
          <div class="section-header" @click="showOtherFields = !showOtherFields">
            <t-icon :name="showOtherFields ? 'chevron-down' : 'chevron-right'" size="16px" />
            <span>其他字段 ({{ otherFields.length }})</span>
          </div>
          <div v-if="showOtherFields" class="other-fields">
            <div v-for="field in otherFields" :key="field" class="other-field">
              <span class="info-label">{{ field }}:</span>
              <pre class="field-value">{{ formatFieldValue(analysisData[field]) }}</pre>
            </div>
          </div>
        </div>

        <!-- 原始 JSON -->
        <div class="raw-json-section">
          <div class="section-header" @click="showRawJson = !showRawJson">
            <t-icon :name="showRawJson ? 'chevron-down' : 'chevron-right'" size="16px" />
            <span>原始 JSON 数据</span>
          </div>
          <div v-if="showRawJson" class="raw-json-content">
            <pre class="raw-json">{{ formattedJson }}</pre>
          </div>
        </div>
      </div>
      <div v-else class="analysis-empty">
        （无内容）
      </div>
    </div>
  </t-dialog>
</template>

<script setup>
import { ref, computed, watch } from "vue"

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false
  },
  jsonData: {
    type: [String, Object],
    default: ''
  }
})

const emit = defineEmits(['update:modelValue'])

// 使用 computed 实现双向绑定
const dialogVisible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const loading = ref(false)
const error = ref('')
const analysisData = ref(null)
const showRawJson = ref(false)
const showOtherFields = ref(false)

// 已知的标准字段（不包含在"其他字段"中）
const knownFields = [
  'round_id', 'detector', 'verdict', 'risk_score', 'summary', 'tool_analysis',
  'syscall_analysis', 'alerts', 'error', 'tool_call_id', 'expected_tool',
  'actual_tool', 'authorized', 'arguments', 'events', 'tool_args', 'ts'
]

// 判断数据格式
const isOldFormat = computed(() => {
  if (!analysisData.value) return false
  return !!(analysisData.value.detector || analysisData.value.verdict !== undefined)
})

// 风险判定主题
function getVerdictTheme() {
  if (!analysisData.value) return 'default'
  const v = analysisData.value.verdict
  if (v === 'abnormal') return 'danger'
  if (v === 'normal') return 'success'
  if (v === 'error') return 'warning'
  return 'default'
}

// 风险判定文本
function getVerdictText() {
  if (!analysisData.value) return '-'
  const v = analysisData.value.verdict
  const map = { 'abnormal': '异常', 'normal': '正常', 'error': '错误' }
  return map[v] || v || '-'
}

// 严重程度主题
function getSeverityTheme(alert) {
  const s = getSeverity(alert)
  if (s === 'high') return 'danger'
  if (s === 'medium') return 'warning'
  if (s === 'low') return 'primary'
  return 'default'
}

// 是否已授权
const isAuthorized = computed(() => {
  if (!analysisData.value) return true
  if (isOldFormat.value) {
    return analysisData.value.tool_analysis?.authorized !== false
  }
  return analysisData.value.authorized !== false
})

// 工具调用 ID
const toolCallId = computed(() => {
  if (!analysisData.value) return ''
  if (isOldFormat.value) {
    return analysisData.value.tool_analysis?.tool_call_id || ''
  }
  return analysisData.value.tool_call_id || ''
})

// 期望工具
const expectedTool = computed(() => {
  if (!analysisData.value) return '-'
  if (isOldFormat.value) {
    return analysisData.value.tool_analysis?.expected_tool || '-'
  }
  return analysisData.value.expected_tool || '-'
})

// 实际工具
const actualTool = computed(() => {
  if (!analysisData.value) return '-'
  if (isOldFormat.value) {
    return analysisData.value.tool_analysis?.actual_tool || '-'
  }
  return analysisData.value.actual_tool || '-'
})

// 风险分数
const riskScore = computed(() => {
  if (!analysisData.value) return null
  return analysisData.value.risk_score
})

// 事件数
const eventCount = computed(() => {
  if (!analysisData.value) return '-'
  if (isOldFormat.value) {
    return analysisData.value.syscall_analysis?.processed_event_count ?? '-'
  }
  return analysisData.value.events ?? '-'
})

// 检测器信息
const detectorInfo = computed(() => {
  if (!analysisData.value || !isOldFormat.value) return null
  return analysisData.value.detector
})

// syscall_analysis 数据
const hasSyscallAnalysis = computed(() => {
  return isOldFormat.value && analysisData.value?.syscall_analysis
})

const syscallAnalysis = computed(() => {
  return analysisData.value?.syscall_analysis || {}
})

// 工具参数
const toolArgs = computed(() => {
  if (!analysisData.value) return null
  if (isOldFormat.value) {
    return analysisData.value.tool_analysis?.arguments
  }
  const firstAlert = analysisData.value.alerts?.[0]?.context
  return firstAlert?.tool_args || analysisData.value.arguments || null
})

// 其他字段
const otherFields = computed(() => {
  if (!analysisData.value) return []
  return Object.keys(analysisData.value).filter(key => !knownFields.includes(key))
})

// 格式化字段值
function formatFieldValue(value) {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'object') {
    return JSON.stringify(value, null, 2)
  }
  return String(value)
}

// 格式化原始 JSON
const formattedJson = computed(() => {
  if (!analysisData.value) return ''
  return JSON.stringify(analysisData.value, null, 2)
})

// 告警字段获取函数
function getSeverity(alert) {
  return alert.severity || 'high'
}

function getAlertId(alert) {
  return alert.alert_id || alert.source_event_id || 'N/A'
}

function getRuleId(alert) {
  return alert.rule_id || '-'
}

function getAlertMessage(alert) {
  return alert.msg || alert.message || ''
}

function getPid(alert) {
  return alert.pid !== undefined ? alert.pid : 'N/A'
}

function getSourceEventId(alert) {
  return alert.source_event_id || ''
}

function getSourceLine(alert) {
  if (alert.source_line !== undefined) return alert.source_line
  return null
}

function getRoundId(alert) {
  return alert.round_id || ''
}

function getExpectedTool(alert) {
  return alert.expected_tool || ''
}

function getActualTool(alert) {
  return alert.actual_tool || ''
}

function getAuthorized(alert) {
  if (alert.authorized === true) return true
  if (alert.authorized === false) return false
  return null
}

function getResource(alert) {
  return alert.resource || null
}

function getEvidence(alert) {
  return alert.evidence || null
}

function getContext(alert) {
  return alert.context || null
}

// 监听弹窗打开
watch(dialogVisible, (val) => {
  if (val) {
    parseJsonData()
  } else {
    analysisData.value = null
    error.value = ''
    showRawJson.value = false
    showOtherFields.value = false
  }
})

// 解析 JSON 数据
function parseJsonData() {
  if (!props.jsonData) {
    error.value = '未提供数据'
    return
  }
  
  loading.value = true
  error.value = ''
  
  try {
    let data = props.jsonData
    
    // 如果已经是对象且不是字符串，直接使用
    if (typeof data === 'object' && data !== null && typeof data !== 'string') {
      analysisData.value = data
      return
    }
    
    // 是字符串，需要解析
    let cleaned = data.trim()
    let parsed = null
    
    // 递归解析函数 - 处理多重 JSON 编码
    const tryParse = (str, depth = 0) => {
      if (depth > 5) return str  // 防止无限递归
      
      try {
        const result = JSON.parse(str)
        // 如果结果还是字符串，继续解析
        if (typeof result === 'string') {
          return tryParse(result, depth + 1)
        }
        return result
      } catch {
        return null
      }
    }
    
    parsed = tryParse(cleaned)
    
    if (parsed === null) {
      throw new Error('JSON 解析失败')
    }
    
    analysisData.value = parsed
  } catch (err) {
    console.error('JSON 解析失败:', err, '原始数据:', props.jsonData)
    error.value = err.message || '解析数据失败'
    analysisData.value = null
  } finally {
    loading.value = false
  }
}

function onClose() {
  emit('update:modelValue', false)
}
</script>

<style scoped>
.syscall-analysis-dialog-content {
  min-height: 200px;
  max-height: 75vh;
  overflow-y: auto;
}

.analysis-loading,
.analysis-error,
.analysis-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 40px 0;
  color: #999;
}

.analysis-error {
  color: #e34d59;
}

.analysis-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 基本信息 */
.info-section {
  background: #f5f7fa;
  padding: 12px 16px;
  border-radius: 6px;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 12px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-label {
  font-size: 12px;
  color: #666;
}

.info-value {
  font-size: 14px;
  color: #333;
  font-weight: 500;
}

.info-value.mono {
  font-family: "SF Mono", Menlo, monospace;
  font-size: 12px;
}

.summary-section {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.summary-label {
  font-size: 12px;
  color: #666;
}

.summary-text {
  font-size: 14px;
  color: #333;
}

/* 分析区块 */
.analysis-section {
  background: #fafafa;
  border: 1px solid #e7e7e7;
  border-radius: 6px;
  padding: 12px 16px;
}

.section-header {
  font-size: 14px;
  font-weight: 600;
  color: #333;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
}

/* 检测器信息 */
.detector-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.detector-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* 参数显示 */
.arguments-json {
  background: #1a1a2e;
  color: #e0e0e0;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 12px;
  overflow-x: auto;
  max-height: 150px;
  overflow-y: auto;
}

/* 统计信息 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-label {
  font-size: 12px;
  color: #666;
}

.stat-value {
  font-size: 16px;
  color: #333;
  font-weight: 600;
}

.text-warning {
  color: #ed7b2f;
}

.text-error {
  color: #e34d59;
}

/* 告警列表 */
.alerts-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
}

.alert-item {
  background: #fff;
  border: 1px solid #e7e7e7;
  border-radius: 4px;
  padding: 12px;
}

.alert-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.alert-id {
  font-family: "SF Mono", Menlo, monospace;
  font-size: 12px;
  color: #666;
}

.alert-rule {
  font-size: 12px;
  color: #666;
  margin-bottom: 4px;
}

.alert-message {
  font-size: 14px;
  color: #333;
  margin-bottom: 8px;
}

.alert-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  color: #666;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.alert-resource {
  margin-top: 8px;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 4px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.resource-label {
  font-size: 12px;
  color: #666;
}

.resource-type {
  font-size: 12px;
  color: #333;
  font-weight: 500;
}

.resource-path {
  font-family: "SF Mono", Menlo, monospace;
  font-size: 12px;
  color: #0052d9;
  background: #e6f4ff;
  padding: 2px 6px;
  border-radius: 3px;
}

.alert-evidence {
  margin-top: 8px;
}

.evidence-label {
  font-size: 12px;
  color: #666;
  margin-bottom: 4px;
}

.evidence-json {
  background: #f5f5f5;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 11px;
  overflow-x: auto;
  max-height: 150px;
  overflow-y: auto;
}

.alert-context {
  margin-top: 8px;
}

.context-label {
  font-size: 12px;
  color: #666;
  margin-bottom: 4px;
}

.context-json {
  background: #f5f5f5;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 11px;
  overflow-x: auto;
  max-height: 150px;
  overflow-y: auto;
}

/* 错误信息 */
.error-section {
  background: #fff2f0;
  border-color: #ffccc7;
}

.error-code {
  font-family: "SF Mono", Menlo, monospace;
  font-size: 12px;
  color: #333;
}

/* 其他字段 */
.other-fields {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}

.other-field {
  display: flex;
  gap: 12px;
}

.field-value {
  background: #f5f5f5;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 12px;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 100px;
  overflow-y: auto;
}

/* 原始 JSON */
.raw-json-section {
  border-top: 1px solid #e7e7e7;
  padding-top: 12px;
}

.raw-json-content {
  margin-top: 8px;
}

.raw-json {
  background: #1a1a2e;
  color: #e0e0e0;
  padding: 12px;
  border-radius: 4px;
  font-size: 12px;
  overflow-x: auto;
  max-height: 300px;
  overflow-y: auto;
}
</style>
