<template>
  <div class="registry-tab">
    <RegistryWarning />

    <!-- Path Config -->
    <div class="path-card">
      <div class="path-header">
        <div class="path-label"><t-icon name="folder" size="16px" style="color: #0052D9;" /><span>策略库路径</span></div>
        <PrivilegeStatus hint="修改路径/策略配置需要特权验证" @unlock="showPrivDialog = true" />
      </div>
      <div class="path-input">
        <t-input v-model="registryPath" :disabled="!adminValid" placeholder="/home/hx/jjq/clawAVC/backend/auditor/translator/policy_registry" style="flex:1;" />
        <t-button theme="primary" size="small" :disabled="!adminValid || !registryPath.trim()" @click="savePath" :loading="savingPath">保存</t-button>
      </div>
      <p class="path-hint">路径必须以 <code>policy_registry</code> 结尾，且包含 <code>scenes.json</code> 和 <code>tools/</code></p>
      <div v-if="pathError" class="path-error">{{ pathError }}</div>
      <div v-if="pathSuccess" class="path-success">{{ pathSuccess }}</div>
    </div>

    <!-- Scene Detail (when a scene is selected) -->
    <div v-if="selectedScene" class="scene-detail-card">
      <div class="detail-header">
        <t-button variant="text" size="small" @click="selectedScene = null"><t-icon name="chevron-left" /> 返回概览</t-button>
        <span class="detail-title">{{ selectedScene }}</span>
      </div>

      <!-- Desc -->
      <div class="detail-section">
        <div class="section-label">场景描述</div>
        <t-textarea v-model="sceneDesc" :disabled="!adminValid" :autosize="{ minRows: 2, maxRows: 4 }" />
        <t-button size="small" theme="primary" :disabled="!adminValid" @click="saveDesc" :loading="savingDesc" style="margin-top: 8px;">保存描述</t-button>
      </div>

      <!-- Functions -->
      <div class="detail-section">
        <div class="section-label">
          Functions
          <t-button size="small" variant="outline" :disabled="!adminValid" @click="showAddFunc = true"><t-icon name="add" /> 新增</t-button>
        </div>
        <div class="func-list">
          <div v-for="(def, fname) in sceneFunctions" :key="fname" class="func-item" @click="editFunc(fname, def)">
            <div class="func-name">{{ fname }}</div>
            <div class="func-desc">{{ def.desc || '(无描述)' }}</div>
            <div class="func-actions">
              <t-button size="small" variant="text" theme="danger" :disabled="!adminValid" @click.stop="removeFunc(fname)">移除</t-button>
            </div>
          </div>
        </div>
        <p class="delete-hint"><t-icon name="info-circle" size="14px" /> 删除整个场景请手动删除 <code>tools/{{ selectedScene }}.json</code> 及 <code>scenes.json</code> 对应元素</p>
      </div>
    </div>

    <!-- Scene Overview (default) -->
    <div v-else class="registry-card">
      <div class="card-title">场景概览 <t-button size="small" variant="outline" @click="loadRegistry">刷新</t-button></div>
      <div v-if="registry" class="registry-grid">
        <div v-for="(scene, name) in registry.scenes" :key="name" class="registry-item" @click="selectScene(name)">
          <div class="registry-name">{{ name }}</div>
          <div class="registry-desc">{{ scene.desc }}</div>
          <div class="registry-funcs">
            <t-tag v-for="f in scene.functions?.slice(0, 4)" :key="f" size="small" variant="outline">{{ f }}</t-tag>
            <t-tag v-if="scene.functions?.length > 4" size="small" variant="light">+{{ scene.functions.length - 4 }}</t-tag>
          </div>
        </div>
      </div>
    </div>

    <!-- Add Function Dialog -->
    <t-dialog v-model:visible="showAddFunc" header="新增 Function" :confirm-btn="{ content: '添加', theme: 'primary', loading: addingFunc }" @confirm="doAddFunc">
      <div class="add-func-form">
        <div class="form-row"><label>函数名</label><t-input v-model="newFuncName" placeholder="如 safe_file_reader__read_text" /></div>
        <div class="form-row"><label>描述</label><t-input v-model="newFuncDesc" placeholder="函数描述" /></div>
      </div>
    </t-dialog>

    <!-- Edit Function Dialog -->
    <t-drawer v-model:visible="showEditFunc" header="编辑 Function" size="520px" :footer="false">
      <div v-if="editFuncName" class="edit-func">
        <div class="edit-field"><label>函数名</label><t-input :value="editFuncName" disabled /></div>
        <div class="edit-field"><label>定义 (JSON)</label>
          <textarea v-model="editFuncJson" class="func-json-editor" rows="15" :disabled="!adminValid"></textarea>
        </div>
        <t-button theme="primary" :disabled="!adminValid" @click="saveFunc" :loading="savingFunc">保存</t-button>
      </div>
    </t-drawer>

    <PrivilegeDialog v-model="showPrivDialog" @success="() => {}" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from "vue"
import { MessagePlugin } from "tdesign-vue-next"
import PrivilegeDialog from "../../components/PrivilegeDialog.vue"
import PrivilegeStatus from "../../components/PrivilegeStatus.vue"
import RegistryWarning from "../../components/RegistryWarning.vue"

const showPrivDialog = ref(false)
const registryPath = ref("")
const savingPath = ref(false)
const pathError = ref("")
const pathSuccess = ref("")
const registry = ref(null)
const tick = ref(0)
let _t = null
const adminValid = computed(() => { void tick.value; return !!sessionStorage.getItem("clawavc_admin_session") && Date.now() < Number(sessionStorage.getItem("clawavc_admin_expiry") || 0) })

// Scene detail
const selectedScene = ref(null)
const sceneDesc = ref("")
const sceneFunctions = ref({})
const savingDesc = ref(false)

// Add function
const showAddFunc = ref(false)
const newFuncName = ref("")
const newFuncDesc = ref("")
const addingFunc = ref(false)

// Edit function
const showEditFunc = ref(false)
const editFuncName = ref("")
const editFuncJson = ref("")
const savingFunc = ref(false)

onMounted(() => { _t = setInterval(() => tick.value++, 1000); loadPath(); loadRegistry() })
onUnmounted(() => clearInterval(_t))

async function loadPath() { try { const r = await fetch("/api/translator/registry-path"); const j = await r.json(); if (j.ok) registryPath.value = j.data.path || "" } catch {} }

async function savePath() {
  savingPath.value = true; pathError.value = ""; pathSuccess.value = ""
  try {
    const r = await fetch("/api/translator/registry-path", { method: "PUT", headers: { "Content-Type": "application/json", "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "" }, body: JSON.stringify({ path: registryPath.value.trim() }) })
    const j = await r.json()
    if (j.ok) { pathSuccess.value = "路径已保存，策略库已重新加载"; loadRegistry() } else pathError.value = j.error
  } catch { pathError.value = "连接失败" }
  savingPath.value = false
}

async function loadRegistry() { try { const r = await fetch("/api/translator/registry"); const j = await r.json(); if (j.ok) registry.value = j.data } catch {} }

async function selectScene(name) {
  selectedScene.value = name
  try {
    const r = await fetch(`/api/translator/scene/${name}`)
    const j = await r.json()
    if (j.ok) { sceneDesc.value = j.data.desc; sceneFunctions.value = j.data.functions_detail }
  } catch {}
}

async function saveDesc() {
  savingDesc.value = true
  try {
    const r = await fetch(`/api/translator/scene/${selectedScene.value}/desc`, { method: "PUT", headers: { "Content-Type": "application/json", "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "" }, body: JSON.stringify({ desc: sceneDesc.value }) })
    const j = await r.json()
    if (j.ok) MessagePlugin.success("描述已保存"); else MessagePlugin.error(j.error)
  } catch { MessagePlugin.error("连接失败") }
  savingDesc.value = false
}

async function doAddFunc() {
  if (!newFuncName.value.trim()) return
  addingFunc.value = true
  try {
    const r = await fetch(`/api/translator/scene/${selectedScene.value}/functions`, { method: "PUT", headers: { "Content-Type": "application/json", "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "" }, body: JSON.stringify({ action: "add", name: newFuncName.value.trim(), definition: { type: "function", desc: newFuncDesc.value, params: {} } }) })
    const j = await r.json()
    if (j.ok) { MessagePlugin.success("函数已添加"); showAddFunc.value = false; newFuncName.value = ""; newFuncDesc.value = ""; selectScene(selectedScene.value) }
    else MessagePlugin.error(j.error)
  } catch { MessagePlugin.error("连接失败") }
  addingFunc.value = false
}

async function removeFunc(fname) {
  try {
    const r = await fetch(`/api/translator/scene/${selectedScene.value}/functions`, { method: "PUT", headers: { "Content-Type": "application/json", "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "" }, body: JSON.stringify({ action: "remove", name: fname }) })
    const j = await r.json()
    if (j.ok) { MessagePlugin.success("函数已移除"); selectScene(selectedScene.value) }
    else MessagePlugin.error(j.error)
  } catch { MessagePlugin.error("连接失败") }
}

function editFunc(fname, def) {
  editFuncName.value = fname
  editFuncJson.value = JSON.stringify(def, null, 2)
  showEditFunc.value = true
}

async function saveFunc() {
  savingFunc.value = true
  try {
    const definition = JSON.parse(editFuncJson.value)
    const r = await fetch(`/api/translator/scene/${selectedScene.value}/function/${editFuncName.value}`, { method: "PUT", headers: { "Content-Type": "application/json", "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "" }, body: JSON.stringify({ definition }) })
    const j = await r.json()
    if (j.ok) { MessagePlugin.success("函数定义已保存"); showEditFunc.value = false; selectScene(selectedScene.value) }
    else MessagePlugin.error(j.error)
  } catch (e) { MessagePlugin.error("JSON 格式错误") }
  savingFunc.value = false
}
</script>

<style scoped>
.path-card { background: #fff; border-radius: 12px; padding: 18px 20px; border: 1px solid #eee; margin-bottom: 16px; }
.path-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.path-label { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; color: #333; }
.path-input { display: flex; gap: 8px; margin-bottom: 6px; }
.path-hint { font-size: 11px; color: #999; }
.path-hint code { background: #f0f5ff; padding: 1px 4px; border-radius: 3px; color: #0052D9; }
.path-error { font-size: 12px; color: #ff5252; margin-top: 6px; background: #fff5f5; padding: 6px 10px; border-radius: 6px; }
.path-success { font-size: 12px; color: #00a870; margin-top: 6px; background: #f0fff8; padding: 6px 10px; border-radius: 6px; }
.registry-card { background: #fff; border-radius: 12px; padding: 24px; border: 1px solid #eee; }
.card-title { font-size: 15px; font-weight: 600; margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }
.registry-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.registry-item { background: #f9fafb; border-radius: 8px; padding: 14px; border: 1px solid #eee; cursor: pointer; transition: all 0.2s; }
.registry-item:hover { border-color: #0052D9; background: #f0f5ff; }
.registry-name { font-size: 14px; font-weight: 600; color: #0052D9; margin-bottom: 4px; }
.registry-desc { font-size: 12px; color: #888; margin-bottom: 8px; line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.registry-funcs { display: flex; flex-wrap: wrap; gap: 4px; }
/* Scene Detail */
.scene-detail-card { background: #fff; border-radius: 12px; padding: 24px; border: 1px solid #eee; }
.detail-header { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
.detail-title { font-size: 18px; font-weight: 600; color: #0052D9; }
.detail-section { margin-bottom: 20px; }
.section-label { font-size: 13px; font-weight: 600; color: #333; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
.func-list { display: flex; flex-direction: column; gap: 8px; }
.func-item { display: flex; align-items: center; padding: 10px 14px; background: #f9fafb; border: 1px solid #eee; border-radius: 8px; cursor: pointer; transition: border-color 0.2s; }
.func-item:hover { border-color: #0052D9; }
.func-name { font-size: 13px; font-weight: 600; color: #333; min-width: 200px; font-family: "SF Mono", monospace; }
.func-desc { font-size: 12px; color: #888; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.func-actions { margin-left: 8px; }
.delete-hint { font-size: 11px; color: #999; margin-top: 12px; display: flex; align-items: center; gap: 4px; }
.delete-hint code { background: #f0f5ff; padding: 1px 4px; border-radius: 3px; color: #0052D9; }
.add-func-form .form-row { margin-bottom: 12px; }
.add-func-form label { font-size: 13px; font-weight: 500; color: #666; display: block; margin-bottom: 4px; }
.edit-func .edit-field { margin-bottom: 14px; }
.edit-func label { font-size: 13px; font-weight: 500; color: #666; display: block; margin-bottom: 4px; }
.func-json-editor { width: 100%; border: 1px solid #ddd; border-radius: 8px; padding: 12px; font-family: "SF Mono", monospace; font-size: 12px; line-height: 1.6; resize: vertical; outline: none; }
.func-json-editor:focus { border-color: #0052D9; }
</style>
