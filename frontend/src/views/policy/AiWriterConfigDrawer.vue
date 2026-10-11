<template>
  <t-drawer v-model:visible="inner" header="AI 帮写参数" size="860px" :close-on-overlay-click="true"
            :footer="false" destroy-on-close>
    <div class="cfg">
      <!-- ① 连接参数 -->
      <div class="sec">
        <div class="sec-head"><t-icon name="link" /> 模型连接参数</div>
        <p class="sec-tip">与「模型配置」Tab 相互独立，仅用于 AI 帮写的生成调用。</p>
        <div class="grid">
          <label class="fi"><span>Base URL</span>
            <t-input v-model="cfg.api_base_url" placeholder="https://api.longcat.chat/openai" />
          </label>
          <label class="fi"><span>Model</span>
            <t-input v-model="cfg.model" placeholder="如 LongCat-2.0-Preview / u2-flash" />
          </label>
        </div>
        <label class="fi block"><span>API Token</span>
          <t-input v-model="cfg.api_key" type="password" :placeholder="cfg.has_api_key ? '已配置（留空则不修改）' : 'sk-...'" />
          <span class="dim" v-if="cfg.api_key_masked">当前：{{ cfg.api_key_masked }}</span>
        </label>
        <div class="grid">
          <label class="fi"><span>Temperature</span><t-input v-model="cfg.temperature" placeholder="0" /></label>
          <label class="fi"><span>超时（秒）</span><t-input v-model="cfg.timeout" placeholder="120" /></label>
        </div>
        <div class="row">
          <t-button theme="default" variant="outline" :loading="testing" @click="doTest">
            <template #icon><t-icon name="check-circle" /></template>测试连接
          </t-button>
          <span v-if="testResult" class="dim">{{ testResult }}</span>
          <t-button theme="primary" :loading="saving" @click="saveConfig">
            <template #icon><t-icon name="save" /></template>保存参数
          </t-button>
        </div>
      </div>

      <!-- ② Skill 提示词 -->
      <div class="sec">
        <div class="sec-head"><t-icon name="file-copy" /> Skill 提示词（SKILL.md）</div>
        <p class="sec-tip">该文档作为 AI 生成时的系统提示词基座，直接决定生成策略遵循的规范。保存时自动备份原文件。</p>
        <div class="row">
          <span class="dim">{{ skill.path }}</span>
          <span class="dim">字数 {{ skill.content?.length || 0 }}</span>
          <t-button size="small" theme="danger" variant="outline" @click="doRestore">恢复默认</t-button>
          <t-button size="small" theme="primary" :loading="savingDoc" @click="saveDoc">保存提示词</t-button>
        </div>
        <t-textarea v-model="skill.content" class="mono" :autosize="{ minRows: 18, maxRows: 32 }" />
        <div class="row" v-if="skill.backups?.length">
          <span class="dim">最近备份：</span>
          <t-tag v-for="b in skill.backups.slice(0, 5)" :key="b.name" size="small" variant="light">{{ b.name.replace("SKILL.md.bak-", "") }}</t-tag>
        </div>
      </div>
    </div>
  </t-drawer>
</template>

<script setup>
import { ref, watch, computed } from "vue"
import { MessagePlugin } from "tdesign-vue-next"

const props = defineProps({ visible: { type: Boolean, default: false } })
const emit = defineEmits(["update:visible"])
const inner = computed({
  get: () => props.visible,
  set: (v) => emit("update:visible", v),
})

const ADMIN_HEAD = () => ({
  "Content-Type": "application/json",
  "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "",
})

const cfg = ref({ api_base_url: "", model: "", api_key: "", temperature: "0", timeout: "120",
                  has_api_key: false, api_key_masked: "" })
const skill = ref({ content: "", path: "", backups: [] })
const testing = ref(false)
const saving = ref(false)
const savingDoc = ref(false)
const testResult = ref("")

async function load() {
  const c = await (await fetch("/api/translator/ai-writer/config")).json()
  if (c.ok) cfg.value = { ...cfg.value, ...c.data, api_key: "" }
  const s = await (await fetch("/api/translator/ai-writer/skill-doc")).json()
  if (s.ok) skill.value = s.data
}

async function saveConfig() {
  saving.value = true
  try {
    const r = await fetch("/api/translator/ai-writer/config", {
      method: "PUT", headers: ADMIN_HEAD(),
      body: JSON.stringify({ api_base_url: cfg.value.api_base_url, model: cfg.value.model,
                             api_key: cfg.value.api_key, temperature: cfg.value.temperature,
                             timeout: cfg.value.timeout }),
    })
    const j = await r.json()
    if (j.ok) MessagePlugin.success("参数已保存")
    else MessagePlugin.error(j.error || "保存失败")
    await load()
  } finally { saving.value = false }
}

async function doTest() {
  testing.value = true; testResult.value = ""
  try {
    const r = await fetch("/api/translator/ai-writer/test", { method: "POST", headers: ADMIN_HEAD() })
    const j = await r.json()
    testResult.value = j.ok ? `连通：${j.data.model} · ${j.data.latency_ms}ms` : `失败：${j.error}`
  } catch (e) { testResult.value = `失败：${e}` } finally { testing.value = false }
}

async function saveDoc() {
  savingDoc.value = true
  try {
    const r = await fetch("/api/translator/ai-writer/skill-doc", {
      method: "PUT", headers: ADMIN_HEAD(), body: JSON.stringify({ content: skill.value.content }),
    })
    const j = await r.json()
    if (j.ok) MessagePlugin.success(`已保存（备份 ${j.data.backup}）`)
    else MessagePlugin.error(j.error || "保存失败")
    await load()
  } finally { savingDoc.value = false }
}

async function doRestore() {
  const r = await fetch("/api/translator/ai-writer/skill-doc/restore", {
    method: "POST", headers: ADMIN_HEAD(), body: JSON.stringify({}),
  })
  const j = await r.json()
  if (j.ok) MessagePlugin.success(`已恢复（来源：${j.data.source}）`)
  else MessagePlugin.error(j.error || "恢复失败")
  await load()
}

watch(() => props.visible, (v) => { if (v) load() })
</script>

<style scoped>
.cfg { display: flex; flex-direction: column; gap: 20px; }
.sec { border: 1px solid #E5E7EB; border-radius: 10px; padding: 16px; }
.sec-head { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: #1F2329; }
.sec-tip { margin: 6px 0 14px; font-size: 13px; color: #4E5969; line-height: 1.6; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.fi { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: #4E5969; }
.fi.block { margin-top: 14px; }
.row { display: flex; align-items: center; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
.dim { color: #A6A6A6; font-size: 12px; }
.mono { font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; margin-top: 10px; }
</style>
