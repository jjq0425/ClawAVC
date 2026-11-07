<template>
  <div class="sens">
    <div class="hero-card">
      <div class="hero-icon"><t-icon name="secured" size="30px" /></div>
      <div class="hero-body">
        <h3>敏感文件配置 <span class="hero-sub">哪些资源算敏感、什么动作才成立</span></h3>
        <p>按「敏感分组」管理：路径命中分组 + 动作性质相符，才会被判为敏感越权。可以人工维护，也可以让 AI 依据业务需求给出建议；
           <b>AI 只出建议，是否采纳由你决定</b>，保存前会做字段与红线校验。</p>
      </div>
      <div class="hero-actions">
        <t-button theme="default" variant="outline" @click="drawer = true">
          <template #icon><t-icon name="setting-1" /></template>AI 参数
        </t-button>
        <t-button theme="primary" variant="outline" @click="aiPanel = !aiPanel">
          <template #icon><t-icon name="bulb" /></template>AI 生成建议
        </t-button>
      </div>
    </div>

    <div class="stat-row">
      <div class="stat"><div class="n">{{ groups.length }}</div><div class="l">敏感分组</div></div>
      <div class="stat"><div class="n">{{ countBy('critical') }}</div><div class="l">critical</div></div>
      <div class="stat"><div class="n">{{ countBy('high') }}</div><div class="l">high</div></div>
      <div class="stat"><div class="n">{{ countMatch('any') }}</div><div class="l">读到即成立（any）</div></div>
      <div class="stat"><div class="n">{{ meta.version || '-' }}</div><div class="l">配置版本</div></div>
    </div>

    <details class="fold">
      <summary>判定模型与红线（改动前必读）</summary>
      <div class="fold-body">
        <p><b>判定三条件（同时满足才算敏感越权）：</b></p>
        <ol>
          <li><b>资源性质</b>：路径命中某分组（<code>prefixes</code> 用 startswith；<code>globs</code> 中 <code>*</code> 不跨路径分隔符，<code>**</code> 跨目录）</li>
          <li><b>动作性质</b>：分组 <code>match</code> 与实际动作相符 —— <code>any</code> 读到即成立（凭据类）；<code>write_only</code> 仅在观测到 write/create/delete 时成立（持久化面、二进制目录，读它们是常规行为）</li>
          <li><b>主体越界</b>：由分析器判定，不在此配置表达</li>
        </ol>
        <p class="warn-line"><b>红线：</b>① 不要按扩展名收 <code>*.pem</code> / <code>*.crt</code>（公开 CA 证书包会误判为私钥材料），私钥容器只收 <code>.p12</code> / <code>.pfx</code>；
          ② 不要用放宽敏感规则来压误报（误报要修根因，如 IR 授权缺失）；③ 前缀会连带命中，收窄优先用精确 glob；
          ④ 每条分组必须带 <code>reason</code>（威胁语义）与 <code>basis</code>（公开依据）；⑤ <code>severity</code> 只影响展示与排序，不参与判定。</p>
      </div>
    </details>

    <section v-if="aiPanel" class="panel ai-panel">
      <div class="panel-head"><t-icon name="bulb" /> AI 建议生成（独立模型参数）</div>
      <label class="fi"><span>业务需求 / 改动意图</span>
        <t-textarea v-model="requirement" :autosize="{ minRows: 3, maxRows: 8 }"
                    placeholder="例：新增数据库备份目录为敏感资源，仅落盘写入才成立；近期发现读取 /etc/environment 的误报，请给出收窄建议" />
      </label>
      <div class="row-actions">
        <t-button theme="primary" :loading="aiBusy" :disabled="!requirement.trim()" @click="doGenerate">
          <template #icon><t-icon name="play" /></template>生成建议
        </t-button>
        <span class="dim">生成只产出建议，不会自动修改配置</span>
      </div>
      <div v-if="aiText" class="stream"><pre>{{ aiText }}</pre></div>
      <div v-if="suggestions.length" class="sug-list">
        <div v-for="(s, i) in suggestions" :key="i" class="sug">
          <div class="sug-head">
            <t-tag :theme="actionTheme(s.action)" size="small" variant="light">{{ s.action }}</t-tag>
            <b>{{ s.group?.title || s.id || '未命名' }}</b>
            <span class="dim">{{ s.group?.match }} · {{ s.group?.severity }}</span>
          </div>
          <div class="dim">理由：{{ s.rationale || '—' }}</div>
          <div v-if="s.group?.globs?.length" class="mono dim">globs: {{ s.group.globs.join(' , ') }}</div>
          <div class="row-actions">
            <t-button size="small" theme="primary" variant="outline" @click="adopt(s)">采纳（合并到本地）</t-button>
          </div>
        </div>
      </div>
      <div v-if="aiSummary" class="dim">AI 总结：{{ aiSummary }}</div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <t-icon name="app" /> 敏感分组（{{ groups.length }}）
        <div class="head-actions">
          <t-button size="small" theme="default" variant="outline" @click="reload">重新加载</t-button>
          <t-button size="small" theme="primary" variant="outline" @click="openNew">
            <template #icon><t-icon name="add" /></template>新增分组
          </t-button>
          <t-button size="small" theme="primary" :loading="saving" @click="save">保存配置</t-button>
        </div>
      </div>

      <div class="grid">
        <div v-for="(g, i) in groups" :key="g.id || i" class="gcard">
          <div class="g-head">
            <t-tag :theme="g.severity === 'critical' ? 'danger' : 'warning'" size="small" variant="light">
              {{ g.severity }}
            </t-tag>
            <b>{{ g.title || g.id }}</b>
            <t-tag size="small" variant="outline">{{ g.match }}</t-tag>
            <t-tag v-if="g.override_runtime" size="small" theme="danger" variant="outline">穿透运行时</t-tag>
          </div>
          <div class="dim gid">{{ g.id }}</div>
          <div v-if="g.attck?.length" class="dim">ATT&amp;CK：{{ g.attck.join(' · ') }}</div>
          <details class="g-detail">
            <summary>路径规则（{{ (g.prefixes || []).length + (g.globs || []).length }}）</summary>
            <div v-if="g.prefixes?.length" class="mono">prefixes: {{ g.prefixes.join(' , ') }}</div>
            <div v-if="g.globs?.length" class="mono">globs: {{ g.globs.join(' , ') }}</div>
          </details>
          <div class="g-reason">{{ g.reason || '（缺少 reason）' }}</div>
          <div class="dim">依据：{{ g.basis || '（缺少 basis）' }}</div>
          <div class="g-ops">
            <t-button size="small" variant="text" theme="primary" @click="openEdit(i)">编辑</t-button>
            <t-button size="small" variant="text" theme="danger" @click="removeGroup(i)">删除</t-button>
          </div>
        </div>
      </div>

      <div v-if="validation && (validation.errors?.length || validation.warnings?.length)" class="validate">
        <div v-for="e in validation.errors || []" :key="e" class="v err">E · {{ e }}</div>
        <div v-for="w in validation.warnings || []" :key="w" class="v warn">W · {{ w }}</div>
      </div>
    </section>

    <t-dialog v-model:visible="editDlg" :header="editing === null ? '新增敏感分组' : '编辑敏感分组'"
              width="720px" :confirm-btn="{ content: '确定', theme: 'primary' }" @confirm="commitEdit">
      <div class="edit-form">
        <div class="grid2">
          <label class="fi"><span>id（小写字母/数字/下划线）</span><t-input v-model="form.id" placeholder="如 db_backup" /></label>
          <label class="fi"><span>title</span><t-input v-model="form.title" placeholder="如 数据库备份目录" /></label>
        </div>
        <div class="grid2">
          <label class="fi"><span>severity</span>
            <t-select v-model="form.severity" :options="[{label:'critical',value:'critical'},{label:'high',value:'high'}]" />
          </label>
          <label class="fi"><span>match</span>
            <t-select v-model="form.match"
                      :options="[{label:'any（读到即成立）',value:'any'},{label:'write_only（仅写入成立）',value:'write_only'}]" />
          </label>
        </div>
        <label class="fi"><span>override_runtime（凭据类建议开启，可穿透运行时白名单）</span>
          <t-select v-model="form.override_runtime" :options="[{label:'否',value:false},{label:'是',value:true}]" />
        </label>
        <label class="fi"><span>ATT&amp;CK 编号（逗号分隔）</span>
          <t-input v-model="attckText" placeholder="如 T1552.001, T1558" />
        </label>
        <label class="fi"><span>prefixes（每行一条，startswith 语义）</span>
          <t-textarea v-model="prefixText" :autosize="{ minRows: 2, maxRows: 6 }" placeholder="/etc/" />
        </label>
        <label class="fi"><span>globs（每行一条，* 不跨分隔符，** 跨目录）</span>
          <t-textarea v-model="globText" :autosize="{ minRows: 3, maxRows: 10 }" placeholder="/etc/shadow&#10;**/.ssh/**" />
        </label>
        <label class="fi"><span>reason（威胁语义，必填）</span>
          <t-textarea v-model="form.reason" :autosize="{ minRows: 2, maxRows: 6 }" />
        </label>
        <label class="fi"><span>basis（公开依据，必填：ATT&amp;CK / CIS / Falco / auditd）</span>
          <t-textarea v-model="form.basis" :autosize="{ minRows: 2, maxRows: 6 }" />
        </label>
        <p class="dim">红线提醒：不要收 <code>*.pem</code> / <code>*.crt</code>；保存时会校验。</p>
      </div>
    </t-dialog>

    <SensitiveConfigDrawer v-model:visible="drawer" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
import { MessagePlugin } from "tdesign-vue-next"
import SensitiveConfigDrawer from "./SensitiveConfigDrawer.vue"

const ADMIN_HEAD = () => ({
  "Content-Type": "application/json",
  "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "",
})

const drawer = ref(false)
const aiPanel = ref(false)
const groups = ref([])
const meta = ref({})
const saving = ref(false)
const validation = ref(null)
const requirement = ref("")
const suggestions = ref([])
const aiText = ref("")
const aiSummary = ref("")
const aiBusy = ref(false)

const editDlg = ref(false)
const editing = ref(null)
const attckText = ref("")
const prefixText = ref("")
const globText = ref("")
const emptyForm = () => ({ id: "", title: "", severity: "high", match: "write_only",
  override_runtime: false, attck: [], prefixes: [], globs: [], reason: "", basis: "" })
const form = ref(emptyForm())

const countBy = (sev) => groups.value.filter(g => g.severity === sev).length
const countMatch = (m) => groups.value.filter(g => g.match === m).length
const actionTheme = (a) => (a === 'add' ? 'primary' : (a === 'remove' ? 'danger' : 'warning'))

async function reload() {
  const j = await (await fetch("/api/translator/sensitive/config")).json()
  if (j.ok) { groups.value = j.data.sensitive_groups || []; meta.value = j.data.meta || {} }
  validation.value = null
}

async function save() {
  saving.value = true
  try {
    const r = await fetch("/api/translator/sensitive/config", {
      method: "PUT", headers: ADMIN_HEAD(),
      body: JSON.stringify({ meta: meta.value, sensitive_groups: groups.value }),
    })
    const j = await r.json()
    if (j.ok) {
      MessagePlugin.success("敏感文件配置已保存（版本 " + (j.data.meta?.version || '-') + "）")
      groups.value = j.data.sensitive_groups || []
      meta.value = j.data.meta || {}
      validation.value = j.data.validation || null
    } else {
      validation.value = { errors: j.errors || [j.error || '保存失败'], warnings: j.warnings || [] }
      MessagePlugin.error("保存被校验拦截，请查看下方提示")
    }
  } finally { saving.value = false }
}

function openNew() {
  editing.value = null
  form.value = emptyForm()
  attckText.value = ""; prefixText.value = ""; globText.value = ""
  editDlg.value = true
}

function openEdit(i) {
  editing.value = i
  const g = JSON.parse(JSON.stringify(groups.value[i]))
  form.value = { ...emptyForm(), ...g }
  attckText.value = (g.attck || []).join(", ")
  prefixText.value = (g.prefixes || []).join("\n")
  globText.value = (g.globs || []).join("\n")
  editDlg.value = true
}

function commitEdit() {
  const g = {
    id: form.value.id.trim(), title: form.value.title.trim(), severity: form.value.severity,
    match: form.value.match, override_runtime: !!form.value.override_runtime,
    attck: attckText.value.split(",").map(s => s.trim()).filter(Boolean),
    prefixes: prefixText.value.split("\n").map(s => s.trim()).filter(Boolean),
    globs: globText.value.split("\n").map(s => s.trim()).filter(Boolean),
    reason: form.value.reason.trim(), basis: form.value.basis.trim(),
  }
  if (editing.value === null) {
    if (groups.value.some(x => x.id === g.id)) { MessagePlugin.warning("id 已存在"); return }
    groups.value.push(g)
  } else {
    groups.value[editing.value] = g
  }
  editDlg.value = false
}

function removeGroup(i) {
  groups.value.splice(i, 1)
}

async function doGenerate() {
  aiBusy.value = true; aiText.value = ""; suggestions.value = []; aiSummary.value = ""
  try {
    const r = await fetch("/api/translator/sensitive/generate", {
      method: "POST", headers: ADMIN_HEAD(),
      body: JSON.stringify({ requirement: requirement.value, current: { meta: meta.value, sensitive_groups: groups.value } }),
    })
    const reader = r.body.getReader(); const dec = new TextDecoder()
    let buf = ""
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      const parts = buf.split("\n\n"); buf = parts.pop() || ""
      for (const p of parts) {
        const line = p.split("\n").find(l => l.startsWith("data: "))
        if (!line) continue
        const ev = JSON.parse(line.slice(6))
        if (ev.type === "text") aiText.value = ev.data
        else if (ev.type === "error") MessagePlugin.error(ev.message || "生成失败")
        else if (ev.type === "done") {
          suggestions.value = ev.data.suggestions || []
          aiSummary.value = ev.data.summary || ""
        }
      }
    }
    if (!suggestions.value.length && !aiText.value) MessagePlugin.warning("未生成建议，可补充更具体的业务需求")
  } catch (e) { MessagePlugin.error(String(e)) } finally { aiBusy.value = false }
}

function adopt(s) {
  const g = s.group || {}
  if (!g.id) { MessagePlugin.warning("建议缺少 id，无法采纳"); return }
  const idx = groups.value.findIndex(x => x.id === g.id)
  if (s.action === "remove") {
    if (idx >= 0) groups.value.splice(idx, 1)
  } else {
    const merged = { ...(idx >= 0 ? groups.value[idx] : {}), ...g }
    if (idx >= 0) groups.value[idx] = merged
    else groups.value.push(merged)
  }
  MessagePlugin.success(`已采纳：${g.id}（请点「保存配置」落盘）`)
}

onMounted(reload)
</script>

<style scoped>
.sens { display: flex; flex-direction: column; gap: 16px; }
.hero-card { display: flex; align-items: flex-start; gap: 14px; padding: 18px 20px; border-radius: 14px;
  background: linear-gradient(135deg, #0F172A 0%, #1E3A8A 55%, #2563EB 100%); color: #fff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, .18); }
.hero-icon { flex: 0 0 46px; height: 46px; border-radius: 12px; display: grid; place-items: center;
  background: rgba(255, 255, 255, .16); }
.hero-body { flex: 1; }
.hero-body h3 { margin: 0 0 6px; font-size: 20px; font-weight: 600; }
.hero-sub { font-size: 13px; font-weight: 400; opacity: .85; margin-left: 8px; }
.hero-body p { margin: 0; font-size: 14px; line-height: 1.8; opacity: .92; }
.hero-actions { display: flex; gap: 10px; flex-wrap: wrap; }
.stat-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
@media (max-width: 900px) { .stat-row { grid-template-columns: repeat(2, 1fr); } }
.stat { background: #fff; border: 1px solid #E5E7EB; border-radius: 12px; padding: 12px 14px; text-align: center; }
.stat .n { font-size: 22px; font-weight: 600; color: #1E3A8A; line-height: 1.3; }
.stat .l { font-size: 12px; color: #8A94A6; }
.panel { background: #fff; border: 1px solid #E5E7EB; border-radius: 14px; padding: 18px 20px; }
.panel-head { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: #1F2329; margin-bottom: 14px; flex-wrap: wrap; }
.head-actions { margin-left: auto; display: flex; gap: 8px; flex-wrap: wrap; }
.ai-panel { border-left: 4px solid #2563EB; }
.fold { background: #FCFDFF; border: 1px solid #E5E7EB; border-radius: 12px; padding: 12px 16px; }
.fold summary { cursor: pointer; font-weight: 600; color: #1E3A8A; }
.fold-body { font-size: 13.5px; color: #4E5969; line-height: 1.8; }
.warn-line { color: #8A5A00; background: #FEF3E2; border: 1px solid #F3D9AF; border-radius: 8px; padding: 8px 12px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
.gcard { border: 1px solid #E5E7EB; border-radius: 12px; padding: 14px 16px; background: #FCFDFF;
  display: flex; flex-direction: column; gap: 6px; }
.g-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 14.5px; }
.gid { font-family: "SFMono-Regular", Consolas, monospace; }
.g-detail { margin-top: 4px; }
.g-detail summary { cursor: pointer; font-size: 13px; color: #1E3A8A; }
.g-reason { font-size: 13.5px; }
.g-ops { display: flex; gap: 6px; margin-top: 6px; }
.fi { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: #4E5969; margin-bottom: 12px; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.row-actions { display: flex; align-items: center; gap: 10px; margin: 12px 0; flex-wrap: wrap; }
.dim { color: #A6A6A6; font-size: 12.5px; }
.mono { font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; }
.stream pre { margin: 10px 0; padding: 12px; background: #0F172A; color: #CBD5E1; border-radius: 8px;
  font-size: 12px; max-height: 240px; overflow: auto; }
.sug-list { display: flex; flex-direction: column; gap: 10px; }
.sug { border: 1px solid #E5E7EB; border-radius: 10px; padding: 12px 14px; background: #FCFDFF; }
.sug-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.validate { margin-top: 14px; display: flex; flex-direction: column; gap: 6px; }
.v { font-size: 13px; }
.v.err { color: #E34D59; }
.v.warn { color: #D97706; }
</style>
