<template>
  <div class="advice-tab">
    <!-- ① 机制说明 Hero -->
    <div class="hero-card">
      <div class="hero-icon"><t-icon name="secured" size="30px" /></div>
      <div class="hero-body">
        <h3>可替代工具引导 <span class="hero-sub">最小安全权限策略</span></h3>
        <p>将各类风险命令的「替代方案 / 最小权限建议」从策略 JSON 中剥离，统一维护在独立引导文档中，由策略 JSON 在<b>场景级</b>通过 <code>advice_docs</code> 引用。文档按风险类别分块，每块以 <code>&lt;!-- applies: 场景名 --&gt;</code> 标注适用场景。</p>
      </div>
    </div>

    <!-- ② 角色规划 -->
    <div class="role-grid">
      <div class="role-card role-user">
        <div class="role-head"><t-icon name="user-circle" size="20px" /><b>普通用户角色</b></div>
        <p>启用本引导：命中 warn 类命令时须先说明风险，并优先采用替代方案（最小安全权限策略）。</p>
      </div>
      <div class="role-card role-ops">
        <div class="role-head"><t-icon name="setting-1" size="20px" /><b>运维人员角色</b></div>
        <p>以其本身 query 为主体策略，不强制套用引导文档（按用户原始意图生成）。</p>
      </div>
    </div>

    <!-- ③ 使用指引（注入开关 / 编辑 / 同步） -->
    <div class="note-card">
      <div class="note-title"><t-icon name="info-circle" size="16px" /> 使用指引</div>
      <div class="note-row">
        <t-tag theme="primary" variant="light">注入开关</t-tag>
        <span><b>开启</b>：引导文档按场景分块注入 Level-2 提示词（翻译模型据此选择替代方案，仅加载与当前场景匹配的分块）；<b>关闭</b>：不进入翻译模型提示词，仅作为参考文档供查看与同步 AGENTS.md。开关写入场景 JSON 的 <code>advice_docs[].inject</code> 字段。</span>
      </div>
      <div class="note-row">
        <t-tag theme="warning" variant="light">分块编辑</t-tag>
        <span>文档按风险类别分块，可在此<b>逐块编辑正文、修改适用场景（applies）、新增或删除分块</b>，文档由<b>全局配置 <code>advice_docs.json</code></b>声明（仅含 path 与 inject）；某场景是否注入该文档，完全取决于其分块是否存在<b>适用于该场景</b>（或全局）的内容——新增分块时填写 applies 场景名即可，无需改动任何场景 JSON。保存后写回 Markdown 并经注册表热重载生效。<code>applies</code> 支持多场景（逗号分隔，如 <code>shell_exec, file_ops</code>），留空表示全局分块（注入所有场景）；文档头部「适用场景」即由各分块 applies 汇总得出。</span>
      </div>
      <div class="note-row">
        <t-tag theme="success" variant="light">同步至 AGENTS.md</t-tag>
        <span>将引导内容注入主模型（OpenClaw）的自我认知约束文档，使其在生成命令阶段即具备风险识别能力——与审计侧基于 IR 的事中判定形成「事前引导 + 事中拦截」双重防线；同步为幂等标记块操作，<b>始终全量同步</b>，可随时更新或移除。</span>
      </div>
    </div>

    <!-- ④ 当前 Policy 联动 -->
    <div class="linkage-card">
      <div class="linkage-tip">
        <t-icon name="link" size="16px" />
        <span>可替代工具引导与<b>当前 Policy</b> 绑定：仅当当前策略库的场景 JSON 在场景级配置了 <code>advice_docs</code> 字段时，对应文档才会被引用加载；切换 Policy（如 default ↔ ops）后，引用关系与加载内容随之切换。</span>
      </div>
      <div class="policy-bar" v-if="currentPolicy">
        <span class="policy-label">当前策略库</span>
        <code class="policy-path">{{ currentPolicy }}</code>
      </div>
    </div>

    <!-- ⑤ 引导文档卡 -->
    <div v-for="doc in docs" :key="doc.path" class="doc-card">
      <div class="doc-head">
        <div class="doc-title">
          <span class="doc-badge">引导文档：{{ doc.path }}</span>
          <span class="status-dot" :class="doc.loaded ? 'on' : 'off'"></span>
          <span class="status-text" :class="doc.loaded ? 'on' : 'off'">
            {{ doc.loaded ? "已加载" : "未加载（提示词降级为占位）" }}
          </span>
          <span class="inject-switch">
            <t-switch v-model="doc.inject" size="small" @change="(v) => toggleInject(doc, v)" />
            <span class="inject-label" :class="{ off: !doc.inject }">
              {{ doc.inject ? "已注入 IR 翻译模型" : "未注入（仅参考文档）" }}
            </span>
          </span>
        </div>
        <div class="doc-actions">
          <t-button size="small" variant="outline" @click="loadDocs">
            <template #icon><t-icon name="refresh" /></template>刷新
          </t-button>
          <t-button size="small" theme="primary" :loading="pushing === doc.path" :disabled="!doc.loaded" @click="pushToAgents(doc)">
            <template #icon><t-icon name="upload" /></template>同步至 AGENTS.md
          </t-button>
          <t-button size="small" theme="danger" variant="outline" :loading="deleting" :disabled="!agentsPresent" @click="deleteFromAgents()">
            <template #icon><t-icon name="delete" /></template>删除
          </t-button>
        </div>
      </div>

      <div class="path-bar">
        <span class="path-label">完整路径</span>
        <code class="path-value">{{ doc.resolved_path }}</code>
        <t-button size="small" shape="square" variant="text" @click="copyPath(doc.resolved_path)" title="复制路径">
          <t-icon name="copy" />
        </t-button>
        <span class="path-ref">引用路径 {{ doc.path }}</span>
      </div>

      <div class="refs-bar">
        <span class="path-label">当前引用</span>
        <t-tag v-for="r in doc.refs" :key="r" size="small" variant="outline" class="ref-chip">{{ r }}</t-tag>
        <t-tag size="small" :theme="agentsPresent ? 'success' : 'default'" variant="light" class="ref-chip">
          {{ agentsPresent ? "AGENTS.md 已含引导块" : "AGENTS.md 未注入" }}
        </t-tag>
        <span class="refs-hint">该文档由全局配置 <code>advice_docs.json</code> 声明；适用哪些场景完全由各分块的 applies 标注决定（见下方分块编辑）。</span>
      </div>

      <!-- 分块编辑器 -->
      <div class="editor-wrap">
        <div class="sec-toolbar">
          <span class="tb-label"><t-icon name="file-paste" size="14px" /> 引导文档分块编辑（共 {{ (edits[doc.path] || {}).sections?.length || 0 }} 块）</span>
          <div class="tb-actions">
            <t-button size="small" variant="outline" @click="addSection(doc)">
              <template #icon><t-icon name="add" /></template>新增分块
            </t-button>
            <t-button size="small" variant="outline" @click="resetEdit(doc)">还原</t-button>
            <t-button size="small" variant="outline" @click="preview = !preview">
              {{ preview ? "返回编辑" : "预览注入视图" }}
            </t-button>
            <t-button size="small" theme="primary" :loading="saving === doc.path" @click="saveDoc(doc)">保存</t-button>
          </div>
        </div>

        <pre v-if="preview" class="doc-content">{{ injectedView(doc) }}</pre>

        <div v-else class="sec-list">
          <div v-for="(sec, i) in (edits[doc.path] || {}).sections || []" :key="i" class="sec-block">
            <div class="sec-head">
              <t-input v-model="sec.title" size="small" class="sec-title" placeholder="分块标题（如：文件删除）" />
              <t-select
                v-model="sec.applies"
                class="sec-applies"
                size="small"
                multiple
                clearable
                filterable
                :min-collapsed-num="3"
                :options="sceneOptions"
                placeholder="applies 场景（可多选，留空=全局）"
              />
              <t-button size="small" variant="text" theme="danger" @click="removeSection(doc, i)">删除</t-button>
            </div>
            <t-textarea v-model="sec.body" :autosize="{ minRows: 2, maxRows: 14 }" class="sec-body" />
          </div>
          <div v-if="!((edits[doc.path] || {}).sections || []).length" class="empty-tip">暂无分块，点击「新增分块」添加</div>
        </div>
      </div>
    </div>

    <t-empty v-if="!loading && !docs.length" description="当前策略库未配置任何 advice_docs 引用" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
import { MessagePlugin } from "tdesign-vue-next"

const AGENTS_TARGET = "~/.openclaw/workspace/AGENTS.md"
const docs = ref([])
const currentPolicy = ref("")
const loading = ref(false)
const pushing = ref("")
const deleting = ref(false)
const saving = ref("")
const agentsPresent = ref(false)
const edits = ref({})      // { docPath: { preamble, sections: [{title, appliesText, body}] } }
const preview = ref(false)
const scenes = ref([])

// 可选项 = 当前策略库场景 + 文档中已使用（可能已失效）的场景值，保证历史值可见可删
const sceneOptions = computed(() => {
  const set = new Set(scenes.value)
  docs.value.forEach(d => (d.sections || []).forEach(sec => (sec.applies || []).forEach(x => set.add(x))))
  Object.values(edits.value).forEach(e => (e.sections || []).forEach(sec => (sec.applies || []).forEach(x => set.add(x))))
  return [...set].map(v => ({ label: v, value: v }))
})

async function loadScenes() {
  try {
    const r = await fetch("/api/translator/registry")
    const j = await r.json()
    if (j.ok && j.data && j.data.scenes) scenes.value = Object.keys(j.data.scenes)
  } catch {}
}

function toEdit(doc) {
  return {
    preamble: doc.preamble || "",
    sections: (doc.sections || []).map(s => ({
      title: s.title,
      applies: [...(s.applies || [])],
      body: s.body || ""
    }))
  }
}

async function loadDocs() {
  loading.value = true
  try {
    const r = await fetch("/api/translator/advice-docs")
    const j = await r.json()
    if (j.ok) {
      docs.value = j.data
      j.data.forEach(d => { edits.value[d.path] = toEdit(d) })
    } else MessagePlugin.error(j.error || "加载失败")
  } catch { MessagePlugin.error("连接后端失败") }
  loading.value = false
}

async function loadPolicy() {
  try {
    const r = await fetch("/api/translator/registry-path")
    const j = await r.json()
    if (j.ok) currentPolicy.value = j.data.path
  } catch {}
}

async function loadAgentsStatus() {
  try {
    const r = await fetch(`/api/openclaw/soul-advice?target_path=${encodeURIComponent(AGENTS_TARGET)}`)
    const j = await r.json()
    if (j.ok) agentsPresent.value = !!j.data.present
  } catch {}
}

async function toggleInject(doc, val) {
  try {
    const r = await fetch("/api/translator/advice-docs/inject", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: doc.path, inject: !!val })
    })
    const j = await r.json()
    if (j.ok) MessagePlugin.success(val ? "已开启注入 IR 翻译模型" : "已关闭注入（仅作参考文档）")
    else { MessagePlugin.error(j.error || "切换失败"); await loadDocs() }
  } catch { MessagePlugin.error("连接后端失败"); await loadDocs() }
}

function addSection(doc) {
  const e = edits.value[doc.path] || (edits.value[doc.path] = { preamble: "", sections: [] })
  e.sections.push({ title: "新分块", applies: [], body: "" })
}

function removeSection(doc, idx) {
  edits.value[doc.path]?.sections.splice(idx, 1)
}

function resetEdit(doc) {
  edits.value[doc.path] = toEdit(doc)
  MessagePlugin.info("已还原为文档当前内容")
}

function injectedView(doc) {
  const scenes = doc.scenes || []
  if (doc.inject === false) return "[已关闭注入：该文档不进入翻译模型提示词]"
  if (doc.injected && scenes.length && doc.injected[scenes[0]]) return doc.injected[scenes[0]]
  return doc.content
}

async function saveDoc(doc) {
  const e = edits.value[doc.path]
  if (!e) return
  const sections = e.sections
    .filter(s => (s.title || "").trim())
    .map(s => ({
      title: s.title.trim(),
      applies: (s.applies || []).map(x => String(x).trim()).filter(Boolean),
      body: s.body || ""
    }))
  if (!sections.length) { MessagePlugin.warning("至少保留一个分块"); return }
  saving.value = doc.path
  try {
    const r = await fetch("/api/translator/advice-docs/content", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: doc.path, preamble: e.preamble, sections })
    })
    const j = await r.json()
    if (j.ok) {
      MessagePlugin.success(`已保存 ${j.data.sections} 个分块（${j.data.bytes} 字节）`)
      await loadDocs()
    } else MessagePlugin.error(j.error || "保存失败")
  } catch { MessagePlugin.error("连接后端失败") }
  saving.value = ""
}

async function pushToAgents(doc) {
  pushing.value = doc.path
  try {
    const r = await fetch("/api/openclaw/soul-advice", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: doc.resolved_path, target_path: AGENTS_TARGET })
    })
    const j = await r.json()
    if (j.ok) {
      MessagePlugin.success(`已${j.data.action === "replaced" ? "覆盖更新" : "追加"}至 AGENTS.md（全量）`)
      await loadAgentsStatus()
    } else MessagePlugin.error(j.error || "同步失败")
  } catch { MessagePlugin.error("连接后端失败") }
  pushing.value = ""
}

async function deleteFromAgents() {
  deleting.value = true
  try {
    const r = await fetch("/api/openclaw/soul-advice", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_path: AGENTS_TARGET })
    })
    const j = await r.json()
    if (j.ok) {
      MessagePlugin.success(j.data.action === "deleted" ? "已从 AGENTS.md 移除引导块" : "AGENTS.md 中本无引导块")
      agentsPresent.value = false
    } else MessagePlugin.error(j.error || "删除失败")
  } catch { MessagePlugin.error("连接后端失败") }
  deleting.value = false
}

async function copyPath(p) {
  try { await navigator.clipboard.writeText(p); MessagePlugin.success("路径已复制") }
  catch { MessagePlugin.warning("复制失败，请手动选择") }
}

onMounted(() => { loadDocs(); loadAgentsStatus(); loadPolicy(); loadScenes() })
</script>

<style scoped>
.advice-tab { display: flex; flex-direction: column; gap: 14px; }

/* Hero */
.hero-card { display: flex; gap: 16px; align-items: flex-start; padding: 20px 22px;
  background: linear-gradient(135deg, #f0f6ff 0%, #eef7f2 100%);
  border: 1px solid #dbe7f8; border-radius: 12px; }
.hero-icon { flex-shrink: 0; width: 52px; height: 52px; border-radius: 12px;
  display: flex; align-items: center; justify-content: center; color: #fff;
  background: linear-gradient(135deg, #3d7fff 0%, #2fb886 100%); box-shadow: 0 4px 10px rgba(61,127,255,.25); }
.hero-body h3 { margin: 0 0 6px; font-size: 17px; font-weight: 700; color: #1a2b4a; display: flex; align-items: center; gap: 10px; }
.hero-sub { font-size: 11px; font-weight: 500; color: #2469d8; background: #e2edff; padding: 2px 10px; border-radius: 999px; }
.hero-body p { margin: 0; font-size: 13px; color: #5a6b85; line-height: 1.8; }

/* 角色规划 */
.role-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 14px; }
.role-card { border-radius: 10px; padding: 14px 16px; border: 1px solid; }
.role-card p { margin: 8px 0 0; font-size: 13px; line-height: 1.7; }
.role-head { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.role-user { background: #f3faf6; border-color: #cfeee0; } .role-user .role-head, .role-user p { color: #1f6b47; }
.role-ops { background: #fdf7ef; border-color: #f5e2c8; } .role-ops .role-head, .role-ops p { color: #8a5a1c; }

/* 说明卡 */
.note-card { background: #fff; border: 1px solid #e7e7e7; border-radius: 10px; padding: 14px 18px; }
.note-title { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; color: #333; margin-bottom: 10px; }
.note-row { display: flex; align-items: flex-start; gap: 8px; font-size: 13px; color: #555; line-height: 1.8; }
.note-row + .note-row { margin-top: 8px; }
.note-row code, .linkage-tip code { background: #f0f2f5; padding: 1px 6px; border-radius: 4px; font-size: 12px; }

/* Policy 联动 */
.linkage-card { background: #f6f9ff; border: 1px solid #d4e4ff; border-radius: 10px; padding: 12px 16px; }
.linkage-tip { display: flex; gap: 8px; align-items: flex-start; font-size: 13px; color: #40516e; line-height: 1.8; }
.policy-bar { display: flex; align-items: center; gap: 10px; margin-top: 10px; padding-top: 10px; border-top: 1px dashed #d4e4ff; }
.policy-label, .path-label { flex-shrink: 0; font-size: 12px; color: #8892a6; }
.policy-path { font-size: 12px; color: #2469d8; background: #e9f1ff; padding: 3px 10px; border-radius: 6px; word-break: break-all; }

/* 文档卡 */
.doc-card { background: #fff; border: 1px solid #e7e7e7; border-radius: 12px; padding: 16px 20px;
  box-shadow: 0 1px 3px rgba(30,50,90,.04); transition: box-shadow .2s; }
.doc-card:hover { box-shadow: 0 4px 14px rgba(30,50,90,.1); }
.doc-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
.doc-title { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.doc-badge { font-size: 12px; font-weight: 600; color: #fff; padding: 3px 12px; border-radius: 999px;
  background: linear-gradient(135deg, #3d7fff, #6a5cff); font-family: monospace; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; }
.status-dot.on { background: #2fb886; animation: pulse 2s infinite; }
.status-dot.off { background: #d9455f; }
.status-text { font-size: 12px; } .status-text.on { color: #1f8f5f; } .status-text.off { color: #d9455f; }
.inject-switch { display: inline-flex; align-items: center; gap: 6px; margin-left: 4px;
  padding-left: 12px; border-left: 1px solid #eee; }
.inject-label { font-size: 12px; color: #1f8f5f; }
.inject-label.off { color: #8a94a6; }
.doc-actions { display: flex; gap: 8px; flex-wrap: wrap; }

.path-bar, .refs-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.path-bar { padding: 9px 12px; background: #f7f9fc; border-radius: 8px; }
.path-value { font-size: 12px; color: #2469d8; font-family: monospace; word-break: break-all; }
.path-ref { font-size: 11px; color: #a0a8b8; font-family: monospace; margin-left: auto; }
.ref-chip { font-family: monospace; font-size: 11px; }
.refs-hint { font-size: 11px; color: #9aa3b2; line-height: 1.7; flex-basis: 100%; }
.refs-hint code { background: #f0f2f5; padding: 1px 5px; border-radius: 4px; }

/* 分块编辑器 */
.editor-wrap { margin-top: 12px; border: 1px solid #edf0f5; border-radius: 8px; overflow: hidden; }
.sec-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap;
  font-size: 12px; color: #5a6b85; padding: 8px 12px; background: #fafbfd; border-bottom: 1px solid #edf0f5; }
.tb-label { display: flex; align-items: center; gap: 6px; font-weight: 600; }
.tb-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.sec-list { padding: 12px; display: flex; flex-direction: column; gap: 10px; background: #fff; }
.sec-block { border: 1px solid #eef1f6; border-radius: 8px; padding: 10px 12px; background: #fcfdff; }
.sec-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.sec-title { max-width: 260px; }
.sec-applies { min-width: 300px; max-width: 460px; }
.sec-body :deep(textarea) { font-family: monospace; font-size: 12px; line-height: 1.7; }
.empty-tip { text-align: center; color: #a0a8b8; font-size: 12px; padding: 16px; }
.doc-content { background: #fff; padding: 14px 16px; font-size: 12px; line-height: 1.7; margin: 0;
  max-height: 480px; overflow: auto; white-space: pre-wrap; word-break: break-word; color: #374151; }

@keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(47,184,134,.45); } 70% { box-shadow: 0 0 0 7px rgba(47,184,134,0); } 100% { box-shadow: 0 0 0 0 rgba(47,184,134,0); } }
</style>
