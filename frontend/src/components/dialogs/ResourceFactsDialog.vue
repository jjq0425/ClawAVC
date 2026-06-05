<template>
  <t-dialog 
    :visible="dialogVisible" 
    header="资源事实分析"
    width="700px" 
    :footer="false"
    @close="onClose"
    top="5vh"
  >
    <div class="resource-dialog-content">
      <div v-if="loading" class="detail-loading">
        <t-loading size="large" />
        <p>加载中...</p>
      </div>
      <div v-else-if="error" class="detail-error">
        <t-icon name="error-circle" size="48px" />
        <p>{{ error }}</p>
      </div>
      <div v-else-if="!resourceData" class="detail-empty">
        <t-icon name="folder-open" size="48px" />
        <p>无资源事实数据</p>
      </div>
      <div v-else class="resource-detail">
        <!-- 声明的资源 -->
        <div class="section-block" v-if="declaredResources.length > 0">
          <div class="section-header">
            <t-icon name="folder" size="16px" />
            <span>声明的资源</span>
            <t-tag size="small" variant="light">{{ declaredResources.length }} 个</t-tag>
          </div>
          <div class="section-content">
            <div class="declared-list">
              <div v-for="(res, index) in declaredResources" :key="index" class="declared-item">
                <t-icon name="file" size="14px" />
                <span class="declared-path">{{ res }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 资源事实 -->
        <div class="section-block" v-for="(fact, index) in resourceFacts" :key="index">
          <div class="section-header">
            <t-icon name="file-search" size="16px" />
            <span>资源事实 #{{ index + 1 }}</span>
            <t-tag size="small" variant="light">{{ fact.type }}</t-tag>
          </div>
          <div class="section-content">
            <!-- 资源概览 -->
            <div class="fact-summary">
              <div class="fact-path">
                <t-icon name="location" size="14px" />
                <span>{{ fact.path || '-' }}</span>
              </div>
              <div class="fact-stats">
                <div class="stat-item">
                  <div class="stat-value">{{ fact.open_count || 0 }}</div>
                  <div class="stat-label">打开</div>
                </div>
                <div class="stat-item">
                  <div class="stat-value">{{ fact.read_count || 0 }}</div>
                  <div class="stat-label">读取</div>
                </div>
                <div class="stat-item">
                  <div class="stat-value">{{ formatBytes(fact.read_returned_bytes || 0) }}</div>
                  <div class="stat-label">字节</div>
                </div>
              </div>
            </div>

            <!-- 操作详情 -->
            <div class="fact-actions" v-if="fact.actions?.length > 0">
              <span class="actions-label">执行操作：</span>
              <t-tag v-for="action in fact.actions" :key="action" theme="primary" variant="light" size="small">
                <t-icon :name="getActionIcon(action)" size="12px" style="margin-right: 2px;" />
                {{ action }}
              </t-tag>
            </div>

            <!-- 证据事件 -->
            <div class="fact-evidence" v-if="fact.evidence_event_ids?.length > 0">
              <div class="evidence-header" @click="toggleEvidence(index)">
                <t-icon :name="expandedEvidence[index] ? 'chevron-down' : 'chevron-right'" size="14px" />
                <span>证据事件 ({{ fact.evidence_event_ids.length }})</span>
              </div>
              <div v-show="expandedEvidence[index]" class="evidence-list">
                <div v-for="(eid, eindex) in fact.evidence_event_ids" :key="eid" class="evidence-item">
                  <span class="evidence-index">#{{ eindex + 1 }}</span>
                  <span class="evidence-id">{{ eid }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 压缩统计 -->
        <div class="section-block" v-if="compactStats">
          <div class="section-header">
            <t-icon name="chart-bar" size="16px" />
            <span>压缩统计</span>
          </div>
          <div class="section-content">
            <div class="stats-grid">
              <div class="stats-item">
                <div class="stats-label">系统调用序列</div>
                <div class="stats-value">{{ compactStats.syscall_sequence || '-' }}</div>
              </div>
              <div class="stats-item">
                <div class="stats-label">LSM 检查</div>
                <div class="stats-value">{{ compactStats.lsm_checks || '-' }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </t-dialog>
</template>

<script setup>
import { ref, watch, reactive, computed } from "vue"

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false
  },
  content: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['update:modelValue'])

// 使用 computed 实现双向绑定
const dialogVisible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

// 监听弹窗打开
watch(dialogVisible, (val) => {
  if (val) {
    loadContent()
  } else {
    resourceData.value = null
    error.value = ''
  }
})

// 同时监听 content 变化
watch(() => props.content, (newVal) => {
  if (dialogVisible.value) {
    loadContent()
  }
})

// 通知父组件关闭
function onClose() {
  emit('update:modelValue', false)
}

const loading = ref(false)
const error = ref('')
const resourceData = ref(null)

// 展开的证据索引
const expandedEvidence = reactive({})

async function loadContent() {
  const content = props.content
  
  if (!content || !content.trim()) {
    resourceData.value = null
    error.value = ''
    loading.value = false
    return
  }
  
  loading.value = true
  error.value = ''
  
  try {
    // 清理内容，移除可能的换行符问题
    let cleanContent = content.trim()
    
    // 尝试修复常见的 JSON 问题
    // 如果内容以未转义的换行符结尾，尝试修复
    cleanContent = cleanContent.replace(/,\s*$/, '')
    
    const obj = JSON.parse(cleanContent)
    resourceData.value = obj
  } catch (e) {
    console.error('ResourceFacts parse error:', e, 'content:', props.content?.substring(0, 200))
    error.value = '解析失败: ' + e.message
    resourceData.value = null
  } finally {
    loading.value = false
  }
}

function toggleSection(section) {
  expandedSections.value[section] = !expandedSections.value[section]
}

function toggleEvidence(index) {
  expandedEvidence[index] = !expandedEvidence[index]
}

// 数据提取
const declaredResources = computed(() => {
  return resourceData.value?.declared_resources || []
})

const resourceFacts = computed(() => {
  return resourceData.value?.resource_facts || []
})

const compactStats = computed(() => {
  return resourceData.value?.compact_stats || null
})

function formatBytes(bytes) {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

function getActionIcon(action) {
  const icons = {
    'open': 'folder-open',
    'read': 'file-search',
    'write': 'file-edit',
    'close': 'close',
    'unlink': 'delete',
    'mkdir': 'folder-add',
    'rmdir': 'folder-delete'
  }
  return icons[action] || 'file'
}

// 监听内容变化
watch(() => props.content, (newVal) => {
  loadContent()
})
</script>

<style scoped>
.resource-dialog-content {
  min-height: 200px;
  max-height: 600px;
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

/* 声明的资源 */
.declared-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.declared-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #fff;
  border-radius: 6px;
  font-size: 12px;
}

.declared-path {
  font-family: "SF Mono", monospace;
  color: #333;
  word-break: break-all;
}

/* 资源事实概览 */
.fact-summary {
  display: flex;
  gap: 16px;
  align-items: center;
}

.fact-path {
  display: flex;
  align-items: center;
  gap: 6px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-family: "SF Mono", monospace;
}

.fact-stats {
  display: flex;
  gap: 8px;
}

.fact-stats .stat-item {
  background: #fff;
  border-radius: 6px;
  padding: 8px 12px;
  text-align: center;
  min-width: 50px;
}

.fact-stats .stat-value {
  font-size: 14px;
  font-weight: 600;
  color: #333;
}

.fact-stats .stat-label {
  font-size: 10px;
  color: #999;
}

/* 操作详情 */
.fact-actions {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed #e8ecf0;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.actions-label {
  font-size: 12px;
  color: #666;
}

/* 证据事件 */
.fact-evidence {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed #e8ecf0;
}

.evidence-header {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 12px;
  color: #666;
  padding: 4px 0;
}

.evidence-header:hover {
  color: #333;
}

.evidence-list {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 150px;
  overflow-y: auto;
}

.evidence-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  background: #fff;
  border-radius: 4px;
  font-size: 11px;
}

.evidence-index {
  color: #999;
  font-weight: 600;
  min-width: 20px;
}

.evidence-id {
  font-family: "SF Mono", monospace;
  color: #0052d9;
  word-break: break-all;
}

/* 压缩统计 */
.stats-grid {
  display: flex;
  gap: 16px;
}

.stats-item {
  flex: 1;
  background: #fff;
  border-radius: 6px;
  padding: 12px 16px;
  text-align: center;
}

.stats-item .stats-label {
  font-size: 11px;
  color: #999;
  margin-bottom: 4px;
}

.stats-item .stats-value {
  font-size: 14px;
  font-weight: 600;
  color: #333;
  font-family: "SF Mono", monospace;
}
</style>
