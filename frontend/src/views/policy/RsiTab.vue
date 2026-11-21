<template>
  <div class="rsi">
    <!-- ① 机制说明 -->
    <div class="hero-card">
<!-- 图标托盘：进化循环语义 -->
      <div class="hero-icon"><t-icon name="refresh" size="30px" /></div>
<!-- 说明主体：标题 + 五步闭环说明 -->
      <div class="hero-body">
<!-- 标题 + 副标题：五步闭环（数据→分析→改造→回测→反馈） -->
        <h3>RSI 自进化 <span class="hero-sub">数据 → 分析 → 改造 → 回测 → 反馈</span></h3>
<!-- 机制说明段：强调引用真实判定数据与人工勾选后才落库 -->
<!-- 产物为新建角色库，可回测对比，并作为下一轮进化输入 -->
        <p>引用历史 <b>round_id</b> 的真实数据（query、IR、行为、判定与得分），结合角色说明与提示词，由 AI 判断
           <b>哪些越权需收紧</b>、<b>哪些策略应放宽</b>，并给出<b>字段级改造方向</b>；人工勾选后落到新建角色库，
           可回测对比改动前后效果，并作为下一轮进化的输入，形成可持续迭代链路。</p>
      </div>
<!-- AI 参数按钮：模型/端点配置抽屉 -->
      <t-button theme="default" variant="outline" @click="drawer = true">
        <template #icon><t-icon name="setting-1" /></template>AI 参数
      </t-button>
<!-- 自进化角色覆盖按钮：把进化产物合入基础角色 -->
      <t-button theme="primary" variant="outline" @click="openOverwrite">
        <template #icon><t-icon name="layers" /></template>自进化角色覆盖
      </t-button>
    </div>

    <!-- 自进化角色覆盖对话框 -->
    <t-dialog v-model:visible="owVisible" header="自进化角色覆盖" :confirm-btn="{ content: '确认覆盖', theme: 'primary', loading: owBusy }"
              @confirm="doOverwrite" width="520px">
      <div class="ow-form">
<!-- 源角色选择：仅列 _evolved_ 角色 -->
        <label class="fi"><span>自进化角色（名含 _evolved_，作为内容来源）</span>
<!-- 覆盖源角色选择 -->
          <t-select v-model="owSource" :options="evolvedOptions" placeholder="选择自进化角色" />
        </label>
<!-- 目标角色选择：不含 _evolved_ 且非内置 default/ops -->
        <label class="fi"><span>基础角色（名不含 _evolved_，被覆盖并沿用其名）</span>
<!-- 覆盖目标角色选择 -->
          <t-select v-model="owTarget" :options="baseRoleOptions" placeholder="选择要覆盖的基础角色" />
        </label>
<!-- 覆盖语义说明：内容替换、角色名不变、热重载、自动备份 -->
        <div class="dim">覆盖后：基础角色的 policy_registry 内容被替换为自进化角色内容，角色名保持不变；
          目标为当前生效角色时自动热重载。覆盖前自动备份到 policies/.backups/。</div>
      </div>
    </t-dialog>

<!-- 步骤条容器：六步，点击可回跳 -->
    <t-steps :current="step" class="rsi-steps" @change="onStepChange">
<!-- 步骤条项 1：选样本 -->
      <t-step-item title="选样本" content="检索并选择 round_id" />
<!-- 步骤条项 2：上下文 -->
      <t-step-item title="上下文" content="汇聚数据与策略摘要" />
<!-- 步骤条项 3：AI 分析 -->
      <t-step-item title="AI 分析" content="风险 / 放宽 / 改造" />
<!-- 步骤条项 4：评审 -->
      <t-step-item title="评审" content="勾选并生成变更计划" />
<!-- 步骤条项 5：应用 -->
      <t-step-item title="应用" content="新建角色库并校验" />
<!-- 步骤条项 6：回测归档 -->
      <t-step-item title="回测归档" content="对比与迭代历史" />
    </t-steps>

    <!-- ② 步骤 0：选样本 -->
    <div class="panel" v-show="step === 0">
<!-- 面板头：步骤 1 选样本 -->
      <div class="panel-head"><t-icon name="search" /> 步骤 1 · 选择分析样本</div>
<!-- 角色选择栏：决定 round 过滤范围与进化基线 -->
      <div class="filter-bar role-bar">
<!-- 角色下拉：必选，切换后清空已选样本 -->
        <label class="fi role-first"><span>① 选择角色（必选，决定 trace 过滤与进化基线）</span>
<!-- 角色选择：样本过滤与基线联动的源头 -->
          <t-select v-model="selRole" size="small" class="w220" placeholder="先选择角色" clearable
                    :options="baseOptions" @change="onRoleChange" />
        </label>
      </div>
<!-- 检索条件栏：round_id / 关键字 / 仅异常 / 时间区间 -->
      <div class="filter-bar">
<!-- round_id 输入：精确过滤 -->
        <t-input v-model="f.round_id" size="small" class="w180" placeholder="round_id" clearable
                 :disabled="!selRole" @enter="loadRounds" />
<!-- 关键字输入：user_query 模糊过滤 -->
        <t-input v-model="f.query" size="small" class="w220" placeholder="关键字（user_query）" clearable
                 :disabled="!selRole" @enter="loadRounds" />
<!-- 仅异常勾选：只看判定异常的 round -->
        <t-checkbox v-model="f.abnormal" :disabled="!selRole">仅异常</t-checkbox>
<!-- 起始时间输入 -->
        <t-input v-model="f.time_from" size="small" class="w180" placeholder="起始时间 2026-10-01" clearable :disabled="!selRole" />
<!-- 结束时间输入 -->
        <t-input v-model="f.time_to" size="small" class="w180" placeholder="结束时间" clearable :disabled="!selRole" />
<!-- 检索按钮：触发样本拉取 -->
        <t-button size="small" theme="primary" :disabled="!selRole" @click="loadRounds">检索</t-button>
<!-- 已选计数：上限 50 条 -->
        <span class="dim">已选 {{ selected.length }} 条（最多 50）</span>
      </div>
<!-- 样本表：行点击即选中，selected-row-keys 双向 -->
      <t-table v-if="selRole" :data="rounds" :columns="roundCols" row-key="round_id" size="small" bordered
               class="rsi-table" :selected-row-keys="selected" @select-change="onSelect" select-on-row-click>
      </t-table>
<!-- 未选角色提示 -->
      <div v-else class="dim" style="padding: 18px 0;">请先在上方选择角色，仅展示该角色（策略库）生效期间产生的 round。</div>
      <div class="form-grid">
<!-- 角色说明输入：注入进化提示词（角色定位一句话） -->
        <label class="fi"><span>角色说明</span>
<!-- 角色说明输入框 -->
          <t-input v-model="roleDesc" placeholder="如：只读数据分析师，仅可读取 /data" />
        </label>
<!-- 用户提示词输入：本轮进化的重点方向 -->
        <label class="fi"><span>用户提示词</span>
<!-- 用户提示词输入框 -->
          <t-input v-model="userPrompt" placeholder="如：重点收紧文件写入，放宽只读查询" />
        </label>
      </div>
      <div class="row-actions">
<!-- 下一步按钮：有选中样本才可用 -->
        <t-button theme="primary" :disabled="!selected.length" @click="gotoContext">
          <template #icon><t-icon name="arrow-right" /></template>下一步：汇聚上下文
        </t-button>
      </div>
    </div>

    <!-- ③ 步骤 1：上下文 -->
    <div class="panel" v-show="step === 1">
<!-- 面板头：步骤 2 上下文 -->
      <div class="panel-head"><t-icon name="layers" /> 步骤 2 · 上下文汇聚</div>
<!-- 上下文统计三卡：样本数/场景数/工具文件数 -->
      <div class="ctx-grid">
        <div class="ctx-card">
<!-- 卡 1：参与样本数 -->
          <div class="ctx-title">参与样本</div>
<!-- 参与样本数 -->
          <div class="ctx-num">{{ ctx?.items?.length || 0 }}</div>
          <div class="dim">条 round</div>
        </div>
        <div class="ctx-card">
<!-- 卡 2：策略库场景数与当前角色库 -->
          <div class="ctx-title">策略库场景</div>
<!-- 场景数：来自策略库摘要 -->
          <div class="ctx-num">{{ ctx?.policy_summary?.scenes?.length || 0 }}</div>
<!-- 当前角色库名 -->
          <div class="dim">{{ ctx?.policy_summary?.policy || '-' }}</div>
        </div>
        <div class="ctx-card">
<!-- 卡 3：tools/*.json 计数 -->
          <div class="ctx-title">工具文件</div>
          <div class="ctx-num">{{ Object.keys(ctx?.policy_summary?.tools || {}).length }}</div>
<!-- 工具文件计数说明 -->
          <div class="dim">个 tools/*.json</div>
        </div>
      </div>
<!-- 样本明细折叠区：含 IR 摘要与行为 -->
      <details class="fold" open>
<!-- 折叠标题 -->
        <summary>样本明细（含 IR 摘要与行为）</summary>
<!-- 样本条目循环：round_id/时间/得分 -->
        <div v-for="it in ctx?.items || []" :key="it.round_id" class="ctx-item">
<!-- 条目头：标签 + 时间 + 得分着色 -->
          <div class="ctx-item-head">
<!-- 样本标签 -->
            <t-tag size="small" variant="outline">{{ it.round_id }}</t-tag>
<!-- 样本时间 -->
            <span class="dim">{{ it.time_start }}</span>
<!-- 样本得分：着色显示 -->
            <span :class="scoreClass(it.overall_score)">{{ fmtScore(it.overall_score) }}</span>
          </div>
<!-- 用户请求原文 -->
          <div class="ctx-q">{{ it.user_query || '(无 query)' }}</div>
<!-- 行为摘要：工具动作序列 -->
          <div class="dim behaviors">行为：{{ (it.behaviors || []).join(' | ') || '—' }}</div>
        </div>
      </details>
      <div class="row-actions">
<!-- 开始 AI 分析按钮：有上下文才可用 -->
        <t-button theme="primary" :loading="busy" :disabled="!ctx" @click="doAnalyze">
          <template #icon><t-icon name="bulb" /></template>开始 AI 分析
        </t-button>
<!-- 分析失败提示：引导检查 AI 参数 -->
        <span v-if="analyzeErr" class="err">分析失败：{{ analyzeErr }}（可在 AI 参数中检查模型配置）</span>
      </div>
    </div>

    <!-- ④ 步骤 2/3：AI 分析与评审 -->
    <div class="panel" v-show="step === 2 || step === 3">
<!-- 面板头：AI 分析结论 -->
      <div class="panel-head"><t-icon name="dashboard" /> 步骤 3 · AI 分析结论</div>
<!-- 流式输出区：AI 分析过程文本 -->
      <div class="stream" v-if="streamText"><pre>{{ streamText }}</pre></div>
<!-- 结果视图：风险/放宽/改造三类，可勾选 -->
      <RsiResultView :result="result" :adopted="adopted" selectable @toggle="(cat, i, v) => toggle(cat, i, v)" />
      <div class="row-actions">
<!-- 生成变更计划按钮：按勾选项生成字段级计划 -->
        <t-button theme="primary" :disabled="!result" @click="doPlan">
          <template #icon><t-icon name="check" /></template>生成变更计划（{{ adoptedCount }} 项已勾选）
        </t-button>
      </div>
<!-- 计划视图：变更表格，path/建议值可编辑 -->
      <RsiPlanView :changes="plan?.changes || []" editable />
<!-- 有计划才显示下一步按钮 -->
      <div class="row-actions" v-if="plan?.changes?.length">
        <t-button theme="primary" @click="step = 4">
          <template #icon><t-icon name="arrow-right" /></template>下一步：应用
        </t-button>
<!-- 填写提示：数组加方括号，字符串可省引号 -->
        <span class="dim">提示：建议值请填合法 JSON（数组加方括号），字符串可省略引号</span>
      </div>
    </div>

    <!-- ⑤ 步骤 4：应用 -->
    <div class="panel" v-show="step === 4">
<!-- 面板头：应用到新建角色库 -->
      <div class="panel-head"><t-icon name="save" /> 步骤 4 · 应用到新建角色库</div>
      <div class="form-grid">
<!-- 进化角色名：自动生成（原角色名_evolved_月日时分），只读 -->
        <label class="fi"><span>进化后角色名（自动生成：原角色名_evolved_月日时分，不可修改）</span>
          <t-input :value="evolvedName" readonly />
        </label>
<!-- 基线选择：默认=所选角色库 -->
        <label class="fi"><span>基线</span>
          <t-select v-model="base" :options="baseOptions" />
        </label>
<!-- 角色标题：展示用途 -->
        <label class="fi"><span>角色标题</span>
          <t-input v-model="roleTitle" placeholder="如：进化后的只读分析师" />
        </label>
      </div>
      <div class="row-actions">
<!-- 新建角色库并应用按钮 -->
        <t-button theme="primary" :loading="busy" :disabled="!evolvedName || !plan?.changes?.length" @click="doApply">
          <template #icon><t-icon name="check-circle" /></template>新建角色库并应用
        </t-button>
<!-- 说明：可用「自进化角色覆盖」合入基础角色 -->
        <span class="dim">角色名带时间戳全局唯一，无需强制重建；如需生效可稍后用右上角「自进化角色覆盖」合入基础角色</span>
      </div>
<!-- 应用结果：路径 + 落盘/人工/校验统计 -->
      <div v-if="applied" class="result-box">
        <t-tag theme="success" variant="light">已应用</t-tag>
        <code>{{ applied.path }}</code>
<!-- 落盘条数与需人工处理条数 -->
        <span class="dim">落盘 {{ applied.applied?.length || 0 }} 条 · 需人工 {{ applied.manual?.length || 0 }} 条 · 校验 {{ applied.validation?.ok ? '通过' : '存在阻断错误' }}</span>
        <div v-for="e in applied.errors || []" :key="e" class="err">· {{ e }}</div>
        <div v-for="m in applied.manual || []" :key="m.reason" class="dim">· 需人工处理：{{ m.reason }}</div>
      </div>
<!-- 校验结果区：通过/阻断 + E/W 列表 -->
<!-- 校验结果区 -->
      <div v-if="applied?.validation" class="validate-box">
<!-- 结构校验结论行 -->
        <div class="v-line" :class="applied.validation.ok ? 'ok' : 'err'">
          <t-icon :name="applied.validation.ok ? 'check-circle' : 'close-circle'" />
          结构校验：{{ applied.validation.ok ? '通过' : '存在阻断级错误' }}
        </div>
<!-- E 级错误条目 -->
        <div v-for="e in applied.validation.errors || []" :key="e" class="v-item err"><t-tag theme="danger" size="small">E</t-tag>{{ e }}</div>
<!-- W 级警告条目 -->
        <div v-for="w in applied.validation.warnings || []" :key="w" class="v-item warn"><t-tag theme="warning" size="small">W</t-tag>{{ w }}</div>
      </div>
    </div>

    <!-- ⑥ 步骤 5：回测与历史 -->
    <div class="panel" v-show="step === 5">
<!-- 面板头：归档与自测 -->
      <div class="panel-head"><t-icon name="chart-bar" /> 步骤 5 · 归档与自测</div>
      <div class="row-actions">
<!-- 归档按钮：写入进化历史 -->
        <t-button theme="default" variant="outline" @click="doSaveRun">归档本轮进化</t-button>
<!-- 归档回显 -->
        <span v-if="savedRun" class="dim">已归档：{{ savedRun }}</span>
<!-- 开始下一轮按钮：带入本轮改进上下文 -->
        <t-button v-if="savedRun" theme="primary" variant="outline" @click="startNextRound">
          <template #icon><t-icon name="arrow-right" /></template>开始下一轮迭代
        </t-button>
<!-- 下一轮说明：新角色 + 自动反馈 -->
        <span v-if="savedRun" class="dim">下一轮将以 {{ evolvedName }} 为角色，并自动带入本轮改进上下文</span>
      </div>
<!-- 回测区：建议重跑原始 query 验证进化效果 -->
      <div v-if="savedRun" class="hist">
<!-- 回测建议标题 -->
        <div class="plan-head">回测建议（自行验证）</div>
        <div class="dim" style="margin: 6px 0;">
<!-- 回测说明：攻击类应被拦截、合法类应放行 -->
          角色库 <code>{{ evolvedName }}</code> 已生成。建议将下列原始 query 重新执行（把该角色「自进化角色覆盖」到基础角色，
          或切换生效后重跑），对比判定结果：攻击类应被拦截、合法类应正常放行，即本轮进化有效。
        </div>
<!-- 自测表：原始 query + 原得分/原判定 -->
<!-- 自测表：原始 query + 原判定 -->
        <t-table :data="ctx?.items || []" :columns="selfTestCols" row-key="round_id" size="small" bordered class="rsi-table">
<!-- 自测表得分列模板 -->
          <template #score="{ row }"><span :class="scoreClass(row.overall_score)">{{ fmtScore(row.overall_score) }}</span></template>
<!-- 自测表判定列模板 -->
          <template #ab="{ row }">{{ row.is_abnormal === 1 ? "异常" : row.is_abnormal === 0 ? "正常" : "—" }}</template>
        </t-table>
      </div>
    </div>

<!-- AI 参数抽屉：模型/端点配置 -->
    <RsiConfigDrawer v-model:visible="drawer" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
import { MessagePlugin } from "tdesign-vue-next"
import RsiConfigDrawer from "./RsiConfigDrawer.vue"
import RsiResultView from "./RsiResultView.vue"
import RsiPlanView from "./RsiPlanView.vue"

// 管理员请求头：进化写操作需特权会话
const ADMIN_HEAD = () => ({
  "Content-Type": "application/json",
  "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "",
})

// 当前步骤索引（0-5 对应六个面板）
const step = ref(0)
// AI 参数抽屉开关
const drawer = ref(false)
// 长操作进行中标志
const busy = ref(false)
// 样本列表与已选集合
const rounds = ref([])
// 已选样本集合（表格多选双向）
const selected = ref([])
// 检索条件：round_id/关键字/仅异常/时间区间
const f = ref({ round_id: "", query: "", abnormal: false, time_from: "", time_to: "" })
// 当前角色：样本过滤与进化基线的锚点
const selRole = ref("")
// 角色库列表：下拉与覆盖对话框共用
const policyList = ref([])
// 角色说明/用户提示词/父轮反馈：注入进化提示词的三段上下文
const roleDesc = ref("")
const userPrompt = ref("")
const parentFeedback = ref("")
// 进化上下文：样本 + 策略库摘要
const ctx = ref(null)
// AI 分析结论 / 流式文本 / 失败信息
const result = ref(null)
// 流式过程文本
const streamText = ref("")
// 分析失败信息
const analyzeErr = ref("")
// 人工勾选结果：三类（风险/放宽/改造）各自的下标集合
const adopted = ref({ risks: [], relax: [], transform: [] })
// 变更计划：changes 数组（含可编辑字段）
const plan = ref(null)
// 应用表单：基线/标题（角色名由时间戳生成）
const role = ref("")
// 应用表单：基线角色库（默认 default）
const base = ref("default")
const roleTitle = ref("")
// 进化角色名（只读）与应用结果
const evolvedName = ref("")
const applied = ref(null)
// 归档 run_id 与当前任务号
const savedRun = ref("")
// 当前进化任务号（日志关联）
const taskId = ref("")

// 角色下拉选项：来自角色库列表，缺省回退 default/ops
const baseOptions = computed(() => {
// 选项映射：角色名→下拉项
  const opts = policyList.value.map((p) => ({ label: p.name, value: p.name }))
// 空列表回退 default/ops
  return opts.length ? opts : [{ label: "default", value: "default" }, { label: "ops", value: "ops" }]
})

// 样本表列定义：多选列 + round_id/时间/请求
const roundCols = [
  { colKey: "row-select", type: "multiple", width: 46 },
  { colKey: "round_id", title: "round_id", width: 150 },
  { colKey: "time_start", title: "时间", width: 170 },
  { colKey: "user_query", title: "用户请求", ellipsis: true },
]
// 计划表列定义（RsiPlanView 使用）
const planCols = [
  { colKey: "kind", title: "类型", width: 90 },
  { colKey: "target", title: "目标文件", width: 170 },
  { colKey: "path", title: "字段路径（可编辑）", width: 300 },
  { colKey: "proposed", title: "建议值（可编辑）", width: 240 },
  { colKey: "reason", title: "理由", ellipsis: true },
  { colKey: "risk", title: "风险", width: 80 },
]
// 自测表列定义：原始 query/原得分/原判定
const selfTestCols = [
  { colKey: "round_id", title: "round_id", width: 150 },
  { colKey: "user_query", title: "原始 query（重新执行以自测）", ellipsis: true },
  { colKey: "score", title: "原得分", width: 90 },
  { colKey: "ab", title: "原判定", width: 90 },
]

// 已勾选计数：三类数量之和
const adoptedCount = computed(() => adopted.value.risks.length + adopted.value.relax.length + adopted.value.transform.length)

// 得分格式化：空值显示 —，否则两位小数
function fmtScore(v) { return v === null || v === undefined || v === "" ? "—" : Number(v).toFixed(2) }
// 得分着色：≥0.5 绿色，<0.5 红色
function scoreClass(v) { const n = Number(v); return !isFinite(n) ? "dim" : (n >= 0.5 ? "ok-t" : "err-t") }
// 严重级→标签主题色映射
function sevTheme(s) { return s === "high" ? "danger" : s === "medium" ? "warning" : "default" }
// 变更类型→主题色：收紧红/放宽黄/改造蓝
function kindTheme(k) { return k === "tighten" ? "danger" : k === "relax" ? "warning" : "primary" }
// 建议值格式化：数组逗号连接，空值 —
function fmtVal(v) { return Array.isArray(v) ? v.join(", ") : (v === "" || v === null || v === undefined ? "—" : String(v)) }
// 勾选切换：维护 adopted 的下标集合
function toggle(cat, i, on) {
  // 勾选集合维护：add/delete 后转数组
  const arr = new Set(adopted.value[cat])
  on ? arr.add(i) : arr.delete(i)
  adopted.value[cat] = [...arr]
}
// 步骤条同步：点击可回跳
function onStepChange(v) { if (typeof v === "number") step.value = v }

// 统一请求封装：非 ok 弹错误提示
async function jfetch(url, opts = {}) {
  const r = await fetch(url, opts)
  const j = await r.json().catch(() => ({ ok: false, error: "响应解析失败" }))
  if (!j.ok && j.error) MessagePlugin.error(j.error)
  return j
}

// 样本检索：按角色 + 过滤条件拉取（上限 50）
async function loadRounds() {
// 未选角色：清空列表不请求
  if (!selRole.value) { rounds.value = []; return }
// 组装查询参数：仅非空项参与
// 查询参数组装：角色 + 过滤条件
  const p = new URLSearchParams({ limit: "50", role: selRole.value })
// 过滤参数：仅非空项参与
  if (f.value.round_id) p.set("round_id", f.value.round_id)
  if (f.value.query) p.set("query", f.value.query)
  if (f.value.abnormal) p.set("abnormal", "true")
  if (f.value.time_from) p.set("time_from", f.value.time_from)
  if (f.value.time_to) p.set("time_to", f.value.time_to)
  const j = await jfetch(`/api/rounds?${p.toString()}`)
// 样本列表回填
  if (j.ok) rounds.value = j.data
}

// 角色库列表加载：过滤 skilltrust 基准库
async function loadPolicies() {
  try {
// 角色库列表拉取（含 evolved 供覆盖选择）
    const r = await fetch("/api/translator/policies")
    const j = await r.json()
// 过滤 skilltrust 基准库后回存
    if (j.ok) policyList.value = (j.data?.policies || []).filter((x) => x.name !== "skilltrust")
  } catch (e) { /* 忽略：下拉回退到 default/ops */ }
}

// ── 自进化角色覆盖 ──
// 覆盖对话框可见性
const owVisible = ref(false)
// 覆盖对话框执行中标志（防重复提交）
const owBusy = ref(false)
// 覆盖源角色（内容来源）
const owSource = ref("")
// 覆盖目标角色（被覆盖，沿用其名）
const owTarget = ref("")
// 覆盖对话框：源=含 _evolved_ 的角色
// evolved 角色筛选（覆盖源候选）
const evolvedOptions = computed(() => policyList.value.filter((p) => p.name.includes("_evolved_")).map((p) => ({ label: p.name, value: p.name })))
// 覆盖对话框：目标=不含 _evolved_ 的自建角色
const baseRoleOptions = computed(() => policyList.value
// 非 evolved 且非内置的角色筛选（覆盖目标候选）
  .filter((p) => !p.name.includes("_evolved_") && !["default", "ops"].includes(p.name))
  .map((p) => ({ label: p.name, value: p.name })))

// 打开覆盖对话框：预选第一项
function openOverwrite() {
// 打开时重置上次选择
  owSource.value = ""; owTarget.value = ""
  loadPolicies().then(() => {
// 预选第一个可选项
    if (!owSource.value && evolvedOptions.value.length) owSource.value = evolvedOptions.value[0].value
// 预选第一个基础角色
    if (!owTarget.value && baseRoleOptions.value.length) owTarget.value = baseRoleOptions.value[0].value
  })
  owVisible.value = true
}

// 执行覆盖：源角色内容替换目标角色，热重载生效
async function doOverwrite() {
// 前置校验：两项都必选
  if (!owSource.value || !owTarget.value) { MessagePlugin.warning("请选择源角色与目标角色"); return }
  owBusy.value = true
  try {
// 覆盖请求：源内容替换目标
    const j = await jfetch("/api/translator/policies/overwrite", {
      method: "POST", headers: ADMIN_HEAD(),
      body: JSON.stringify({ source: owSource.value, target: owTarget.value }),
    })
    if (j.ok) {
// 成功提示：含热重载状态
      MessagePlugin.success(`已覆盖：${owSource.value} → ${owTarget.value}${j.data?.hot_reloaded ? "（已热重载）" : ""}`)
      owVisible.value = false
      loadPolicies()
    }
  } finally { owBusy.value = false }
}

// 角色切换联动：清空已选样本并重拉
function onRoleChange() {
  // 先选角色：切换角色后清空已选样本并仅加载该角色的 round
  selected.value = []
  loadRounds()
  // 联动应用表单：基线=所选角色库，产物名在生成计划时按时间戳生成
// 联动应用表单：基线=所选角色库
  if (selRole.value) base.value = selRole.value
}

// 手工项（tighten/relax 缺字段路径）在评审表格中可编辑 path / 建议值
// 手工项建议值解析：字符串尝试 JSON.parse，失败原样返回
function tryParseVal(s) {
  if (typeof s !== "string") return s
// 手工项建议值：尝试 JSON.parse，失败按原字符串
  const t = s.trim()
  try { return JSON.parse(t) } catch (e) { return s }
}

// 表格多选回调：更新已选集合
function onSelect(keys) { selected.value = keys }

// 自进化任务日志：每完成一步写入后端任务文件；失败仅告警，不阻断主流程
// 进化任务日志：每步写入后端，失败仅告警
async function logTaskStep(step, name, data) {
  try {
// 步骤日志提交：任务号+步骤+数据
    const j = await jfetch("/api/translator/rsi/tasks/step", {
      method: "POST", headers: ADMIN_HEAD(),
      body: JSON.stringify({ task_id: taskId.value, step, name, data,
                             role: evolvedName.value || selRole.value || "", base: base.value || "" }),
    })
// 首次写入返回任务号：后续复用
    if (j.ok && j.data?.task_id) taskId.value = j.data.task_id
  } catch (e) {
    console.warn("自进化任务日志写入失败", e)
  }
}

// 步骤 1→2：汇聚上下文（样本 + 策略库摘要）
async function gotoContext() {
  busy.value = true
  try {
// 上下文请求：round_ids + 三段提示上下文
    const j = await jfetch("/api/translator/rsi/context", {
      method: "POST", headers: ADMIN_HEAD(),
      body: JSON.stringify({ round_ids: selected.value, role_desc: roleDesc.value,
                             user_prompt: userPrompt.value, parent_feedback: parentFeedback.value }),
    })
    if (j.ok) {
// 上下文回填并进入步骤 2
      ctx.value = j.data; step.value = 1
      // 步骤 1 选样本 + 步骤 2 上下文：记录当时选了哪些 round、角色说明与提示词
// 日志：记录选样与提示词原文
      await logTaskStep(1, "选样本", { role: selRole.value, round_ids: selected.value,
        role_desc: roleDesc.value, user_prompt: userPrompt.value, parent_feedback: parentFeedback.value })
// 日志：记录样本数/角色库/场景/工具
      await logTaskStep(2, "上下文", { items: (j.data.items || []).length,
        policy: j.data.policy_summary?.policy || "", scenes: j.data.policy_summary?.scenes || [],
        tools: Object.keys(j.data.policy_summary?.tools || {}) })
    }
  } finally { busy.value = false }
}

// SSE 流式请求：text 事件刷新过程文本，done 交付结论
async function ssePost(url, body) {
// SSE 请求：手工 fetch 以读取流
  const r = await fetch(url, { method: "POST", headers: ADMIN_HEAD(), body: JSON.stringify(body) })
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = "", done = null
  while (true) {
// 逐 chunk 读取
    const { value, done: fin } = await reader.read()
    if (fin) break
// 增量解码拼接
    buf += dec.decode(value, { stream: true })
    const parts = buf.split("\n\n")
    buf = parts.pop() || ""
    for (const p of parts) {
// 提取 data: 行
      const line = p.split("\n").find(l => l.startsWith("data: "))
      if (!line) continue
      const ev = JSON.parse(line.slice(6))
// text：过程文本刷新
      if (ev.type === "text") streamText.value = ev.data
// error：失败信息记录
      else if (ev.type === "error") { analyzeErr.value = ev.message || "分析失败"; MessagePlugin.error(analyzeErr.value) }
      else if (ev.type === "done") done = ev.data
    }
  }
  return done
}

// 步骤 2→3：AI 分析（风险/放宽/改造三方向）
async function doAnalyze() {
  busy.value = true; analyzeErr.value = ""; streamText.value = ""
  try {
// AI 分析请求（SSE）
    const data = await ssePost("/api/translator/rsi/analyze", {
      round_ids: selected.value, role_desc: roleDesc.value,
      user_prompt: userPrompt.value, parent_feedback: parentFeedback.value,
    })
// 有结论才推进
    if (data?.result) {
      result.value = data.result
// 勾选结果清零
      adopted.value = { risks: [], relax: [], transform: [] }
      step.value = 2
      MessagePlugin.success("AI 分析完成")
      // 步骤 3：记录 AI 当时给出的完整结论与模型信息
// 日志：记录 AI 完整结论与模型元信息
      await logTaskStep(3, "AI 分析", { result: data.result, meta: data.meta || {}, round_ids: selected.value })
    }
  } catch (e) { MessagePlugin.error(String(e)) } finally { busy.value = false }
}

// 步骤 3→4：按勾选生成字段级变更计划
async function doPlan() {
// 计划请求：结论 + 人工勾选
  const j = await jfetch("/api/translator/rsi/plan", {
    method: "POST", headers: ADMIN_HEAD(),
    body: JSON.stringify({ result: result.value, adopted: adopted.value }),
  })
  if (j.ok) {
    // proposedTxt 供表格内编辑；proposed 保留原值作为回退
// 计划回填：文本形态便于表格内编辑
    plan.value = { ...j.data, changes: (j.data?.changes || []).map((c) => ({
      ...c, proposedTxt: typeof c.proposed === "string" ? c.proposed : JSON.stringify(c.proposed),
    })) }
    step.value = 3
    // 按选定角色预填应用表单：基线=该角色库，产物名=原角色名_evolved_月日时分（固定不可改）
// 预填应用表单
    if (selRole.value) {
      base.value = selRole.value
// 两位数字补零
      const p = (n) => String(n).padStart(2, "0")
      const d = new Date()
// 进化角色名：原角色名_evolved_月日时分
      evolvedName.value = `${selRole.value}_evolved_${p(d.getMonth() + 1)}${p(d.getDate())}${p(d.getHours())}${p(d.getMinutes())}`
// 标题缺省
      if (!roleTitle.value) roleTitle.value = "进化后的角色库"
    }
    // 步骤 4：记录人工勾选结果与生成的变更计划
// 日志：记录勾选结果与变更计划
    await logTaskStep(4, "评审", { adopted: adopted.value, changes: plan.value.changes })
  }
}

// 步骤 4→5：应用到新建角色库并结构校验
async function doApply() {
  busy.value = true
  try {
// 变更数组：文本建议值 parse 为对象
    const changes = (plan.value?.changes || []).map((c) => ({
      ...c, proposed: tryParseVal(c.proposedTxt ?? c.proposed),
    }))
// 基线缺省回退
    if (!base.value) base.value = selRole.value || "default"
// 应用请求：新建角色库并套用变更
    const j = await jfetch("/api/translator/rsi/apply", {
      method: "POST", headers: ADMIN_HEAD(),
      body: JSON.stringify({ role: evolvedName.value, base: base.value, title: roleTitle.value,
                             force: false, changes, task_id: taskId.value }),
    })
    if (j.ok) {
// 应用结果回填
      applied.value = j.data
      // 步骤 5 由后端在应用成功时写入；无 task_id 时后端自动新建任务
// 任务号延续（步骤5后端写）
      if (j.data?.task_id) taskId.value = j.data.task_id
      MessagePlugin.success("已应用并校验完成"); step.value = 4
    }
  } finally { busy.value = false }
}

// 归档：写入进化历史（含全部输入输出）
async function doSaveRun() {
// 归档请求：含输入/结论/计划/结果全量
  const j = await jfetch("/api/translator/rsi/runs", {
    method: "POST", headers: ADMIN_HEAD(),
    body: JSON.stringify({
      role: evolvedName.value, base: base.value, round_ids: selected.value,
      role_desc: roleDesc.value, user_prompt: userPrompt.value, parent_feedback: parentFeedback.value,
      ai_result: result.value, adopted: plan.value?.changes || [], applied: applied.value,
// 归档请求体：回测暂关闭，状态置 applied
      backtest: { enabled: false }, status: "applied",
    }),
  })
  if (j.ok) {
// run_id 回显
    savedRun.value = j.data.run_id
    MessagePlugin.success(`已归档 ${j.data.run_id}`)
// 日志：记录归档 run_id
    await logTaskStep(7, "归档", { run_id: j.data.run_id })
  }
}

// 开始下一轮：以本轮新建的进化角色为新角色，自动带入本轮改进上下文作为反馈
function startNextRound() {
// 下一轮反馈组装：归档号+角色+改进摘要
  const summary = (result.value?.summary || "").trim()
  const parts = []
// 归档信息片段
  if (savedRun.value) parts.push(`上一轮归档 ${savedRun.value}`)
// 进化角色信息片段
  if (evolvedName.value) parts.push(`进化角色 ${evolvedName.value}（基线 ${base.value}）`)
// 改进摘要片段
  if (summary) parts.push(`改进摘要：${summary}`)
// 反馈注入：下一轮自动带入
  parentFeedback.value = parts.join("；")
  loadPolicies().then(() => {
    if (evolvedName.value) {
// 下一轮角色=本轮进化角色（复用联动重拉样本）
      selRole.value = evolvedName.value
// 下一轮基线=本轮进化角色
      base.value = evolvedName.value
      onRoleChange()
    }
  })
  selected.value = []
// 重置本轮结果
  result.value = null; plan.value = null; applied.value = null
// 清空归档与角色名
  savedRun.value = ""; evolvedName.value = ""
// 回到第一步
  step.value = 0
  MessagePlugin.success("已带入本轮改进上下文，开始下一轮迭代")
}

// 挂载：加载角色库列表
onMounted(() => { loadPolicies() })
</script>

<style scoped>
/* 根容器：纵排布局 */
.rsi { display: flex; flex-direction: column; gap: 16px; }
/* 机制说明卡：渐变底 */
.hero-card { display: flex; align-items: flex-start; gap: 14px; padding: 18px 20px; border-radius: 14px;
  background: linear-gradient(135deg, #E8F0FE 0%, #F7FAFF 55%, #FFFFFF 100%);
  border: 1px solid #DCE6F7; box-shadow: 0 2px 10px rgba(0, 82, 217, .06); }
/* 图标托盘：渐变蓝底 */
.hero-icon { flex: 0 0 46px; height: 46px; border-radius: 12px; display: grid; place-items: center;
  background: linear-gradient(135deg, #0052D9, #366EF4); color: #fff; }
/* 说明主体弹性填充 */
.hero-body { flex: 1; }
/* 标题层级 */
.hero-body h3 { margin: 0 0 6px; font-size: 20px; font-weight: 600; color: #1F2329; }
/* 副标题弱化跟随 */
.hero-sub { font-size: 13px; font-weight: 400; color: #4E5969; margin-left: 8px; }
/* 说明段 */
.hero-body p { margin: 0; font-size: 14px; line-height: 1.7; color: #4E5969; }
/* 步骤条容器 */
.rsi-steps { padding: 6px 0 10px; }
/* 面板容器：白底圆角 */
.panel { background: #fff; border: 1px solid #E5E7EB; border-radius: 12px; padding: 16px 18px; }
/* 面板头：图标+标题 */
.panel-head { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600;
  color: #1F2329; margin-bottom: 14px; }
/* 检索条件栏：横排换行 */
.filter-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
/* 固定宽度工具类 */
.w180 { width: 180px; } .w220 { width: 220px; }
/* 角色栏间距 */
.role-bar { margin-bottom: 2px; }
/* 角色栏首项宽度 */
.role-first { width: 320px; font-weight: 500; color: #1F2329; }
/* 表格上边距 */
.rsi-table { margin-top: 6px; }
/* 表单网格：两列 */
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 14px; }
/* 表单项纵排 */
.fi { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: #4E5969; }
/* 操作行布局 */
.row-actions { display: flex; align-items: center; gap: 12px; margin-top: 14px; flex-wrap: wrap; }
/* 弱化文本（RsiTab） */
.dim { color: #A6A6A6; font-size: 12px; }
/* 错误文本 */
.err { color: #E34D59; font-size: 13px; }
/* 通过态文本 */
.ok-t { color: #00A870; font-weight: 600; }
/* 低分文本红色 */
.err-t { color: #E34D59; font-weight: 600; }
/* 上下文三卡网格 */
.ctx-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
/* 统计卡：浅底圆角 */
.ctx-card { border: 1px solid #E5E7EB; border-radius: 10px; padding: 12px 14px; background: #FCFDFF; }
/* 卡标题 */
.ctx-title { font-size: 12px; color: #4E5969; }
/* 卡数字：大号深蓝 */
.ctx-num { font-size: 22px; font-weight: 600; color: #0052D9; line-height: 1.4; }
/* 折叠区容器 */
.fold { margin-top: 14px; border: 1px solid #E5E7EB; border-radius: 10px; padding: 10px 14px; background: #FCFDFF; }
/* 折叠标题手型 */
.fold summary { cursor: pointer; font-size: 13px; font-weight: 600; color: #1F2329; }
/* 样本条目：虚线分隔 */
.ctx-item { border-top: 1px dashed #E5E7EB; padding: 10px 0; }
.ctx-item:first-of-type { border-top: none; }
/* 条目头布局 */
.ctx-item-head { display: flex; align-items: center; gap: 10px; }
/* 用户请求原文 */
.ctx-q { font-size: 13px; color: #1F2329; margin-top: 4px; }
/* 行为摘要行 */
.behaviors { margin-top: 4px; }
/* 流式输出：暗底等宽限高 */
.stream pre { margin: 0; padding: 12px; border-radius: 8px; background: #0F172A; color: #CBD5E1;
  font-size: 12px; max-height: 260px; overflow: auto; }
/* 结论区（RsiResultView 用） */
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
/* 计划/回测区 */
.plan, .hist { margin-top: 16px; }
.plan-head { font-size: 13px; font-weight: 600; color: #1F2329; margin-bottom: 8px; }
/* 应用结果行 */
.result-box { display: flex; align-items: center; gap: 10px; margin-top: 14px; font-size: 13px; flex-wrap: wrap; }
.result-box code { background: #F7F9FC; padding: 2px 8px; border-radius: 6px; }
/* 校验结果区 */
.validate-box { margin-top: 14px; display: flex; flex-direction: column; gap: 6px; }
/* 校验结论行（RsiTab） */
.v-line { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 500; }
.v-line.ok { color: #00A870; } .v-line.err { color: #E34D59; }
.v-item { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.v-item.err { color: #E34D59; } .v-item.warn { color: #ED7B2F; }
</style>
