<template>
  <!-- 变更计划展示：editable 时可在表格内补全字段路径与建议值，否则只读 -->
<!-- 变更计划表：类型/目标/路径/建议值/理由/风险 -->
  <div v-if="(changes || []).length" class="plan">
<!-- 计划头：条数与落盘统计 -->
    <div class="plan-head">
<!-- 计划条数 -->
      变更计划（{{ changes.length }} 条）
      <span class="dim">
<!-- 可直接落盘条数 -->
        可直接落盘 {{ changes.filter((c) => c.path).length }} 条 ·
<!-- 需补路径条数（表格内补全） -->
        需补字段路径 {{ changes.filter((c) => !c.path).length }} 条<span v-if="editable">（在表格中补全 path 与建议值后即可一并应用）</span>
      </span>
    </div>
<!-- 计划表格 -->
    <t-table :data="changes" :columns="cols" row-key="idx" size="small" bordered class="rsi-table">
<!-- 类型列：收紧红/放宽黄/改造蓝 -->
      <template #kind="{ row }">
        <t-tag :theme="kindTheme(row.kind)" size="small" variant="light">{{ row.kind }}</t-tag>
      </template>
<!-- 路径列：可编辑或只读 -->
      <template #path="{ row }">
<!-- 路径编辑输入（点分路径） -->
        <t-input v-if="editable" v-model="row.path" size="small"
                 placeholder="点分路径，如 functions.exec.params.command.constraint_spec.static.denylist" />
<!-- 路径只读展示 -->
        <span v-else class="mono">{{ row.path || '—' }}</span>
      </template>
<!-- 建议值列：可编辑或只读 -->
      <template #proposed="{ row }">
<!-- 建议值编辑输入（JSON） -->
        <t-input v-if="editable" v-model="row.proposedTxt" size="small"
                 placeholder="建议值（JSON，如 ['/data/analytics/**']）" />
<!-- 建议值只读展示 -->
        <span v-else>{{ fmtVal(row.proposed) }}</span>
      </template>
<!-- 风险级列 -->
      <template #risk="{ row }">
        <t-tag :theme="sevTheme(row.risk_level)" size="small" variant="light">{{ row.risk_level }}</t-tag>
      </template>
    </t-table>
  </div>
</template>

<script setup>
// 两项 props：变更数组/是否可编辑
const props = defineProps({
  changes: { type: Array, default: () => [] },
  editable: { type: Boolean, default: false },
})

// 计划表列定义（宽度随可编辑切换）
const cols = [
  { colKey: 'kind', title: '类型', width: 100 },
  { colKey: 'target', title: '目标文件', width: 200 },
  { colKey: 'path', title: '字段路径', ellipsis: !props.editable, width: props.editable ? 300 : 260 },
  { colKey: 'proposed', title: '建议值', width: props.editable ? 240 : 190 },
  { colKey: 'reason', title: '理由', ellipsis: true },
  { colKey: 'risk', title: '风险', width: 90 },
]
// 类型 → 主题色：tighten 红/relax 黄/其余蓝
function kindTheme(k) { return k === 'tighten' ? 'danger' : k === 'relax' ? 'warning' : 'primary' }
// 风险级 → 主题色
function sevTheme(s) { return s === 'high' ? 'danger' : s === 'medium' ? 'warning' : 'default' }
// 建议值格式化（与结果视图一致）
function fmtVal(v) { return Array.isArray(v) ? v.join(', ') : (v === '' || v === null || v === undefined ? '—' : String(v)) }
</script>

<style scoped>
/* 计划区容器 */
.plan { margin-top: 16px; }
/* 计划头样式 */
.plan-head { font-size: 13px; font-weight: 600; color: #1F2329; margin-bottom: 8px; }
/* 表格上边距 */
.rsi-table { margin-top: 6px; }
/* 等宽字体（计划视图） */
.mono { font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; }
/* 弱化文本（计划视图） */
.dim { color: #A6A6A6; font-size: 12px; }
</style>
