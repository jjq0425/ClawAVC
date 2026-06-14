<template>
  <t-dialog 
    :visible="dialogVisible" 
    header="系统调用分析判断结果"
    width="800px" 
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
              <span class="info-value">{{ analysisData.round_id }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">授权状态:</span>
              <t-tag :theme="analysisData.authorized !== false ? 'success' : 'danger'" variant="light">
                {{ analysisData.authorized === false ? '未授权' : '已授权' }}
              </t-tag>
            </div>
            <div class="info-item">
              <span class="info-label">期望工具:</span>
              <span class="info-value">{{ analysisData.expected_tool || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">实际工具:</span>
              <span class="info-value" :class="{ 'text-error': analysisData.authorized === false }">
                {{ analysisData.actual_tool || '-' }}
              </span>
            </div>
          </div>
          <div v-if="analysisData.events" class="summary-section">
            <span class="summary-label">处理事件数:</span>
            <span class="summary-text">{{ analysisData.events }}</span>
          </div>
        </div>

        <!-- 工具参数 -->
        <div v-if="toolArgs" class="analysis-section">
          <div class="section-header">工具调用参数</div>
          <pre class="arguments-json">{{ JSON.stringify(toolArgs, null, 2) }}</pre>
        </div>

        <!-- 告警列表 -->
        <div v-if="analysisData.alerts && analysisData.alerts.length > 0" class="analysis-section">
          <div class="section-header">告警详情 ({{ analysisData.alerts.length }} 条)</div>
          <div class="alerts-list">
            <div v-for="(alert, idx) in analysisData.alerts" :key="idx" class="alert-item">
              <div class="alert-header">
                <t-tag theme="danger" variant="light" size="small">
                  {{ alert.severity || 'high' }}
                </t-tag>
                <span class="alert-source">{{ alert.source_event_id || 'N/A' }}</span>
              </div>
              <div class="alert-rule">规则: {{ alert.rule_id }}</div>
              <div class="alert-message">{{ alert.msg || alert.message }}</div>
              <div class="alert-meta">
                <span>PID: {{ alert.pid || 'N/A' }}</span>
                <span v-if="alert.ts" class="alert-ts">时间戳: {{ formatTimestamp(alert.ts) }}</span>
              </div>
              <div v-if="alert.context" class="alert-context">
                <span class="context-label">上下文:</span>
                <pre class="context-json">{{ JSON.stringify(alert.context, null, 2) }}</pre>
              </div>
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

// 工具参数（从 context.tool_args 或独立字段获取）
const toolArgs = computed(() => {
  if (!analysisData.value) return null
  const firstAlert = analysisData.value.alerts?.[0]?.context
  if (firstAlert?.tool_args) {
    return firstAlert.tool_args
  }
  return null
})

// 格式化原始 JSON
const formattedJson = computed(() => {
  if (!analysisData.value) return ''
  return JSON.stringify(analysisData.value, null, 2)
})

// 格式化时间戳
function formatTimestamp(ts) {
  if (!ts) return ''
  // 如果是秒级时间戳（大于 1e12 说明是毫秒）
  if (ts < 1e12) {
    ts = ts * 1000
  }
  const date = new Date(ts)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

// 监听弹窗打开
watch(dialogVisible, (val) => {
  if (val) {
    parseJsonData()
  } else {
    analysisData.value = null
    error.value = ''
    showRawJson.value = false
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
      
      console.log('尝试解析 JSON, 原始长度:', cleaned.length, '前50字符:', cleaned.substring(0, 50))
      
      // 递归解析函数 - 处理多重 JSON 编码
      const tryParse = (str, depth = 0) => {
        if (depth > 5) return str  // 防止无限递归
        
        try {
          const result = JSON.parse(str)
          // 如果结果还是字符串，继续解析
          if (typeof result === 'string') {
            console.log('发现嵌套 JSON 字符串，继续解析, depth:', depth + 1)
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
      
      console.log('解析后的数据类型:', typeof parsed)
      console.log('解析后的数据 keys:', parsed ? Object.keys(parsed) : 'null')
      console.log('解析后的 round_id:', parsed?.round_id)
      
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
  max-height: 70vh;
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

.alert-source {
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
  gap: 16px;
  font-size: 12px;
  color: #666;
}

.alert-ts {
  font-family: "SF Mono", Menlo, monospace;
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

.text-error {
  color: #e34d59;
}
</style>
