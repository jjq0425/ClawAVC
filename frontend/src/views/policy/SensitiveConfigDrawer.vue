<template>
<!-- 敏感配置专用 AI 参数抽屉 -->
  <t-drawer v-model:visible="inner" header="敏感文件配置 · 专用 AI 参数" size="760px"
            :close-on-overlay-click="true" :footer="false" destroy-on-close>
    <div class="cfg">
      <div class="sec">
<!-- 区头：模型连接参数 -->
        <div class="sec-head"><t-icon name="link" /> 模型连接参数</div>
<!-- 说明：仅用于敏感规则建议生成 -->
        <p class="sec-tip">与「模型配置」「AI 帮写」「RSI 自进化」各自独立，仅用于敏感规则建议生成。</p>
        <div class="grid">
<!-- 接口地址输入 -->
          <label class="fi"><span>Base URL</span>
<!-- 接口地址占位示例 -->
<!-- 接口地址绑定 -->
            <t-input v-model="cfg.api_base_url" placeholder="https://api.longcat.chat/openai" />
          </label>
<!-- 模型名输入 -->
          <label class="fi"><span>Model</span>
<!-- 模型名占位示例 -->
<!-- 模型名绑定 -->
            <t-input v-model="cfg.model" placeholder="如 LongCat-2.0-Preview / u2-flash" />
          </label>
        </div>
<!-- 密钥输入：留空不修改 -->
        <label class="fi block"><span>API Token</span>
          <t-input v-model="cfg.api_key" type="password"
                   :placeholder="cfg.has_api_key ? '已配置（留空则不修改）' : 'sk-...'" />
<!-- 当前密钥掩码 -->
          <span class="dim" v-if="cfg.api_key_masked">当前：{{ cfg.api_key_masked }}</span>
        </label>
        <div class="grid">
<!-- 采样温度 -->
<!-- 温度占位 -->
          <label class="fi"><span>Temperature</span><t-input v-model="cfg.temperature" placeholder="0" /></label>
<!-- 超时 -->
<!-- 超时占位 -->
          <label class="fi"><span>超时（秒）</span><t-input v-model="cfg.timeout" placeholder="120" /></label>
        </div>
<!-- 最大输出 token 标签：推理型模型建议调大 -->
        <label class="fi block"><span>最大输出 token（推理型模型建议调大，留空用服务端默认）</span>
<!-- max_tokens 占位示例 -->
          <t-input v-model="cfg.max_tokens" placeholder="如 32768" />
        </label>
        <div class="row">
          <t-button theme="default" variant="outline" :loading="testing" @click="doTest">
<!-- 测试连接按钮 -->
            <template #icon><t-icon name="check-circle" /></template>测试连接
          </t-button>
          <t-button variant="outline" :loading="copying" @click="copyIrConfig" title="把「策略翻译 → 模型配置」的 Base URL / Model / API Token 同步过来（本地 portkey 网关必用网关 token）">
<!-- 复用按钮：同步 IR 模型连接参数 -->
            <template #icon><t-icon name="link" /></template>复用 IR 模型配置
          </t-button>
<!-- 连通性结果 -->
          <span v-if="testResult" class="dim">{{ testResult }}</span>
          <t-button theme="primary" :loading="saving" @click="saveConfig">
<!-- 保存参数按钮 -->
            <template #icon><t-icon name="save" /></template>保存参数
          </t-button>
        </div>
      </div>
    </div>
  </t-drawer>
</template>

<script setup>
// Vue API
import { ref, computed, watch } from "vue"
// TDesign 全局消息插件
import { MessagePlugin } from "tdesign-vue-next"

// 抽屉可见性 prop
const props = defineProps({ visible: { type: Boolean, default: false } })
// update:visible 事件
const emit = defineEmits(["update:visible"])
// 可见性代理：prop ↔ emit
const inner = computed({ get: () => props.visible, set: (v) => emit("update:visible", v) })

// 管理员请求头（写接口需特权）
const ADMIN_HEAD = () => ({
  "Content-Type": "application/json",
  "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "",
})

// 安全读取 JSON：后端异常时可能返回 HTML 错误页，直接 r.json() 会抛
// "Unexpected token '<'" 掩盖真实原因，这里给出 HTTP 状态与响应摘要。
async function readJson(r) {
// 先取文本再解析（非 JSON 报状态+摘要）
  const text = await r.text()
  try { return JSON.parse(text) }
  catch {
// 响应摘要（前 90 字符）
    const brief = (text || "").replace(/\s+/g, " ").slice(0, 90)
    throw new Error(`接口返回非 JSON（HTTP ${r.status}）：${brief || "空响应"}`)
  }
}

// 连接参数编辑态（含 max_tokens）
const cfg = ref({ api_base_url: "", model: "", api_key: "", temperature: "0", timeout: "120",
                  max_tokens: "", has_api_key: false, api_key_masked: "" })
// 测试连接中
const testing = ref(false)
// 保存参数中
const saving = ref(false)
// 复用配置中
const copying = ref(false)
// 连通性结果文本
const testResult = ref("")

// 加载连接参数
async function load() {
  const c = await readJson(await fetch("/api/translator/sensitive/ai-config"))
// 连接参数回填（密钥置空）
  if (c.ok) cfg.value = { ...cfg.value, ...c.data, api_key: "" }
}

// 保存连接参数（PUT）
async function saveConfig() {
  saving.value = true
  try {
    const r = await fetch("/api/translator/sensitive/ai-config", {
      method: "PUT", headers: ADMIN_HEAD(),
// 保存请求体（含 max_tokens）
      body: JSON.stringify({ api_base_url: cfg.value.api_base_url, model: cfg.value.model,
                             api_key: cfg.value.api_key, temperature: cfg.value.temperature,
                             timeout: cfg.value.timeout, max_tokens: cfg.value.max_tokens }),
    })
    const j = await readJson(r)
// 保存成功/失败分支
    j.ok ? MessagePlugin.success("参数已保存") : MessagePlugin.error(j.error || "保存失败")
    await load()
  } finally { saving.value = false }
}

// 复用 IR 模型连接参数
async function copyIrConfig() {
  copying.value = true
  try {
    const r = await fetch("/api/translator/sensitive/ai-config/copy-from-ir", {
      method: "POST", headers: ADMIN_HEAD(),
    })
    const j = await readJson(r)
// 复用成功提示
    if (j.ok) { MessagePlugin.success("已复用 IR 意图翻译模型的连接参数（含 API Token）"); await load() }
    else MessagePlugin.error(j.error || "复用失败")
  } catch (e) { MessagePlugin.error(`复用失败：${e.message || e}`) }
  finally { copying.value = false }
}

// 测试连接：回显模型与时延
async function doTest() {
  testing.value = true; testResult.value = ""
  try {
    const r = await fetch("/api/translator/sensitive/test", { method: "POST", headers: ADMIN_HEAD() })
    const j = await readJson(r)
// 连通性结果（模型+时延）
    testResult.value = j.ok ? `连通：${j.data.model} · ${j.data.latency_ms}ms` : `失败：${j.error || "未知错误"}`
  } catch (e) { testResult.value = `失败：${e}` } finally { testing.value = false }
}

// 打开抽屉时懒加载
watch(() => props.visible, (v) => { if (v) load() })
</script>

<style scoped>
/* 抽屉内容纵排 */
.cfg { display: flex; flex-direction: column; gap: 20px; }
/* 区块容器 */
.sec { border: 1px solid #E5E7EB; border-radius: 10px; padding: 16px; }
/* 区头样式 */
.sec-head { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: #1F2329; }
/* 区说明文字 */
.sec-tip { margin: 6px 0 14px; font-size: 13px; color: #4E5969; line-height: 1.6; }
/* 双列网格 */
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
/* 表单项纵排 */
.fi { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: #4E5969; }
/* 块级表单项 */
.fi.block { margin-top: 14px; }
/* 操作行布局 */
.row { display: flex; align-items: center; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
/* 弱化文本（敏感抽屉） */
.dim { color: #A6A6A6; font-size: 12px; }
</style>
