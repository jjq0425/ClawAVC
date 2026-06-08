<template>
  <t-dialog 
    :visible="dialogVisible" 
    header="内核态LSM Hook判断结果"
    width="700px" 
    :footer="false"
    @close="onClose"
    top="5vh"
  >
    <div class="markdown-dialog-content">
      <div v-if="loading" class="md-loading">
        <t-loading size="small" />
        <span>加载中...</span>
      </div>
      <div v-else-if="error" class="md-error">
        <t-icon name="error-circle" size="24px" />
        <span>{{ error }}</span>
      </div>
      <div v-else-if="mdContent" class="md-content" v-html="renderedMarkdown"></div>
      <div v-else class="md-empty">
        （无内容）
      </div>
    </div>
  </t-dialog>
</template>

<script setup>
import { ref, computed, watch } from "vue"
import MarkdownIt from 'markdown-it'

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

// 使用 computed 实现双向绑定
const dialogVisible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const loading = ref(false)
const error = ref('')
const mdContent = ref('')

// 使用 markdown-it 渲染 markdown
const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true
})

const renderedMarkdown = computed(() => {
  if (!mdContent.value) return ''
  return md.render(mdContent.value)
})

// 监听弹窗打开
watch(dialogVisible, (val) => {
  if (val) {
    loadContent()
  } else {
    mdContent.value = ''
    error.value = ''
  }
})

async function loadContent() {
  if (!props.filePath) {
    error.value = '未指定文件路径'
    return
  }
  
  loading.value = true
  error.value = ''
  
  try {
    const response = await fetch(`/api/kernel/file?path=${encodeURIComponent(props.filePath)}`)
    if (response.ok) {
      const data = await response.json()
      if (data.ok) {
        mdContent.value = data.data
      } else {
        error.value = data.error || '加载失败'
        mdContent.value = ''
      }
    } else {
      error.value = '无法读取文件内容'
      mdContent.value = ''
    }
  } catch (err) {
    error.value = err.message || '网络请求失败'
    mdContent.value = ''
  } finally {
    loading.value = false
  }
}

function onClose() {
  emit('update:modelValue', false)
}
</script>

<style scoped>
.markdown-dialog-content {
  min-height: 200px;
  max-height: 60vh;
  overflow-y: auto;
}

.md-loading,
.md-error,
.md-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 40px 0;
  color: #999;
}

.md-error {
  color: #e34d59;
}

.md-content {
  font-size: 14px;
  line-height: 1.8;
  color: #333;
  padding: 8px 0;
}

:deep(.md-content h1),
:deep(.md-content h2),
:deep(.md-content h3) {
  margin: 16px 0 8px;
  font-weight: 600;
}

:deep(.md-content h1) { font-size: 20px; }
:deep(.md-content h2) { font-size: 16px; }
:deep(.md-content h3) { font-size: 14px; }

:deep(.md-content p) {
  margin: 8px 0;
}

:deep(.md-content ul),
:deep(.md-content ol) {
  margin: 8px 0;
  padding-left: 20px;
}

:deep(.md-content li) {
  margin: 4px 0;
}

:deep(.md-content code) {
  background: #f5f5f5;
  padding: 2px 4px;
  border-radius: 3px;
  font-family: "SF Mono", monospace;
  font-size: 13px;
}

:deep(.md-content pre) {
  background: #1a1a2e;
  color: #e0e0e0;
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 12px 0;
}

:deep(.md-content pre code) {
  background: none;
  padding: 0;
  color: inherit;
}

:deep(.md-content blockquote) {
  border-left: 4px solid #0052d9;
  padding-left: 12px;
  margin: 12px 0;
  color: #666;
}

:deep(.md-content table) {
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0;
}

:deep(.md-content th),
:deep(.md-content td) {
  border: 1px solid #ddd;
  padding: 8px 12px;
  text-align: left;
}

:deep(.md-content th) {
  background: #f5f5f5;
  font-weight: 600;
}

:deep(.md-content a) {
  color: #0052d9;
  text-decoration: none;
}

:deep(.md-content a:hover) {
  text-decoration: underline;
}
</style>
