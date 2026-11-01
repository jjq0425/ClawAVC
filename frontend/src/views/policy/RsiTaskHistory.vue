<template>
  <div class="rsi-history">
    <div class="hero-card">
      <div class="hero-body">
        <h3>自进化任务历史 <span class="hero-sub">只读回看 · 每一步的选择与 AI 建议</span></h3>
        <p>每次执行「新建角色并应用」都会落一个自进化任务，记录当时选择的样本、汇聚的上下文、AI 给出的策略建议、
           人工勾选与变更计划、应用结果，以及运行过的回测。此页仅用于回看，不能修改策略，也不能重新应用。</p>
      </div>
      <t-button theme="default" variant="outline" @click="loadTasks">
        <template #icon><t-icon name="refresh" /></template>刷新
      </t-button>
    </div>

    <div class="panel">
      <div class="panel-head"><t-icon name="folder" /> 任务列表</div>
      <t-table :data="items" :columns="cols" row-key="task_id" size="small" bordered class="rsi-table" :loading="loading">
        <template #status="{ row }">
          <t-tag :theme="statusTheme(row.status)" size="small" variant="light">{{ statusText(row.status) }}</t-tag>
        </template>
        <template #ops="{ row }">
          <t-button size="small" variant="text" theme="primary" @click="openTask(row.task_id)">查看</t-button>
        </template>
      </t-table>
      <t-empty v-if="!items.length && !loading" description="暂无自进化任务" size="small" />
    </div>

    <div class="panel" v-if="current">
      <div class="panel-head"><t-icon name="dashboard" /> 任务详情 · {{ current.task_id }}</div>
      <div class="dim task-meta">
        角色 {{ current.role || '-' }} · 基线 {{ current.base || '-' }} · 状态 {{ statusText(current.status) }} ·
        创建 {{ current.created_at }} · 更新 {{ current.updated_at }}
      </div>

      <div v-for="s in current.steps || []" :key="s.step" class="step-item">
        <div class="step-head">
          <t-tag size="small" variant="outline">{{ s.step }}</t-tag>
          <b>{{ s.name }}</b>
          <span class="dim">{{ s.time }}</span>
        </div>

        <div v-if="s.step === 1" class="step-body">
          <div>选择角色：<t-tag size="small" variant="outline">{{ s.data.role || '-' }}</t-tag></div>
          <div class="dim">样本 round（{{ (s.data.round_ids || []).length }} 条）</div>
          <div class="tag-list">
            <t-tag v-for="r in (s.data.round_ids || [])" :key="r" size="small" variant="outline">{{ r }}</t-tag>
          </div>
          <div>角色说明：{{ s.data.role_desc || '—' }}</div>
          <div>用户提示词：{{ s.data.user_prompt || '—' }}</div>
          <div v-if="s.data.parent_feedback" class="dim">上一轮反馈：{{ s.data.parent_feedback }}</div>
        </div>

        <div v-else-if="s.step === 2" class="step-body">
          <div>样本 {{ s.data.items }} 条 · 策略库 {{ s.data.policy || '-' }} ·
            场景 {{ (s.data.scenes || []).length }} · 工具文件 {{ (s.data.tools || []).length }}</div>
          <div class="dim">工具：{{ (s.data.tools || []).join('、') || '—' }}</div>
        </div>

        <div v-else-if="s.step === 3" class="step-body">
          <div class="dim">模型 {{ s.data.meta?.model || '-' }} · 耗时 {{ s.data.meta?.latency_ms ?? '-' }} ms ·
            输出 token {{ s.data.meta?.usage?.completion_tokens ?? '-' }}</div>
          <RsiResultView :result="s.data.result" />
        </div>

        <div v-else-if="s.step === 4" class="step-body">
          <div class="dim">采纳：risks {{ (s.data.adopted?.risks || []).length }} ·
            relax {{ (s.data.adopted?.relax || []).length }} ·
            transform {{ (s.data.adopted?.transform || []).length }}</div>
          <RsiPlanView :changes="s.data.changes || []" />
        </div>

        <div v-else-if="s.step === 5" class="step-body">
          <div>目标角色 {{ s.data.apply_request?.role || '-' }} · 基线 {{ s.data.apply_request?.base || '-' }}</div>
          <div>落盘 {{ (s.data.apply_result?.applied || []).length }} 条 ·
            需人工 {{ (s.data.apply_result?.manual || []).length }} 条 ·
            校验 {{ s.data.apply_result?.validation?.ok ? '通过' : '存在阻断错误' }}</div>
          <div class="dim">路径：{{ s.data.apply_result?.path || '-' }}</div>
          <div v-for="e in (s.data.apply_result?.errors || [])" :key="e" class="err">· {{ e }}</div>
          <details v-if="(s.data.apply_request?.changes || []).length" class="fold">
            <summary>应用时的变更内容</summary>
            <RsiPlanView :changes="s.data.apply_request.changes" />
          </details>
        </div>

        <div v-else-if="s.step === 6" class="step-body">
          <div>角色 {{ s.data.role || '-' }} · 模式 {{ s.data.mode || '-' }} ·
            提升 {{ s.data.backtest_result?.improved ?? '-' }} ·
            下降 {{ s.data.backtest_result?.regressed ?? '-' }} ·
            持平 {{ s.data.backtest_result?.unchanged ?? '-' }}</div>
          <t-table v-if="(s.data.backtest_result?.items || []).length" :data="s.data.backtest_result.items"
                   :columns="btCols" row-key="round_id" size="small" bordered class="rsi-table" />
        </div>

        <div v-else-if="s.step === 7" class="step-body">
          <div>归档 run_id：{{ s.data.run_id || '-' }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue"
import { MessagePlugin } from "tdesign-vue-next"
import RsiResultView from "./RsiResultView.vue"
import RsiPlanView from "./RsiPlanView.vue"

const items = ref([])
const current = ref(null)
const loading = ref(false)

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
const btCols = [
  { colKey: "round_id", title: "round_id", width: 150 },
  { colKey: "before_score", title: "改动前", width: 90 },
  { colKey: "after_score", title: "改动后", width: 90 },
  { colKey: "delta", title: "涨跌", width: 80 },
  { colKey: "before_abnormal", title: "改动前异常", width: 100 },
  { colKey: "after_abnormal", title: "改动后异常", width: 100 },
]

function statusText(s) {
  return { draft: "进行中", analyzed: "已分析", planned: "已生成计划", applied: "已应用",
           backtested: "已回测", archived: "已归档" }[s] || (s || "-")
}
function statusTheme(s) {
  return ["applied", "backtested", "archived"].includes(s) ? "success"
    : (s === "planned" ? "primary" : "default")
}

async function loadTasks() {
  loading.value = true
  try {
    const r = await fetch("/api/translator/rsi/tasks?limit=50")
    const j = await r.json()
    items.value = j.ok ? (j.data.items || []) : []
    if (!j.ok) MessagePlugin.error(j.error || "任务列表读取失败")
  } catch (e) { MessagePlugin.error(String(e)) } finally { loading.value = false }
}

async function openTask(taskId) {
  try {
    const r = await fetch("/api/translator/rsi/tasks/" + encodeURIComponent(taskId))
    const j = await r.json()
    current.value = j.ok ? j.data : null
    if (!j.ok) MessagePlugin.error(j.error || "任务读取失败")
  } catch (e) { MessagePlugin.error(String(e)) }
}

onMounted(loadTasks)
</script>

<style scoped>
.rsi-history { display: flex; flex-direction: column; gap: 16px; }
.hero-card { display: flex; align-items: flex-start; gap: 14px; padding: 18px 20px; border-radius: 14px;
  background: linear-gradient(135deg, #E8F0FE 0%, #F7FAFF 55%, #FFFFFF 100%);
  border: 1px solid #DCE6F7; box-shadow: 0 2px 10px rgba(0, 82, 217, .06); }
.hero-body { flex: 1; }
.hero-body h3 { margin: 0 0 6px; font-size: 20px; font-weight: 600; color: #1F2329; }
.hero-sub { font-size: 13px; font-weight: 400; color: #4E5969; margin-left: 8px; }
.hero-body p { margin: 0; font-size: 14px; line-height: 1.7; color: #4E5969; }
.panel { background: #fff; border: 1px solid #E5E7EB; border-radius: 12px; padding: 16px 18px; }
.panel-head { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600;
  color: #1F2329; margin-bottom: 14px; }
.rsi-table { margin-top: 6px; }
.dim { color: #A6A6A6; font-size: 12px; }
.err { color: #E34D59; font-size: 13px; }
.task-meta { margin-bottom: 12px; }
.step-item { border-top: 1px dashed #E5E7EB; padding: 12px 0; }
.step-item:first-of-type { border-top: none; }
.step-head { display: flex; align-items: center; gap: 10px; font-size: 14px; }
.step-body { margin-top: 8px; font-size: 13px; display: flex; flex-direction: column; gap: 6px; }
.tag-list { display: flex; flex-wrap: wrap; gap: 6px; }
.fold { margin-top: 8px; border: 1px solid #E5E7EB; border-radius: 10px; padding: 10px 14px; background: #FCFDFF; }
.fold summary { cursor: pointer; font-size: 13px; font-weight: 600; color: #1F2329; }
</style>
