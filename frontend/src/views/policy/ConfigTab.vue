<template>
  <div class="config-tab">
    <PrivilegeStatus hint="修改模型配置需要特权验证" @unlock="showPrivDialog = true" />
    <div class="config-card" style="margin-top: 16px;">
      <div class="config-row"><label>API Base URL</label><t-input v-model="cfg.api_base_url" :disabled="!adminValid" placeholder="https://api.openai.com/v1" /></div>
      <div class="config-row">
        <div class="api-key-wrapper">
          <label>API Key</label>
          <div class="api-key-input">
            <t-input 
              v-model="cfg.api_key" 
              :disabled="!adminValid" 
              type="password" 
              placeholder="sk-..."
              :clearable="adminValid"
            />
            <span v-if="!adminValid" class="api-key-hint">已配置（需特权验证后才可修改）</span>
          </div>
        </div>
      </div>
      <div class="config-row"><label>Model</label><t-input v-model="cfg.model" :disabled="!adminValid" placeholder="gpt-4o-mini" /></div>
      <div class="config-row half"><div><label>Temperature</label><t-input v-model="cfg.temperature" :disabled="!adminValid" placeholder="0" /></div><div><label>Timeout (秒)</label><t-input v-model="cfg.timeout" :disabled="!adminValid" placeholder="180" /></div></div>
      <div class="config-row"><label>JSON Mode</label><t-switch v-model="jsonMode" :disabled="!adminValid" /></div>
      <div class="config-row">
        <label>函数定义注入格式</label>
        <t-select v-model="promptFormat" :disabled="!adminValid" style="max-width: 360px"
          :options="[{ label: 'JSON 原样注入（默认，兼容现有行为）', value: 'json' }, { label: '结构化提示词（Markdown 分节，体积约省 70%）', value: 'text' }]" />
      </div>
      <div class="fmt-hint">控制 Level-2 提示词中函数定义的呈现方式：<b>json</b> 为整份注册表 JSON；<b>text</b> 为结构化 Markdown（场景 → 函数 → 参数约束 → 可替代工具引导），可读性更好、更省 token。</div>
      <t-button theme="primary" :disabled="!adminValid" @click="save" :loading="saving">保存配置</t-button>
    </div>
    <PrivilegeDialog v-model="showPrivDialog" @success="onPriv" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from "vue"
import { MessagePlugin } from "tdesign-vue-next"
import PrivilegeDialog from "../../components/PrivilegeDialog.vue"
import PrivilegeStatus from "../../components/PrivilegeStatus.vue"

const showPrivDialog = ref(false)
const cfg = ref({ api_base_url: "", api_key: "", model: "", temperature: "0", timeout: "180" })
const jsonMode = ref(true)
const promptFormat = ref("json")
const saving = ref(false)
const tick = ref(0)
let _t = null
const adminValid = computed(() => { void tick.value; const s = sessionStorage.getItem("clawavc_admin_session"); return !!s && Date.now() < Number(sessionStorage.getItem("clawavc_admin_expiry") || 0) })
onMounted(() => { _t = setInterval(() => tick.value++, 1000); load() })
onUnmounted(() => clearInterval(_t))
function onPriv() {}

async function load() {
  try { 
    const r = await fetch("/api/translator/config"); 
    const j = await r.json(); 
    if (j.ok) { 
      cfg.value = j.data; 
      jsonMode.value = j.data.json_mode === "1"
      promptFormat.value = (j.data.registry_prompt_format || "json").toLowerCase() 
    } 
  } catch {}
}
async function save() {
  saving.value = true
  try {
    // 构建请求数据，api_key 为空时不发送（后端会跳过空值）
    const data = { 
      api_base_url: cfg.value.api_base_url,
      model: cfg.value.model,
      temperature: cfg.value.temperature,
      timeout: cfg.value.timeout,
      json_mode: jsonMode.value ? "1" : "0",
      registry_prompt_format: promptFormat.value
    }
    // 只有当用户输入了 API Key 时才发送
    if (cfg.value.api_key.trim()) {
      data.api_key = cfg.value.api_key.trim()
    }
    const r = await fetch("/api/translator/config", { 
      method: "PUT", 
      headers: { "Content-Type": "application/json", "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "" }, 
      body: JSON.stringify(data) 
    })
    const j = await r.json()
    if (j.ok) MessagePlugin.success("配置已保存"); else MessagePlugin.error(j.error)
  } catch { MessagePlugin.error("连接失败") }
  saving.value = false
}
</script>

<style scoped>
.config-card { background: #fff; border-radius: 12px; padding: 24px; border: 1px solid #eee; }
.config-row { margin-bottom: 14px; }
.config-row label { font-size: 13px; font-weight: 500; color: #666; display: block; margin-bottom: 4px; }
.config-row.half { display: flex; gap: 16px; }
.config-row.half > div { flex: 1; }
.api-key-wrapper { width: 100%; }
.api-key-input { display: flex; align-items: center; gap: 8px; }
.api-key-hint { font-size: 12px; color: #999; }
.fmt-hint { margin: -6px 0 12px; font-size: 12px; color: #8a94a6; line-height: 1.7; }
</style>
