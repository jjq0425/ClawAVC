<template>
<!-- 自进化任务历史页：只读回看每个任务的步骤与 AI 建议 -->
  <div class="rsi-history">
<!-- 说明卡 -->
    <div class="hero-card">
<!-- 说明主体 -->
      <div class="hero-body">
<!-- 标题 + 副标题 -->
        <h3>自进化任务历史 <span class="hero-sub">只读回看 · 每一步的选择与 AI 建议</span></h3>
<!-- 说明：记录样本/上下文/建议/勾选/结果，只读不可改 -->
        <p>每次执行「新建角色并应用」都会落一个自进化任务，记录当时选择的样本、汇聚的上下文、AI 给出的策略建议、
           人工勾选与变更计划、应用结果，以及运行过的回测。此页仅用于回看，不能修改策略，也不能重新应用。</p>
      </div>
<!-- 刷新按钮 -->
      <t-button theme="default" variant="outline" @click="loadTasks">
        <template #icon><t-icon name="refresh" /></template>刷新
      </t-button>
    </div>

    <div class="panel">
<!-- 任务列表面板头 -->
      <div class="panel-head"><t-icon name="folder" /> 任务列表</div>
<!-- 任务表：任务号/时间/角色/基线/状态 -->
      <t-table :data="items" :columns="cols" row-key="task_id" size="small" bordered class="rsi-table" :loading="loading">
<!-- 状态列模板：按状态着色 -->
        <template #status="{ row }">
<!-- 状态标签 -->
          <t-tag :theme="statusTheme(row.status)" size="small" variant="light">{{ statusText(row.status) }}</t-tag>
        </template>
<!-- 操作列模板 -->
        <template #ops="{ row }">
<!-- 查看按钮：打开任务详情 -->
          <t-button size="small" variant="text" theme="primary" @click="openTask(row.task_id)">查看</t-button>
        </template>
      </t-table>
<!-- 空态：暂无任务 -->
      <t-empty v-if="!items.length && !loading" description="暂无自进化任务" size="small" />
    </div>

<!-- 任务详情面板 -->
    <div class="panel" v-if="current">
<!-- 详情标题 -->
      <div class="panel-head"><t-icon name="dashboard" /> 任务详情 · {{ current.task_id }}</div>
<!-- 任务元信息：角色/基线/状态/时间 -->
      <div class="dim task-meta">
        角色 {{ current.role || '-' }} · 基线 {{ current.base || '-' }} · 状态 {{ statusText(current.status) }} ·
        创建 {{ current.created_at }} · 更新 {{ current.updated_at }}
      </div>

<!-- 步骤循环：1~7 各步骤分派展示 -->
      <div v-for="s in current.steps || []" :key="s.step" class="step-item">
<!-- 步骤头：序号 + 名称 + 时间 -->
        <div class="step-head">
<!-- 步骤序号 -->
          <t-tag size="small" variant="outline">{{ s.step }}</t-tag>
          <b>{{ s.name }}</b>
<!-- 步骤时间 -->
          <span class="dim">{{ s.time }}</span>
        </div>

<!-- 步骤 1：选样本 -->
        <div v-if="s.step === 1" class="step-body">
<!-- 所选角色 -->
          <div>选择角色：<t-tag size="small" variant="outline">{{ s.data.role || '-' }}</t-tag></div>
<!-- 样本 round 清单 -->
          <div class="dim">样本 round（{{ (s.data.round_ids || []).length }} 条）</div>
<!-- round 标签组 -->
          <div class="tag-list">
<!-- 单个 round 标签 -->
            <t-tag v-for="r in (s.data.round_ids || [])" :key="r" size="small" variant="outline">{{ r }}</t-tag>
          </div>
<!-- 角色说明原文 -->
          <div>角色说明：{{ s.data.role_desc || '—' }}</div>
<!-- 用户提示词原文 -->
          <div>用户提示词：{{ s.data.user_prompt || '—' }}</div>
<!-- 父轮反馈（跨轮迭代上下文） -->
          <div v-if="s.data.parent_feedback" class="dim">上一轮反馈：{{ s.data.parent_feedback }}</div>
        </div>

<!-- 步骤 2：上下文汇聚 -->
        <div v-else-if="s.step === 2" class="step-body">
<!-- 样本数/策略库/场景/工具统计 -->
          <div>样本 {{ s.data.items }} 条 · 策略库 {{ s.data.policy || '-' }} ·
            场景 {{ (s.data.scenes || []).length }} · 工具文件 {{ (s.data.tools || []).length }}</div>
<!-- 工具文件清单 -->
          <div class="dim">工具：{{ (s.data.tools || []).join('、') || '—' }}</div>
        </div>

<!-- 步骤 3：AI 分析 -->
        <div v-else-if="s.step === 3" class="step-body">
<!-- 模型/耗时/输出 token 元信息 -->
          <div class="dim">模型 {{ s.data.meta?.model || '-' }} · 耗时 {{ s.data.meta?.latency_ms ?? '-' }} ms ·
            输出 token {{ s.data.meta?.usage?.completion_tokens ?? '-' }}</div>
<!-- AI 分析结论视图 -->
          <RsiResultView :result="s.data.result" />
        </div>

<!-- 步骤 4：评审勾选 -->
        <div v-else-if="s.step === 4" class="step-body">
<!-- 三类勾选计数 -->
          <div class="dim">采纳：risks {{ (s.data.adopted?.risks || []).length }} ·
            relax {{ (s.data.adopted?.relax || []).length }} ·
            transform {{ (s.data.adopted?.transform || []).length }}</div>
<!-- 变更计划视图 -->
          <RsiPlanView :changes="s.data.changes || []" />
        </div>

<!-- 步骤 5：应用结果 -->
        <div v-else-if="s.step === 5" class="step-body">
<!-- 应用请求：角色/基线 -->
          <div>目标角色 {{ s.data.apply_request?.role || '-' }} · 基线 {{ s.data.apply_request?.base || '-' }}</div>
<!-- 落盘/需人工/校验统计 -->
          <div>落盘 {{ (s.data.apply_result?.applied || []).length }} 条 ·
            需人工 {{ (s.data.apply_result?.manual || []).length }} 条 ·
            校验 {{ s.data.apply_result?.validation?.ok ? '通过' : '存在阻断错误' }}</div>
<!-- 产物路径 -->
          <div class="dim">路径：{{ s.data.apply_result?.path || '-' }}</div>
<!-- 应用错误列表 -->
          <div v-for="e in (s.data.apply_result?.errors || [])" :key="e" class="err">· {{ e }}</div>
<!-- 应用时变更内容折叠区 -->
          <details v-if="(s.data.apply_request?.changes || []).length" class="fold">
<!-- 折叠标题 -->
            <summary>应用时的变更内容</summary>
            <RsiPlanView :changes="s.data.apply_request.changes" />
          </details>
        </div>

<!-- 步骤 6：回测 -->
        <div v-else-if="s.step === 6" class="step-body">
<!-- 回测统计：提升/下降/持平 -->
          <div>角色 {{ s.data.role || '-' }} · 模式 {{ s.data.mode || '-' }} ·
            提升 {{ s.data.backtest_result?.improved ?? '-' }} ·
            下降 {{ s.data.backtest_result?.regressed ?? '-' }} ·
            持平 {{ s.data.backtest_result?.unchanged ?? '-' }}</div>
<!-- 回测明细表 -->
          <t-table v-if="(s.data.backtest_result?.items || []).length" :data="s.data.backtest_result.items"
                   :columns="btCols" row-key="round_id" size="small" bordered class="rsi-table" />
        </div>

<!-- 步骤 7：归档 -->
        <div v-else-if="s.step === 7" class="step-body">
<!-- 归档 run_id -->
          <div>归档 run_id：{{ s.data.run_id || '-' }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
// Vue API：响应式 + 挂载钩子
import { ref, onMounted } from "vue"
// TDesign 全局消息插件
import { MessagePlugin } from "tdesign-vue-next"
import RsiResultView from "./RsiResultView.vue"
import RsiPlanView from "./RsiPlanView.vue"

// 任务列表
const items = ref([])
// 当前查看的任务详情
const current = ref(null)
// 列表加载中标志
const loading = ref(false)

// 任务表列定义
const cols = [
  { colKey: "task_id", title: "任务", width: 190 },
  { colKey: "created_at", title: "创建时间", width: 170 },
  { colKey: "role", title: "进化角色", ellipsis: true },
  { colKey: "base", title: "基线", width: 140 },
  { colKey: "status", title: "状态", width: 110 },
  { colKey: "step_count", title: "步骤", width: 70 },
  { colKey: "round_count", title: "样本", width: 70 },
  { colKey: "ops", title: "操作", width: 90 },
]
// 回测明细表列定义：改动前后得分与异常
const btCols = [
/* 回测表 round 列 */
  { colKey: "round_id", title: "round_id", width: 150 },
  { colKey: "before_score", title: "改动前", width: 90 },
  { colKey: "after_score", title: "改动后", width: 90 },
  { colKey: "delta", title: "涨跌", width: 80 },
  { colKey: "before_abnormal", title: "改动前异常", width: 100 },
  { colKey: "after_abnormal", title: "改动后异常", width: 100 },
]

// 状态 → 中文文案映射（六态）
function statusText(s) {
  return { draft: "进行中", analyzed: "已分析", planned: "已生成计划", applied: "已应用",
           backtested: "已回测", archived: "已归档" }[s] || (s || "-")
}
// 状态 → 标签主题色：完成态绿/计划蓝/其余灰
function statusTheme(s) {
  return ["applied", "backtested", "archived"].includes(s) ? "success"
    : (s === "planned" ? "primary" : "default")
}

// 任务列表加载（上限 50 条）
async function loadTasks() {
  loading.value = true
  try {
    const r = await fetch("/api/translator/rsi/tasks?limit=50")
    const j = await r.json()
    items.value = j.ok ? (j.data.items || []) : []
    if (!j.ok) MessagePlugin.error(j.error || "任务列表读取失败")
  } catch (e) { MessagePlugin.error(String(e)) } finally { loading.value = false }
}

// 任务详情加载：按 task_id 拉取
async function openTask(taskId) {
  try {
    const r = await fetch("/api/translator/rsi/tasks/" + encodeURIComponent(taskId))
    const j = await r.json()
    current.value = j.ok ? j.data : null
    if (!j.ok) MessagePlugin.error(j.error || "任务读取失败")
  } catch (e) { MessagePlugin.error(String(e)) }
}

// 挂载即加载列表
onMounted(loadTasks)
</script>

<style scoped>
/* 页容器：纵排布局 */
.rsi-history { display: flex; flex-direction: column; gap: 16px; }
/* 说明卡样式 */
.hero-card { display: flex; align-items: flex-start; gap: 14px; padding: 18px 20px; border-radius: 14px;
  background: linear-gradient(135deg, #E8F0FE 0%, #F7FAFF 55%, #FFFFFF 100%);
  border: 1px solid #DCE6F7; box-shadow: 0 2px 10px rgba(0, 82, 217, .06); }
/* 说明主体弹性填充 */
.hero-body { flex: 1; }
/* 标题样式 */
.hero-body h3 { margin: 0 0 6px; font-size: 20px; font-weight: 600; color: #1F2329; }
/* 副标题弱化跟随 */
/* 副标题弱化跟随 */
.hero-sub { font-size: 13px; font-weight: 400; color: #4E5969; margin-left: 8px; }
/* 说明段样式 */
.hero-body p { margin: 0; font-size: 14px; line-height: 1.7; color: #4E5969; }
/* 面板容器：白底圆角 */
.panel { background: #fff; border: 1px solid #E5E7EB; border-radius: 12px; padding: 16px 18px; }
/* 面板头样式 */
.panel-head { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600;
  color: #1F2329; margin-bottom: 14px; }
/* 表格上边距 */
.rsi-table { margin-top: 6px; }
/* 弱化文本（历史页） */
.dim { color: #A6A6A6; font-size: 12px; }
/* 错误文本 */
.err { color: #E34D59; font-size: 13px; }
/* 任务元信息行 */
.task-meta { margin-bottom: 12px; }
/* 步骤条目：虚线分隔 */
.step-item { border-top: 1px dashed #E5E7EB; padding: 12px 0; }
/* 首个步骤无分隔线 */
.step-item:first-of-type { border-top: none; }
/* 步骤头布局 */
.step-head { display: flex; align-items: center; gap: 10px; font-size: 14px; }
/* 步骤正文：纵排 */
.step-body { margin-top: 8px; font-size: 13px; display: flex; flex-direction: column; gap: 6px; }
/* round 标签组布局 */
.tag-list { display: flex; flex-wrap: wrap; gap: 6px; }
/* 折叠区容器 */
.fold { margin-top: 8px; border: 1px solid #E5E7EB; border-radius: 10px; padding: 10px 14px; background: #FCFDFF; }
/* 折叠标题手型 */
.fold summary { cursor: pointer; font-size: 13px; font-weight: 600; color: #1F2329; }
</style>
