<template>
<!-- 注册表降级警示：策略库文件缺失/损坏时整页顶部提示（子组件） -->
  <RegistryWarning />
<!-- 双栏布局：左=两阶段提示词配置，右=翻译测试；下方为管线流程图 -->
  <div class="translate-layout">
    <!-- Left: Prompt Editor -->
<!-- 左栏·提示词面板：L1 场景分类与 L2 IR 生成两节，均支持保存/预览 -->
<!-- 保存走 PUT /api/translator/prompts，预览由服务端注入变量后回显 -->
    <div class="prompt-panel">
      <div class="panel-title">提示词配置</div>
<!-- L1 分节：场景分类提示词，占位符 {SCENE_LIST} 注入场景清单 -->
      <div class="prompt-section">
        <div class="prompt-header"><span class="prompt-label">Level-1 场景分类</span></div>
<!-- 可用变量提示：与占位符一一对应，蓝色高亮 -->
        <p class="prompt-hint">可用变量: <span class="var-highlight">{SCENE_LIST}</span></p>
<!-- 提示词文本域：编辑态与后端保存值双向绑定，等宽字体 -->
        <textarea v-model="editLevel1" class="prompt-textarea" placeholder="加载中..." rows="6"></textarea>
<!-- 操作行：保存（写入后端）/ 预览（注入变量） -->
        <div class="prompt-footer">
          <t-button size="small" theme="primary" @click="savePrompt('level1')" :loading="savingPrompt">保存</t-button>
          <t-button size="small" variant="outline" @click="previewPrompt('level1')">预览</t-button>
        </div>
      </div>
<!-- L2 分节：IR 生成提示词，占位符 {SELECTED_REGISTRY} 注入所选场景的工具注册表 -->
<!-- 注册表内容按 L1 命中场景筛选，控制上下文长度 -->
      <div class="prompt-section">
        <div class="prompt-header"><span class="prompt-label">Level-2 IR 生成</span></div>
<!-- 可用变量提示行 -->
        <p class="prompt-hint">可用变量: <span class="var-highlight">{SELECTED_REGISTRY}</span></p>
        <textarea v-model="editLevel2" class="prompt-textarea" placeholder="加载中..." rows="6"></textarea>
<!-- 操作行：保存 / 预览 -->
        <div class="prompt-footer">
          <t-button size="small" theme="primary" @click="savePrompt('level2')" :loading="savingPrompt">保存</t-button>
          <t-button size="small" variant="outline" @click="previewPrompt('level2')">预览</t-button>
        </div>
      </div>
    </div>

    <!-- Right: Test Panel -->
<!-- 右栏·翻译测试面板：输入用户查询，一键执行两阶段翻译 -->
<!-- 接口 POST /api/translator/test，返回 level1/level2/validation/meta -->
    <div class="test-panel">
      <div class="panel-title">翻译测试</div>
<!-- 测试输入区：查询文本 + 执行按钮纵排 -->
      <div class="test-input">
<!-- 用户查询输入：示例为「安全地读取 /tmp/hello.py」类只读请求 -->
        <t-textarea v-model="testQuery" placeholder="输入用户查询，例如：安全地读取 /tmp/hello.py" :autosize="{ minRows: 2, maxRows: 4 }" />
<!-- 执行翻译按钮：loading 期间防重复提交 -->
        <t-button theme="primary" block @click="runFullTest" :loading="testing">
          <t-icon name="play-circle" /> 执行翻译
        </t-button>
<!-- 说明：翻译使用「策略翻译→模型配置」，与网关模型无关 -->
        <p class="test-note">翻译使用「策略翻译 → 模型配置」中配置的模型，与网关模型无关</p>
      </div>
<!-- 结果区：有结果才渲染 -->
      <div v-if="testResult" class="test-result">
<!-- L1 结果块：场景分类命中列表 -->
        <div class="result-block">
          <div class="result-label">Level-1 场景</div>
<!-- 场景标签组：每个命中场景一个标签；空结果显示占位 -->
          <div class="result-tags">
            <t-tag v-for="s in testResult.level1" :key="s" theme="primary" variant="light">{{ s }}</t-tag>
            <span v-if="!testResult.level1?.length" class="empty-hint">(无匹配)</span>
          </div>
        </div>
<!-- L2 结果块：IR 策略 JSON -->
        <div v-if="testResult.level2" class="result-block">
          <div class="result-label">Level-2 IR</div>
<!-- IR 等宽展示：2 空格缩进格式化 -->
          <pre class="result-json">{{ JSON.stringify(testResult.level2, null, 2) }}</pre>
        </div>
<!-- 校验结果块：结构/语义两级校验的通过与否 -->
        <div v-if="testResult.validation" class="result-block">
          <div class="result-label">校验</div>
<!-- 通过/失败标签：绿色 success / 红色 danger -->
          <t-tag :theme="testResult.validation.ok ? 'success' : 'danger'" variant="light" size="small">
            {{ testResult.validation.ok ? '通过' : '失败' }}
          </t-tag>
<!-- 行内校验错误：分号拼接展示 -->
          <span v-if="testResult.validation.errors?.length" class="val-errors">{{ testResult.validation.errors.join('; ') }}</span>
        </div>
<!-- 调用信息块：模型与两级时延 -->
        <div v-if="testResult.meta" class="result-block">
          <div class="result-label">调用信息</div>
<!-- 元信息标签组：模型名 + L1/L2 时延（ms） -->
          <div class="meta-chips">
            <t-tag size="small" variant="outline">{{ testResult.meta?.level1?.model }}</t-tag>
            <t-tag size="small" variant="outline">L1: {{ testResult.meta?.level1?.latency_ms }}ms</t-tag>
            <t-tag size="small" variant="outline" v-if="testResult.meta?.level2?.latency_ms">L2: {{ testResult.meta.level2.latency_ms }}ms</t-tag>
          </div>
        </div>
      </div>
<!-- 错误行：接口失败或返回 error 时显示 -->
      <div v-if="testError" class="test-error">{{ testError }}</div>
    </div>
  </div>

  <!-- Pipeline -->
<!-- 管线流程卡：用户查询→L1→scenes[]→L2→规范化→校验→IR -->
<!-- 节点配色区分阶段：蓝=L1、绿=L2、紫=规范化、橙=校验 -->
  <div class="pipeline-card">
    <div class="pipeline-title">翻译管线流程</div>
<!-- 节点流：横向排列 + 箭头连接，窄屏自动换行 -->
    <div class="pipeline-flow">
<!-- 输入节点：用户查询 -->
      <div class="flow-node input-node"><div class="node-icon">💬</div><div class="node-text">用户查询</div></div>
      <div class="flow-arrow">→</div>
<!-- Level-1 节点：场景分类（LLM + {SCENE_LIST}） -->
      <div class="flow-node stage-node level1-node"><div class="node-badge">Level-1</div><div class="node-text">场景分类</div><div class="node-detail">LLM + {SCENE_LIST}</div></div>
      <div class="flow-arrow">→</div>
<!-- 中间产物节点：scenes[] -->
      <div class="flow-node mid-node"><div class="node-icon">🏷️</div><div class="node-text">scenes[]</div></div>
      <div class="flow-arrow">→</div>
<!-- Level-2 节点：IR 生成（LLM + {SELECTED_REGISTRY}） -->
      <div class="flow-node stage-node level2-node"><div class="node-badge">Level-2</div><div class="node-text">IR 生成</div><div class="node-detail">LLM + {SELECTED_REGISTRY}</div></div>
      <div class="flow-arrow">→</div>
<!-- 规范化节点：格式校正 + 自动补全 serverName__ -->
      <div class="flow-node stage-node normalize-node"><div class="node-badge">Normalize</div><div class="node-text">标准化</div><div class="node-detail">格式校正 + 自动补全</div></div>
      <div class="flow-arrow">→</div>
<!-- 校验节点：与注册表比对 identifier/params 合法性 -->
      <div class="flow-node stage-node validate-node"><div class="node-badge">Validate</div><div class="node-text">校验</div><div class="node-detail">注册表比对</div></div>
      <div class="flow-arrow">→</div>
<!-- 输出节点：subject/objects 权限策略（IR 策略） -->
      <div class="flow-node output-node"><div class="node-icon">📋</div><div class="node-text">subject/objects IR</div></div>
    </div>
<!-- 分阶段文字说明：与节点图一一对应 -->
    <div class="pipeline-desc">
      <p><strong>Stage 1 - 场景分类：</strong>将用户请求分类到预定义场景，使用 <code>{SCENE_LIST}</code> 注入。</p>
      <p><strong>Stage 2 - IR 生成：</strong>基于选中场景的函数定义（<code>{SELECTED_REGISTRY}</code>），生成 subject/objects 权限策略。</p>
      <p><strong>Normalize：</strong>统一格式，自动补全 serverName__，填充缺省参数。</p>
      <p><strong>Validate：</strong>比对注册表，校验 identifier/params 合法性。</p>
    </div>
  </div>

  <!-- Preview Dialog -->
<!-- 预览对话框：展示变量注入后的最终提示词 -->
<!-- 变量来源：{SCENE_LIST}=scenes.json；{SELECTED_REGISTRY}=tools/*.json -->
  <t-dialog v-model:visible="previewVisible" :header="'提示词预览 - ' + previewLevel" width="750px" :footer="false">
    <div class="preview-info">
<!-- 变量来源说明行：按级别提示不同注册表文件 -->
      <div class="preview-var-source">
        <t-icon name="info-circle" size="14px" style="color: #0052D9;" />
        <span v-if="previewLevel === 'Level-1'">变量 <code>{SCENE_LIST}</code> 来源：<strong>policy_registry/scenes.json</strong></span>
        <span v-else>变量 <code>{SELECTED_REGISTRY}</code> 来源：<strong>policy_registry/tools/*.json</strong></span>
      </div>
    </div>
<!-- 预览内容：等宽字体 + 自动换行 -->
    <pre class="preview-pre">{{ previewContent }}</pre>
  </t-dialog>
</template>

<script setup>
// Vue 响应式 API：ref（本页无 computed/watch）
import { ref } from "vue"
// 注册表警示子组件（顶部渲染）
import RegistryWarning from "../../components/RegistryWarning.vue"
// TDesign 全局消息插件：成功/失败提示
import { MessagePlugin } from "tdesign-vue-next"

// 提示词编辑态：两阶段内容的本地镜像，保存/预览共用
// 挂载时从后端回填；未保存的修改仅存本地
const editLevel1 = ref("")
const editLevel2 = ref("")
// 保存按钮 loading 态（防重复提交）
const savingPrompt = ref(false)
const testQuery = ref("")
// 翻译执行中标志
const testing = ref(false)
// 测试结果：level1 场景 / level2 IR / validation 校验 / meta 元信息四块
const testResult = ref(null)
const testError = ref("")
// 预览对话框状态组：可见性 + 级别名 + 注入后内容
const previewVisible = ref(false)
const previewLevel = ref("")
const previewContent = ref("")

// Load prompts on mount
// 挂载即拉取当前提示词：失败静默，文本域保持「加载中...」占位
// 不阻塞页面：提示词加载与翻译测试相互独立
;(async () => {
  try {
// GET /api/translator/prompts：一次返回两级内容
    const res = await fetch("/api/translator/prompts")
    const json = await res.json()
// ok 校验后回填编辑态
    if (json.ok) {
      editLevel1.value = json.data.level1.value || ""
      editLevel2.value = json.data.level2.value || ""
    }
  } catch (e) {}
})()

// 保存提示词：按级别 PUT 单级内容，保存后立即生效（热更新）
// 网络失败给出错误提示，不影响另一级
async function savePrompt(level) {
  savingPrompt.value = true
// 按级别组装请求体：{level1: ...} 或 {level2: ...}
  const body = {}
  body[level] = level === "level1" ? editLevel1.value : editLevel2.value
  try {
// 提交保存请求
    const res = await fetch("/api/translator/prompts", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    const json = await res.json()
    if (json.ok) MessagePlugin.success("提示词已保存")
    else MessagePlugin.error(json.error)
  } catch (e) { MessagePlugin.error("连接失败") }
  savingPrompt.value = false
}

// 预览：把当前文本 POST 给服务端，注入变量后返回最终提示词
// 用于确认占位符拼写与注册表内容是否符合预期
async function previewPrompt(level) {
  const promptText = level === "level1" ? editLevel1.value : editLevel2.value
  previewLevel.value = level === "level1" ? "Level-1" : "Level-2"
  try {
// 请求预览接口
    const res = await fetch("/api/translator/prompts/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ level, prompt: promptText }) })
    const json = await res.json()
    if (json.ok) { previewContent.value = json.data.preview; previewVisible.value = true }
    else MessagePlugin.error(json.error)
  } catch (e) { MessagePlugin.error("连接失败") }
}

// 执行翻译：POST 用户查询，走完整两阶段管线
// 结果含 L1 场景、L2 IR、校验结论与模型/时延元信息
async function runFullTest() {
  if (!testQuery.value.trim()) return
// 重置上次结果与错误信息
  testing.value = true; testError.value = ""; testResult.value = null
  try {
// 提交翻译请求
    const res = await fetch("/api/translator/test", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: testQuery.value.trim() }) })
    const json = await res.json()
    if (json.ok) testResult.value = json.data
    else testError.value = json.error
  } catch (e) { testError.value = "连接失败" }
  testing.value = false
}
</script>

<style scoped>
/* 双栏布局：左提示词 / 右测试，16px 间距 */
.translate-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
/* 面板容器通用样式：白底圆角卡片 */
.prompt-panel, .test-panel { background: #fff; border-radius: 12px; padding: 20px; border: 1px solid #eee; }
/* 面板标题 */
.panel-title { font-size: 15px; font-weight: 600; color: #333; margin-bottom: 16px; }
/* 分节：底分隔线，末节无分隔线 */
.prompt-section { margin-bottom: 18px; padding-bottom: 16px; border-bottom: 1px solid #f3f3f3; }
.prompt-section:last-child { border-bottom: none; }
.prompt-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.prompt-label { font-size: 13px; font-weight: 600; color: #333; }
.prompt-hint { font-size: 12px; color: #999; margin-bottom: 8px; }
.var-highlight { color: #0052D9; font-weight: 600; font-family: monospace; background: #f0f5ff; padding: 1px 4px; border-radius: 3px; }
/* 提示词文本域：等宽字体 + 手动调整高度 */
.prompt-textarea { width: 100%; border: 1px solid #ddd; border-radius: 8px; padding: 10px; font-family: "SF Mono", monospace; font-size: 12px; line-height: 1.6; resize: vertical; outline: none; }
/* 文本域聚焦态：蓝色描边 */
.prompt-textarea:focus { border-color: #0052D9; }
.prompt-footer { display: flex; gap: 8px; margin-top: 8px; }
/* 测试输入区：纵排布局 */
.test-input { display: flex; flex-direction: column; gap: 10px; }
.test-note { font-size: 11px; color: #999; text-align: center; }
/* 结果区：与输入区留距 */
.test-result { margin-top: 16px; }
/* 结果块间距 */
.result-block { margin-bottom: 12px; }
.result-label { font-size: 12px; font-weight: 600; color: #0052D9; margin-bottom: 6px; text-transform: uppercase; }
.result-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.empty-hint { font-size: 12px; color: #ccc; font-style: italic; }
/* IR JSON 代码块：暗底等宽 + 横向滚动 + 限高 */
.result-json { background: #f8f9fa; border-radius: 8px; padding: 12px; font-size: 11px; line-height: 1.6; overflow-x: auto; max-height: 300px; color: #333; font-family: "SF Mono", monospace; margin: 0; }
/* 元信息标签组 */
.meta-chips { display: flex; gap: 6px; }
.val-errors { font-size: 11px; color: #ff5252; margin-left: 6px; }
.test-error { margin-top: 12px; background: #fff5f5; border: 1px solid #ffe0e0; border-radius: 8px; padding: 10px; font-size: 13px; color: #ff5252; }
/* 管线流程卡：白底容器 */
.pipeline-card { background: #fff; border-radius: 12px; padding: 24px; border: 1px solid #eee; margin-top: 16px; }
.pipeline-title { font-size: 15px; font-weight: 600; color: #333; margin-bottom: 16px; }
.pipeline-flow { display: flex; align-items: center; justify-content: center; gap: 6px; padding: 20px 0; overflow-x: auto; flex-wrap: wrap; }
/* 流程节点基类：灰底圆角 + 最小宽度 */
.flow-node { background: #f8f9fa; border-radius: 10px; padding: 10px 14px; text-align: center; border: 1px solid #eee; min-width: 80px; }
/* 阶段节点：蓝色粗边框 */
.flow-node.stage-node { border: 2px solid #0052D9; background: #f0f5ff; }
/* L1 节点配色 */
.flow-node.level1-node { border-color: #0052D9; }
/* L2 节点配色：绿系 */
.flow-node.level2-node { border-color: #00a870; background: #f0fff8; }
/* 规范化节点配色：紫系 */
.flow-node.normalize-node { border-color: #722ed1; background: #f8f0ff; }
.flow-node.normalize-node .node-badge { background: #722ed1; }
/* 校验节点配色：橙系 */
.flow-node.validate-node { border-color: #ED7B2F; background: #fffbf5; }
.flow-node.validate-node .node-badge { background: #ED7B2F; }
/* 输入节点配色：黄系 */
.flow-node.input-node { background: #fffbe6; border-color: #ffe8b8; }
/* 输出节点配色：绿系 */
.flow-node.output-node { background: #f0fff8; border-color: #c2f0d8; }
.flow-node.mid-node { background: #f5f5f5; }
/* 节点图标 */
.node-icon { font-size: 18px; margin-bottom: 2px; }
/* 节点徽标：阶段名小标签 */
.node-badge { font-size: 10px; font-weight: 700; text-transform: uppercase; background: #0052D9; color: #fff; padding: 2px 6px; border-radius: 4px; display: inline-block; margin-bottom: 2px; }
.level2-node .node-badge { background: #00a870; }
.node-text { font-size: 11px; font-weight: 600; color: #333; }
/* 节点补充说明：等宽小字 */
.node-detail { font-size: 9px; color: #999; margin-top: 2px; font-family: monospace; }
/* 流程箭头 */
.flow-arrow { font-size: 16px; color: #ccc; font-weight: bold; }
/* 分阶段文字说明：两倍行距便于阅读 */
.pipeline-desc { margin-top: 16px; font-size: 12px; color: #666; line-height: 1.8; }
.pipeline-desc p { margin-bottom: 4px; }
.pipeline-desc code { background: #f0f5ff; padding: 1px 4px; border-radius: 3px; color: #0052D9; }
/* 预览信息行 */
.preview-info { margin-bottom: 12px; }
.preview-var-source { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #666; background: #f0f5ff; padding: 8px 12px; border-radius: 6px; }
.preview-var-source code { color: #0052D9; font-weight: 600; }
.preview-var-source strong { color: #333; }
/* 预览代码块：限高滚动 */
.preview-pre { background: #f8f9fa; border-radius: 8px; padding: 16px; font-size: 11px; line-height: 1.6; white-space: pre-wrap; word-break: break-all; max-height: 500px; overflow-y: auto; font-family: "SF Mono", monospace; color: #333; }
</style>
