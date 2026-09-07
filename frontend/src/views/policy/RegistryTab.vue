<template>
  <div class="registry-tab">
    <RegistryWarning />

    <!-- 当前 Policy（免特权切换） -->
    <div class="policy-card policy-card--active">
      <div class="policy-card__head">
        <div class="policy-card__title"><t-icon name="layers" size="16px" /><span>当前 Policy</span></div>
        <t-tag v-if="currentPolicy" theme="success" variant="light" size="small">已生效</t-tag>
      </div>
      <div class="policy-switch">
        <t-select v-model="switchTarget" :options="policyOptions" placeholder="选择 Policy" style="flex:1;" />
        <t-button
          theme="primary"
          size="small"
          :disabled="!switchTarget || switchTarget === currentPolicy || switching"
          :loading="switching"
          @click="doSwitchPolicy"
        >切换</t-button>
      </div>
      <p class="policy-path">
        <t-icon name="folder" size="13px" />
        <code>{{ resolvedPath || '—' }}</code>
      </p>
      <p class="policy-hint">切换无需特权，任何登录用户均可操作；切换后立即热重载，翻译与监控即时使用新策略。</p>
      <div v-if="policyError" class="policy-msg error">{{ policyError }}</div>
      <div v-if="policySuccess" class="policy-msg success">{{ policySuccess }}</div>
    </div>

    <!-- Policy 管理（需特权） -->
    <div class="policy-card">
      <div class="policy-card__head">
        <div class="policy-card__title"><t-icon name="setting" size="16px" /><span>Policy 管理</span></div>
        <PrivilegeStatus hint="新建/复制/重命名/删除 Policy 需要特权验证" @unlock="showPrivDialog = true" />
      </div>
      <div class="policy-manage">
        <t-button size="small" variant="outline" :disabled="!adminValid" @click="openCreate">
          <t-icon name="add" /> 新建
        </t-button>
        <t-button size="small" variant="outline" :disabled="!adminValid" @click="openRename">
          <t-icon name="edit" /> 重命名
        </t-button>
        <t-button size="small" variant="outline" theme="danger" :disabled="!adminValid" @click="openDelete">
          <t-icon name="delete" /> 删除
        </t-button>
      </div>
      <p class="policy-hint">新建时可选择「复制自」某个已有 Policy，保证场景集合一致（当前 Policy 共 {{ currentScenes }} 个场景）。</p>
      <div v-if="manageError" class="policy-msg error">{{ manageError }}</div>
      <div v-if="manageSuccess" class="policy-msg success">{{ manageSuccess }}</div>
    </div>

    <!-- 路径模板（需特权） -->
    <div class="path-card">
      <div class="path-header">
        <div class="path-label"><t-icon name="folder" size="16px" style="color: #0052D9;" /><span>路径模板</span></div>
        <PrivilegeStatus hint="修改路径模板需要特权验证" @unlock="showPrivDialog = true" />
      </div>
      <div class="path-input">
        <t-input v-model="pathTemplate" :disabled="!adminValid" placeholder=".../auditor/translator/policies/{policy}/policy_registry" style="flex:1;" />
        <t-button theme="primary" size="small" :disabled="!adminValid || !pathTemplate.trim()" @click="saveTemplate" :loading="savingTemplate">保存</t-button>
      </div>
      <p class="path-hint">用 <code>{policy}</code> 代表不同 Policy 的目录名；路径必须以 <code>policy_registry</code> 结尾，且包含 <code>scenes.json</code> 和 <code>tools/</code></p>
      <div v-if="templateError" class="policy-msg error">{{ templateError }}</div>
      <div v-if="templateSuccess" class="policy-msg success">{{ templateSuccess }}</div>
    </div>

    <!-- Scene Detail (when a scene is selected) -->
    <div v-if="selectedScene" class="scene-detail-card">
      <div class="detail-header">
        <t-button variant="text" size="small" @click="selectedScene = null"><t-icon name="chevron-left" /> 返回概览</t-button>
        <span class="detail-title">{{ selectedScene }}</span>
        <t-tag v-if="currentPolicy" theme="primary" variant="light" size="small">当前编辑：{{ currentPolicy }}</t-tag>
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

    <!-- Policy 管理对话框 -->
    <t-dialog v-model:visible="showCreate" header="新建 Policy" :confirm-btn="{ content: '创建', theme: 'primary', loading: creating }" @confirm="doCreate">
      <div class="policy-form">
        <div class="form-row"><label>Policy 名称</label><t-input v-model="newName" placeholder="如 strict（字母/数字/下划线/中划线）" /></div>
        <div class="form-row"><label>复制自（可选）</label>
          <t-select v-model="copyFrom" :options="policyOptions" placeholder="留空则创建空骨架" clearable />
        </div>
      </div>
    </t-dialog>

    <t-dialog v-model:visible="showRename" header="重命名 Policy" :confirm-btn="{ content: '保存', theme: 'primary', loading: renaming }" @confirm="doRename">
      <div class="policy-form">
        <div class="form-row"><label>原 Policy</label><t-select v-model="renameOld" :options="policyOptions" placeholder="选择要重命名的 Policy" /></div>
        <div class="form-row"><label>新名称</label><t-input v-model="renameNew" placeholder="新名称" /></div>
      </div>
    </t-dialog>

    <t-dialog
      v-model:visible="showDelete"
      header="删除 Policy"
      :confirm-btn="{ content: '确认删除', theme: 'danger', loading: deleting }"
      @confirm="doDelete"
    >
      <p class="policy-delete-tip">确定要删除 Policy「{{ deleteTarget }}」吗？该操作会删除其策略库目录及全部场景文件，且不可恢复。</p>
      <p class="policy-delete-path"><code>{{ deletePathPreview }}</code></p>
      <p class="policy-delete-note">当前正在使用的 Policy 不可删除，请先切换到其他 Policy。</p>
      <t-select v-model="deleteTarget" :options="deletableOptions" placeholder="选择要删除的 Policy" style="margin-top: 12px;" />
    </t-dialog>

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
const registry = ref(null)

// 多 Policy 状态
const policies = ref([])
const currentPolicy = ref("")
const switchTarget = ref("")
const resolvedPath = ref("")
const pathTemplate = ref("")
const switching = ref(false)
const savingTemplate = ref(false)
const policyError = ref("")
const policySuccess = ref("")
const templateError = ref("")
const templateSuccess = ref("")
const manageError = ref("")
const manageSuccess = ref("")

// Policy 管理对话框
const showCreate = ref(false)
const newName = ref("")
const copyFrom = ref("")
const creating = ref(false)
const showRename = ref(false)
const renameOld = ref("")
const renameNew = ref("")
const renaming = ref(false)
const showDelete = ref(false)
const deleteTarget = ref("")
const deleting = ref(false)

const policyOptions = computed(() =>
  policies.value.map((p) => ({ label: `${p.name}（${p.scenes} 场景）`, value: p.name, disabled: !p.healthy }))
)
const deletableOptions = computed(() => policyOptions.value.filter((o) => o.value !== currentPolicy.value))
const currentScenes = computed(() => (policies.value.find((p) => p.name === currentPolicy.value) || {}).scenes || 0)
const deletePathPreview = computed(() => (policies.value.find((p) => p.name === deleteTarget.value) || {}).path || "—")
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

onMounted(() => { _t = setInterval(() => tick.value++, 1000); loadPolicies(); loadRegistry() })
onUnmounted(() => clearInterval(_t))

const ADMIN_HEAD = () => ({ "Content-Type": "application/json", "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "" })

async function loadPolicies() {
  try {
    const r = await fetch("/api/translator/policies")
    const j = await r.json()
    if (j.ok) {
      policies.value = j.data.policies || []
      currentPolicy.value = j.data.current || ""
      resolvedPath.value = j.data.resolved_path || ""
      pathTemplate.value = j.data.template || ""
      if (!switchTarget.value) switchTarget.value = currentPolicy.value
    }
  } catch {}
}

// 切换当前 Policy（免特权）
async function doSwitchPolicy() {
  if (!switchTarget.value || switchTarget.value === currentPolicy.value) return
  switching.value = true; policyError.value = ""; policySuccess.value = ""
  try {
    const r = await fetch("/api/translator/policies/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: switchTarget.value }),
    })
    const j = await r.json()
    if (j.ok) {
      currentPolicy.value = j.data.current
      resolvedPath.value = j.data.path
      policySuccess.value = `已切换到 Policy「${j.data.current}」，策略库已重新加载`
      MessagePlugin.success(policySuccess.value)
      loadRegistry()
    } else policyError.value = j.error
  } catch { policyError.value = "连接失败" }
  switching.value = false
}

// 保存路径模板（需特权）
async function saveTemplate() {
  savingTemplate.value = true; templateError.value = ""; templateSuccess.value = ""
  try {
    const r = await fetch("/api/translator/policy-path-template", {
      method: "PUT",
      headers: ADMIN_HEAD(),
      body: JSON.stringify({ template: pathTemplate.value.trim() }),
    })
    const j = await r.json()
    if (j.ok) {
      templateSuccess.value = j.data.applied ? "模板已保存，策略库已重新加载" : "模板已保存，但当前解析路径无效，请检查目录"
      loadPolicies(); loadRegistry()
    } else templateError.value = j.error
  } catch { templateError.value = "连接失败" }
  savingTemplate.value = false
}

// ─── Policy 管理：新建 / 重命名 / 删除（均需特权） ───
function openCreate() { newName.value = ""; copyFrom.value = ""; manageError.value = ""; manageSuccess.value = ""; showCreate.value = true }

async function doCreate() {
  if (!newName.value.trim()) return
  creating.value = true
  try {
    const r = await fetch("/api/translator/policies/create", {
      method: "POST",
      headers: ADMIN_HEAD(),
      body: JSON.stringify({ name: newName.value.trim(), from: copyFrom.value || "" }),
    })
    const j = await r.json()
    if (j.ok) { MessagePlugin.success("Policy 已创建"); showCreate.value = false; loadPolicies() }
    else MessagePlugin.error(j.error)
  } catch { MessagePlugin.error("连接失败") }
  creating.value = false
}

function openRename() { renameOld.value = currentPolicy.value || ""; renameNew.value = ""; manageError.value = ""; manageSuccess.value = ""; showRename.value = true }

async function doRename() {
  if (!renameOld.value || !renameNew.value.trim()) return
  renaming.value = true
  try {
    const r = await fetch("/api/translator/policies/rename", {
      method: "PUT",
      headers: ADMIN_HEAD(),
      body: JSON.stringify({ old: renameOld.value, new: renameNew.value.trim() }),
    })
    const j = await r.json()
    if (j.ok) {
      MessagePlugin.success(j.data.switched ? "已重命名并同步切换" : "已重命名")
      showRename.value = false
      loadPolicies(); loadRegistry()
    } else MessagePlugin.error(j.error)
  } catch { MessagePlugin.error("连接失败") }
  renaming.value = false
}

function openDelete() { deleteTarget.value = deletableOptions.value[0]?.value || ""; manageError.value = ""; manageSuccess.value = ""; showDelete.value = true }

async function doDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    const r = await fetch(`/api/translator/policies/${encodeURIComponent(deleteTarget.value)}`, { method: "DELETE", headers: ADMIN_HEAD() })
    const j = await r.json()
    if (j.ok) { MessagePlugin.success("Policy 已删除"); showDelete.value = false; loadPolicies() }
    else MessagePlugin.error(j.error)
  } catch { MessagePlugin.error("连接失败") }
  deleting.value = false
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
/* 多 Policy 卡片 */
.policy-card {
  background: #fff;
  border-radius: 12px;
  padding: 18px 20px;
  border: 1px solid #eee;
  margin-bottom: 16px;
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
}
.policy-card:hover { box-shadow: 0 4px 16px rgba(0, 82, 217, 0.08); border-color: #d6e4ff; }
.policy-card--active { border-color: #c7dbff; background: linear-gradient(180deg, #fbfdff 0%, #fff 100%); }
.policy-card__head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.policy-card__title { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; color: #333; }
.policy-card__title .t-icon { color: #0052D9; font-size: 18px; }
.policy-switch { display: flex; gap: 8px; }
.policy-path { display: flex; align-items: center; gap: 6px; margin: 10px 0 4px; font-size: 11px; color: #888; }
.policy-path code { background: #f0f5ff; color: #0052D9; padding: 2px 6px; border-radius: 4px; font-family: "SF Mono", monospace; word-break: break-all; }
.policy-hint { font-size: 11px; color: #999; margin: 8px 0 0; line-height: 1.6; }
.policy-manage { display: flex; gap: 8px; flex-wrap: wrap; }
.policy-msg { font-size: 12px; margin-top: 8px; padding: 6px 10px; border-radius: 6px; }
.policy-msg.error { color: #ff5252; background: #fff5f5; }
.policy-msg.success { color: #00a870; background: #f0fff8; }
.policy-form .form-row { margin-bottom: 12px; }
.policy-form label { display: block; font-size: 13px; font-weight: 500; color: #666; margin-bottom: 6px; }
.policy-delete-tip { font-size: 13px; color: #333; margin: 0 0 8px; }
.policy-delete-path { margin: 0 0 8px; }
.policy-delete-path code { background: #fff5f5; color: #ff5252; padding: 2px 6px; border-radius: 4px; font-size: 11px; word-break: break-all; }
.policy-delete-note { font-size: 11px; color: #999; margin: 0; }

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
