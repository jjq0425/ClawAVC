<template>
<!-- RSI AI 参数抽屉：模型连接 + 三段分析提示词 -->
<!-- 抽屉宽度 -->
  <t-drawer v-model:visible="inner" header="RSI 自进化 · AI 参数与分析提示词" size="880px"
            :close-on-overlay-click="true" :footer="false" destroy-on-close>
    <div class="cfg">
      <div class="sec">
<!-- 区头：模型连接参数 -->
        <div class="sec-head"><t-icon name="link" /> 模型连接参数</div>
<!-- 说明：本抽屉参数仅用于 RSI 分析调用 -->
        <p class="sec-tip">与「模型配置」「AI 帮写」各自独立，仅用于 RSI 分析调用。</p>
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
<!-- 密钥占位双态 -->
<!-- 未配置时的密钥占位 -->
          <t-input v-model="cfg.api_key" type="password" :placeholder="cfg.has_api_key ? '已配置（留空则不修改）' : 'sk-...'" />
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

      <div class="sec">
<!-- 区头：分析提示词模板（可编辑） -->
        <div class="sec-head"><t-icon name="file-copy" /> 分析提示词模板（可编辑）</div>
<!-- 说明：总纲+放宽+改造三段拼接 -->
        <p class="sec-tip">三段模板会拼接成系统提示词：分析总纲 + 放宽判定准则 + 改造建议准则。留空并保存即恢复内置默认。</p>
        <div class="row">
<!-- 恢复内置默认按钮 -->
          <t-button theme="danger" variant="outline" size="small" @click="restorePrompts">恢复默认</t-button>
<!-- 保存提示词按钮 -->
          <t-button theme="primary" size="small" :loading="savingPrompts" @click="savePrompts">保存提示词</t-button>
<!-- 内置默认标识 -->
          <span class="dim" v-if="p.is_default?.prompt_analyze">分析总纲：内置默认</span>
        </div>
        <div class="pt">
<!-- 段标题：分析总纲 -->
          <div class="pt-head">① 分析总纲（决定输出结构与判断口径）</div>
<!-- 总纲编辑：决定输出结构与口径 -->
          <t-textarea v-model="p.prompt_analyze" class="mono" :autosize="{ minRows: 14, maxRows: 26 }" />
        </div>
        <div class="pt">
<!-- 段标题：放宽准则 -->
          <div class="pt-head">② 放宽判定准则</div>
<!-- 放宽准则编辑 -->
          <t-textarea v-model="p.prompt_relax" class="mono" :autosize="{ minRows: 6, maxRows: 14 }" />
        </div>
        <div class="pt">
<!-- 段标题：改造建议 -->
          <div class="pt-head">③ 改造建议准则</div>
<!-- 改造建议编辑 -->
          <t-textarea v-model="p.prompt_transform" class="mono" :autosize="{ minRows: 8, maxRows: 18 }" />
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

// 连接参数编辑态
const cfg = ref({ api_base_url: "", model: "", api_key: "", temperature: "0", timeout: "120",
                  has_api_key: false, api_key_masked: "" })
// 三段提示词编辑态 + 是否内置默认
const p = ref({ prompt_analyze: "", prompt_relax: "", prompt_transform: "", is_default: {} })
// 测试连接中
const testing = ref(false)
// 保存参数中
const saving = ref(false)
// 复用配置中
const copying = ref(false)
// 保存提示词中
const savingPrompts = ref(false)
// 连通性结果文本
const testResult = ref("")

// 加载连接参数与提示词
async function load() {
  const c = await readJson(await fetch("/api/translator/rsi/config"))
// 连接参数回填（密钥置空）
  if (c.ok) cfg.value = { ...cfg.value, ...c.data, api_key: "" }
  const s = await readJson(await fetch("/api/translator/rsi/prompts"))
// 提示词三段回填
  if (s.ok) p.value = s.data
}

// 保存连接参数（PUT）
async function saveConfig() {
  saving.value = true
  try {
    const r = await fetch("/api/translator/rsi/config", {
      method: "PUT", headers: ADMIN_HEAD(),
      body: JSON.stringify({ api_base_url: cfg.value.api_base_url, model: cfg.value.model,
                             api_key: cfg.value.api_key, temperature: cfg.value.temperature,
                             timeout: cfg.value.timeout }),
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
    const r = await fetch("/api/translator/rsi/config/copy-from-ir", {
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
    const r = await fetch("/api/translator/rsi/test", { method: "POST", headers: ADMIN_HEAD() })
    const j = await readJson(r)
// 连通性结果（模型+时延）
    testResult.value = j.ok ? `连通：${j.data.model} · ${j.data.latency_ms}ms` : `失败：${j.error}`
  } catch (e) { testResult.value = `失败：${e}` } finally { testing.value = false }
}

// 保存三段提示词
async function savePrompts() {
  savingPrompts.value = true
  try {
    const r = await fetch("/api/translator/rsi/prompts", {
      method: "PUT", headers: ADMIN_HEAD(),
// 提示词保存请求体（三段）
      body: JSON.stringify({ prompt_analyze: p.value.prompt_analyze,
                             prompt_relax: p.value.prompt_relax,
                             prompt_transform: p.value.prompt_transform }),
    })
    const j = await readJson(r)
// 提示词保存成功分支
    j.ok ? MessagePlugin.success("提示词已保存") : MessagePlugin.error(j.error || "保存失败")
    await load()
  } finally { savingPrompts.value = false }
}

// 恢复内置默认提示词
async function restorePrompts() {
  const r = await fetch("/api/translator/rsi/prompts/restore", { method: "POST", headers: ADMIN_HEAD() })
  const j = await readJson(r)
// 恢复默认成功文案
  j.ok ? MessagePlugin.success("已恢复内置默认提示词") : MessagePlugin.error(j.error || "恢复失败")
  await load()
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
/* 弱化文本（RSI 抽屉） */
.dim { color: #A6A6A6; font-size: 12px; }
/* 等宽字体 */
.mono { font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; }
/* 提示词段容器 */
.pt { margin-top: 14px; }
/* 段标题样式 */
.pt-head { font-size: 13px; font-weight: 600; color: #1F2329; margin-bottom: 6px; }
</style>
