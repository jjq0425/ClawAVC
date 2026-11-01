<template>
  <!-- 变更计划展示：editable 时可在表格内补全字段路径与建议值，否则只读 -->
  <div v-if="(changes || []).length" class="plan">
    <div class="plan-head">
      变更计划（{{ changes.length }} 条）
      <span class="dim">
        可直接落盘 {{ changes.filter((c) => c.path).length }} 条 ·
        需补字段路径 {{ changes.filter((c) => !c.path).length }} 条<span v-if="editable">（在表格中补全 path 与建议值后即可一并应用）</span>
      </span>
    </div>
    <t-table :data="changes" :columns="cols" row-key="idx" size="small" bordered class="rsi-table">
      <template #kind="{ row }">
        <t-tag :theme="kindTheme(row.kind)" size="small" variant="light">{{ row.kind }}</t-tag>
      </template>
      <template #path="{ row }">
        <t-input v-if="editable" v-model="row.path" size="small"
                 placeholder="点分路径，如 functions.exec.params.command.constraint_spec.static.denylist" />
        <span v-else class="mono">{{ row.path || '—' }}</span>
      </template>
      <template #proposed="{ row }">
        <t-input v-if="editable" v-model="row.proposedTxt" size="small"
                 placeholder="建议值（JSON，如 ['/data/analytics/**']）" />
        <span v-else>{{ fmtVal(row.proposed) }}</span>
      </template>
      <template #risk="{ row }">
        <t-tag :theme="sevTheme(row.risk_level)" size="small" variant="light">{{ row.risk_level }}</t-tag>
      </template>
    </t-table>
  </div>
</template>

<script setup>
const props = defineProps({
  changes: { type: Array, default: () => [] },
  editable: { type: Boolean, default: false },
})

const cols = [
  { colKey: 'kind', title: '类型', width: 100 },
  { colKey: 'target', title: '目标文件', width: 200 },
  { colKey: 'path', title: '字段路径', ellipsis: !props.editable, width: props.editable ? 300 : 260 },
  { colKey: 'proposed', title: '建议值', width: props.editable ? 240 : 190 },
  { colKey: 'reason', title: '理由', ellipsis: true },
  { colKey: 'risk', title: '风险', width: 90 },
]
function kindTheme(k) { return k === 'tighten' ? 'danger' : k === 'relax' ? 'warning' : 'primary' }
function sevTheme(s) { return s === 'high' ? 'danger' : s === 'medium' ? 'warning' : 'default' }
function fmtVal(v) { return Array.isArray(v) ? v.join(', ') : (v === '' || v === null || v === undefined ? '—' : String(v)) }
</script>

<style scoped>
.plan { margin-top: 16px; }
.plan-head { font-size: 13px; font-weight: 600; color: #1F2329; margin-bottom: 8px; }
.rsi-table { margin-top: 6px; }
.mono { font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; }
.dim { color: #A6A6A6; font-size: 12px; }
</style>
