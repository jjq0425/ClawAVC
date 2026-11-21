<template>
  <!-- AI 分析结论展示：selectable 时可勾选（RSI 流程用），否则只读（任务历史用） -->
<!-- AI 分析结论：总体结论 + 三列（收紧/放宽/改造） -->
  <div v-if="result" class="concl">
<!-- 总体结论卡 -->
    <div class="concl-summary">
<!-- 结论标签 -->
      <div class="dim">总体结论</div>
<!-- 结论正文 -->
      <div>{{ result.summary || '—' }}</div>
<!-- 分析假设（如有） -->
      <div class="dim" v-if="result.assumptions">假设：{{ result.assumptions }}</div>
    </div>

    <div class="concl-col">
<!-- 列标题：收紧类 -->
      <div class="col-head risk"><t-icon name="error-circle" /> 越权风险（收紧） · {{ list('risks').length }}</div>
<!-- 单条收紧建议：可勾选 -->
      <div v-for="(r, i) in list('risks')" :key="'rk' + i" class="concl-item" :class="{ on: selectable && isOn('risks', i) }">
        <t-checkbox v-if="selectable" :model-value="isOn('risks', i)" @change="v => emit('toggle', 'risks', i, v)" />
        <div class="ci-body">
          <div class="ci-line"><b>{{ r.scene || '-' }} / {{ r.tool || '-' }}</b>
<!-- 严重级标签 -->
            <t-tag :theme="sevTheme(r.severity)" size="small" variant="light">{{ r.severity }}</t-tag>
            <t-tag size="small" variant="outline">{{ r.round_id }}</t-tag></div>
<!-- 越权行为描述 -->
          <div class="dim">行为：{{ r.behavior }}</div>
<!-- 越权点描述 -->
          <div>越权点：{{ r.violation }}</div>
          <div class="ci-act">建议：{{ r.action }}</div>
        </div>
      </div>
<!-- 收紧列空态 -->
      <t-empty v-if="!list('risks').length" description="未识别出越权风险" size="small" />
    </div>

    <div class="concl-col">
<!-- 列标题：放宽类 -->
      <div class="col-head relax"><t-icon name="unlock" /> 应放宽 · {{ list('relax').length }}</div>
<!-- 单条放宽建议：可勾选 -->
      <div v-for="(r, i) in list('relax')" :key="'rx' + i" class="concl-item" :class="{ on: selectable && isOn('relax', i) }">
        <t-checkbox v-if="selectable" :model-value="isOn('relax', i)" @change="v => emit('toggle', 'relax', i, v)" />
        <div class="ci-body">
          <div class="ci-line"><b>{{ r.scene || '-' }} / {{ r.tool || '-' }}</b>
            <t-tag size="small" variant="outline">{{ r.round_id }}</t-tag></div>
<!-- 被拦行为描述 -->
          <div class="dim">被拦行为：{{ r.blocked_behavior }}</div>
<!-- 放宽理由 -->
          <div>理由：{{ r.reason }}</div>
          <div class="ci-act">建议：{{ r.action }}</div>
        </div>
      </div>
<!-- 放宽列空态 -->
      <t-empty v-if="!list('relax').length" description="无需放宽项" size="small" />
    </div>

    <div class="concl-col">
<!-- 列标题：改造类 -->
      <div class="col-head trans"><t-icon name="edit-1" /> 策略改造 · {{ list('transform').length }}</div>
<!-- 单条改造建议：可勾选 -->
      <div v-for="(t, i) in list('transform')" :key="'tf' + i" class="concl-item" :class="{ on: selectable && isOn('transform', i) }">
        <t-checkbox v-if="selectable" :model-value="isOn('transform', i)" @change="v => emit('toggle', 'transform', i, v)" />
        <div class="ci-body">
<!-- 改造目标文件 -->
          <div class="ci-line"><b>{{ t.target }}</b>
<!-- 改造风险级标签 -->
            <t-tag :theme="sevTheme(t.risk_level)" size="small" variant="light">{{ t.risk_level }}</t-tag></div>
<!-- 字段路径（等宽） -->
          <div class="mono dim">{{ t.path }}</div>
<!-- 现值 → 建议值 -->
          <div class="ci-act">现值 → 建议值：{{ fmtVal(t.current) }} → {{ fmtVal(t.proposed) }}</div>
          <div class="dim">理由：{{ t.reason }}</div>
        </div>
      </div>
<!-- 改造列空态 -->
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

// 取某一类建议列表（空安全）
function list(cat) { return (props.result || {})[cat] || [] }
// 判断第 i 条是否已勾选
function isOn(cat, i) { return ((props.adopted || {})[cat] || []).includes(i) }
// 严重级 → 标签主题色
function sevTheme(s) { return s === 'high' ? 'danger' : s === 'medium' ? 'warning' : 'default' }
// 建议值格式化：数组逗号连接，空值 —
function fmtVal(v) { return Array.isArray(v) ? v.join(', ') : (v === '' || v === null || v === undefined ? '—' : String(v)) }
</script>

<style scoped>
/* 结论区纵排 */
.concl { display: flex; flex-direction: column; gap: 14px; }
/* 总体结论卡样式 */
.concl-summary { border: 1px solid #E5E7EB; border-radius: 10px; padding: 12px 14px; background: #FCFDFF; }
/* 结论列样式 */
.concl-col { border: 1px solid #E5E7EB; border-radius: 10px; padding: 12px 14px; }
/* 列头样式 */
.col-head { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 14px; margin-bottom: 10px; }
/* 收紧列红 */
.col-head.risk { color: #E34D59; }
/* 放宽列橙 */
.col-head.relax { color: #ED7B2F; }
/* 改造列蓝 */
.col-head.trans { color: #0052D9; }
/* 建议条目布局 */
.concl-item { display: flex; gap: 10px; align-items: flex-start; padding: 8px 10px; border-radius: 8px; transition: background .15s ease; }
.concl-item:hover { background: #F7F9FC; }
/* 勾选态背景 */
.concl-item.on { background: #F0F6FF; }
/* 建议正文弹性填充 */
.ci-body { flex: 1; font-size: 13px; }
/* 建议首行布局 */
.ci-line { display: flex; align-items: center; gap: 8px; }
/* 动作建议行 */
.ci-act { color: #1F2329; margin-top: 2px; }
.mono { font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; }
/* 弱化文本（结果视图） */
.dim { color: #A6A6A6; font-size: 12px; }
</style>
