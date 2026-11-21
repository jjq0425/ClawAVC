<template>
<!-- 模型配置页：连接参数 / JSON 模式 / 函数注入格式 -->
  <div class="config-tab">
<!-- 特权状态组件：配置修改需特权 -->
    <PrivilegeStatus hint="修改模型配置需要特权验证" @unlock="showPrivDialog = true" />
<!-- 配置卡片容器 -->
    <div class="config-card" style="margin-top: 16px;">
<!-- 接口地址行 -->
      <div class="config-row"><label>API Base URL</label><t-input v-model="cfg.api_base_url" :disabled="!adminValid" placeholder="https://api.openai.com/v1" /></div>
      <div class="config-row">
<!-- 密钥行容器 -->
        <div class="api-key-wrapper">
          <label>API Key</label>
<!-- 密钥输入行 -->
          <div class="api-key-input">
            <t-input 
              v-model="cfg.api_key" 
              :disabled="!adminValid" 
              type="password" 
              placeholder="sk-..."
              :clearable="adminValid"
            />
<!-- 未特权时密钥只读提示 -->
            <span v-if="!adminValid" class="api-key-hint">已配置（需特权验证后才可修改）</span>
          </div>
        </div>
      </div>
<!-- 模型行 -->
      <div class="config-row"><label>Model</label><t-input v-model="cfg.model" :disabled="!adminValid" placeholder="gpt-4o-mini" /></div>
<!-- 半行：温度 + 超时 -->
      <div class="config-row half"><div><label>Temperature</label><t-input v-model="cfg.temperature" :disabled="!adminValid" placeholder="0" /></div><div><label>Timeout (秒)</label><t-input v-model="cfg.timeout" :disabled="!adminValid" placeholder="180" /></div></div>
<!-- JSON 模式开关 -->
      <div class="config-row"><label>JSON Mode</label><t-switch v-model="jsonMode" :disabled="!adminValid" /></div>
      <div class="config-row">
<!-- 函数定义注入格式标签 -->
        <label>函数定义注入格式</label>
<!-- 注入格式选择：json / text -->
        <t-select v-model="promptFormat" :disabled="!adminValid" style="max-width: 360px"
          :options="[{ label: 'JSON 原样注入（默认，兼容现有行为）', value: 'json' }, { label: '结构化提示词（Markdown 分节，体积约省 70%）', value: 'text' }]" />
      </div>
<!-- 格式说明：text 为结构化 Markdown，省约 70% token -->
      <div class="fmt-hint">控制 Level-2 提示词中函数定义的呈现方式：<b>json</b> 为整份注册表 JSON；<b>text</b> 为结构化 Markdown（场景 → 函数 → 参数约束 → 可替代工具引导），可读性更好、更省 token。</div>
<!-- 保存按钮 -->
      <t-button theme="primary" :disabled="!adminValid" @click="save" :loading="saving">保存配置</t-button>
    </div>
<!-- 特权验证对话框 -->
    <PrivilegeDialog v-model="showPrivDialog" @success="onPriv" />
  </div>
</template>

<script setup>
// Vue API + 挂载/卸载钩子
import { ref, computed, onMounted, onUnmounted } from "vue"
// TDesign 全局消息插件
import { MessagePlugin } from "tdesign-vue-next"
// 特权验证对话框子组件
import PrivilegeDialog from "../../components/PrivilegeDialog.vue"
import PrivilegeStatus from "../../components/PrivilegeStatus.vue"

// 特权对话框可见性
const showPrivDialog = ref(false)
// 连接参数编辑态
const cfg = ref({ api_base_url: "", api_key: "", model: "", temperature: "0", timeout: "180" })
// JSON 模式开关
const jsonMode = ref(true)
// 函数注入格式：json / text
const promptFormat = ref("json")
// 保存中标志
const saving = ref(false)
// 特权过期检查驱动：每秒自增
const tick = ref(0)
// 定时器句柄
let _t = null
// 特权有效性：会话存在且未过期
const adminValid = computed(() => { void tick.value; const s = sessionStorage.getItem("clawavc_admin_session"); return !!s && Date.now() < Number(sessionStorage.getItem("clawavc_admin_expiry") || 0) })
onMounted(() => { _t = setInterval(() => tick.value++, 1000); load() })
onUnmounted(() => clearInterval(_t))
// 特权成功回调（无需处理）
function onPriv() {}

// 加载配置并回填
async function load() {
  try { 
    const r = await fetch("/api/translator/config"); 
    const j = await r.json(); 
    if (j.ok) { 
// 参数回填
      cfg.value = j.data; 
// JSON 模式回填
      jsonMode.value = j.data.json_mode === "1"
// 注入格式回填（缺省 json）
      promptFormat.value = (j.data.registry_prompt_format || "json").toLowerCase() 
    } 
  } catch {}
}
// 保存：空密钥不发送
async function save() {
  saving.value = true
  try {
    // 构建请求数据，api_key 为空时不发送（后端会跳过空值）
// 请求体组装
    const data = { 
      api_base_url: cfg.value.api_base_url,
      model: cfg.value.model,
      temperature: cfg.value.temperature,
      timeout: cfg.value.timeout,
      json_mode: jsonMode.value ? "1" : "0",
      registry_prompt_format: promptFormat.value
    }
    // 只有当用户输入了 API Key 时才发送
// 仅用户输入密钥时携带
    if (cfg.value.api_key.trim()) {
      data.api_key = cfg.value.api_key.trim()
    }
    const r = await fetch("/api/translator/config", { 
      method: "PUT", 
      headers: { "Content-Type": "application/json", "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "" }, 
      body: JSON.stringify(data) 
    })
    const j = await r.json()
// 保存成功/失败提示
    if (j.ok) MessagePlugin.success("配置已保存"); else MessagePlugin.error(j.error)
  } catch { MessagePlugin.error("连接失败") }
  saving.value = false
}
</script>

<style scoped>
/* 配置卡容器 */
.config-card { background: #fff; border-radius: 12px; padding: 24px; border: 1px solid #eee; }
/* 配置行间距 */
.config-row { margin-bottom: 14px; }
/* 行标签样式 */
.config-row label { font-size: 13px; font-weight: 500; color: #666; display: block; margin-bottom: 4px; }
/* 半行布局 */
.config-row.half { display: flex; gap: 16px; }
.config-row.half > div { flex: 1; }
/* 密钥行容器 */
.api-key-wrapper { width: 100%; }
/* 密钥输入行 */
.api-key-input { display: flex; align-items: center; gap: 8px; }
/* 密钥只读提示 */
.api-key-hint { font-size: 12px; color: #999; }
/* 格式说明样式 */
.fmt-hint { margin: -6px 0 12px; font-size: 12px; color: #8a94a6; line-height: 1.7; }
</style>
