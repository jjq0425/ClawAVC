<template>
  <!-- AI 分析结论展示：selectable 时可勾选（RSI 流程用），否则只读（任务历史用） -->
  <div v-if="result" class="concl">
    <div class="concl-summary">
      <div class="dim">总体结论</div>
      <div>{{ result.summary || '—' }}</div>
      <div class="dim" v-if="result.assumptions">假设：{{ result.assumptions }}</div>
    </div>

    <div class="concl-col">
      <div class="col-head risk"><t-icon name="error-circle" /> 越权风险（收紧） · {{ list('risks').length }}</div>
      <div v-for="(r, i) in list('risks')" :key="'rk' + i" class="concl-item" :class="{ on: selectable && isOn('risks', i) }">
        <t-checkbox v-if="selectable" :model-value="isOn('risks', i)" @change="v => emit('toggle', 'risks', i, v)" />
        <div class="ci-body">
          <div class="ci-line"><b>{{ r.scene || '-' }} / {{ r.tool || '-' }}</b>
            <t-tag :theme="sevTheme(r.severity)" size="small" variant="light">{{ r.severity }}</t-tag>
            <t-tag size="small" variant="outline">{{ r.round_id }}</t-tag></div>
          <div class="dim">行为：{{ r.behavior }}</div>
          <div>越权点：{{ r.violation }}</div>
          <div class="ci-act">建议：{{ r.action }}</div>
        </div>
      </div>
      <t-empty v-if="!list('risks').length" description="未识别出越权风险" size="small" />
    </div>

    <div class="concl-col">
      <div class="col-head relax"><t-icon name="unlock" /> 应放宽 · {{ list('relax').length }}</div>
      <div v-for="(r, i) in list('relax')" :key="'rx' + i" class="concl-item" :class="{ on: selectable && isOn('relax', i) }">
        <t-checkbox v-if="selectable" :model-value="isOn('relax', i)" @change="v => emit('toggle', 'relax', i, v)" />
        <div class="ci-body">
          <div class="ci-line"><b>{{ r.scene || '-' }} / {{ r.tool || '-' }}</b>
            <t-tag size="small" variant="outline">{{ r.round_id }}</t-tag></div>
          <div class="dim">被拦行为：{{ r.blocked_behavior }}</div>
          <div>理由：{{ r.reason }}</div>
          <div class="ci-act">建议：{{ r.action }}</div>
        </div>
      </div>
      <t-empty v-if="!list('relax').length" description="无需放宽项" size="small" />
    </div>

    <div class="concl-col">
      <div class="col-head trans"><t-icon name="edit-1" /> 策略改造 · {{ list('transform').length }}</div>
      <div v-for="(t, i) in list('transform')" :key="'tf' + i" class="concl-item" :class="{ on: selectable && isOn('transform', i) }">
        <t-checkbox v-if="selectable" :model-value="isOn('transform', i)" @change="v => emit('toggle', 'transform', i, v)" />
        <div class="ci-body">
          <div class="ci-line"><b>{{ t.target }}</b>
            <t-tag :theme="sevTheme(t.risk_level)" size="small" variant="light">{{ t.risk_level }}</t-tag></div>
          <div class="mono dim">{{ t.path }}</div>
          <div class="ci-act">现值 → 建议值：{{ fmtVal(t.current) }} → {{ fmtVal(t.proposed) }}</div>
          <div class="dim">理由：{{ t.reason }}</div>
        </div>
      </div>
      <t-empty v-if="!list('transform').length" description="无改造建议" size="small" />
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  result: { type: Object, default: null },
  adopted: { type: Object, default: () => ({ risks: [], relax: [], transform: [] }) },
  selectable: { type: Boolean, default: false },
})
const emit = defineEmits(['toggle'])

function list(cat) { return (props.result || {})[cat] || [] }
function isOn(cat, i) { return ((props.adopted || {})[cat] || []).includes(i) }
function sevTheme(s) { return s === 'high' ? 'danger' : s === 'medium' ? 'warning' : 'default' }
function fmtVal(v) { return Array.isArray(v) ? v.join(', ') : (v === '' || v === null || v === undefined ? '—' : String(v)) }
</script>

<style scoped>
.concl { display: flex; flex-direction: column; gap: 14px; }
.concl-summary { border: 1px solid #E5E7EB; border-radius: 10px; padding: 12px 14px; background: #FCFDFF; }
.concl-col { border: 1px solid #E5E7EB; border-radius: 10px; padding: 12px 14px; }
.col-head { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 14px; margin-bottom: 10px; }
.col-head.risk { color: #E34D59; }
.col-head.relax { color: #ED7B2F; }
.col-head.trans { color: #0052D9; }
.concl-item { display: flex; gap: 10px; align-items: flex-start; padding: 8px 10px; border-radius: 8px; transition: background .15s ease; }
.concl-item:hover { background: #F7F9FC; }
.concl-item.on { background: #F0F6FF; }
.ci-body { flex: 1; font-size: 13px; }
.ci-line { display: flex; align-items: center; gap: 8px; }
.ci-act { color: #1F2329; margin-top: 2px; }
.mono { font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; }
.dim { color: #A6A6A6; font-size: 12px; }
</style>
