<template>
<!-- AI 帮写参数抽屉：模型连接 + Skill 提示词两区 -->
  <t-drawer v-model:visible="inner" header="AI 帮写参数" size="860px" :close-on-overlay-click="true"
            :footer="false" destroy-on-close>
<!-- 抽屉内容容器 -->
    <div class="cfg">
      <!-- ① 连接参数 -->
      <div class="sec">
<!-- 区头图标 -->
        <div class="sec-head"><t-icon name="link" /> 模型连接参数</div>
<!-- 说明：本抽屉参数仅用于 AI 帮写生成调用 -->
        <p class="sec-tip">与「模型配置」Tab 相互独立，仅用于 AI 帮写的生成调用。</p>
        <div class="grid">
<!-- 接口地址输入 -->
          <label class="fi"><span>Base URL</span>
<!-- 接口地址占位示例 -->
            <t-input v-model="cfg.api_base_url" placeholder="https://api.longcat.chat/openai" />
          </label>
<!-- 模型名输入 -->
          <label class="fi"><span>Model</span>
<!-- 模型名占位示例 -->
            <t-input v-model="cfg.model" placeholder="如 LongCat-2.0-Preview / u2-flash" />
          </label>
        </div>
<!-- 密钥输入：留空不修改 -->
<!-- 掩码展示当前已配置密钥 -->
        <label class="fi block"><span>API Token</span>
<!-- 密钥占位：已配置/未配置双态 -->
          <t-input v-model="cfg.api_key" type="password" :placeholder="cfg.has_api_key ? '已配置（留空则不修改）' : 'sk-...'" />
<!-- 当前密钥掩码回显 -->
          <span class="dim" v-if="cfg.api_key_masked">当前：{{ cfg.api_key_masked }}</span>
        </label>
        <div class="grid">
<!-- 采样温度输入 -->
<!-- 温度占位 -->
          <label class="fi"><span>Temperature</span><t-input v-model="cfg.temperature" placeholder="0" /></label>
<!-- 超时输入 -->
<!-- 超时占位 -->
          <label class="fi"><span>超时（秒）</span><t-input v-model="cfg.timeout" placeholder="120" /></label>
        </div>
        <div class="row">
<!-- 测试连接按钮 -->
          <t-button theme="default" variant="outline" :loading="testing" @click="doTest">
<!-- 测试连接按钮文本 -->
            <template #icon><t-icon name="check-circle" /></template>测试连接
          </t-button>
<!-- 复用 IR 模型配置按钮 -->
          <t-button variant="outline" :loading="copying" @click="copyIrConfig" title="把「策略翻译 → 模型配置」的 Base URL / Model / API Token 同步过来（本地 portkey 网关必用网关 token）">
<!-- 复用按钮文本 -->
            <template #icon><t-icon name="link" /></template>复用 IR 模型配置
          </t-button>
<!-- 连通性结果回显 -->
          <span v-if="testResult" class="dim">{{ testResult }}</span>
<!-- 保存参数按钮 -->
          <t-button theme="primary" :loading="saving" @click="saveConfig">
<!-- 保存按钮文本 -->
            <template #icon><t-icon name="save" /></template>保存参数
          </t-button>
        </div>
      </div>

      <!-- ② Skill 提示词 -->
      <div class="sec">
<!-- ② 区头：Skill 提示词（SKILL.md） -->
        <div class="sec-head"><t-icon name="file-copy" /> Skill 提示词（SKILL.md）</div>
<!-- 说明：SKILL.md 决定生成规范，保存自动备份 -->
        <p class="sec-tip">该文档作为 AI 生成时的系统提示词基座，直接决定生成策略遵循的规范。保存时自动备份原文件。</p>
        <div class="row">
<!-- 提示词文件路径 -->
          <span class="dim">{{ skill.path }}</span>
<!-- 字数统计 -->
          <span class="dim">字数 {{ skill.content?.length || 0 }}</span>
<!-- 恢复内置默认按钮 -->
          <t-button size="small" theme="danger" variant="outline" @click="doRestore">恢复默认</t-button>
<!-- 保存提示词按钮 -->
          <t-button size="small" theme="primary" :loading="savingDoc" @click="saveDoc">保存提示词</t-button>
        </div>
<!-- 提示词正文编辑（等宽） -->
        <t-textarea v-model="skill.content" class="mono" :autosize="{ minRows: 18, maxRows: 32 }" />
<!-- 最近备份列表 -->
        <div class="row" v-if="skill.backups?.length">
          <span class="dim">最近备份：</span>
<!-- 备份时间标签 -->
          <t-tag v-for="b in skill.backups.slice(0, 5)" :key="b.name" size="small" variant="light">{{ b.name.replace("SKILL.md.bak-", "") }}</t-tag>
        </div>
      </div>
    </div>
  </t-drawer>
</template>

<script setup>
// Vue API：响应式 + 计算属性 + 侦听
import { ref, watch, computed } from "vue"
// TDesign 全局消息插件
import { MessagePlugin } from "tdesign-vue-next"

// 抽屉可见性 prop + 双向绑定
const props = defineProps({ visible: { type: Boolean, default: false } })
// update:visible 事件
const emit = defineEmits(["update:visible"])
// 可见性代理：prop ↔ emit
const inner = computed({
  get: () => props.visible,
  set: (v) => emit("update:visible", v),
})

// 管理员请求头（写接口需特权）
const ADMIN_HEAD = () => ({
  "Content-Type": "application/json",
  "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "",
})

// 安全读取 JSON：后端异常时可能返回 HTML 错误页，直接 r.json() 会抛
// "Unexpected token '<'" 掩盖真实原因，这里给出 HTTP 状态与响应摘要。
async function readJson(r) {
// 先取文本再解析：非 JSON 时给出状态与摘要
  const text = await r.text()
  try { return JSON.parse(text) }
  catch {
// 响应摘要（前 90 字符）
    const brief = (text || "").replace(/\s+/g, " ").slice(0, 90)
// 非 JSON 响应：报 HTTP 状态与摘要
    throw new Error(`接口返回非 JSON（HTTP ${r.status}）：${brief || "空响应"}`)
  }
}

// 连接参数编辑态（密钥留空不修改）
const cfg = ref({ api_base_url: "", model: "", api_key: "", temperature: "0", timeout: "120",
                  has_api_key: false, api_key_masked: "" })
// SKILL.md 内容 / 路径 / 备份列表
const skill = ref({ content: "", path: "", backups: [] })
// 测试连接中标志
const testing = ref(false)
// 保存参数中标志
const saving = ref(false)
// 复用配置中标志
const copying = ref(false)
// 保存提示词中标志
const savingDoc = ref(false)
// 连通性结果文本
const testResult = ref("")

// 加载连接参数与提示词
async function load() {
  const c = await readJson(await fetch("/api/translator/ai-writer/config"))
// 连接参数回填（密钥置空）
  if (c.ok) cfg.value = { ...cfg.value, ...c.data, api_key: "" }
  const s = await readJson(await fetch("/api/translator/ai-writer/skill-doc"))
// 提示词内容/备份回填
  if (s.ok) skill.value = s.data
}

// 保存连接参数（PUT，需特权）
async function saveConfig() {
  saving.value = true
  try {
    const r = await fetch("/api/translator/ai-writer/config", {
      method: "PUT", headers: ADMIN_HEAD(),
// 保存请求体（不含空密钥）
      body: JSON.stringify({ api_base_url: cfg.value.api_base_url, model: cfg.value.model,
                             api_key: cfg.value.api_key, temperature: cfg.value.temperature,
                             timeout: cfg.value.timeout }),
    })
    const j = await readJson(r)
// 保存成功提示
    if (j.ok) MessagePlugin.success("参数已保存")
    else MessagePlugin.error(j.error || "保存失败")
    await load()
  } finally { saving.value = false }
}

// 复用 IR 模型连接参数（含 Token）
async function copyIrConfig() {
  copying.value = true
  try {
    const r = await fetch("/api/translator/ai-writer/config/copy-from-ir", {
      method: "POST", headers: ADMIN_HEAD(),
    })
    const j = await readJson(r)
    if (j.ok) { MessagePlugin.success("已复用 IR 意图翻译模型的连接参数（含 API Token）"); await load() }
    else MessagePlugin.error(j.error || "复用失败")
  } catch (e) { MessagePlugin.error(`复用失败：${e.message || e}`) }
  finally { copying.value = false }
}

// 测试连接：回显模型与时延
async function doTest() {
  testing.value = true; testResult.value = ""
  try {
    const r = await fetch("/api/translator/ai-writer/test", { method: "POST", headers: ADMIN_HEAD() })
    const j = await readJson(r)
// 连通性结果回显（模型+时延）
    testResult.value = j.ok ? `连通：${j.data.model} · ${j.data.latency_ms}ms` : `失败：${j.error}`
  } catch (e) { testResult.value = `失败：${e}` } finally { testing.value = false }
}

// 保存提示词：自动备份原文件
async function saveDoc() {
  savingDoc.value = true
  try {
    const r = await fetch("/api/translator/ai-writer/skill-doc", {
      method: "PUT", headers: ADMIN_HEAD(), body: JSON.stringify({ content: skill.value.content }),
    })
    const j = await readJson(r)
// 提示词保存成功（含备份名）
    if (j.ok) MessagePlugin.success(`已保存（备份 ${j.data.backup}）`)
    else MessagePlugin.error(j.error || "保存失败")
    await load()
  } finally { savingDoc.value = false }
}

// 恢复内置默认提示词
async function doRestore() {
  const r = await fetch("/api/translator/ai-writer/skill-doc/restore", {
    method: "POST", headers: ADMIN_HEAD(), body: JSON.stringify({}),
  })
  const j = await readJson(r)
// 恢复默认成功提示
  if (j.ok) MessagePlugin.success(`已恢复（来源：${j.data.source}）`)
  else MessagePlugin.error(j.error || "恢复失败")
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
/* 弱化文本（帮写抽屉） */
.dim { color: #A6A6A6; font-size: 12px; }
/* 等宽字体（提示词编辑） */
.mono { font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; margin-top: 10px; }
</style>
