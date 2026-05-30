<template>
  <RegistryWarning />
  <div class="translate-layout">
    <!-- Left: Prompt Editor -->
    <div class="prompt-panel">
      <div class="panel-title">提示词配置</div>
      <div class="prompt-section">
        <div class="prompt-header"><span class="prompt-label">Level-1 场景分类</span></div>
        <p class="prompt-hint">可用变量: <span class="var-highlight">{SCENE_LIST}</span></p>
        <textarea v-model="editLevel1" class="prompt-textarea" placeholder="加载中..." rows="6"></textarea>
        <div class="prompt-footer">
          <t-button size="small" theme="primary" @click="savePrompt('level1')" :loading="savingPrompt">保存</t-button>
          <t-button size="small" variant="outline" @click="previewPrompt('level1')">预览</t-button>
        </div>
      </div>
      <div class="prompt-section">
        <div class="prompt-header"><span class="prompt-label">Level-2 IR 生成</span></div>
        <p class="prompt-hint">可用变量: <span class="var-highlight">{SELECTED_REGISTRY}</span></p>
        <textarea v-model="editLevel2" class="prompt-textarea" placeholder="加载中..." rows="6"></textarea>
        <div class="prompt-footer">
          <t-button size="small" theme="primary" @click="savePrompt('level2')" :loading="savingPrompt">保存</t-button>
          <t-button size="small" variant="outline" @click="previewPrompt('level2')">预览</t-button>
        </div>
      </div>
    </div>

    <!-- Right: Test Panel -->
    <div class="test-panel">
      <div class="panel-title">翻译测试</div>
      <div class="test-input">
        <t-textarea v-model="testQuery" placeholder="输入用户查询，例如：安全地读取 /tmp/hello.py" :autosize="{ minRows: 2, maxRows: 4 }" />
        <t-button theme="primary" block @click="runFullTest" :loading="testing">
          <t-icon name="play-circle" /> 执行翻译
        </t-button>
        <p class="test-note">翻译使用「策略翻译 → 模型配置」中配置的模型，与网关模型无关</p>
      </div>
      <div v-if="testResult" class="test-result">
        <div class="result-block">
          <div class="result-label">Level-1 场景</div>
          <div class="result-tags">
            <t-tag v-for="s in testResult.level1" :key="s" theme="primary" variant="light">{{ s }}</t-tag>
            <span v-if="!testResult.level1?.length" class="empty-hint">(无匹配)</span>
          </div>
        </div>
        <div v-if="testResult.level2" class="result-block">
          <div class="result-label">Level-2 IR</div>
          <pre class="result-json">{{ JSON.stringify(testResult.level2, null, 2) }}</pre>
        </div>
        <div v-if="testResult.validation" class="result-block">
          <div class="result-label">校验</div>
          <t-tag :theme="testResult.validation.ok ? 'success' : 'danger'" variant="light" size="small">
            {{ testResult.validation.ok ? '通过' : '失败' }}
          </t-tag>
          <span v-if="testResult.validation.errors?.length" class="val-errors">{{ testResult.validation.errors.join('; ') }}</span>
        </div>
        <div v-if="testResult.meta" class="result-block">
          <div class="result-label">调用信息</div>
          <div class="meta-chips">
            <t-tag size="small" variant="outline">{{ testResult.meta?.level1?.model }}</t-tag>
            <t-tag size="small" variant="outline">L1: {{ testResult.meta?.level1?.latency_ms }}ms</t-tag>
            <t-tag size="small" variant="outline" v-if="testResult.meta?.level2?.latency_ms">L2: {{ testResult.meta.level2.latency_ms }}ms</t-tag>
          </div>
        </div>
      </div>
      <div v-if="testError" class="test-error">{{ testError }}</div>
    </div>
  </div>

  <!-- Pipeline -->
  <div class="pipeline-card">
    <div class="pipeline-title">翻译管线流程</div>
    <div class="pipeline-flow">
      <div class="flow-node input-node"><div class="node-icon">💬</div><div class="node-text">用户查询</div></div>
      <div class="flow-arrow">→</div>
      <div class="flow-node stage-node level1-node"><div class="node-badge">Level-1</div><div class="node-text">场景分类</div><div class="node-detail">LLM + {SCENE_LIST}</div></div>
      <div class="flow-arrow">→</div>
      <div class="flow-node mid-node"><div class="node-icon">🏷️</div><div class="node-text">scenes[]</div></div>
      <div class="flow-arrow">→</div>
      <div class="flow-node stage-node level2-node"><div class="node-badge">Level-2</div><div class="node-text">IR 生成</div><div class="node-detail">LLM + {SELECTED_REGISTRY}</div></div>
      <div class="flow-arrow">→</div>
      <div class="flow-node stage-node normalize-node"><div class="node-badge">Normalize</div><div class="node-text">标准化</div><div class="node-detail">格式校正 + 自动补全</div></div>
      <div class="flow-arrow">→</div>
      <div class="flow-node stage-node validate-node"><div class="node-badge">Validate</div><div class="node-text">校验</div><div class="node-detail">注册表比对</div></div>
      <div class="flow-arrow">→</div>
      <div class="flow-node output-node"><div class="node-icon">📋</div><div class="node-text">subject/objects IR</div></div>
    </div>
    <div class="pipeline-desc">
      <p><strong>Stage 1 - 场景分类：</strong>将用户请求分类到预定义场景，使用 <code>{SCENE_LIST}</code> 注入。</p>
      <p><strong>Stage 2 - IR 生成：</strong>基于选中场景的函数定义（<code>{SELECTED_REGISTRY}</code>），生成 subject/objects 权限策略。</p>
      <p><strong>Normalize：</strong>统一格式，自动补全 serverName__，填充缺省参数。</p>
      <p><strong>Validate：</strong>比对注册表，校验 identifier/params 合法性。</p>
    </div>
  </div>

  <!-- Preview Dialog -->
  <t-dialog v-model:visible="previewVisible" :header="'提示词预览 - ' + previewLevel" width="750px" :footer="false">
    <div class="preview-info">
      <div class="preview-var-source">
        <t-icon name="info-circle" size="14px" style="color: #0052D9;" />
        <span v-if="previewLevel === 'Level-1'">变量 <code>{SCENE_LIST}</code> 来源：<strong>policy_registry/scenes.json</strong></span>
        <span v-else>变量 <code>{SELECTED_REGISTRY}</code> 来源：<strong>policy_registry/tools/*.json</strong></span>
      </div>
    </div>
    <pre class="preview-pre">{{ previewContent }}</pre>
  </t-dialog>
</template>

<script setup>
import { ref } from "vue"
import RegistryWarning from "../../components/RegistryWarning.vue"
import { MessagePlugin } from "tdesign-vue-next"

const editLevel1 = ref("")
const editLevel2 = ref("")
const savingPrompt = ref(false)
const testQuery = ref("")
const testing = ref(false)
const testResult = ref(null)
const testError = ref("")
const previewVisible = ref(false)
const previewLevel = ref("")
const previewContent = ref("")

// Load prompts on mount
;(async () => {
  try {
    const res = await fetch("/api/translator/prompts")
    const json = await res.json()
    if (json.ok) {
      editLevel1.value = json.data.level1.value || ""
      editLevel2.value = json.data.level2.value || ""
    }
  } catch (e) {}
})()

async function savePrompt(level) {
  savingPrompt.value = true
  const body = {}
  body[level] = level === "level1" ? editLevel1.value : editLevel2.value
  try {
    const res = await fetch("/api/translator/prompts", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    const json = await res.json()
    if (json.ok) MessagePlugin.success("提示词已保存")
    else MessagePlugin.error(json.error)
  } catch (e) { MessagePlugin.error("连接失败") }
  savingPrompt.value = false
}

async function previewPrompt(level) {
  const promptText = level === "level1" ? editLevel1.value : editLevel2.value
  previewLevel.value = level === "level1" ? "Level-1" : "Level-2"
  try {
    const res = await fetch("/api/translator/prompts/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ level, prompt: promptText }) })
    const json = await res.json()
    if (json.ok) { previewContent.value = json.data.preview; previewVisible.value = true }
    else MessagePlugin.error(json.error)
  } catch (e) { MessagePlugin.error("连接失败") }
}

async function runFullTest() {
  if (!testQuery.value.trim()) return
  testing.value = true; testError.value = ""; testResult.value = null
  try {
    const res = await fetch("/api/translator/test", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: testQuery.value.trim() }) })
    const json = await res.json()
    if (json.ok) testResult.value = json.data
    else testError.value = json.error
  } catch (e) { testError.value = "连接失败" }
  testing.value = false
}
</script>

<style scoped>
.translate-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.prompt-panel, .test-panel { background: #fff; border-radius: 12px; padding: 20px; border: 1px solid #eee; }
.panel-title { font-size: 15px; font-weight: 600; color: #333; margin-bottom: 16px; }
.prompt-section { margin-bottom: 18px; padding-bottom: 16px; border-bottom: 1px solid #f3f3f3; }
.prompt-section:last-child { border-bottom: none; }
.prompt-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.prompt-label { font-size: 13px; font-weight: 600; color: #333; }
.prompt-hint { font-size: 12px; color: #999; margin-bottom: 8px; }
.var-highlight { color: #0052D9; font-weight: 600; font-family: monospace; background: #f0f5ff; padding: 1px 4px; border-radius: 3px; }
.prompt-textarea { width: 100%; border: 1px solid #ddd; border-radius: 8px; padding: 10px; font-family: "SF Mono", monospace; font-size: 12px; line-height: 1.6; resize: vertical; outline: none; }
.prompt-textarea:focus { border-color: #0052D9; }
.prompt-footer { display: flex; gap: 8px; margin-top: 8px; }
.test-input { display: flex; flex-direction: column; gap: 10px; }
.test-note { font-size: 11px; color: #999; text-align: center; }
.test-result { margin-top: 16px; }
.result-block { margin-bottom: 12px; }
.result-label { font-size: 12px; font-weight: 600; color: #0052D9; margin-bottom: 6px; text-transform: uppercase; }
.result-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.empty-hint { font-size: 12px; color: #ccc; font-style: italic; }
.result-json { background: #f8f9fa; border-radius: 8px; padding: 12px; font-size: 11px; line-height: 1.6; overflow-x: auto; max-height: 300px; color: #333; font-family: "SF Mono", monospace; margin: 0; }
.meta-chips { display: flex; gap: 6px; }
.val-errors { font-size: 11px; color: #ff5252; margin-left: 6px; }
.test-error { margin-top: 12px; background: #fff5f5; border: 1px solid #ffe0e0; border-radius: 8px; padding: 10px; font-size: 13px; color: #ff5252; }
.pipeline-card { background: #fff; border-radius: 12px; padding: 24px; border: 1px solid #eee; margin-top: 16px; }
.pipeline-title { font-size: 15px; font-weight: 600; color: #333; margin-bottom: 16px; }
.pipeline-flow { display: flex; align-items: center; justify-content: center; gap: 6px; padding: 20px 0; overflow-x: auto; flex-wrap: wrap; }
.flow-node { background: #f8f9fa; border-radius: 10px; padding: 10px 14px; text-align: center; border: 1px solid #eee; min-width: 80px; }
.flow-node.stage-node { border: 2px solid #0052D9; background: #f0f5ff; }
.flow-node.level1-node { border-color: #0052D9; }
.flow-node.level2-node { border-color: #00a870; background: #f0fff8; }
.flow-node.normalize-node { border-color: #722ed1; background: #f8f0ff; }
.flow-node.normalize-node .node-badge { background: #722ed1; }
.flow-node.validate-node { border-color: #ED7B2F; background: #fffbf5; }
.flow-node.validate-node .node-badge { background: #ED7B2F; }
.flow-node.input-node { background: #fffbe6; border-color: #ffe8b8; }
.flow-node.output-node { background: #f0fff8; border-color: #c2f0d8; }
.flow-node.mid-node { background: #f5f5f5; }
.node-icon { font-size: 18px; margin-bottom: 2px; }
.node-badge { font-size: 10px; font-weight: 700; text-transform: uppercase; background: #0052D9; color: #fff; padding: 2px 6px; border-radius: 4px; display: inline-block; margin-bottom: 2px; }
.level2-node .node-badge { background: #00a870; }
.node-text { font-size: 11px; font-weight: 600; color: #333; }
.node-detail { font-size: 9px; color: #999; margin-top: 2px; font-family: monospace; }
.flow-arrow { font-size: 16px; color: #ccc; font-weight: bold; }
.pipeline-desc { margin-top: 16px; font-size: 12px; color: #666; line-height: 1.8; }
.pipeline-desc p { margin-bottom: 4px; }
.pipeline-desc code { background: #f0f5ff; padding: 1px 4px; border-radius: 3px; color: #0052D9; }
.preview-info { margin-bottom: 12px; }
.preview-var-source { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #666; background: #f0f5ff; padding: 8px 12px; border-radius: 6px; }
.preview-var-source code { color: #0052D9; font-weight: 600; }
.preview-var-source strong { color: #333; }
.preview-pre { background: #f8f9fa; border-radius: 8px; padding: 16px; font-size: 11px; line-height: 1.6; white-space: pre-wrap; word-break: break-all; max-height: 500px; overflow-y: auto; font-family: "SF Mono", monospace; color: #333; }
</style>
