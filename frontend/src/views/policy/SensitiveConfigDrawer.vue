<template>
  <t-drawer v-model:visible="inner" header="敏感文件配置 · 专用 AI 参数" size="760px"
            :close-on-overlay-click="true" :footer="false" destroy-on-close>
    <div class="cfg">
      <div class="sec">
        <div class="sec-head"><t-icon name="link" /> 模型连接参数</div>
        <p class="sec-tip">与「模型配置」「AI 帮写」「RSI 自进化」各自独立，仅用于敏感规则建议生成。</p>
        <div class="grid">
          <label class="fi"><span>Base URL</span>
            <t-input v-model="cfg.api_base_url" placeholder="https://api.longcat.chat/openai" />
          </label>
          <label class="fi"><span>Model</span>
            <t-input v-model="cfg.model" placeholder="如 LongCat-2.0-Preview / u2-flash" />
          </label>
        </div>
        <label class="fi block"><span>API Token</span>
          <t-input v-model="cfg.api_key" type="password"
                   :placeholder="cfg.has_api_key ? '已配置（留空则不修改）' : 'sk-...'" />
          <span class="dim" v-if="cfg.api_key_masked">当前：{{ cfg.api_key_masked }}</span>
        </label>
        <div class="grid">
          <label class="fi"><span>Temperature</span><t-input v-model="cfg.temperature" placeholder="0" /></label>
          <label class="fi"><span>超时（秒）</span><t-input v-model="cfg.timeout" placeholder="120" /></label>
        </div>
        <label class="fi block"><span>最大输出 token（推理型模型建议调大，留空用服务端默认）</span>
          <t-input v-model="cfg.max_tokens" placeholder="如 32768" />
        </label>
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
                  max_tokens: "", has_api_key: false, api_key_masked: "" })
const testing = ref(false)
const saving = ref(false)
const testResult = ref("")

async function load() {
  const c = await (await fetch("/api/translator/sensitive/ai-config")).json()
  if (c.ok) cfg.value = { ...cfg.value, ...c.data, api_key: "" }
}

async function saveConfig() {
  saving.value = true
  try {
    const r = await fetch("/api/translator/sensitive/ai-config", {
      method: "PUT", headers: ADMIN_HEAD(),
      body: JSON.stringify({ api_base_url: cfg.value.api_base_url, model: cfg.value.model,
                             api_key: cfg.value.api_key, temperature: cfg.value.temperature,
                             timeout: cfg.value.timeout, max_tokens: cfg.value.max_tokens }),
    })
    const j = await r.json()
    j.ok ? MessagePlugin.success("参数已保存") : MessagePlugin.error(j.error || "保存失败")
    await load()
  } finally { saving.value = false }
}

async function doTest() {
  testing.value = true; testResult.value = ""
  try {
    const r = await fetch("/api/translator/sensitive/test", { method: "POST", headers: ADMIN_HEAD() })
    const text = await r.text()
    let j
    try { j = JSON.parse(text) }
    catch (e) { j = { ok: false, error: `HTTP ${r.status}：接口返回非 JSON（${text.slice(0, 80)}…）` } }
    testResult.value = j.ok ? `连通：${j.data.model} · ${j.data.latency_ms}ms` : `失败：${j.error || "未知错误"}`
  } catch (e) { testResult.value = `失败：${e}` } finally { testing.value = false }
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
</style>
