<template>
  <div class="rsi">
    <!-- ① 机制说明 -->
    <div class="hero-card">
      <div class="hero-icon"><t-icon name="refresh" size="30px" /></div>
      <div class="hero-body">
        <h3>RSI 自进化 <span class="hero-sub">数据 → 分析 → 改造 → 回测 → 反馈</span></h3>
        <p>引用历史 <b>round_id</b> 的真实数据（query、IR、行为、判定与得分），结合角色说明与提示词，由 AI 判断
           <b>哪些越权需收紧</b>、<b>哪些策略应放宽</b>，并给出<b>字段级改造方向</b>；人工勾选后落到新建角色库，
           可回测对比改动前后效果，并作为下一轮进化的输入，形成可持续迭代链路。</p>
      </div>
      <t-button theme="default" variant="outline" @click="drawer = true">
        <template #icon><t-icon name="setting-1" /></template>AI 参数
      </t-button>
      <t-button theme="primary" variant="outline" @click="openOverwrite">
        <template #icon><t-icon name="layers" /></template>自进化角色覆盖
      </t-button>
    </div>

    <!-- 自进化角色覆盖对话框 -->
    <t-dialog v-model:visible="owVisible" header="自进化角色覆盖" :confirm-btn="{ content: '确认覆盖', theme: 'primary', loading: owBusy }"
              @confirm="doOverwrite" width="520px">
      <div class="ow-form">
        <label class="fi"><span>自进化角色（名含 _evolved_，作为内容来源）</span>
          <t-select v-model="owSource" :options="evolvedOptions" placeholder="选择自进化角色" />
        </label>
        <label class="fi"><span>基础角色（名不含 _evolved_，被覆盖并沿用其名）</span>
          <t-select v-model="owTarget" :options="baseRoleOptions" placeholder="选择要覆盖的基础角色" />
        </label>
        <div class="dim">覆盖后：基础角色的 policy_registry 内容被替换为自进化角色内容，角色名保持不变；
          目标为当前生效角色时自动热重载。覆盖前自动备份到 policies/.backups/。</div>
      </div>
    </t-dialog>

    <t-steps :current="step" class="rsi-steps" @change="onStepChange">
      <t-step-item title="选样本" content="检索并选择 round_id" />
      <t-step-item title="上下文" content="汇聚数据与策略摘要" />
      <t-step-item title="AI 分析" content="风险 / 放宽 / 改造" />
      <t-step-item title="评审" content="勾选并生成变更计划" />
      <t-step-item title="应用" content="新建角色库并校验" />
      <t-step-item title="回测归档" content="对比与迭代历史" />
    </t-steps>

    <!-- ② 步骤 0：选样本 -->
    <div class="panel" v-show="step === 0">
      <div class="panel-head"><t-icon name="search" /> 步骤 1 · 选择分析样本</div>
      <div class="filter-bar role-bar">
        <label class="fi role-first"><span>① 选择角色（必选，决定 trace 过滤与进化基线）</span>
          <t-select v-model="selRole" size="small" class="w220" placeholder="先选择角色" clearable
                    :options="baseOptions" @change="onRoleChange" />
        </label>
      </div>
      <div class="filter-bar">
        <t-input v-model="f.round_id" size="small" class="w180" placeholder="round_id" clearable
                 :disabled="!selRole" @enter="loadRounds" />
        <t-input v-model="f.query" size="small" class="w220" placeholder="关键字（user_query）" clearable
                 :disabled="!selRole" @enter="loadRounds" />
        <t-checkbox v-model="f.abnormal" :disabled="!selRole">仅异常</t-checkbox>
        <t-input v-model="f.time_from" size="small" class="w180" placeholder="起始时间 2026-10-01" clearable :disabled="!selRole" />
        <t-input v-model="f.time_to" size="small" class="w180" placeholder="结束时间" clearable :disabled="!selRole" />
        <t-button size="small" theme="primary" :disabled="!selRole" @click="loadRounds">检索</t-button>
        <span class="dim">已选 {{ selected.length }} 条（最多 50）</span>
      </div>
      <t-table v-if="selRole" :data="rounds" :columns="roundCols" row-key="round_id" size="small" bordered
               class="rsi-table" :selected-row-keys="selected" @select-change="onSelect" select-on-row-click>
      </t-table>
      <div v-else class="dim" style="padding: 18px 0;">请先在上方选择角色，仅展示该角色（策略库）生效期间产生的 round。</div>
      <div class="form-grid">
        <label class="fi"><span>角色说明</span>
          <t-input v-model="roleDesc" placeholder="如：只读数据分析师，仅可读取 /data" />
        </label>
        <label class="fi"><span>用户提示词</span>
          <t-input v-model="userPrompt" placeholder="如：重点收紧文件写入，放宽只读查询" />
        </label>
      </div>
      <div class="row-actions">
        <t-button theme="primary" :disabled="!selected.length" @click="gotoContext">
          <template #icon><t-icon name="arrow-right" /></template>下一步：汇聚上下文
        </t-button>
      </div>
    </div>

    <!-- ③ 步骤 1：上下文 -->
    <div class="panel" v-show="step === 1">
      <div class="panel-head"><t-icon name="layers" /> 步骤 2 · 上下文汇聚</div>
      <div class="ctx-grid">
        <div class="ctx-card">
          <div class="ctx-title">参与样本</div>
          <div class="ctx-num">{{ ctx?.items?.length || 0 }}</div>
          <div class="dim">条 round</div>
        </div>
        <div class="ctx-card">
          <div class="ctx-title">策略库场景</div>
          <div class="ctx-num">{{ ctx?.policy_summary?.scenes?.length || 0 }}</div>
          <div class="dim">{{ ctx?.policy_summary?.policy || '-' }}</div>
        </div>
        <div class="ctx-card">
          <div class="ctx-title">工具文件</div>
          <div class="ctx-num">{{ Object.keys(ctx?.policy_summary?.tools || {}).length }}</div>
          <div class="dim">个 tools/*.json</div>
        </div>
      </div>
      <details class="fold" open>
        <summary>样本明细（含 IR 摘要与行为）</summary>
        <div v-for="it in ctx?.items || []" :key="it.round_id" class="ctx-item">
          <div class="ctx-item-head">
            <t-tag size="small" variant="outline">{{ it.round_id }}</t-tag>
            <span class="dim">{{ it.time_start }}</span>
            <span :class="scoreClass(it.overall_score)">{{ fmtScore(it.overall_score) }}</span>
          </div>
          <div class="ctx-q">{{ it.user_query || '(无 query)' }}</div>
          <div class="dim behaviors">行为：{{ (it.behaviors || []).join(' | ') || '—' }}</div>
        </div>
      </details>
      <div class="row-actions">
        <t-button theme="primary" :loading="busy" :disabled="!ctx" @click="doAnalyze">
          <template #icon><t-icon name="bulb" /></template>开始 AI 分析
        </t-button>
        <span v-if="analyzeErr" class="err">分析失败：{{ analyzeErr }}（可在 AI 参数中检查模型配置）</span>
      </div>
    </div>

    <!-- ④ 步骤 2/3：AI 分析与评审 -->
    <div class="panel" v-show="step === 2 || step === 3">
      <div class="panel-head"><t-icon name="dashboard" /> 步骤 3 · AI 分析结论</div>
      <div class="stream" v-if="streamText"><pre>{{ streamText }}</pre></div>
      <div v-if="result" class="concl">
        <div class="concl-summary">
          <div class="dim">总体结论</div>
          <div>{{ result.summary || '—' }}</div>
          <div class="dim" v-if="result.assumptions">假设：{{ result.assumptions }}</div>
        </div>

        <div class="concl-col">
          <div class="col-head risk"><t-icon name="error-circle" /> 越权风险（收紧） · {{ result.risks.length }}</div>
          <div v-for="(r, i) in result.risks" :key="'rk' + i" class="concl-item" :class="{ on: adopted.risks.includes(i) }">
            <t-checkbox :model-value="adopted.risks.includes(i)" @change="v => toggle('risks', i, v)" />
            <div class="ci-body">
              <div class="ci-line"><b>{{ r.scene || '-' }} / {{ r.tool || '-' }}</b>
                <t-tag :theme="sevTheme(r.severity)" size="small" variant="light">{{ r.severity }}</t-tag>
                <t-tag size="small" variant="outline">{{ r.round_id }}</t-tag></div>
              <div class="dim">行为：{{ r.behavior }}</div>
              <div>越权点：{{ r.violation }}</div>
              <div class="ci-act">建议：{{ r.action }}</div>
            </div>
          </div>
          <t-empty v-if="!result.risks.length" description="未识别出越权风险" size="small" />
        </div>

        <div class="concl-col">
          <div class="col-head relax"><t-icon name="unlock" /> 应放宽 · {{ result.relax.length }}</div>
          <div v-for="(r, i) in result.relax" :key="'rx' + i" class="concl-item" :class="{ on: adopted.relax.includes(i) }">
            <t-checkbox :model-value="adopted.relax.includes(i)" @change="v => toggle('relax', i, v)" />
            <div class="ci-body">
              <div class="ci-line"><b>{{ r.scene || '-' }} / {{ r.tool || '-' }}</b>
                <t-tag size="small" variant="outline">{{ r.round_id }}</t-tag></div>
              <div class="dim">被拦行为：{{ r.blocked_behavior }}</div>
              <div>理由：{{ r.reason }}</div>
              <div class="ci-act">建议：{{ r.action }}</div>
            </div>
          </div>
          <t-empty v-if="!result.relax.length" description="无需放宽项" size="small" />
        </div>

        <div class="concl-col">
          <div class="col-head trans"><t-icon name="edit-1" /> 策略改造 · {{ result.transform.length }}</div>
          <div v-for="(t, i) in result.transform" :key="'tf' + i" class="concl-item" :class="{ on: adopted.transform.includes(i) }">
            <t-checkbox :model-value="adopted.transform.includes(i)" @change="v => toggle('transform', i, v)" />
            <div class="ci-body">
              <div class="ci-line"><b>{{ t.target }}</b>
                <t-tag :theme="sevTheme(t.risk_level)" size="small" variant="light">{{ t.risk_level }}</t-tag></div>
              <div class="mono dim">{{ t.path }}</div>
              <div class="ci-act">现值 → 建议值：{{ fmtVal(t.current) }} → {{ fmtVal(t.proposed) }}</div>
              <div class="dim">理由：{{ t.reason }}</div>
            </div>
          </div>
          <t-empty v-if="!result.transform.length" description="无改造建议" size="small" />
        </div>
      </div>
      <div class="row-actions">
        <t-button theme="primary" :disabled="!result" @click="doPlan">
          <template #icon><t-icon name="check" /></template>生成变更计划（{{ adoptedCount }} 项已勾选）
        </t-button>
      </div>
      <div v-if="plan?.changes?.length" class="plan">
        <div class="plan-head">
          变更计划（{{ plan.changes.length }} 条）
          <span class="dim">
            可直接落盘 {{ plan.changes.filter((c) => c.path).length }} 条 ·
            需补字段路径 {{ plan.changes.filter((c) => !c.path).length }} 条（在表格中补全 path 与建议值后即可一并应用）
          </span>
        </div>
        <t-table :data="plan.changes" :columns="planCols" row-key="idx" size="small" bordered class="rsi-table">
          <template #kind="{ row }">
            <t-tag :theme="kindTheme(row.kind)" size="small" variant="light">{{ row.kind }}</t-tag>
          </template>
          <template #path="{ row }">
            <t-input v-model="row.path" size="small" placeholder="点分路径，如 functions.exec.params.command.constraint_spec.static.denylist" />
          </template>
          <template #proposed="{ row }">
            <t-input v-model="row.proposedTxt" size="small" :placeholder="'建议值（JSON，如 [&quot;/data/analytics/**&quot;]）'"
                     @change="(v) => (row.proposedTxt = v)" />
          </template>
          <template #risk="{ row }">
            <t-tag :theme="sevTheme(row.risk_level)" size="small" variant="light">{{ row.risk_level }}</t-tag>
          </template>
        </t-table>
      </div>
      <div class="row-actions" v-if="plan?.changes?.length">
        <t-button theme="primary" @click="step = 4">
          <template #icon><t-icon name="arrow-right" /></template>下一步：应用
        </t-button>
        <span class="dim">提示：建议值请填合法 JSON（数组加方括号），字符串可省略引号</span>
      </div>
    </div>

    <!-- ⑤ 步骤 4：应用 -->
    <div class="panel" v-show="step === 4">
      <div class="panel-head"><t-icon name="save" /> 步骤 4 · 应用到新建角色库</div>
      <div class="form-grid">
        <label class="fi"><span>进化后角色名（自动生成：原角色名_evolved_月日时分，不可修改）</span>
          <t-input :value="evolvedName" readonly />
        </label>
        <label class="fi"><span>基线</span>
          <t-select v-model="base" :options="baseOptions" />
        </label>
        <label class="fi"><span>角色标题</span>
          <t-input v-model="roleTitle" placeholder="如：进化后的只读分析师" />
        </label>
      </div>
      <div class="row-actions">
        <t-button theme="primary" :loading="busy" :disabled="!evolvedName || !plan?.changes?.length" @click="doApply">
          <template #icon><t-icon name="check-circle" /></template>新建角色库并应用
        </t-button>
        <span class="dim">角色名带时间戳全局唯一，无需强制重建；如需生效可稍后用右上角「自进化角色覆盖」合入基础角色</span>
      </div>
      <div v-if="applied" class="result-box">
        <t-tag theme="success" variant="light">已应用</t-tag>
        <code>{{ applied.path }}</code>
        <span class="dim">落盘 {{ applied.applied?.length || 0 }} 条 · 需人工 {{ applied.manual?.length || 0 }} 条 · 校验 {{ applied.validation?.ok ? '通过' : '存在阻断错误' }}</span>
        <div v-for="e in applied.errors || []" :key="e" class="err">· {{ e }}</div>
        <div v-for="m in applied.manual || []" :key="m.reason" class="dim">· 需人工处理：{{ m.reason }}</div>
      </div>
      <div v-if="applied?.validation" class="validate-box">
        <div class="v-line" :class="applied.validation.ok ? 'ok' : 'err'">
          <t-icon :name="applied.validation.ok ? 'check-circle' : 'close-circle'" />
          结构校验：{{ applied.validation.ok ? '通过' : '存在阻断级错误' }}
        </div>
        <div v-for="e in applied.validation.errors || []" :key="e" class="v-item err"><t-tag theme="danger" size="small">E</t-tag>{{ e }}</div>
        <div v-for="w in applied.validation.warnings || []" :key="w" class="v-item warn"><t-tag theme="warning" size="small">W</t-tag>{{ w }}</div>
      </div>
    </div>

    <!-- ⑥ 步骤 5：回测与历史 -->
    <div class="panel" v-show="step === 5">
      <div class="panel-head"><t-icon name="chart-bar" /> 步骤 5 · 归档与自测</div>
      <div class="row-actions">
        <t-button theme="default" variant="outline" @click="doSaveRun">归档本轮进化</t-button>
        <span v-if="savedRun" class="dim">已归档：{{ savedRun }}</span>
        <t-button v-if="savedRun" theme="primary" variant="outline" @click="startNextRound">
          <template #icon><t-icon name="arrow-right" /></template>开始下一轮迭代
        </t-button>
        <span v-if="savedRun" class="dim">下一轮将以 {{ evolvedName }} 为角色，并自动带入本轮改进上下文</span>
      </div>
      <div v-if="savedRun" class="hist">
        <div class="plan-head">回测建议（自行验证）</div>
        <div class="dim" style="margin: 6px 0;">
          角色库 <code>{{ evolvedName }}</code> 已生成。建议将下列原始 query 重新执行（把该角色「自进化角色覆盖」到基础角色，
          或切换生效后重跑），对比判定结果：攻击类应被拦截、合法类应正常放行，即本轮进化有效。
        </div>
        <t-table :data="ctx?.items || []" :columns="selfTestCols" row-key="round_id" size="small" bordered class="rsi-table">
          <template #score="{ row }"><span :class="scoreClass(row.overall_score)">{{ fmtScore(row.overall_score) }}</span></template>
          <template #ab="{ row }">{{ row.is_abnormal === 1 ? "异常" : row.is_abnormal === 0 ? "正常" : "—" }}</template>
        </t-table>
      </div>
    </div>

    <RsiConfigDrawer v-model:visible="drawer" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
import { MessagePlugin } from "tdesign-vue-next"
import RsiConfigDrawer from "./RsiConfigDrawer.vue"

const ADMIN_HEAD = () => ({
  "Content-Type": "application/json",
  "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "",
})

const step = ref(0)
const drawer = ref(false)
const busy = ref(false)
const rounds = ref([])
const selected = ref([])
const f = ref({ round_id: "", query: "", abnormal: false, time_from: "", time_to: "" })
const selRole = ref("")
const policyList = ref([])
const roleDesc = ref("")
const userPrompt = ref("")
const parentFeedback = ref("")
const ctx = ref(null)
const result = ref(null)
const streamText = ref("")
const analyzeErr = ref("")
const adopted = ref({ risks: [], relax: [], transform: [] })
const plan = ref(null)
const role = ref("")
const base = ref("default")
const roleTitle = ref("")
const evolvedName = ref("")
const applied = ref(null)
const savedRun = ref("")

const baseOptions = computed(() => {
  const opts = policyList.value.map((p) => ({ label: p.name, value: p.name }))
  return opts.length ? opts : [{ label: "default", value: "default" }, { label: "ops", value: "ops" }]
})

const roundCols = [
  { colKey: "row-select", type: "multiple", width: 46 },
  { colKey: "round_id", title: "round_id", width: 150 },
  { colKey: "time_start", title: "时间", width: 170 },
  { colKey: "user_query", title: "用户请求", ellipsis: true },
]
const planCols = [
  { colKey: "kind", title: "类型", width: 90 },
  { colKey: "target", title: "目标文件", width: 170 },
  { colKey: "path", title: "字段路径（可编辑）", width: 300 },
  { colKey: "proposed", title: "建议值（可编辑）", width: 240 },
  { colKey: "reason", title: "理由", ellipsis: true },
  { colKey: "risk", title: "风险", width: 80 },
]
const selfTestCols = [
  { colKey: "round_id", title: "round_id", width: 150 },
  { colKey: "user_query", title: "原始 query（重新执行以自测）", ellipsis: true },
  { colKey: "score", title: "原得分", width: 90 },
  { colKey: "ab", title: "原判定", width: 90 },
]

const adoptedCount = computed(() => adopted.value.risks.length + adopted.value.relax.length + adopted.value.transform.length)

function fmtScore(v) { return v === null || v === undefined || v === "" ? "—" : Number(v).toFixed(2) }
function scoreClass(v) { const n = Number(v); return !isFinite(n) ? "dim" : (n >= 0.5 ? "ok-t" : "err-t") }
function sevTheme(s) { return s === "high" ? "danger" : s === "medium" ? "warning" : "default" }
function kindTheme(k) { return k === "tighten" ? "danger" : k === "relax" ? "warning" : "primary" }
function fmtVal(v) { return Array.isArray(v) ? v.join(", ") : (v === "" || v === null || v === undefined ? "—" : String(v)) }
function toggle(cat, i, on) {
  const arr = new Set(adopted.value[cat])
  on ? arr.add(i) : arr.delete(i)
  adopted.value[cat] = [...arr]
}
function onStepChange(v) { if (typeof v === "number") step.value = v }

async function jfetch(url, opts = {}) {
  const r = await fetch(url, opts)
  const j = await r.json().catch(() => ({ ok: false, error: "响应解析失败" }))
  if (!j.ok && j.error) MessagePlugin.error(j.error)
  return j
}

async function loadRounds() {
  if (!selRole.value) { rounds.value = []; return }
  const p = new URLSearchParams({ limit: "50", role: selRole.value })
  if (f.value.round_id) p.set("round_id", f.value.round_id)
  if (f.value.query) p.set("query", f.value.query)
  if (f.value.abnormal) p.set("abnormal", "true")
  if (f.value.time_from) p.set("time_from", f.value.time_from)
  if (f.value.time_to) p.set("time_to", f.value.time_to)
  const j = await jfetch(`/api/rounds?${p.toString()}`)
  if (j.ok) rounds.value = j.data
}

async function loadPolicies() {
  try {
    const r = await fetch("/api/translator/policies")
    const j = await r.json()
    if (j.ok) policyList.value = (j.data?.policies || []).filter((x) => x.name !== "skilltrust")
  } catch (e) { /* 忽略：下拉回退到 default/ops */ }
}

// ── 自进化角色覆盖 ──
const owVisible = ref(false)
const owBusy = ref(false)
const owSource = ref("")
const owTarget = ref("")
const evolvedOptions = computed(() => policyList.value.filter((p) => p.name.includes("_evolved_")).map((p) => ({ label: p.name, value: p.name })))
const baseRoleOptions = computed(() => policyList.value
  .filter((p) => !p.name.includes("_evolved_") && !["default", "ops"].includes(p.name))
  .map((p) => ({ label: p.name, value: p.name })))

function openOverwrite() {
  owSource.value = ""; owTarget.value = ""
  loadPolicies().then(() => {
    if (!owSource.value && evolvedOptions.value.length) owSource.value = evolvedOptions.value[0].value
    if (!owTarget.value && baseRoleOptions.value.length) owTarget.value = baseRoleOptions.value[0].value
  })
  owVisible.value = true
}

async function doOverwrite() {
  if (!owSource.value || !owTarget.value) { MessagePlugin.warning("请选择源角色与目标角色"); return }
  owBusy.value = true
  try {
    const j = await jfetch("/api/translator/policies/overwrite", {
      method: "POST", headers: ADMIN_HEAD(),
      body: JSON.stringify({ source: owSource.value, target: owTarget.value }),
    })
    if (j.ok) {
      MessagePlugin.success(`已覆盖：${owSource.value} → ${owTarget.value}${j.data?.hot_reloaded ? "（已热重载）" : ""}`)
      owVisible.value = false
      loadPolicies()
    }
  } finally { owBusy.value = false }
}

function onRoleChange() {
  // 先选角色：切换角色后清空已选样本并仅加载该角色的 round
  selected.value = []
  loadRounds()
  // 联动应用表单：基线=所选角色库，产物名在生成计划时按时间戳生成
  if (selRole.value) base.value = selRole.value
}

// 手工项（tighten/relax 缺字段路径）在评审表格中可编辑 path / 建议值
function tryParseVal(s) {
  if (typeof s !== "string") return s
  const t = s.trim()
  try { return JSON.parse(t) } catch (e) { return s }
}

function onSelect(keys) { selected.value = keys }

async function gotoContext() {
  busy.value = true
  try {
    const j = await jfetch("/api/translator/rsi/context", {
      method: "POST", headers: ADMIN_HEAD(),
      body: JSON.stringify({ round_ids: selected.value, role_desc: roleDesc.value,
                             user_prompt: userPrompt.value, parent_feedback: parentFeedback.value }),
    })
    if (j.ok) { ctx.value = j.data; step.value = 1 }
  } finally { busy.value = false }
}

async function ssePost(url, body) {
  const r = await fetch(url, { method: "POST", headers: ADMIN_HEAD(), body: JSON.stringify(body) })
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = "", done = null
  while (true) {
    const { value, done: fin } = await reader.read()
    if (fin) break
    buf += dec.decode(value, { stream: true })
    const parts = buf.split("\n\n")
    buf = parts.pop() || ""
    for (const p of parts) {
      const line = p.split("\n").find(l => l.startsWith("data: "))
      if (!line) continue
      const ev = JSON.parse(line.slice(6))
      if (ev.type === "text") streamText.value = ev.data
      else if (ev.type === "error") { analyzeErr.value = ev.message || "分析失败"; MessagePlugin.error(analyzeErr.value) }
      else if (ev.type === "done") done = ev.data
    }
  }
  return done
}

async function doAnalyze() {
  busy.value = true; analyzeErr.value = ""; streamText.value = ""
  try {
    const data = await ssePost("/api/translator/rsi/analyze", {
      round_ids: selected.value, role_desc: roleDesc.value,
      user_prompt: userPrompt.value, parent_feedback: parentFeedback.value,
    })
    if (data?.result) {
      result.value = data.result
      adopted.value = { risks: [], relax: [], transform: [] }
      step.value = 2
      MessagePlugin.success("AI 分析完成")
    }
  } catch (e) { MessagePlugin.error(String(e)) } finally { busy.value = false }
}

async function doPlan() {
  const j = await jfetch("/api/translator/rsi/plan", {
    method: "POST", headers: ADMIN_HEAD(),
    body: JSON.stringify({ result: result.value, adopted: adopted.value }),
  })
  if (j.ok) {
    // proposedTxt 供表格内编辑；proposed 保留原值作为回退
    plan.value = { ...j.data, changes: (j.data?.changes || []).map((c) => ({
      ...c, proposedTxt: typeof c.proposed === "string" ? c.proposed : JSON.stringify(c.proposed),
    })) }
    step.value = 3
    // 按选定角色预填应用表单：基线=该角色库，产物名=原角色名_evolved_月日时分（固定不可改）
    if (selRole.value) {
      base.value = selRole.value
      const p = (n) => String(n).padStart(2, "0")
      const d = new Date()
      evolvedName.value = `${selRole.value}_evolved_${p(d.getMonth() + 1)}${p(d.getDate())}${p(d.getHours())}${p(d.getMinutes())}`
      if (!roleTitle.value) roleTitle.value = "进化后的角色库"
    }
  }
}

async function doApply() {
  busy.value = true
  try {
    const changes = (plan.value?.changes || []).map((c) => ({
      ...c, proposed: tryParseVal(c.proposedTxt ?? c.proposed),
    }))
    if (!base.value) base.value = selRole.value || "default"
    const j = await jfetch("/api/translator/rsi/apply", {
      method: "POST", headers: ADMIN_HEAD(),
      body: JSON.stringify({ role: evolvedName.value, base: base.value, title: roleTitle.value,
                             force: false, changes }),
    })
    if (j.ok) { applied.value = j.data; MessagePlugin.success("已应用并校验完成"); step.value = 4 }
  } finally { busy.value = false }
}

async function doSaveRun() {
  const j = await jfetch("/api/translator/rsi/runs", {
    method: "POST", headers: ADMIN_HEAD(),
    body: JSON.stringify({
      role: evolvedName.value, base: base.value, round_ids: selected.value,
      role_desc: roleDesc.value, user_prompt: userPrompt.value, parent_feedback: parentFeedback.value,
      ai_result: result.value, adopted: plan.value?.changes || [], applied: applied.value,
      backtest: { enabled: false }, status: "applied",
    }),
  })
  if (j.ok) { savedRun.value = j.data.run_id; MessagePlugin.success(`已归档 ${j.data.run_id}`) }
}

// 开始下一轮：以本轮新建的进化角色为新角色，自动带入本轮改进上下文作为反馈
function startNextRound() {
  const summary = (result.value?.summary || "").trim()
  const parts = []
  if (savedRun.value) parts.push(`上一轮归档 ${savedRun.value}`)
  if (evolvedName.value) parts.push(`进化角色 ${evolvedName.value}（基线 ${base.value}）`)
  if (summary) parts.push(`改进摘要：${summary}`)
  parentFeedback.value = parts.join("；")
  loadPolicies().then(() => {
    if (evolvedName.value) {
      selRole.value = evolvedName.value
      base.value = evolvedName.value
      onRoleChange()
    }
  })
  selected.value = []
  result.value = null; plan.value = null; applied.value = null
  savedRun.value = ""; evolvedName.value = ""
  step.value = 0
  MessagePlugin.success("已带入本轮改进上下文，开始下一轮迭代")
}

onMounted(() => { loadPolicies() })
</script>

<style scoped>
.rsi { display: flex; flex-direction: column; gap: 16px; }
.hero-card { display: flex; align-items: flex-start; gap: 14px; padding: 18px 20px; border-radius: 14px;
  background: linear-gradient(135deg, #E8F0FE 0%, #F7FAFF 55%, #FFFFFF 100%);
  border: 1px solid #DCE6F7; box-shadow: 0 2px 10px rgba(0, 82, 217, .06); }
.hero-icon { flex: 0 0 46px; height: 46px; border-radius: 12px; display: grid; place-items: center;
  background: linear-gradient(135deg, #0052D9, #366EF4); color: #fff; }
.hero-body { flex: 1; }
.hero-body h3 { margin: 0 0 6px; font-size: 20px; font-weight: 600; color: #1F2329; }
.hero-sub { font-size: 13px; font-weight: 400; color: #4E5969; margin-left: 8px; }
.hero-body p { margin: 0; font-size: 14px; line-height: 1.7; color: #4E5969; }
.rsi-steps { padding: 6px 0 10px; }
.panel { background: #fff; border: 1px solid #E5E7EB; border-radius: 12px; padding: 16px 18px; }
.panel-head { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600;
  color: #1F2329; margin-bottom: 14px; }
.filter-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.w180 { width: 180px; } .w220 { width: 220px; }
.role-bar { margin-bottom: 2px; }
.role-first { width: 320px; font-weight: 500; color: #1F2329; }
.rsi-table { margin-top: 6px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 14px; }
.fi { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: #4E5969; }
.row-actions { display: flex; align-items: center; gap: 12px; margin-top: 14px; flex-wrap: wrap; }
.dim { color: #A6A6A6; font-size: 12px; }
.err { color: #E34D59; font-size: 13px; }
.ok-t { color: #00A870; font-weight: 600; }
.err-t { color: #E34D59; font-weight: 600; }
.ctx-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.ctx-card { border: 1px solid #E5E7EB; border-radius: 10px; padding: 12px 14px; background: #FCFDFF; }
.ctx-title { font-size: 12px; color: #4E5969; }
.ctx-num { font-size: 22px; font-weight: 600; color: #0052D9; line-height: 1.4; }
.fold { margin-top: 14px; border: 1px solid #E5E7EB; border-radius: 10px; padding: 10px 14px; background: #FCFDFF; }
.fold summary { cursor: pointer; font-size: 13px; font-weight: 600; color: #1F2329; }
.ctx-item { border-top: 1px dashed #E5E7EB; padding: 10px 0; }
.ctx-item:first-of-type { border-top: none; }
.ctx-item-head { display: flex; align-items: center; gap: 10px; }
.ctx-q { font-size: 13px; color: #1F2329; margin-top: 4px; }
.behaviors { margin-top: 4px; }
.stream pre { margin: 0; padding: 12px; border-radius: 8px; background: #0F172A; color: #CBD5E1;
  font-size: 12px; max-height: 260px; overflow: auto; }
.concl { display: flex; flex-direction: column; gap: 14px; }
.concl-summary { border: 1px solid #E5E7EB; border-radius: 10px; padding: 12px 14px; background: #FCFDFF; }
.concl-col { border: 1px solid #E5E7EB; border-radius: 10px; padding: 12px 14px; }
.col-head { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 14px; margin-bottom: 10px; }
.col-head.risk { color: #E34D59; }
.col-head.relax { color: #ED7B2F; }
.col-head.trans { color: #0052D9; }
.concl-item { display: flex; gap: 10px; align-items: flex-start; padding: 8px 10px; border-radius: 8px;
  transition: background .15s ease; }
.concl-item:hover { background: #F7F9FC; }
.concl-item.on { background: #F0F6FF; }
.ci-body { flex: 1; font-size: 13px; }
.ci-line { display: flex; align-items: center; gap: 8px; }
.ci-act { color: #1F2329; margin-top: 2px; }
.mono { font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; }
.plan, .hist { margin-top: 16px; }
.plan-head { font-size: 13px; font-weight: 600; color: #1F2329; margin-bottom: 8px; }
.result-box { display: flex; align-items: center; gap: 10px; margin-top: 14px; font-size: 13px; flex-wrap: wrap; }
.result-box code { background: #F7F9FC; padding: 2px 8px; border-radius: 6px; }
.validate-box { margin-top: 14px; display: flex; flex-direction: column; gap: 6px; }
.v-line { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 500; }
.v-line.ok { color: #00A870; } .v-line.err { color: #E34D59; }
.v-item { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.v-item.err { color: #E34D59; } .v-item.warn { color: #ED7B2F; }
</style>
