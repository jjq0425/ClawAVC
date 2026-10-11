<template>
  <div class="aiw">
    <!-- ① 机制说明 -->
    <div class="hero-card">
      <div class="hero-icon"><t-icon name="root-list" size="30px" /></div>
      <div class="hero-body">
        <h3>AI 帮写 <span class="hero-sub">skill + workflow 组合生成角色策略库</span></h3>
        <p>由 <b>workflow</b> 先按基线创建目录结构（基线只读），再由 <b>AI</b> 依据你的指令生成场景、并按提示填充各场景权限约束；
           AI 只产出「权限意图 spec」，落盘与校验统一由 skill <code>clawavc-policy-creator</code> 执行，保证格式统一、结构完整。产物只落在新建角色目录。</p>
      </div>
      <t-button theme="default" variant="outline" @click="drawer = true">
        <template #icon><t-icon name="setting-1" /></template>AI 参数
      </t-button>
    </div>

    <!-- ② 阶段步骤条 -->
    <t-steps :current="step" class="aiw-steps" @change="onStepChange">
      <t-step-item title="建目录结构" content="选择基线并创建角色目录" />
      <t-step-item title="AI 生成场景" content="依据指令决定场景增删" />
      <t-step-item title="AI 填充内容" content="逐场景生成权限约束" />
      <t-step-item title="校验与生效" content="结构校验并切换生效" />
    </t-steps>

    <!-- ③ 阶段 A：建目录 -->
    <div class="panel" v-show="step === 0">
      <div class="panel-head"><t-icon name="folder-add" /> 阶段 A · 创建基础目录结构</div>
      <div class="form-grid">
        <label class="fi"><span>角色名</span>
          <t-input v-model="form.role" placeholder="如 analyst（字母数字下划线中划线，1-64）" />
        </label>
        <label class="fi"><span>基线策略库</span>
          <t-select v-model="form.base" :options="baseOptions" @change="loadBaseScenes" />
        </label>
        <label class="fi"><span>角色标题</span>
          <t-input v-model="form.title" placeholder="如 只读数据分析师" />
        </label>
      </div>
      <div class="fi block">
        <span>权限说明（给 AI 的自然语言指令）</span>
        <t-textarea v-model="form.instruction" :autosize="{ minRows: 3, maxRows: 8 }"
          placeholder="例：只能读 /data 下的文件，不能写；禁止联网；不许使用 git 命令" />
      </div>
      <div class="row-actions">
        <t-checkbox v-model="form.force">已存在同名角色时强制重建</t-checkbox>
        <t-button theme="primary" :loading="busy" @click="doScaffold">
          <template #icon><t-icon name="folder-add" /></template>创建角色目录
        </t-button>
      </div>
      <div class="result" v-if="scaffoldInfo">
        <t-tag theme="success" variant="light">已创建</t-tag>
        <code>{{ scaffoldInfo.path }}</code>
        <span class="dim">工具文件 {{ scaffoldInfo.tool_count }} 个 · 场景 {{ scaffoldInfo.scenes.length }} 个</span>
      </div>
    </div>

    <!-- ④ 阶段 B：AI 生成场景 -->
    <div class="panel" v-show="step === 1">
      <div class="panel-head"><t-icon name="layer" /> 阶段 B · AI 生成场景清单</div>
      <div class="fi block">
        <span>补充提示（可选，用于纠正或强调）</span>
        <t-input v-model="hintB" placeholder="如：保留搜索能力，但禁用邮件与即时通讯" />
      </div>
      <div class="row-actions">
        <t-button theme="primary" :loading="busy" :disabled="!form.role" @click="doGenerateScenes">
          <template #icon><t-icon name="bulb" /></template>让 AI 规划场景
        </t-button>
        <t-button theme="default" variant="outline" :disabled="!scenesResult" @click="applyScenes">
          确认并应用（禁用勾选场景）
        </t-button>
      </div>
      <div class="stream" v-if="streamText"><pre>{{ streamText }}</pre></div>
      <t-table v-if="sceneRows.length" :data="sceneRows" :columns="sceneCols" row-key="name" size="small" bordered
               class="aiw-table" :selected-row-keys="[]">
        <template #disable="{ row }"><t-checkbox v-model="row.disable" /></template>
        <template #reason="{ row }"><span class="dim">{{ row.reason || '—' }}</span></template>
      </t-table>
    </div>

    <!-- ⑤ 阶段 C：AI 填充场景内容 -->
    <div class="panel" v-show="step === 2">
      <div class="panel-head"><t-icon name="edit-1" /> 阶段 C · 逐场景填充权限约束</div>
      <div class="scene-list">
        <div class="scene-card" v-for="s in activeScenes" :key="s">
          <div class="scene-head">
            <b>{{ s }}</b><span class="dim">{{ sceneDesc(s) }}</span>
            <t-tag v-if="patches[s]" theme="success" variant="light" size="small">已生成</t-tag>
            <t-tag v-else theme="default" variant="light" size="small">待生成</t-tag>
          </div>
          <div class="scene-actions">
            <t-input v-model="hints[s]" size="small" class="scene-hint" placeholder="本场景的补充提示（可选）" />
            <t-button size="small" theme="primary" variant="outline" :loading="sceneBusy === s" @click="doGenerateScene(s)">
              {{ patches[s] ? "重生成" : "AI 生成" }}
            </t-button>
            <t-button size="small" theme="danger" variant="outline" v-if="patches[s]" @click="clearPatch(s)">清除</t-button>
          </div>
          <t-textarea v-if="patches[s]" v-model="patchText[s]" :autosize="{ minRows: 4, maxRows: 14 }" class="mono" />
        </div>
      </div>
      <div class="row-actions">
        <t-button theme="primary" :loading="busy" :disabled="!form.role" @click="doApply">
          <template #icon><t-icon name="check" /></template>应用全部补丁并落盘
        </t-button>
        <span class="dim">落盘按基线重建后套用全部补丁，结果可复现；直接改文件不会被保留</span>
      </div>
    </div>

    <!-- ⑥ 阶段 D：校验与生效 -->
    <div class="panel" v-show="step === 3">
      <div class="panel-head"><t-icon name="check-circle" /> 阶段 D · 校验与生效</div>
      <div class="row-actions">
        <t-button theme="default" variant="outline" :disabled="!form.role" @click="doValidate">重新校验</t-button>
        <t-select v-model="rollbackTs" :options="snapOptions" size="small" class="snap-select" placeholder="选择快照回滚" />
        <t-button theme="warning" variant="outline" :disabled="!rollbackTs" @click="doRollback">回滚</t-button>
        <t-button theme="danger" :disabled="!form.role || !validation?.ok" @click="switchDlg = true">
          <template #icon><t-icon name="swap" /></template>切换为该角色策略库
        </t-button>
      </div>
      <div v-if="validation" class="validate-box">
        <div class="v-line" :class="validation.ok ? 'ok' : 'err'">
          <t-icon :name="validation.ok ? 'check-circle' : 'close-circle'" />
          结构校验：{{ validation.ok ? "通过" : "存在阻断级错误" }} · 场景 {{ validation.info?.scenes ?? "-" }} 个 · 工具文件 {{ validation.info?.tool_files ?? "-" }} 个
        </div>
        <div v-for="e in validation.errors" :key="e" class="v-item err"><t-tag theme="danger" size="small">E</t-tag>{{ e }}</div>
        <div v-for="w in validation.warnings" :key="w" class="v-item warn"><t-tag theme="warning" size="small">W</t-tag>{{ w }}</div>
      </div>
      <div v-if="lastChanges?.length" class="changes">
        <div class="changes-title">最近一次落盘变更（{{ lastChanges.length }} 条）</div>
        <div v-for="c in lastChanges" :key="c" class="dim">· {{ c }}</div>
      </div>
    </div>

    <!-- ⑦ 切换确认 -->
    <t-dialog v-model:visible="switchDlg" header="确认切换生效" :confirm-btn="{ theme: 'danger', content: '确认切换' }" @confirm="doSwitch">
      <p>即将把当前生效策略库切换为 <b>{{ form.role }}</b>，切换后热重载立即生效（无需重启后端）。</p>
      <p class="dim">建议先完成校验，确认无误后再切换。</p>
    </t-dialog>

    <AiWriterConfigDrawer v-model:visible="drawer" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
import { MessagePlugin } from "tdesign-vue-next"
import AiWriterConfigDrawer from "./AiWriterConfigDrawer.vue"

const ADMIN_HEAD = () => ({
  "Content-Type": "application/json",
  "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "",
})

const step = ref(0)
const busy = ref(false)
const drawer = ref(false)
const switchDlg = ref(false)
const streamText = ref("")
const scaffoldInfo = ref(null)
const scenesResult = ref(null)
const sceneRows = ref([])
const baseScenes = ref([])
const patches = ref({})
const patchText = ref({})
const hints = ref({})
const hintB = ref("")
const validation = ref(null)
const lastChanges = ref([])
const snapshots = ref([])
const rollbackTs = ref("")
const sceneBusy = ref("")

const form = ref({ role: "", base: "default", title: "", instruction: "", force: false })
const baseOptions = [{ label: "default（普通办公/开发/分析）", value: "default" },
                     { label: "ops（运维/系统管理）", value: "ops" }]

const sceneCols = [
  { colKey: "name", title: "场景", width: 180 },
  { colKey: "desc", title: "说明", ellipsis: true },
  { colKey: "disable", title: "禁用", width: 90 },
  { colKey: "reason", title: "AI 理由", ellipsis: true },
]
const snapOptions = computed(() => snapshots.value.map(s => ({ label: `${s.ts} · ${s.label || "快照"}`, value: s.ts })))
const activeScenes = computed(() => sceneRows.value.filter(r => !r.disable).map(r => r.name))
const sceneDesc = (n) => (baseScenes.value.find(s => s.name === n)?.desc || "")

async function jfetch(url, opts = {}) {
  const r = await fetch(url, opts)
  const j = await r.json().catch(() => ({ ok: false, error: "响应解析失败" }))
  if (!j.ok && j.error) MessagePlugin.error(j.error)
  return j
}

async function ssePost(url, body, onText) {
  const r = await fetch(url, { method: "POST", headers: ADMIN_HEAD(), body: JSON.stringify(body) })
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ""
  let done = null
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
      if (ev.type === "text" && onText) onText(ev.data)
      else if (ev.type === "error") MessagePlugin.error(ev.message || "生成失败")
      else if (ev.type === "done") done = ev.data
    }
  }
  return done
}

async function loadBaseScenes() {
  const j = await jfetch(`/api/translator/ai-writer/base-scenes?base=${form.value.base}`)
  if (!j.ok) return
  baseScenes.value = j.data.scenes
  sceneRows.value = j.data.scenes.map(s => ({ name: s.name, desc: s.desc, disable: false, reason: "" }))
}

async function doScaffold() {
  if (!form.value.role) return MessagePlugin.warning("请填写角色名")
  busy.value = true
  try {
    const j = await jfetch("/api/translator/ai-writer/scaffold", {
      method: "POST", headers: ADMIN_HEAD(), body: JSON.stringify(form.value),
    })
    if (j.ok) {
      scaffoldInfo.value = j.data
      MessagePlugin.success(`已创建 ${j.data.role}（${j.data.tool_count} 个工具文件）`)
      step.value = 1
      await loadSnapshots()
    }
  } finally { busy.value = false }
}

async function doGenerateScenes() {
  busy.value = true; streamText.value = ""
  try {
    const data = await ssePost("/api/translator/ai-writer/generate-scenes",
      { ...form.value, hint: hintB.value }, t => { streamText.value = t })
    if (!data) return
    scenesResult.value = data
    const disableSet = new Set(data.disable || [])
    const reason = data.reason || {}
    sceneRows.value = sceneRows.value.map(r => ({ ...r, disable: disableSet.has(r.name), reason: reason[r.name] || "" }))
    MessagePlugin.success(`AI 规划完成：禁用 ${data.disable?.length || 0} 个场景`)
  } catch (e) { MessagePlugin.error(String(e)) } finally { busy.value = false }
}

async function applyScenes() {
  const disable = sceneRows.value.filter(r => r.disable).map(r => r.name)
  const j = await jfetch("/api/translator/ai-writer/patch", {
    method: "PUT", headers: ADMIN_HEAD(),
    body: JSON.stringify({ role: form.value.role, scene: "__scenes__", patch: { scenes: { disable } } }),
  })
  if (!j.ok) return
  const ap = await jfetch("/api/translator/ai-writer/apply", {
    method: "POST", headers: ADMIN_HEAD(), body: JSON.stringify({ role: form.value.role, reset: true }),
  })
  if (ap.ok) { lastChanges.value = ap.data.changes; validation.value = ap.data.validation }
  MessagePlugin.success(`已应用场景规划（禁用 ${disable.length} 个）`)
  step.value = 2
  await loadSnapshots()
}

async function doGenerateScene(scene) {
  sceneBusy.value = scene
  try {
    const data = await ssePost("/api/translator/ai-writer/generate-scene",
      { role: form.value.role, scene, base: form.value.base, instruction: form.value.instruction,
        title: form.value.title, hint: hints.value[scene] || "" })
    if (!data) return
    const patch = data.patch
    patches.value = { ...patches.value, [scene]: patch }
    patchText.value = { ...patchText.value, [scene]: JSON.stringify(patch, null, 2) }
    await jfetch("/api/translator/ai-writer/patch", {
      method: "PUT", headers: ADMIN_HEAD(),
      body: JSON.stringify({ role: form.value.role, scene, patch }),
    })
    MessagePlugin.success(`${scene} 约束已生成（可在文本框内微调后应用）`)
  } catch (e) { MessagePlugin.error(String(e)) } finally { sceneBusy.value = "" }
}

async function clearPatch(scene) {
  await jfetch("/api/translator/ai-writer/patch", {
    method: "PUT", headers: ADMIN_HEAD(),
    body: JSON.stringify({ role: form.value.role, scene, patch: null }),
  })
  const p = { ...patches.value }; delete p[scene]; patches.value = p
  const t = { ...patchText.value }; delete t[scene]; patchText.value = t
}

async function doApply() {
  busy.value = true
  try {
    for (const [scene, txt] of Object.entries(patchText.value)) {
      try {
        const obj = JSON.parse(txt)
        patches.value = { ...patches.value, [scene]: obj }
        await jfetch("/api/translator/ai-writer/patch", {
          method: "PUT", headers: ADMIN_HEAD(),
          body: JSON.stringify({ role: form.value.role, scene, patch: obj }),
        })
      } catch { MessagePlugin.warning(`${scene} 的 JSON 无法解析，已跳过该场景`) }
    }
    const ap = await jfetch("/api/translator/ai-writer/apply", {
      method: "POST", headers: ADMIN_HEAD(), body: JSON.stringify({ role: form.value.role, reset: true }),
    })
    if (ap.ok) {
      lastChanges.value = ap.data.changes
      validation.value = ap.data.validation
      MessagePlugin.success("已落盘并完成校验")
      step.value = 3
      await loadSnapshots()
    }
  } finally { busy.value = false }
}

async function doValidate() {
  const j = await jfetch("/api/translator/ai-writer/validate", {
    method: "POST", headers: ADMIN_HEAD(), body: JSON.stringify({ role: form.value.role }),
  })
  if (j.ok) validation.value = j.data
}

async function loadSnapshots() {
  if (!form.value.role) return
  const j = await jfetch(`/api/translator/ai-writer/snapshots?role=${form.value.role}`)
  if (j.ok) snapshots.value = j.data.items
}

async function doRollback() {
  const j = await jfetch("/api/translator/ai-writer/rollback", {
    method: "POST", headers: ADMIN_HEAD(),
    body: JSON.stringify({ role: form.value.role, ts: rollbackTs.value }),
  })
  if (j.ok) { MessagePlugin.success("已回滚"); await doValidate() }
}

async function doSwitch() {
  const j = await jfetch("/api/translator/policies/switch", {
    method: "POST", headers: ADMIN_HEAD(), body: JSON.stringify({ name: form.value.role }),
  })
  if (j.ok) { MessagePlugin.success(`已切换生效：${form.value.role}`); switchDlg.value = false }
}

function onStepChange(v) { step.value = typeof v === "number" ? v : step.value }

onMounted(() => { loadBaseScenes() })
</script>

<style scoped>
.aiw { display: flex; flex-direction: column; gap: 16px; }
.hero-card { display: flex; align-items: flex-start; gap: 14px; padding: 18px 20px; border-radius: 12px;
  background: linear-gradient(135deg, #E8F0FE 0%, #FFFFFF 60%); border: 1px solid #DCE6F7; }
.hero-icon { flex: 0 0 46px; height: 46px; border-radius: 12px; display: grid; place-items: center;
  background: #0052D9; color: #fff; }
.hero-body { flex: 1; }
.hero-body h3 { margin: 0 0 6px; font-size: 20px; font-weight: 600; color: #1F2329; }
.hero-sub { font-size: 13px; font-weight: 400; color: #4E5969; margin-left: 8px; }
.hero-body p { margin: 0; font-size: 14px; line-height: 1.7; color: #4E5969; }
.aiw-steps { padding: 6px 0 10px; }
.panel { background: #fff; border: 1px solid #E5E7EB; border-radius: 12px; padding: 16px 18px; }
.panel-head { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600;
  color: #1F2329; margin-bottom: 14px; }
.form-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.fi { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: #4E5969; }
.fi.block { margin-top: 14px; }
.row-actions { display: flex; align-items: center; gap: 12px; margin-top: 14px; flex-wrap: wrap; }
.result { display: flex; align-items: center; gap: 10px; margin-top: 14px; font-size: 13px; }
.dim { color: #A6A6A6; font-size: 12px; }
.stream { margin-top: 12px; }
.stream pre { margin: 0; padding: 12px; border-radius: 8px; background: #0F172A; color: #CBD5E1;
  font-size: 12px; max-height: 220px; overflow: auto; }
.aiw-table { margin-top: 14px; }
.scene-list { display: flex; flex-direction: column; gap: 12px; }
.scene-card { border: 1px solid #E5E7EB; border-radius: 10px; padding: 12px 14px; background: #FCFDFF; }
.scene-head { display: flex; align-items: center; gap: 10px; font-size: 14px; margin-bottom: 10px; }
.scene-actions { display: flex; align-items: center; gap: 8px; }
.scene-hint { flex: 1; }
.mono { font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; margin-top: 10px; }
.validate-box { margin-top: 14px; display: flex; flex-direction: column; gap: 6px; }
.v-line { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 500; }
.v-line.ok { color: #00A870; }
.v-line.err { color: #E34D59; }
.v-item { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.v-item.err { color: #E34D59; }
.v-item.warn { color: #ED7B2F; }
.changes { margin-top: 14px; border-top: 1px dashed #E5E7EB; padding-top: 12px; }
.changes-title { font-size: 13px; font-weight: 600; color: #1F2329; margin-bottom: 6px; }
.snap-select { width: 240px; }
</style>
