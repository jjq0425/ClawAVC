<template>
  <t-drawer v-model:visible="inner" header="RSI 自进化 · AI 参数与分析提示词" size="880px"
            :close-on-overlay-click="true" :footer="false" destroy-on-close>
    <div class="cfg">
      <div class="sec">
        <div class="sec-head"><t-icon name="link" /> 模型连接参数</div>
        <p class="sec-tip">与「模型配置」「AI 帮写」各自独立，仅用于 RSI 分析调用。</p>
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

      <div class="sec">
        <div class="sec-head"><t-icon name="file-copy" /> 分析提示词模板（可编辑）</div>
        <p class="sec-tip">三段模板会拼接成系统提示词：分析总纲 + 放宽判定准则 + 改造建议准则。留空并保存即恢复内置默认。</p>
        <div class="row">
          <t-button theme="danger" variant="outline" size="small" @click="restorePrompts">恢复默认</t-button>
          <t-button theme="primary" size="small" :loading="savingPrompts" @click="savePrompts">保存提示词</t-button>
          <span class="dim" v-if="p.is_default?.prompt_analyze">分析总纲：内置默认</span>
        </div>
        <div class="pt">
          <div class="pt-head">① 分析总纲（决定输出结构与判断口径）</div>
          <t-textarea v-model="p.prompt_analyze" class="mono" :autosize="{ minRows: 14, maxRows: 26 }" />
        </div>
        <div class="pt">
          <div class="pt-head">② 放宽判定准则</div>
          <t-textarea v-model="p.prompt_relax" class="mono" :autosize="{ minRows: 6, maxRows: 14 }" />
        </div>
        <div class="pt">
          <div class="pt-head">③ 改造建议准则</div>
          <t-textarea v-model="p.prompt_transform" class="mono" :autosize="{ minRows: 8, maxRows: 18 }" />
        </div>
      </div>
    </div>
  </t-drawer>
</template>

<script setup>
import { ref, computed, watch } from "vue"
import { MessagePlugin } from "tdesign-vue-next"

const props = defineProps({ visible: { type: Boolean, default: false } })
const emit = defineEmits(["update:visible"])
const inner = computed({ get: () => props.visible, set: (v) => emit("update:visible", v) })

const ADMIN_HEAD = () => ({
  "Content-Type": "application/json",
  "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "",
})

const cfg = ref({ api_base_url: "", model: "", api_key: "", temperature: "0", timeout: "120",
                  has_api_key: false, api_key_masked: "" })
const p = ref({ prompt_analyze: "", prompt_relax: "", prompt_transform: "", is_default: {} })
const testing = ref(false)
const saving = ref(false)
const savingPrompts = ref(false)
const testResult = ref("")

async function load() {
  const c = await (await fetch("/api/translator/rsi/config")).json()
  if (c.ok) cfg.value = { ...cfg.value, ...c.data, api_key: "" }
  const s = await (await fetch("/api/translator/rsi/prompts")).json()
  if (s.ok) p.value = s.data
}

async function saveConfig() {
  saving.value = true
  try {
    const r = await fetch("/api/translator/rsi/config", {
      method: "PUT", headers: ADMIN_HEAD(),
      body: JSON.stringify({ api_base_url: cfg.value.api_base_url, model: cfg.value.model,
                             api_key: cfg.value.api_key, temperature: cfg.value.temperature,
                             timeout: cfg.value.timeout }),
    })
    const j = await r.json()
    j.ok ? MessagePlugin.success("参数已保存") : MessagePlugin.error(j.error || "保存失败")
    await load()
  } finally { saving.value = false }
}

async function doTest() {
  testing.value = true; testResult.value = ""
  try {
    const r = await fetch("/api/translator/rsi/test", { method: "POST", headers: ADMIN_HEAD() })
    const j = await r.json()
    testResult.value = j.ok ? `连通：${j.data.model} · ${j.data.latency_ms}ms` : `失败：${j.error}`
  } catch (e) { testResult.value = `失败：${e}` } finally { testing.value = false }
}

async function savePrompts() {
  savingPrompts.value = true
  try {
    const r = await fetch("/api/translator/rsi/prompts", {
      method: "PUT", headers: ADMIN_HEAD(),
      body: JSON.stringify({ prompt_analyze: p.value.prompt_analyze,
                             prompt_relax: p.value.prompt_relax,
                             prompt_transform: p.value.prompt_transform }),
    })
    const j = await r.json()
    j.ok ? MessagePlugin.success("提示词已保存") : MessagePlugin.error(j.error || "保存失败")
    await load()
  } finally { savingPrompts.value = false }
}

async function restorePrompts() {
  const r = await fetch("/api/translator/rsi/prompts/restore", { method: "POST", headers: ADMIN_HEAD() })
  const j = await r.json()
  j.ok ? MessagePlugin.success("已恢复内置默认提示词") : MessagePlugin.error(j.error || "恢复失败")
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
.mono { font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; }
.pt { margin-top: 14px; }
.pt-head { font-size: 13px; font-weight: 600; color: #1F2329; margin-bottom: 6px; }
</style>
