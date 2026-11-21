<template>
<!-- 根容器：机制说明卡 + 阶段步骤条 + 生成日志 + A/B/C/D 四阶段面板 + 切换确认 -->
  <div class="aiw">
    <!-- ① 机制说明 -->
<!-- ① 机制说明卡：workflow 先按基线创建目录（基线只读） -->
<!-- 再由 AI 产出「权限意图 spec」，落盘与校验统一由 skill clawavc-policy-creator 执行 -->
<!-- 产物只落在新建角色目录，保证可回滚、可复现 -->
    <div class="hero-card">
<!-- 盾形图标（视觉锚点） -->
      <div class="hero-icon"><t-icon name="root-list" size="30px" /></div>
<!-- 说明主体：标题与机制说明 -->
      <div class="hero-body">
<!-- 标题 + 副标题：一句话说明 skill + workflow 组合生成角色策略库 -->
<!-- 说明段：强调 AI 只出 spec、格式统一与结构完整由 skill 保证 -->
        <h3>AI 帮写 <span class="hero-sub">skill + workflow 组合生成角色策略库</span></h3>
        <p>由 <b>workflow</b> 先按基线创建目录结构（基线只读），再由 <b>AI</b> 依据你的指令生成场景、并按提示填充各场景权限约束；
           AI 只产出「权限意图 spec」，落盘与校验统一由 skill <code>clawavc-policy-creator</code> 执行，保证格式统一、结构完整。产物只落在新建角色目录。</p>
      </div>
<!-- AI 参数按钮：打开模型配置抽屉（与 IR 翻译模型隔离） -->
      <t-button theme="default" variant="outline" @click="drawer = true">
<!-- AI 参数按钮图标与文字 -->
        <template #icon><t-icon name="setting-1" /></template>AI 参数
      </t-button>
    </div>

    <!-- ② 阶段步骤条 -->
<!-- ② 阶段步骤条：建目录 → AI 生成场景 → AI 填充 → 校验生效，点击可回跳 -->
    <t-steps :current="step" class="aiw-steps" @change="onStepChange">
<!-- 步骤项 A：建目录结构（选择基线并创建角色目录） -->
      <t-step-item title="建目录结构" content="选择基线并创建角色目录" />
      <t-step-item title="AI 生成场景" content="依据指令决定场景增删" />
      <t-step-item title="AI 填充内容" content="逐场景生成权限约束" />
      <t-step-item title="校验与生效" content="结构校验并切换生效" />
    </t-steps>

    <!-- ②·5 生成日志（只读回看） -->
<!-- ②·5 生成日志（只读回看）：记录每步输入、AI 产出与结果，不可修改 -->
<!-- 刷新按钮 + 当前角色说明；任务表按 task_id 索引 -->
    <div class="panel">
<!-- 面板头：生成日志标题 -->
      <div class="panel-head"><t-icon name="folder" /> 生成日志（只读）</div>
      <div class="row-actions">
<!-- 刷新：按当前角色重新拉取任务列表 -->
<!-- 刷新按钮：按当前角色重新拉取任务 -->
        <t-button size="small" variant="outline" @click="loadAwTasks">刷新</t-button>
<!-- 说明：角色未填时展示全部角色的任务 -->
        <span class="dim">当前角色：{{ form.role || '全部角色' }}；记录每一步的输入、AI 产出与结果，不可修改</span>
      </div>
<!-- 任务表格：任务号 / 创建时间 / 状态 / 步骤数 -->
      <t-table v-if="awTasks.length" :data="awTasks" :columns="taskCols" row-key="task_id" size="small" bordered class="log-table">
<!-- 操作列：查看任务详情 -->
        <template #ops="{ row }">
<!-- 任务详情按钮：打开只读回看 -->
          <t-button size="small" variant="text" theme="primary" @click="openAwTask(row.task_id)">查看</t-button>
        </template>
      </t-table>
<!-- 空态：暂无生成日志 -->
      <t-empty v-else description="暂无生成日志" size="small" />
<!-- 当前查看的任务：任务号 / 状态 / 角色 / 基线 + 步骤明细 -->
      <div v-if="awCurrent" class="steps-log">
<!-- 任务元信息行：任务号/状态/角色/基线 -->
        <div class="dim log-meta">任务 {{ awCurrent.task_id }} · 状态 {{ awCurrent.status }} · 角色 {{ awCurrent.role }} · 基线 {{ awCurrent.base }}</div>
<!-- 步骤循环：每步一个 step-item，按 step 序号分派展示 -->
        <div v-for="s in awCurrent.steps || []" :key="s.step" class="step-item">
<!-- 步骤头：步骤号标签 + 名称 + 时间 -->
          <div class="step-head">
            <t-tag size="small" variant="outline">{{ s.step }}</t-tag>
            <b>{{ s.name }}</b>
            <span class="dim">{{ s.time }}</span>
          </div>
<!-- 步骤正文：按 step 序号分派展示 -->
          <div class="step-body">
<!-- 步骤 1 明细：角色 / 基线 / 标题 + 权限说明（给 AI 的指令原文） -->
            <div v-if="s.step === 1">
<!-- 步骤 1 数据：角色/基线/标题回显 -->
              角色 {{ s.data.role }} · 基线 {{ s.data.base }} · 标题 {{ s.data.title || '—' }}
<!-- 步骤 1 附：给 AI 的指令原文 -->
              <div class="dim">权限说明：{{ s.data.instruction || '—' }}</div>
            </div>
<!-- 步骤 2 明细：禁用场景列表与 AI 摘要 -->
            <div v-else-if="s.step === 2">
<!-- 步骤 2 数据：禁用场景清单 -->
              禁用场景 {{ (s.data.disable || []).length }} 个：{{ (s.data.disable || []).join('、') || '—' }}
<!-- 步骤 2 附：AI 的归纳说明 -->
              <div class="dim">AI 摘要：{{ s.data.summary || '—' }}</div>
            </div>
<!-- 步骤 3 明细：单场景补丁 JSON（等宽展示） -->
            <div v-else-if="s.step === 3">
<!-- 步骤 3 数据：单场景补丁 JSON -->
              场景 {{ s.data.scene }} 的补丁：
<!-- 补丁等宽展示：与落盘内容一致 -->
              <pre class="mini">{{ JSON.stringify(s.data.patch, null, 2) }}</pre>
            </div>
<!-- 步骤 4 明细：落盘变更条数、快照号、校验结论 -->
            <div v-else-if="s.step === 4">
<!-- 步骤 4 数据：变更计数/快照/校验结论 -->
              落盘变更 {{ (s.data.changes || []).length }} 条 · 快照 {{ s.data.snapshot || '—' }} ·
              校验 {{ s.data.validation?.ok ? '通过' : '存在阻断错误' }}
<!-- 变更明细（最多展示 8 条） -->
              <div v-for="c in (s.data.changes || []).slice(0, 8)" :key="c" class="dim">· {{ c }}</div>
            </div>
<!-- 步骤 5 明细：校验通过 / 错误数 / 警告数 -->
            <div v-else-if="s.step === 5">
<!-- 步骤 5 数据：校验结论 + 错误/警告计数 -->
              校验 {{ s.data.ok ? '通过' : '存在阻断错误' }} · 错误 {{ (s.data.errors || []).length }} ·
              警告 {{ (s.data.warnings || []).length }}
            </div>
<!-- 步骤 6 明细：已切换生效的角色名 -->
            <div v-else-if="s.step === 6">已切换生效：{{ s.data.role }}</div>
<!-- 步骤 7 明细：回滚到的快照时间戳 -->
            <div v-else-if="s.step === 7">回滚至快照 {{ s.data.ts || '最新' }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ③ 阶段 A：建目录 -->
<!-- ③ 阶段 A：创建基础目录结构（角色名 / 基线 / 标题三字段） -->
<!-- 同名角色已存在时可勾选强制重建；成功后自动进入阶段 B -->
    <div class="panel" v-show="step === 0">
<!-- 阶段 A 面板头 -->
      <div class="panel-head"><t-icon name="folder-add" /> 阶段 A · 创建基础目录结构</div>
<!-- 表单网格：三列布局 -->
      <div class="form-grid">
<!-- 角色名输入：字母数字下划线中划线，1-64 字符 -->
        <label class="fi"><span>角色名</span>
<!-- 角色名输入：命名约束见占位提示 -->
          <t-input v-model="form.role" placeholder="如 analyst（字母数字下划线中划线，1-64）" />
        </label>
<!-- 基线选择：default / ops，切换后加载该基线的场景定义 -->
        <label class="fi"><span>基线策略库</span>
<!-- 基线选择：切换后加载该基线场景定义 -->
          <t-select v-model="form.base" :options="baseOptions" @change="loadBaseScenes" />
        </label>
<!-- 角色标题：展示用途（如：只读数据分析师） -->
        <label class="fi"><span>角色标题</span>
<!-- 角色标题输入：展示用途 -->
          <t-input v-model="form.title" placeholder="如 只读数据分析师" />
        </label>
      </div>
<!-- 权限说明块：给 AI 的自然语言指令，决定场景增删与约束方向 -->
<!-- 示例：只能读 /data 下的文件，不能写；禁止联网；不许使用 git 命令 -->
      <div class="fi block">
        <span>权限说明（给 AI 的自然语言指令）</span>
<!-- 权限说明文本域：自然语言指令，AI 按此规划场景与约束 -->
        <t-textarea v-model="form.instruction" :autosize="{ minRows: 3, maxRows: 8 }"
          placeholder="例：只能读 /data 下的文件，不能写；禁止联网；不许使用 git 命令" />
      </div>
<!-- 操作行：强制重建开关 + 创建角色目录按钮 -->
      <div class="row-actions">
<!-- 强制重建开关：同名角色已存在时生效 -->
        <t-checkbox v-model="form.force">已存在同名角色时强制重建</t-checkbox>
<!-- 创建按钮：提交阶段 A 表单 -->
        <t-button theme="primary" :loading="busy" @click="doScaffold">
          <template #icon><t-icon name="folder-add" /></template>创建角色目录
        </t-button>
      </div>
<!-- 创建结果：路径 + 工具文件数 + 场景数 -->
      <div class="result" v-if="scaffoldInfo">
        <t-tag theme="success" variant="light">已创建</t-tag>
<!-- 创建结果：目录绝对路径 -->
        <code>{{ scaffoldInfo.path }}</code>
<!-- 创建结果：工具文件数与场景数 -->
        <span class="dim">工具文件 {{ scaffoldInfo.tool_count }} 个 · 场景 {{ scaffoldInfo.scenes.length }} 个</span>
      </div>
    </div>

    <!-- ④ 阶段 B：AI 生成场景 -->
<!-- ④ 阶段 B：AI 生成场景清单（SSE 流式输出） -->
<!-- 补充提示可选，用于纠正或强调；确认应用后按勾选禁用场景 -->
    <div class="panel" v-show="step === 1">
<!-- 阶段 B 面板头 -->
      <div class="panel-head"><t-icon name="layer" /> 阶段 B · AI 生成场景清单</div>
<!-- 补充提示输入（可选） -->
      <div class="fi block">
        <span>补充提示（可选，用于纠正或强调）</span>
<!-- 补充提示输入：纠正或强调 AI 规划方向 -->
        <t-input v-model="hintB" placeholder="如：保留搜索能力，但禁用邮件与即时通讯" />
      </div>
<!-- 操作行：让 AI 规划场景 / 确认并应用（禁用勾选场景） -->
      <div class="row-actions">
<!-- AI 规划按钮：未填角色时禁用 -->
        <t-button theme="primary" :loading="busy" :disabled="!form.role" @click="doGenerateScenes">
          <template #icon><t-icon name="bulb" /></template>让 AI 规划场景
        </t-button>
<!-- 确认应用按钮：有规划结果才可用 -->
        <t-button theme="default" variant="outline" :disabled="!scenesResult" @click="applyScenes">
          确认并应用（禁用勾选场景）
        </t-button>
      </div>
<!-- 流式输出区：AI 规划过程的实时文本（终端风格暗色块） -->
      <div class="stream" v-if="streamText"><pre>{{ streamText }}</pre></div>
<!-- 场景表格：名称 / 说明 / 禁用勾选 / AI 理由 -->
      <t-table v-if="sceneRows.length" :data="sceneRows" :columns="sceneCols" row-key="name" size="small" bordered
               class="aiw-table" :selected-row-keys="[]">
<!-- 禁用列模板：checkbox 绑定行数据 -->
        <template #disable="{ row }"><t-checkbox v-model="row.disable" /></template>
<!-- 理由列模板：AI 给出的禁用原因 -->
        <template #reason="{ row }"><span class="dim">{{ row.reason || '—' }}</span></template>
      </t-table>
    </div>

    <!-- ⑤ 阶段 C：AI 填充场景内容 -->
<!-- ⑤ 阶段 C：逐场景填充权限约束 -->
<!-- 每场景一张卡：可单独生成 / 重生成 / 清除，补丁文本框可微调后应用 -->
    <div class="panel" v-show="step === 2">
<!-- 阶段 C 面板头 -->
      <div class="panel-head"><t-icon name="edit-1" /> 阶段 C · 逐场景填充权限约束</div>
<!-- 场景列表：纵排卡片 -->
      <div class="scene-list">
<!-- 场景卡循环：key 用场景名 -->
        <div class="scene-card" v-for="s in activeScenes" :key="s">
<!-- 场景头：名称 + 描述 + 已生成/待生成状态标签 -->
          <div class="scene-head">
<!-- 场景描述：来自基线场景定义 -->
            <b>{{ s }}</b><span class="dim">{{ sceneDesc(s) }}</span>
<!-- 生成状态标签：已生成（可重生成） -->
            <t-tag v-if="patches[s]" theme="success" variant="light" size="small">已生成</t-tag>
            <t-tag v-else theme="default" variant="light" size="small">待生成</t-tag>
          </div>
<!-- 场景操作行：本场景提示输入 + 生成按钮 + 清除按钮 -->
          <div class="scene-actions">
<!-- 单场景补充提示输入 -->
            <t-input v-model="hints[s]" size="small" class="scene-hint" placeholder="本场景的补充提示（可选）" />
<!-- 生成/重生成按钮：按场景独立 loading -->
            <t-button size="small" theme="primary" variant="outline" :loading="sceneBusy === s" @click="doGenerateScene(s)">
              {{ patches[s] ? "重生成" : "AI 生成" }}
            </t-button>
<!-- 清除按钮：仅有补丁时显示 -->
            <t-button size="small" theme="danger" variant="outline" v-if="patches[s]" @click="clearPatch(s)">清除</t-button>
          </div>
<!-- 补丁文本域：JSON 可微调，应用时逐场景 parse -->
          <t-textarea v-if="patches[s]" v-model="patchText[s]" :autosize="{ minRows: 4, maxRows: 14 }" class="mono" />
        </div>
      </div>
<!-- 操作行：应用全部补丁并落盘（按基线重建后套用，结果可复现） -->
<!-- 直接改文件不会被保留：一切变更经 patch/apply 接口留痕 -->
      <div class="row-actions">
<!-- 应用按钮：把全部补丁落盘 -->
        <t-button theme="primary" :loading="busy" :disabled="!form.role" @click="doApply">
          <template #icon><t-icon name="check" /></template>应用全部补丁并落盘
        </t-button>
<!-- 说明：直接改文件不被保留，变更必须走 patch/apply -->
        <span class="dim">落盘按基线重建后套用全部补丁，结果可复现；直接改文件不会被保留</span>
      </div>
    </div>

    <!-- ⑥ 阶段 D：校验与生效 -->
<!-- ⑥ 阶段 D：校验与生效（重新校验 / 快照回滚 / 切换生效） -->
<!-- 切换前需结构校验通过；切换后热重载立即生效（无需重启后端） -->
    <div class="panel" v-show="step === 3">
<!-- 阶段 D 面板头 -->
      <div class="panel-head"><t-icon name="check-circle" /> 阶段 D · 校验与生效</div>
<!-- 操作行：重新校验 + 快照回滚 + 切换为该角色策略库 -->
      <div class="row-actions">
<!-- 重新校验按钮 -->
        <t-button theme="default" variant="outline" :disabled="!form.role" @click="doValidate">重新校验</t-button>
<!-- 快照回滚下拉：选项来自 loadSnapshots -->
        <t-select v-model="rollbackTs" :options="snapOptions" size="small" class="snap-select" placeholder="选择快照回滚" />
<!-- 回滚按钮：选中快照才可用 -->
        <t-button theme="warning" variant="outline" :disabled="!rollbackTs" @click="doRollback">回滚</t-button>
<!-- 切换按钮：校验通过才可用，点击弹确认框 -->
        <t-button theme="danger" :disabled="!form.role || !validation?.ok" @click="switchDlg = true">
          <template #icon><t-icon name="swap" /></template>切换为该角色策略库
        </t-button>
      </div>
<!-- 校验结果区：结构校验结论 + 场景数 / 工具文件数 -->
      <div v-if="validation" class="validate-box">
<!-- 校验结论行：通过/阻断双态 -->
        <div class="v-line" :class="validation.ok ? 'ok' : 'err'">
          <t-icon :name="validation.ok ? 'check-circle' : 'close-circle'" />
<!-- 校验统计：场景数/工具文件数 -->
          结构校验：{{ validation.ok ? "通过" : "存在阻断级错误" }} · 场景 {{ validation.info?.scenes ?? "-" }} 个 · 工具文件 {{ validation.info?.tool_files ?? "-" }} 个
        </div>
<!-- 阻断级错误列表（E 级） -->
        <div v-for="e in validation.errors" :key="e" class="v-item err"><t-tag theme="danger" size="small">E</t-tag>{{ e }}</div>
<!-- 警告摘要：基线遗留提示条数，可展开查看详情 -->
        <div v-if="validation.ok && validation.warnings?.length" class="v-warn-summary">
          <span class="dim">基线遗留提示 {{ validation.warnings.length }} 条（不影响校验与切换）</span>
<!-- 警告展开/收起切换 -->
          <t-button variant="text" size="small" theme="primary" @click="showWarnings = !showWarnings">
<!-- 展开按钮文案 -->
            {{ showWarnings ? "收起" : "查看详情" }}
          </t-button>
        </div>
<!-- 警告详情模板：校验失败或手动展开时显示 -->
        <template v-if="!validation.ok || showWarnings">
<!-- 警告条目：基线遗留提示，不影响校验与切换 -->
          <div v-for="w in validation.warnings" :key="w" class="v-item warn"><t-tag theme="warning" size="small">W</t-tag>{{ w }}</div>
        </template>
      </div>
<!-- 最近一次落盘变更列表 -->
      <div v-if="lastChanges?.length" class="changes">
<!-- 变更区标题：条数回显 -->
        <div class="changes-title">最近一次落盘变更（{{ lastChanges.length }} 条）</div>
        <div v-for="c in lastChanges" :key="c" class="dim">· {{ c }}</div>
      </div>
    </div>

    <!-- ⑦ 切换确认 -->
<!-- ⑦ 切换确认对话框：确认后热重载生效，无需重启后端 -->
    <t-dialog v-model:visible="switchDlg" header="确认切换生效" :confirm-btn="{ theme: 'danger', content: '确认切换' }" @confirm="doSwitch">
<!-- 切换说明：热重载语义 -->
      <p>即将把当前生效策略库切换为 <b>{{ form.role }}</b>，切换后热重载立即生效（无需重启后端）。</p>
<!-- 风险提示文案 -->
      <p class="dim">建议先完成校验，确认无误后再切换。</p>
    </t-dialog>

<!-- AI 参数抽屉：模型 / 端点配置（与 IR 翻译模型隔离） -->
    <AiWriterConfigDrawer v-model:visible="drawer" />
  </div>
</template>

<script setup>
// Vue API：ref / computed / onMounted / watch
import { ref, computed, onMounted, watch } from "vue"
// TDesign 全局消息插件
import { MessagePlugin } from "tdesign-vue-next"
// 子组件：AI 参数抽屉
import AiWriterConfigDrawer from "./AiWriterConfigDrawer.vue"

// 管理员请求头：写操作接口需特权会话（X-Admin-Session）
const ADMIN_HEAD = () => ({
  "Content-Type": "application/json",
  "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "",
})

// 流程状态：步骤索引 / 忙碌标志 / 抽屉 / 切换对话框
const step = ref(0)
const busy = ref(false)
const drawer = ref(false)
const switchDlg = ref(false)
// SSE 流式文本：阶段 B/C 的 AI 过程输出
const streamText = ref("")
// 阶段结果：目录脚手架信息 + AI 场景规划结果
const scaffoldInfo = ref(null)
const scenesResult = ref(null)
// 场景行（含禁用勾选）与基线场景定义
const sceneRows = ref([])
const baseScenes = ref([])
// 补丁：per-scene 对象形态 + 可编辑文本形态
const patches = ref({})
const patchText = ref({})
// 提示词：每场景补充提示（hints）+ 阶段 B 全局提示（hintB）
const hints = ref({})
const hintB = ref("")
// 校验结果 / 警告展开开关 / 最近落盘变更
const validation = ref(null)
const showWarnings = ref(false)
const lastChanges = ref([])
// 快照列表与回滚选中的时间戳
const snapshots = ref([])
const rollbackTs = ref("")
// 单场景生成中标志（sceneBusy）/ 当前任务 ID（taskId）
const sceneBusy = ref("")
const taskId = ref("")
// 任务日志列表（awTasks）与当前查看任务（awCurrent）
const awTasks = ref([])
const awCurrent = ref(null)

// 表单：角色 / 基线 / 标题 / 权限说明 / 强制重建
const form = ref({ role: "", base: "default", title: "", instruction: "", force: false })
// 基线下拉选项：default（普通办公/开发/分析）、ops（运维/系统管理）
const baseOptions = [{ label: "default（普通办公/开发/分析）", value: "default" },
                     { label: "ops（运维/系统管理）", value: "ops" }]

// 任务表列定义：任务号 / 时间 / 状态 / 步骤数 / 操作
const taskCols = [
  { colKey: "task_id", title: "任务", width: 190 },
  { colKey: "created_at", title: "创建时间", width: 170 },
  { colKey: "status", title: "状态", width: 120 },
  { colKey: "step_count", title: "步骤", width: 80 },
  { colKey: "ops", title: "操作", width: 90 },
]
// 场景表列定义：场景 / 说明 / 禁用 / AI 理由
const sceneCols = [
  { colKey: "name", title: "场景", width: 180 },
  { colKey: "desc", title: "说明", ellipsis: true },
  { colKey: "disable", title: "禁用", width: 90 },
  { colKey: "reason", title: "AI 理由", ellipsis: true },
]
// 快照选项（computed）：时间戳 + 标签；活动场景（computed）：未勾选禁用的场景
const snapOptions = computed(() => snapshots.value.map(s => ({ label: `${s.ts} · ${s.label || "快照"}`, value: s.ts })))
const activeScenes = computed(() => sceneRows.value.filter(r => !r.disable).map(r => r.name))
// 场景描述查找：从基线场景定义中按名取
const sceneDesc = (n) => (baseScenes.value.find(s => s.name === n)?.desc || "")

// 统一请求封装：json 解析失败给占位错误；非 ok 时弹错误提示
async function jfetch(url, opts = {}) {
  const r = await fetch(url, opts)
// 响应解析：失败时给占位错误对象
  const j = await r.json().catch(() => ({ ok: false, error: "响应解析失败" }))
  if (!j.ok && j.error) MessagePlugin.error(j.error)
// 返回统一 {ok, data, error} 结构
  return j
}

// SSE 流式请求：逐 chunk 解析 data: 事件，返回 done 数据
// onText 回调把累计文本交给调用方渲染
async function ssePost(url, body, onText) {
  const r = await fetch(url, { method: "POST", headers: ADMIN_HEAD(), body: JSON.stringify(body) })
// 获取响应流 reader
  const reader = r.body.getReader()
  const dec = new TextDecoder()
// 流缓冲：跨 chunk 拼接
  let buf = ""
  let done = null
// 循环读流直到结束
  while (true) {
    const { value, done: fin } = await reader.read()
    if (fin) break
    buf += dec.decode(value, { stream: true })
// 按空行分帧；余量回写 buf 等待下一 chunk
    const parts = buf.split("\n\n")
    buf = parts.pop() || ""
    for (const p of parts) {
// 找 data: 行并解析事件 JSON
      const line = p.split("\n").find(l => l.startsWith("data: "))
      if (!line) continue
      const ev = JSON.parse(line.slice(6))
// text 事件：增量文本回调
      if (ev.type === "text" && onText) onText(ev.data)
// error 事件：失败提示
      else if (ev.type === "error") MessagePlugin.error(ev.message || "生成失败")
// done 事件：最终结构化数据
      else if (ev.type === "done") done = ev.data
    }
  }
  return done
}

// AI 帮写任务日志：写入一步（失败仅告警，不阻断生成流程）
// 任务日志写入：每完成一步写入后端任务文件
// 失败仅 console 警告，不阻断生成主流程
async function logStep(step, name, data) {
  try {
// 步骤日志提交：任务号 + 步骤号 + 数据
    const j = await jfetch("/api/translator/ai-writer/tasks/step", {
      method: "POST", headers: ADMIN_HEAD(),
      body: JSON.stringify({ task_id: taskId.value, step, name, data,
                             role: form.value.role, base: form.value.base }),
    })
// 首次写入返回任务号：后续步骤复用同一任务
    if (j.ok && j.data?.task_id) taskId.value = j.data.task_id
  } catch (e) {
    console.warn("AI 帮写任务日志写入失败", e)
  }
}

// 加载任务列表：角色未填时展示全部任务（避免面板空白）
async function loadAwTasks() {
  // 角色名未填时展示全部任务，避免打开页面后日志面板一直空白
// 角色过滤参数：空=全部角色
  const role = form.value.role || ""
  const j = await jfetch(`/api/translator/ai-writer/tasks?role=${encodeURIComponent(role)}&limit=50`)
// 任务列表回填
  if (j.ok) awTasks.value = j.data.items || []
}

// 查看任务详情：回填当前查看对象，失败给提示
async function openAwTask(id) {
  const j = await jfetch(`/api/translator/ai-writer/tasks/${encodeURIComponent(id)}`)
// 任务详情回填（失败置空）
  awCurrent.value = j.ok ? j.data : null
  if (!j.ok) MessagePlugin.error(j.error || "任务读取失败")
}

// 加载基线场景：按所选基线拉取场景定义并初始化场景行
async function loadBaseScenes() {
  const j = await jfetch(`/api/translator/ai-writer/base-scenes?base=${form.value.base}`)
  if (!j.ok) return
// 基线场景定义回存
  baseScenes.value = j.data.scenes
// 场景行初始化：全部默认启用，AI 理由为空
  sceneRows.value = j.data.scenes.map(s => ({ name: s.name, desc: s.desc, disable: false, reason: "" }))
}

// 阶段 A：创建角色目录；成功后自动进入阶段 B
// scaffold 请求表单全量提交（role/base/title/instruction/force）
async function doScaffold() {
// 前置校验：角色名必填
  if (!form.value.role) return MessagePlugin.warning("请填写角色名")
  busy.value = true
  try {
// scaffold 请求体：表单全量
    const j = await jfetch("/api/translator/ai-writer/scaffold", {
      method: "POST", headers: ADMIN_HEAD(), body: JSON.stringify(form.value),
    })
    if (j.ok) {
// 结果回填：路径 / 工具文件数 / 场景数
      scaffoldInfo.value = j.data
      // 步骤 1 由后端记录；这里保存任务 ID 供后续步骤关联
// 任务 ID 关联：后端返回，供后续步骤日志引用同一任务
// scaffold 返回任务号：步骤日志从此关联
      if (j.data.task_id) taskId.value = j.data.task_id
      MessagePlugin.success(`已创建 ${j.data.role}（${j.data.tool_count} 个工具文件）`)
// 步骤推进 + 快照列表加载 + 任务日志刷新
      step.value = 1
      await loadSnapshots()
      loadAwTasks()
    }
  } finally { busy.value = false }
}

// 阶段 B：AI 规划场景（SSE 流式，补充提示可纠正方向）
async function doGenerateScenes() {
// 进入生成：重置流文本
  busy.value = true; streamText.value = ""
  try {
// SSE 生成场景：请求体带表单 + 补充提示
    const data = await ssePost("/api/translator/ai-writer/generate-scenes",
      { ...form.value, hint: hintB.value }, t => { streamText.value = t })
    if (!data) return
// 结果回填：场景规划结果对象
    scenesResult.value = data
// 禁用集合：AI 建议禁用的场景名集合
    const disableSet = new Set(data.disable || [])
// 理由表：每个场景的禁用原因
    const reason = data.reason || {}
// 场景行更新：勾选禁用 + AI 理由回填
    sceneRows.value = sceneRows.value.map(r => ({ ...r, disable: disableSet.has(r.name), reason: reason[r.name] || "" }))
    MessagePlugin.success(`AI 规划完成：禁用 ${data.disable?.length || 0} 个场景`)
    // 步骤 2：记录 AI 当时的场景增删决策与理由
// 步骤 2 日志：记录 AI 当时的场景增删决策与理由、模型元信息
    await logStep(2, "AI 规划场景", { instruction: form.value.instruction, hint: hintB.value,
      disable: data.disable || [], keep: data.keep || [], functions_remove: data.functions_remove || [],
      reason: data.reason || {}, summary: data.summary || "", meta: data.meta || {} })
// 异常提示 + 复位忙碌标志
  } catch (e) { MessagePlugin.error(String(e)) } finally { busy.value = false }
}

// 确认应用：先 patch 场景清单（__scenes__）再 apply 落盘
// 两段式保证「规划结果」与「落盘」可分别留痕
async function applyScenes() {
// 禁用列表：勾选禁用的场景名集合
  const disable = sceneRows.value.filter(r => r.disable).map(r => r.name)
// patch 请求：写入 __scenes__ 特殊场景的禁用清单
  const j = await jfetch("/api/translator/ai-writer/patch", {
    method: "PUT", headers: ADMIN_HEAD(),
// 特殊场景键 __scenes__：承载全局禁用清单
    body: JSON.stringify({ role: form.value.role, scene: "__scenes__", patch: { scenes: { disable } },
                           task_id: taskId.value }),
  })
  if (!j.ok) return
// apply 请求：reset=true 按基线重建后套用（可复现）
  const ap = await jfetch("/api/translator/ai-writer/apply", {
    method: "POST", headers: ADMIN_HEAD(),
    body: JSON.stringify({ role: form.value.role, reset: true, task_id: taskId.value }),
  })
// apply 返回任务号：延续任务链
  if (ap.ok && ap.data.task_id) taskId.value = ap.data.task_id
// 变更与校验回填 + 步骤推进 + 快照刷新
  if (ap.ok) { lastChanges.value = ap.data.changes; validation.value = ap.data.validation; showWarnings.value = false }
  MessagePlugin.success(`已应用场景规划（禁用 ${disable.length} 个）`)
  step.value = 2
  await loadSnapshots()
}

// 单场景生成：SSE 流式产出该场景的权限补丁
// 补丁先暂存后端（patch 接口），应用时统一 apply
async function doGenerateScene(scene) {
// 单场景生成开始：置 loading
  sceneBusy.value = scene
  try {
    const data = await ssePost("/api/translator/ai-writer/generate-scene",
// 单场景生成请求体：全局指令 + 场景级提示
      { role: form.value.role, scene, base: form.value.base, instruction: form.value.instruction,
        title: form.value.title, hint: hints.value[scene] || "" })
    if (!data) return
// 补丁回填：对象形态 + 文本形态（可微调）
    const patch = data.patch
// 补丁对象合并
    patches.value = { ...patches.value, [scene]: patch }
// 补丁文本形态同步（可微调）
    patchText.value = { ...patchText.value, [scene]: JSON.stringify(patch, null, 2) }
// patch 请求：暂存该场景补丁到后端
    await jfetch("/api/translator/ai-writer/patch", {
      method: "PUT", headers: ADMIN_HEAD(),
      body: JSON.stringify({ role: form.value.role, scene, patch, task_id: taskId.value }),
    })
// 成功提示：引导微调后统一应用
    MessagePlugin.success(`${scene} 约束已生成（可在文本框内微调后应用）`)
  } catch (e) { MessagePlugin.error(String(e)) } finally { sceneBusy.value = "" }
}

// 清除单场景补丁：patch 置 null + 前后端同步删除
async function clearPatch(scene) {
  await jfetch("/api/translator/ai-writer/patch", {
    method: "PUT", headers: ADMIN_HEAD(),
// 清除请求：patch 置 null 删除暂存
    body: JSON.stringify({ role: form.value.role, scene, patch: null }),
  })
// 前端同步删除对象形态
  const p = { ...patches.value }; delete p[scene]; patches.value = p
// 前端同步删除文本形态
  const t = { ...patchText.value }; delete t[scene]; patchText.value = t
}

// 应用全部补丁并落盘：逐场景 parse 后统一 apply
// 文本域微调的 JSON 先 parse，解析失败跳过该场景并提示
async function doApply() {
  busy.value = true
  try {
// 逐场景提交：文本形态先 parse 为对象
    for (const [scene, txt] of Object.entries(patchText.value)) {
      try {
// 文本形态 parse 为对象：微调生效
        const obj = JSON.parse(txt)
// parse 后合并进补丁集
        patches.value = { ...patches.value, [scene]: obj }
        await jfetch("/api/translator/ai-writer/patch", {
          method: "PUT", headers: ADMIN_HEAD(),
          body: JSON.stringify({ role: form.value.role, scene, patch: obj, task_id: taskId.value }),
        })
// JSON 无法解析：跳过该场景并提示
      } catch { MessagePlugin.warning(`${scene} 的 JSON 无法解析，已跳过该场景`) }
    }
// apply 请求：reset=true 按基线重建后套用
    const ap = await jfetch("/api/translator/ai-writer/apply", {
      method: "POST", headers: ADMIN_HEAD(),
      body: JSON.stringify({ role: form.value.role, reset: true, task_id: taskId.value }),
    })
// 结果回填：变更列表 + 校验结论 + 步骤推进 + 快照刷新
    if (ap.ok) {
// apply 返回任务号回存
      if (ap.data.task_id) taskId.value = ap.data.task_id
      lastChanges.value = ap.data.changes
      validation.value = ap.data.validation
      MessagePlugin.success("已落盘并完成校验")
// 进入阶段 D
      step.value = 3
      await loadSnapshots()
      loadAwTasks()
    }
  } finally { busy.value = false }
}

// 重新校验：提交角色名，返回结构校验结果
async function doValidate() {
  const j = await jfetch("/api/translator/ai-writer/validate", {
    method: "POST", headers: ADMIN_HEAD(),
    body: JSON.stringify({ role: form.value.role, task_id: taskId.value }),
  })
// 校验结论回填
  if (j.ok) validation.value = j.data
}

// 快照列表加载：供回滚下拉选择
async function loadSnapshots() {
  if (!form.value.role) return
  const j = await jfetch(`/api/translator/ai-writer/snapshots?role=${form.value.role}`)
// 快照列表回填
  if (j.ok) snapshots.value = j.data.items
}

// 回滚：回退到选定快照后重新校验
async function doRollback() {
  const j = await jfetch("/api/translator/ai-writer/rollback", {
    method: "POST", headers: ADMIN_HEAD(),
// 回滚请求体：目标快照时间戳
    body: JSON.stringify({ role: form.value.role, ts: rollbackTs.value, task_id: taskId.value }),
  })
// 回滚成功：提示并重校验
  if (j.ok) { MessagePlugin.success("已回滚"); await doValidate() }
}

// 切换生效：确认后热重载（无需重启后端）
async function doSwitch() {
  const j = await jfetch("/api/translator/policies/switch", {
// 切换请求体：目标角色名
    method: "POST", headers: ADMIN_HEAD(), body: JSON.stringify({ name: form.value.role }),
  })
  if (j.ok) {
// 切换成功提示 + 关闭对话框
    MessagePlugin.success(`已切换生效：${form.value.role}`); switchDlg.value = false
    // 步骤 6：记录切换生效
// 步骤 6 日志：记录切换生效的角色名
    await logStep(6, "切换生效", { role: form.value.role })
    loadAwTasks()
  }
}

// 步骤条同步：点击步骤条可回跳（非法值保持不变）
function onStepChange(v) { step.value = typeof v === "number" ? v : step.value }

// 角色名变更联动：重新加载任务日志
watch(() => form.value.role, () => loadAwTasks())

// 挂载：加载基线场景与任务日志
onMounted(() => { loadBaseScenes(); loadAwTasks() })
</script>

<style scoped>
/* 根容器：纵排布局 */
.aiw { display: flex; flex-direction: column; gap: 16px; }
/* 弱化说明文本（灰小字） */
.dim { color: #A6A6A6; font-size: 12px; }
/* 日志表格上边距 */
.log-table { margin-top: 8px; }
.steps-log { margin-top: 14px; }
.log-meta { margin-bottom: 8px; }
/* 步骤日志元信息行 */
.step-item { border-top: 1px dashed #E5E7EB; padding: 10px 0; }
/* 步骤条目：虚线分隔，首条无分隔线 */
.step-item:first-of-type { border-top: none; }
/* 步骤头：标签 + 名称 + 时间横排 */
.step-head { display: flex; align-items: center; gap: 10px; font-size: 14px; }
.step-body { margin-top: 6px; font-size: 13px; }
/* 迷你代码块：暗底等宽，限高滚动 */
.mini { margin: 6px 0 0; padding: 8px; background: #0F172A; color: #CBD5E1; border-radius: 6px;
  font-size: 11px; max-height: 220px; overflow: auto; }
/* 机制说明卡：渐变底 */
.hero-card { display: flex; align-items: flex-start; gap: 14px; padding: 18px 20px; border-radius: 12px;
  background: linear-gradient(135deg, #E8F0FE 0%, #FFFFFF 60%); border: 1px solid #DCE6F7; }
/* 图标托盘：蓝底白标 */
.hero-icon { flex: 0 0 46px; height: 46px; border-radius: 12px; display: grid; place-items: center;
  background: #0052D9; color: #fff; }
/* 说明主体弹性填充 */
.hero-body { flex: 1; }
/* 标题字号与颜色 */
.hero-body h3 { margin: 0 0 6px; font-size: 20px; font-weight: 600; color: #1F2329; }
/* 副标题弱化跟随 */
.hero-sub { font-size: 13px; font-weight: 400; color: #4E5969; margin-left: 8px; }
/* 说明段行高与颜色 */
.hero-body p { margin: 0; font-size: 14px; line-height: 1.7; color: #4E5969; }
/* 步骤条容器 */
.aiw-steps { padding: 6px 0 10px; }
/* 面板容器：白底圆角 */
.panel { background: #fff; border: 1px solid #E5E7EB; border-radius: 12px; padding: 16px 18px; }
/* 面板头：图标+标题 */
.panel-head { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600;
  color: #1F2329; margin-bottom: 14px; }
/* 表单网格：三列 */
.form-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
/* 表单项纵排 */
.fi { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: #4E5969; }
/* 块级表单项（占整行） */
.fi.block { margin-top: 14px; }
.row-actions { display: flex; align-items: center; gap: 12px; margin-top: 14px; flex-wrap: wrap; }
/* 结果行：标签+路径+统计 */
.result { display: flex; align-items: center; gap: 10px; margin-top: 14px; font-size: 13px; }
.dim { color: #A6A6A6; font-size: 12px; }
/* 流式输出区：暗底终端风格 */
.stream { margin-top: 12px; }
/* 流式输出：暗底等宽限高 */
.stream pre { margin: 0; padding: 12px; border-radius: 8px; background: #0F172A; color: #CBD5E1;
  font-size: 12px; max-height: 220px; overflow: auto; }
/* 场景表上边距 */
.aiw-table { margin-top: 14px; }
/* 场景列表：纵排 */
.scene-list { display: flex; flex-direction: column; gap: 12px; }
/* 场景卡：浅底圆角 */
.scene-card { border: 1px solid #E5E7EB; border-radius: 10px; padding: 12px 14px; background: #FCFDFF; }
/* 场景头布局 */
.scene-head { display: flex; align-items: center; gap: 10px; font-size: 14px; margin-bottom: 10px; }
/* 场景操作行布局 */
.scene-actions { display: flex; align-items: center; gap: 8px; }
/* 场景提示输入弹性填充 */
.scene-hint { flex: 1; }
/* 等宽字体（补丁文本域） */
.mono { font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; margin-top: 10px; }
/* 校验结果区 */
.validate-box { margin-top: 14px; display: flex; flex-direction: column; gap: 6px; }
/* 警告摘要行 */
.v-warn-summary { display: flex; align-items: center; gap: 10px; font-size: 12px; margin-top: 2px; }
/* 校验结论行 */
.v-line { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 500; }
/* 通过态绿色 */
.v-line.ok { color: #00A870; }
.v-line.err { color: #E34D59; }
/* 错误/警告条目行 */
.v-item { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.v-item.err { color: #E34D59; }
.v-item.warn { color: #ED7B2F; }
/* 变更列表区：虚线分隔 */
.changes { margin-top: 14px; border-top: 1px dashed #E5E7EB; padding-top: 12px; }
.changes-title { font-size: 13px; font-weight: 600; color: #1F2329; margin-bottom: 6px; }
/* 快照下拉宽度 */
.snap-select { width: 240px; }
</style>
