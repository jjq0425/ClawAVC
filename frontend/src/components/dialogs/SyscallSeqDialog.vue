<template>
  <t-dialog 
    :visible="dialogVisible" 
    header="系统调用序列"
    width="700px" 
    :footer="false"
    @close="onClose"
  >
    <div class="kernel-detail-content">
      <div v-if="loading" class="detail-loading">
        <t-loading size="large" />
        <p>加载中...</p>
      </div>
      <div v-else-if="error" class="detail-error">
        <t-icon name="error-circle" size="48px" />
        <p>{{ error }}</p>
      </div>
      <div v-else class="detail-content">
        <div class="detail-toolbar">
          <t-button size="small" variant="text" @click="copyContent">
            <t-icon name="file-copy" size="14px" />
            复制内容
          </t-button>
        </div>
        <div v-html="formattedContent"></div>
      </div>
    </div>
  </t-dialog>
</template>

<script setup>
import { ref, watch, computed } from "vue"
import { isJsonl, jsonlToHtml, jsonToJsonHtml, getContentFormat } from "../../utils/jsonHighlighter.js"

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

// 格式化内容为 HTML
const formattedContent = computed(() => {
  if (!content.value) return ''
  
  const format = getContentFormat(content.value)
  
  if (format === 'jsonl') {
    return jsonlToHtml(content.value)
  } else if (format === 'json') {
    return jsonToJsonHtml(content.value)
  } else {
    return `<pre class="text-content">${escapeHtml(content.value)}</pre>`
  }
})

function escapeHtml(str) {
  if (!str) return ''
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

function copyContent() {
  if (!content.value) return
  
  // 使用更兼容的复制方法
  const text = content.value
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.left = '-9999px'
  textarea.style.top = '-9999px'
  document.body.appendChild(textarea)
  textarea.focus()
  textarea.select()
  
  try {
    document.execCommand('copy')
  } catch (err) {
    console.error('复制失败:', err)
  }
  
  document.body.removeChild(textarea)
}
</script>

<style scoped>
.kernel-detail-content { min-height: 300px; }
.detail-loading { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px; }
.detail-loading p { margin-top: 16px; color: #999; font-size: 14px; }
.detail-error { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px; }
.detail-error p { margin-top: 16px; color: #e34d59; font-size: 14px; }
.detail-content { padding: 16px 0; }
.detail-toolbar { margin-bottom: 12px; }

/* JSONL 容器样式 */
.jsonl-container { 
  max-height: 500px; 
  overflow-y: auto;
  background: #1a1a2e; 
  border-radius: 8px;
}

.jsonl-line {
  display: flex;
  align-items: flex-start;
  padding: 8px 16px;
  border-bottom: 1px solid #2d2d44;
}

.jsonl-line:last-child {
  border-bottom: none;
}

.line-number {
  display: inline-block;
  min-width: 40px;
  color: #666;
  font-size: 12px;
  text-align: right;
  margin-right: 16px;
  padding-top: 4px;
}

.json-line {
  margin: 0;
  font-family: "SF Mono", "Fira Code", monospace;
  font-size: 12px;
  line-height: 1.5;
  color: #a0e0a0;
  white-space: pre-wrap;
  word-break: break-all;
  flex: 1;
}

/* JSON 语法高亮 */
.text-content {
  background: #1a1a2e; 
  color: #a0e0a0; 
  padding: 16px; 
  border-radius: 8px; 
  font-size: 12px; 
  line-height: 1.6; 
  white-space: pre-wrap; 
  word-break: break-all; 
  max-height: 500px; 
  overflow-y: auto;
}

:deep(.json-key) { color: #f9c74f; font-weight: bold; }
:deep(.json-string) { color: #99d4ff; }
:deep(.json-number) { color: #ff9de0; }
:deep(.json-boolean) { color: #f9c74f; font-weight: bold; }
:deep(.json-null) { color: #c17a7a; font-weight: bold; }
:deep(.json-brace) { color: #f9c74f; }
:deep(.json-bracket) { color: #f9c74f; }
:deep(.json-colon) { color: #888; }
</style>
