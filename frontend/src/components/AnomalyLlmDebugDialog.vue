<template>
  <t-dialog
    v-model:visible="visible"
    header="二阶段异常判断 · 调试"
    :width="680"
    :confirm-btn="null"
    cancel-btn="关闭"
    @close="onClose"
  >
    <div class="anomaly-debug">
      <!-- 输入区 -->
      <div class="debug-input-row">
        <t-input
          v-model="roundId"
          placeholder="请输入 round_id，如 129b8a51"
          clearable
          size="large"
          @keyup.enter="runTest"
        />
        <t-button
          theme="primary"
          :loading="loading"
          :disabled="!roundId.trim()"
          @click="runTest"
        >
          <template #icon><t-icon name="play-circle" /></template>
          发起请求
        </t-button>
      </div>

      <!-- 结果区 -->
      <div v-if="result" class="debug-result">
        <div class="result-head">
          <t-tag :theme="result.ok ? 'success' : 'danger'" variant="light" size="medium">
            {{ result.ok ? '请求成功' : '请求失败' }}
          </t-tag>
          <span class="result-url" :title="result.url">{{ result.url || '未配置地址' }}</span>
        </div>

        <div v-if="result.error" class="result-error">
          <t-icon name="error-circle" size="14px" />
          <span>{{ result.error }}</span>
        </div>

        <div v-if="result.response" class="result-block">
          <div class="result-label">大模型返回内容</div>
          <pre class="result-pre">{{ result.response }}</pre>
        </div>
      </div>

      <!-- 空态 -->
      <div v-else-if="!loading" class="debug-empty">
        <t-icon name="chat" size="32px" />
        <div>输入 round_id 后点击「发起请求」，将调用二阶段异常判断大模型并返回结果。</div>
      </div>
    </div>
  </t-dialog>
</template>

<script setup>
import { ref } from "vue"
import { MessagePlugin } from "tdesign-vue-next"

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(["update:modelValue"])

const visible = ref(props.modelValue)
const roundId = ref("")
const loading = ref(false)
const result = ref(null)

// 同步 v-model:visible
import { watch } from "vue"
watch(() => props.modelValue, (v) => { visible.value = v })
watch(visible, (v) => { emit("update:modelValue", v) })

function onClose() {
  // 关闭时不清除结果，便于查看；仅在重新打开时重置
}

async function runTest() {
  const rid = roundId.value.trim()
  if (!rid) {
    MessagePlugin.warning("请输入 round_id")
    return
  }
  loading.value = true
  result.value = null
  try {
    const r = await fetch("/api/monitor/anomaly-llm-test-v2", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ round_id: rid }),
    })
    const j = await r.json()
    if (j.ok && j.data) {
      result.value = j.data
      if (!j.data.ok) {
        MessagePlugin.error(j.data.error || "请求失败")
      }
    } else {
      MessagePlugin.error(j.error || "调试请求失败")
    }
  } catch (e) {
    MessagePlugin.error("网络错误：" + (e?.message || e))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.anomaly-debug { padding: 4px 2px; }
.debug-input-row { display: flex; gap: 10px; align-items: center; }
.debug-result { margin-top: 18px; }
.result-head {
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 12px;
}
.result-url {
  font-size: 12px; color: #6b7280;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  flex: 1;
}
.result-error {
  display: flex; align-items: flex-start; gap: 6px;
  padding: 10px 12px; margin-bottom: 12px;
  background: #fff1f0; border: 1px solid #ffccc7; border-radius: 6px;
  color: #cf1322; font-size: 13px; line-height: 1.5;
}
.result-block { margin-top: 4px; }
.result-label {
  font-size: 13px; font-weight: 600; color: #333;
  margin-bottom: 8px;
}
.result-pre {
  background: #1e293b; color: #e2e8f0;
  padding: 14px 16px; border-radius: 8px;
  font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  line-height: 1.6; overflow-x: auto; max-height: 360px; overflow-y: auto;
  white-space: pre-wrap; word-break: break-all; margin: 0;
}
.debug-empty {
  margin-top: 18px; padding: 28px 16px;
  display: flex; flex-direction: column; align-items: center; gap: 10px;
  color: #9ca3af; font-size: 13px; text-align: center; line-height: 1.6;
}
</style>
