<template>
  <t-drawer v-model:visible="visible" header="行详情" size="480px" :close-on-overlay-click="true" :footer="false">
    <div v-if="row" class="drawer-content">
      <div v-if="row._deleted" class="drawer-alert danger">
        <t-icon name="error-circle" size="16px" /> 本行已标记删除，待执行
      </div>
      <div v-else-if="row._modified" class="drawer-alert warning">
        <t-icon name="info-circle" size="16px" /> 本行有未执行的修改
      </div>
      <div v-else-if="row._new" class="drawer-alert success">
        <t-icon name="add-circle" size="16px" /> 本行为新增行，待执行
      </div>
      <div v-for="col in columns" :key="col" class="drawer-field" :class="{ changed: row._originalDiff && row._originalDiff[col] }">
        <div class="field-label">
          {{ col }}
          <t-tag v-if="row._originalDiff && row._originalDiff[col]" theme="warning" variant="light" size="small">已修改</t-tag>
        </div>
        <div class="field-value">
          <pre class="field-pre">{{ formatValue(row[col]) }}</pre>
        </div>
      </div>
    </div>
  </t-drawer>
</template>

<script setup>
import { computed } from "vue"

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  row: { type: Object, default: null },
  columns: { type: Array, default: () => [] },
})

const emit = defineEmits(["update:modelValue"])

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit("update:modelValue", val),
})

function formatValue(val) {
  if (val === null || val === undefined) return "NULL"
  const s = String(val)
  try {
    return JSON.stringify(JSON.parse(s), null, 2)
  } catch (e) {
    return s
  }
}
</script>

<style scoped>
.drawer-content {
  padding: 8px 0;
}
.drawer-alert {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  margin-bottom: 16px;
}
.drawer-alert.danger { background: #fff5f5; color: #ff5252; border: 1px solid #ffe0e0; }
.drawer-alert.warning { background: #fffbe6; color: #ed7b2f; border: 1px solid #ffe8b8; }
.drawer-alert.success { background: #f0fff8; color: #00a870; border: 1px solid #c2f0d8; }
.drawer-field {
  margin-bottom: 16px;
  border-bottom: 1px solid #f3f3f3;
  padding-bottom: 12px;
}
.drawer-field.changed .field-value { border-left: 3px solid #ED7B2F; }
.field-label {
  font-size: 12px;
  font-weight: 600;
  color: #0052D9;
  margin-bottom: 6px;
  text-transform: uppercase;
  display: flex;
  align-items: center;
  gap: 6px;
}
.field-value {
  background: #f8f9fa;
  border-radius: 6px;
  padding: 10px;
  overflow-x: auto;
}
.field-pre {
  font-family: "SF Mono", "Fira Code", monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #333;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
</style>
