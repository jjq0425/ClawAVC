<template>
  <t-dialog
    :visible="visible"
    @update:visible="(v) => emit('update:visible', v)"
    header="选择异常 syscall 序列（单选）"
    :footer="false"
    width="780px"
    placement="center"
    destroy-on-close
  >
    <div class="rule-dialog">
      <div class="rule-dialog-head">
        <t-input
          v-model="ruleFilter"
          placeholder="搜索 rule_id / syscall 名"
          clearable
          class="rule-search"
        >
          <template #prefix-icon><t-icon name="search" /></template>
        </t-input>
        <span class="rule-count">共 {{ filteredRules.length }} / {{ allRules.length }} 条</span>
      </div>

      <div v-if="rulesLoading" class="rule-loading">加载中…</div>
      <div v-else-if="rulesError" class="rule-error">{{ rulesError }}</div>
      <div v-else class="rule-list">
        <t-radio-group v-model="pick">
          <label
            v-for="r in filteredRules"
            :key="r.rule_id"
            class="rule-item"
            :class="{ on: pick === r.rule_id }"
          >
            <t-radio :value="r.rule_id" />
            <div class="rule-meta">
              <div class="rule-title">
                <code class="rule-rid">{{ r.rule_id }}</code>
                <span v-if="r.score != null" class="rule-score">score {{ r.score }}</span>
              </div>
              <div class="rule-seq">{{ r.sequence }}</div>
              <div v-if="r.note" class="rule-note">{{ r.note }}</div>
            </div>
          </label>
        </t-radio-group>
      </div>

      <div class="rule-dialog-foot">
        <t-button theme="default" variant="outline" @click="onCancel">取消</t-button>
        <t-button theme="primary" :disabled="!pick" @click="onConfirm">
          确认选择
        </t-button>
      </div>
    </div>
  </t-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'

const props = defineProps({
  visible: { type: Boolean, default: false },
  modelValue: { type: String, default: '' },     // 当前选中的 rule_id（外部双绑）
  apiBase: { type: String, default: '' },        // API 前缀（如 ''/'/api'）；最终请求 `${apiBase}/attack/rules`
})

const emit = defineEmits(['update:visible', 'update:modelValue', 'confirm'])

const allRules = ref([])
const rulesLoading = ref(false)
const rulesError = ref('')
const ruleFilter = ref('')
const pick = ref(props.modelValue || '')

const filteredRules = computed(() => {
  const q = ruleFilter.value.trim().toLowerCase()
  if (!q) return allRules.value
  return allRules.value.filter((r) =>
    (r.rule_id || '').toLowerCase().includes(q) ||
    (r.sequence || '').toLowerCase().includes(q)
  )
})

async function loadRules() {
  if (allRules.value.length > 0) return
  rulesLoading.value = true
  rulesError.value = ''
  try {
    const url = `${props.apiBase}/attack/rules`
    const res = await fetch(url)
    const data = await res.json()
    if (data.ok && Array.isArray(data.data)) {
      allRules.value = data.data
    } else {
      rulesError.value = data.error || '加载规则失败'
    }
  } catch (e) {
    rulesError.value = '加载规则失败：' + (e?.message || e)
  } finally {
    rulesLoading.value = false
  }
}

// 打开时同步外部当前值、清空筛选并触发加载
watch(
  () => props.visible,
  (v) => {
    if (v) {
      pick.value = props.modelValue || ''
      ruleFilter.value = ''
      loadRules()
    }
  }
)

// 外部 modelValue 在弹窗未开时变了也同步一下
watch(
  () => props.modelValue,
  (v) => {
    if (!props.visible) pick.value = v || ''
  }
)

function onCancel() {
  emit('update:visible', false)
}

function onConfirm() {
  if (!pick.value) return
  emit('update:modelValue', pick.value)
  emit('confirm', pick.value)
  emit('update:visible', false)
  // 提示用户需要再次点击保存配置按钮
  MessagePlugin.info('已选择异常序列，请点击上方「保存配置」按钮使设置生效')
}
</script>

<style scoped>
.rule-dialog { display: flex; flex-direction: column; gap: 12px; min-height: 320px; }
.rule-dialog-head { display: flex; align-items: center; gap: 12px; }
.rule-search { flex: 1; }
.rule-count { font-size: 12px; color: #888; white-space: nowrap; }
.rule-loading, .rule-error { padding: 24px; text-align: center; color: #888; }
.rule-error { color: #d54941; }
.rule-list {
  max-height: 50vh; overflow-y: auto;
  border: 1px solid #eee; border-radius: 8px; padding: 4px;
}
.rule-list :deep(.t-radio-group) { display: flex; flex-direction: column; gap: 4px; width: 100%; }
.rule-item {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 10px 12px; border-radius: 6px; cursor: pointer;
  transition: background 0.15s;
}
.rule-item:hover { background: #f5f7fa; }
.rule-item.on { background: #e8f3ff; }
.rule-meta { flex: 1; min-width: 0; }
.rule-title { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.rule-rid {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px; font-weight: 600; color: #0052D9;
}
.rule-score {
  font-size: 11px; color: #fa8c16; background: #fff7e6;
  padding: 1px 6px; border-radius: 3px;
}
.rule-seq {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px; color: #555; word-break: break-all; margin-bottom: 2px;
}
.rule-note { font-size: 11px; color: #999; line-height: 1.5; }
.rule-dialog-foot { display: flex; justify-content: flex-end; gap: 8px; padding-top: 4px; }
</style>
