<template>
<!-- 策略库注册表页：当前 Policy 切换 / Policy 管理 / 路径模板 / 场景与函数编辑 -->
<!-- 场景概览 → 场景详情（描述 / Functions）两级浏览与编辑 -->
  <div class="registry-tab">
    <RegistryWarning />

    <!-- 当前 Policy（免特权切换） -->
<!-- 当前 Policy 卡（高亮态） -->
    <div class="policy-card policy-card--active">
      <div class="policy-card__head">
<!-- 当前 Policy 卡标题图标 -->
        <div class="policy-card__title"><t-icon name="layers" size="16px" /><span>当前 Policy</span></div>
<!-- 已生效标签 -->
        <t-tag v-if="currentPolicy" theme="success" variant="light" size="small">已生效</t-tag>
      </div>
<!-- 切换行：选择目标 Policy + 切换按钮 -->
      <div class="policy-switch">
<!-- 目标 Policy 下拉 -->
        <t-select v-model="switchTarget" :options="policyOptions" placeholder="选择 Policy" style="flex:1;" />
        <t-button
          theme="primary"
          size="small"
          :disabled="!switchTarget || switchTarget === currentPolicy || switching"
          :loading="switching"
          @click="doSwitchPolicy"
        >切换</t-button>
      </div>
<!-- 当前策略库解析路径回显 -->
      <p class="policy-path">
<!-- 路径前缀图标 -->
        <t-icon name="folder" size="13px" />
<!-- 解析路径（等宽） -->
        <code>{{ resolvedPath || '—' }}</code>
      </p>
<!-- 切换说明：任何登录用户可操作 -->
      <p class="policy-hint">切换无需特权，任何登录用户均可操作；切换后立即热重载，翻译与监控即时使用新策略。</p>
<!-- 切换失败提示 -->
      <div v-if="policyError" class="policy-msg error">{{ policyError }}</div>
<!-- 切换成功提示 -->
      <div v-if="policySuccess" class="policy-msg success">{{ policySuccess }}</div>
    </div>

    <!-- Policy 管理（需特权） -->
    <div class="policy-card">
      <div class="policy-card__head">
<!-- Policy 管理卡头 -->
        <div class="policy-card__title"><t-icon name="setting" size="16px" /><span>Policy 管理</span></div>
<!-- 特权状态组件：管理操作需特权 -->
        <PrivilegeStatus hint="新建/复制/重命名/删除 Policy 需要特权验证" @unlock="showPrivDialog = true" />
      </div>
<!-- 管理操作按钮组 -->
      <div class="policy-manage">
<!-- 新建按钮 -->
        <t-button size="small" variant="outline" :disabled="!adminValid" @click="openCreate">
<!-- 新建按钮图标 -->
          <t-icon name="add" /> 新建
        </t-button>
<!-- 重命名按钮 -->
        <t-button size="small" variant="outline" :disabled="!adminValid" @click="openRename">
<!-- 重命名按钮图标 -->
          <t-icon name="edit" /> 重命名
        </t-button>
<!-- 删除按钮 -->
        <t-button size="small" variant="outline" theme="danger" :disabled="!adminValid" @click="openDelete">
<!-- 删除按钮图标 -->
          <t-icon name="delete" /> 删除
        </t-button>
      </div>
<!-- 新建说明：复制自保证场景集合一致 -->
      <p class="policy-hint">新建时可选择「复制自」某个已有 Policy，保证场景集合一致（当前 Policy 共 {{ currentScenes }} 个场景）。</p>
<!-- 管理失败提示 -->
      <div v-if="manageError" class="policy-msg error">{{ manageError }}</div>
<!-- 管理成功提示 -->
      <div v-if="manageSuccess" class="policy-msg success">{{ manageSuccess }}</div>
    </div>

    <!-- 路径模板（需特权） -->
<!-- 路径模板卡 -->
    <div class="path-card">
<!-- 路径卡头 -->
      <div class="path-header">
<!-- 路径卡标题 -->
        <div class="path-label"><t-icon name="folder" size="16px" style="color: #0052D9;" /><span>路径模板</span></div>
<!-- 路径模板特权组件 -->
        <PrivilegeStatus hint="修改路径模板需要特权验证" @unlock="showPrivDialog = true" />
      </div>
<!-- 模板输入行 -->
      <div class="path-input">
<!-- 路径模板输入：{policy} 占位符 -->
        <t-input v-model="pathTemplate" :disabled="!adminValid" placeholder=".../auditor/translator/policies/{policy}/policy_registry" style="flex:1;" />
<!-- 保存模板按钮 -->
        <t-button theme="primary" size="small" :disabled="!adminValid || !pathTemplate.trim()" @click="saveTemplate" :loading="savingTemplate">保存</t-button>
      </div>
<!-- 模板约束说明：须以 policy_registry 结尾 -->
      <p class="path-hint">用 <code>{policy}</code> 代表不同 Policy 的目录名；路径必须以 <code>policy_registry</code> 结尾，且包含 <code>scenes.json</code> 和 <code>tools/</code></p>
<!-- 模板保存失败提示 -->
      <div v-if="templateError" class="policy-msg error">{{ templateError }}</div>
<!-- 模板保存成功提示 -->
      <div v-if="templateSuccess" class="policy-msg success">{{ templateSuccess }}</div>
    </div>

    <!-- Scene Detail (when a scene is selected) -->
<!-- 场景详情卡（选中场景时替代概览） -->
    <div v-if="selectedScene" class="scene-detail-card">
<!-- 详情头：返回 + 场景名 + 编辑目标 -->
      <div class="detail-header">
<!-- 返回概览按钮 -->
        <t-button variant="text" size="small" @click="selectedScene = null"><t-icon name="chevron-left" /> 返回概览</t-button>
<!-- 场景名标题 -->
        <span class="detail-title">{{ selectedScene }}</span>
<!-- 编辑目标 Policy 标签 -->
        <t-tag v-if="currentPolicy" theme="primary" variant="light" size="small">当前编辑：{{ currentPolicy }}</t-tag>
      </div>

      <!-- Desc -->
      <div class="detail-section">
<!-- 场景描述标签 -->
        <div class="section-label">场景描述</div>
<!-- 场景描述编辑 -->
        <t-textarea v-model="sceneDesc" :disabled="!adminValid" :autosize="{ minRows: 2, maxRows: 4 }" />
<!-- 保存描述按钮 -->
        <t-button size="small" theme="primary" :disabled="!adminValid" @click="saveDesc" :loading="savingDesc" style="margin-top: 8px;">保存描述</t-button>
      </div>

      <!-- Functions -->
      <div class="detail-section">
        <div class="section-label">
          Functions
<!-- Functions 标签行 + 新增按钮 -->
          <t-button size="small" variant="outline" :disabled="!adminValid" @click="showAddFunc = true"><t-icon name="add" /> 新增</t-button>
        </div>
<!-- 函数列表 -->
        <div class="func-list">
<!-- 函数条目：名称 + 描述 + 移除 -->
          <div v-for="(def, fname) in sceneFunctions" :key="fname" class="func-item" @click="editFunc(fname, def)">
<!-- 函数名（等宽） -->
            <div class="func-name">{{ fname }}</div>
<!-- 函数描述 -->
            <div class="func-desc">{{ def.desc || '(无描述)' }}</div>
            <div class="func-actions">
<!-- 移除函数按钮 -->
              <t-button size="small" variant="text" theme="danger" :disabled="!adminValid" @click.stop="removeFunc(fname)">移除</t-button>
            </div>
          </div>
        </div>
<!-- 删除场景的操作提示 -->
        <p class="delete-hint"><t-icon name="info-circle" size="14px" /> 删除整个场景请手动删除 <code>tools/{{ selectedScene }}.json</code> 及 <code>scenes.json</code> 对应元素</p>
      </div>
    </div>

    <!-- Scene Overview (default) -->
<!-- 场景概览卡（默认视图） -->
    <div v-else class="registry-card">
<!-- 概览标题 + 刷新按钮 -->
      <div class="card-title">场景概览 <t-button size="small" variant="outline" @click="loadRegistry">刷新</t-button></div>
<!-- 场景网格 -->
      <div v-if="registry" class="registry-grid">
<!-- 场景卡：点击进入详情 -->
        <div v-for="(scene, name) in registry.scenes" :key="name" class="registry-item" @click="selectScene(name)">
<!-- 场景名 -->
          <div class="registry-name">{{ name }}</div>
<!-- 场景描述（两行截断） -->
          <div class="registry-desc">{{ scene.desc }}</div>
<!-- 场景函数标签组（最多 4 个） -->
          <div class="registry-funcs">
            <t-tag v-for="f in scene.functions?.slice(0, 4)" :key="f" size="small" variant="outline">{{ f }}</t-tag>
<!-- 溢出函数计数标签 -->
            <t-tag v-if="scene.functions?.length > 4" size="small" variant="light">+{{ scene.functions.length - 4 }}</t-tag>
          </div>
        </div>
      </div>
    </div>

    <!-- Policy 管理对话框 -->
<!-- 新建 Policy 对话框 -->
    <t-dialog v-model:visible="showCreate" header="新建 Policy" :confirm-btn="{ content: '创建', theme: 'primary', loading: creating }" @confirm="doCreate">
      <div class="policy-form">
<!-- 名称输入行 -->
        <div class="form-row"><label>Policy 名称</label><t-input v-model="newName" placeholder="如 strict（字母/数字/下划线/中划线）" /></div>
<!-- 复制来源行：留空创建空骨架 -->
        <div class="form-row"><label>复制自（可选）</label>
          <t-select v-model="copyFrom" :options="policyOptions" placeholder="留空则创建空骨架" clearable />
        </div>
      </div>
    </t-dialog>

<!-- 重命名对话框 -->
    <t-dialog v-model:visible="showRename" header="重命名 Policy" :confirm-btn="{ content: '保存', theme: 'primary', loading: renaming }" @confirm="doRename">
      <div class="policy-form">
<!-- 原名选择行 -->
        <div class="form-row"><label>原 Policy</label><t-select v-model="renameOld" :options="policyOptions" placeholder="选择要重命名的 Policy" /></div>
<!-- 新名输入行 -->
        <div class="form-row"><label>新名称</label><t-input v-model="renameNew" placeholder="新名称" /></div>
      </div>
    </t-dialog>

    <t-dialog
      v-model:visible="showDelete"
      header="删除 Policy"
      :confirm-btn="{ content: '确认删除', theme: 'danger', loading: deleting }"
      @confirm="doDelete"
    >
<!-- 删除警示文案 -->
      <p class="policy-delete-tip">确定要删除 Policy「{{ deleteTarget }}」吗？该操作会删除其策略库目录及全部场景文件，且不可恢复。</p>
<!-- 将删除的目录路径 -->
      <p class="policy-delete-path"><code>{{ deletePathPreview }}</code></p>
<!-- 使用中的 Policy 不可删除说明 -->
      <p class="policy-delete-note">当前正在使用的 Policy 不可删除，请先切换到其他 Policy。</p>
<!-- 可删除下拉（排除当前） -->
      <t-select v-model="deleteTarget" :options="deletableOptions" placeholder="选择要删除的 Policy" style="margin-top: 12px;" />
    </t-dialog>

    <!-- Add Function Dialog -->
<!-- 新增 Function 对话框 -->
    <t-dialog v-model:visible="showAddFunc" header="新增 Function" :confirm-btn="{ content: '添加', theme: 'primary', loading: addingFunc }" @confirm="doAddFunc">
      <div class="add-func-form">
        <div class="form-row"><label>函数名</label><t-input v-model="newFuncName" placeholder="如 safe_file_reader__read_text" /></div>
<!-- 函数描述输入行 -->
        <div class="form-row"><label>描述</label><t-input v-model="newFuncDesc" placeholder="函数描述" /></div>
      </div>
    </t-dialog>

    <!-- Edit Function Dialog -->
<!-- 编辑 Function 抽屉 -->
    <t-drawer v-model:visible="showEditFunc" header="编辑 Function" size="520px" :footer="false">
      <div v-if="editFuncName" class="edit-func">
<!-- 函数名（只读） -->
        <div class="edit-field"><label>函数名</label><t-input :value="editFuncName" disabled /></div>
<!-- 函数定义 JSON 编辑区 -->
        <div class="edit-field"><label>定义 (JSON)</label>
<!-- 定义编辑文本域 -->
          <textarea v-model="editFuncJson" class="func-json-editor" rows="15" :disabled="!adminValid"></textarea>
        </div>
<!-- 保存定义按钮 -->
        <t-button theme="primary" :disabled="!adminValid" @click="saveFunc" :loading="savingFunc">保存</t-button>
      </div>
    </t-drawer>

<!-- 特权验证对话框 -->
    <PrivilegeDialog v-model="showPrivDialog" @success="() => {}" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from "vue"
import { MessagePlugin } from "tdesign-vue-next"
import PrivilegeDialog from "../../components/PrivilegeDialog.vue"
import PrivilegeStatus from "../../components/PrivilegeStatus.vue"
import RegistryWarning from "../../components/RegistryWarning.vue"

// 特权对话框可见性
const showPrivDialog = ref(false)
// 注册表数据：scenes / functions
const registry = ref(null)

// 多 Policy 状态
const policies = ref([])
const currentPolicy = ref("")
// 切换目标 Policy
const switchTarget = ref("")
// 当前策略库解析路径
const resolvedPath = ref("")
// 路径模板（{policy} 占位）
const pathTemplate = ref("")
// 切换中标志
const switching = ref(false)
const savingTemplate = ref(false)
// 切换失败信息
const policyError = ref("")
// 切换成功信息
const policySuccess = ref("")
// 模板保存失败信息
const templateError = ref("")
const templateSuccess = ref("")
// 管理操作失败信息
const manageError = ref("")
const manageSuccess = ref("")

// Policy 管理对话框
// 新建对话框状态 + 名称/来源
const showCreate = ref(false)
// 新建表单：名称/复制来源
const newName = ref("")
// 复制来源（留空创建空骨架）
const copyFrom = ref("")
// 新建进行中标志
const creating = ref(false)
// 重命名对话框状态 + 原名/新名
const showRename = ref(false)
// 重命名表单：原名/新名
const renameOld = ref("")
// 新名称输入
const renameNew = ref("")
// 重命名进行中标志
const renaming = ref(false)
// 删除对话框状态 + 目标
const showDelete = ref(false)
// 删除目标
const deleteTarget = ref("")
// 删除进行中标志
const deleting = ref(false)

// Policy 下拉选项：名称+场景数，不健康的禁用
const policyOptions = computed(() =>
  policies.value.map((p) => ({ label: `${p.name}（${p.scenes} 场景）`, value: p.name, disabled: !p.healthy }))
)
// 可删除选项：排除当前生效 Policy
const deletableOptions = computed(() => policyOptions.value.filter((o) => o.value !== currentPolicy.value))
// 当前 Policy 的场景数
const currentScenes = computed(() => (policies.value.find((p) => p.name === currentPolicy.value) || {}).scenes || 0)
// 删除目标路径预览
const deletePathPreview = computed(() => (policies.value.find((p) => p.name === deleteTarget.value) || {}).path || "—")
// 特权会话过期倒计时驱动：每秒自增触发 computed
const tick = ref(0)
let _t = null
// 特权有效性：会话存在且未过期
const adminValid = computed(() => { void tick.value; return !!sessionStorage.getItem("clawavc_admin_session") && Date.now() < Number(sessionStorage.getItem("clawavc_admin_expiry") || 0) })

// Scene detail
// 场景详情状态：名称/描述/函数
const selectedScene = ref(null)
// 场景描述编辑态
const sceneDesc = ref("")
// 场景函数定义集
const sceneFunctions = ref({})
// 描述保存中标志
const savingDesc = ref(false)

// Add function
// 新增函数对话框状态
const showAddFunc = ref(false)
// 新增函数：名称/描述
const newFuncName = ref("")
// 新增函数描述
const newFuncDesc = ref("")
// 新增函数进行中标志
const addingFunc = ref(false)

// Edit function
// 编辑函数抽屉状态 + JSON 文本
const showEditFunc = ref(false)
// 编辑中的函数名
const editFuncName = ref("")
// 函数定义 JSON 文本
const editFuncJson = ref("")
// 定义保存中标志
const savingFunc = ref(false)

// 挂载：启动过期检查定时器并加载 Policy/注册表
onMounted(() => { _t = setInterval(() => tick.value++, 1000); loadPolicies(); loadRegistry() })
// 卸载：清理定时器
onUnmounted(() => clearInterval(_t))

// 管理员请求头（特权接口）
const ADMIN_HEAD = () => ({ "Content-Type": "application/json", "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "" })

// Policy 列表加载：含当前/路径/模板
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
// 切换 Policy：成功后热重载并刷新注册表
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
// 保存路径模板：需特权，保存后重新解析
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

// 新建 Policy：可复制已有保证场景一致
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

// 重命名 Policy：必要时同步切换
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

// 删除 Policy：目录与场景文件一并删除
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

// 注册表加载：场景与函数定义
async function loadRegistry() { try { const r = await fetch("/api/translator/registry"); const j = await r.json(); if (j.ok) registry.value = j.data } catch {} }

// 进入场景详情：加载描述与函数
async function selectScene(name) {
  selectedScene.value = name
  try {
    const r = await fetch(`/api/translator/scene/${name}`)
    const j = await r.json()
    if (j.ok) { sceneDesc.value = j.data.desc; sceneFunctions.value = j.data.functions_detail }
  } catch {}
}

// 保存场景描述
async function saveDesc() {
  savingDesc.value = true
  try {
    const r = await fetch(`/api/translator/scene/${selectedScene.value}/desc`, { method: "PUT", headers: { "Content-Type": "application/json", "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "" }, body: JSON.stringify({ desc: sceneDesc.value }) })
    const j = await r.json()
    if (j.ok) MessagePlugin.success("描述已保存"); else MessagePlugin.error(j.error)
  } catch { MessagePlugin.error("连接失败") }
  savingDesc.value = false
}

// 新增函数：写入注册表
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

// 移除函数：从注册表删除
async function removeFunc(fname) {
  try {
    const r = await fetch(`/api/translator/scene/${selectedScene.value}/functions`, { method: "PUT", headers: { "Content-Type": "application/json", "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "" }, body: JSON.stringify({ action: "remove", name: fname }) })
    const j = await r.json()
    if (j.ok) { MessagePlugin.success("函数已移除"); selectScene(selectedScene.value) }
    else MessagePlugin.error(j.error)
  } catch { MessagePlugin.error("连接失败") }
}

// 打开函数编辑抽屉：定义转 JSON 文本
function editFunc(fname, def) {
  editFuncName.value = fname
  editFuncJson.value = JSON.stringify(def, null, 2)
  showEditFunc.value = true
}

// 保存函数定义：JSON 校验后写入
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
/* Policy 卡 hover 抬升 */
.policy-card:hover { box-shadow: 0 4px 16px rgba(0, 82, 217, 0.08); border-color: #d6e4ff; }
/* 当前 Policy 卡高亮 */
.policy-card--active { border-color: #c7dbff; background: linear-gradient(180deg, #fbfdff 0%, #fff 100%); }
/* 卡头布局 */
.policy-card__head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
/* 卡标题样式 */
.policy-card__title { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; color: #333; }
.policy-card__title .t-icon { color: #0052D9; font-size: 18px; }
/* 切换行布局 */
.policy-switch { display: flex; gap: 8px; }
/* 解析路径行 */
.policy-path { display: flex; align-items: center; gap: 6px; margin: 10px 0 4px; font-size: 11px; color: #888; }
/* 路径代码块样式 */
.policy-path code { background: #f0f5ff; color: #0052D9; padding: 2px 6px; border-radius: 4px; font-family: "SF Mono", monospace; word-break: break-all; }
/* 说明小字 */
.policy-hint { font-size: 11px; color: #999; margin: 8px 0 0; line-height: 1.6; }
/* 管理按钮组布局 */
.policy-manage { display: flex; gap: 8px; flex-wrap: wrap; }
/* 提示条基类 */
.policy-msg { font-size: 12px; margin-top: 8px; padding: 6px 10px; border-radius: 6px; }
/* 失败提示红色 */
.policy-msg.error { color: #ff5252; background: #fff5f5; }
/* 成功提示绿色 */
.policy-msg.success { color: #00a870; background: #f0fff8; }
/* 对话框表单行 */
.policy-form .form-row { margin-bottom: 12px; }
/* 表单标签样式 */
.policy-form label { display: block; font-size: 13px; font-weight: 500; color: #666; margin-bottom: 6px; }
/* 删除警示样式 */
.policy-delete-tip { font-size: 13px; color: #333; margin: 0 0 8px; }
.policy-delete-path { margin: 0 0 8px; }
/* 删除路径代码块 */
.policy-delete-path code { background: #fff5f5; color: #ff5252; padding: 2px 6px; border-radius: 4px; font-size: 11px; word-break: break-all; }
/* 删除说明小字 */
.policy-delete-note { font-size: 11px; color: #999; margin: 0; }

/* 路径模板卡容器 */
.path-card { background: #fff; border-radius: 12px; padding: 18px 20px; border: 1px solid #eee; margin-bottom: 16px; }
/* 路径卡头布局 */
.path-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
/* 路径卡标题样式 */
.path-label { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; color: #333; }
/* 模板输入行 */
.path-input { display: flex; gap: 8px; margin-bottom: 6px; }
/* 模板约束说明 */
.path-hint { font-size: 11px; color: #999; }
.path-hint code { background: #f0f5ff; padding: 1px 4px; border-radius: 3px; color: #0052D9; }
/* 路径错误提示 */
.path-error { font-size: 12px; color: #ff5252; margin-top: 6px; background: #fff5f5; padding: 6px 10px; border-radius: 6px; }
/* 路径成功提示 */
.path-success { font-size: 12px; color: #00a870; margin-top: 6px; background: #f0fff8; padding: 6px 10px; border-radius: 6px; }
.registry-card { background: #fff; border-radius: 12px; padding: 24px; border: 1px solid #eee; }
/* 概览卡标题样式 */
.card-title { font-size: 15px; font-weight: 600; margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }
/* 场景网格：两列 */
.registry-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
/* 场景卡容器 */
.registry-item { background: #f9fafb; border-radius: 8px; padding: 14px; border: 1px solid #eee; cursor: pointer; transition: all 0.2s; }
/* 场景卡 hover */
.registry-item:hover { border-color: #0052D9; background: #f0f5ff; }
/* 场景名样式 */
.registry-name { font-size: 14px; font-weight: 600; color: #0052D9; margin-bottom: 4px; }
/* 场景描述：两行截断 */
.registry-desc { font-size: 12px; color: #888; margin-bottom: 8px; line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
/* 函数标签组布局 */
.registry-funcs { display: flex; flex-wrap: wrap; gap: 4px; }
/* Scene Detail */
.scene-detail-card { background: #fff; border-radius: 12px; padding: 24px; border: 1px solid #eee; }
/* 详情头布局 */
.detail-header { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
/* 场景名标题样式 */
.detail-title { font-size: 18px; font-weight: 600; color: #0052D9; }
/* 详情分区间距 */
.detail-section { margin-bottom: 20px; }
/* 分区标签样式 */
.section-label { font-size: 13px; font-weight: 600; color: #333; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
/* 函数列表纵排 */
.func-list { display: flex; flex-direction: column; gap: 8px; }
/* 函数条目布局 */
.func-item { display: flex; align-items: center; padding: 10px 14px; background: #f9fafb; border: 1px solid #eee; border-radius: 8px; cursor: pointer; transition: border-color 0.2s; }
.func-item:hover { border-color: #0052D9; }
/* 函数名等宽样式 */
.func-name { font-size: 13px; font-weight: 600; color: #333; min-width: 200px; font-family: "SF Mono", monospace; }
/* 函数描述单行省略 */
.func-desc { font-size: 12px; color: #888; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* 函数操作列 */
.func-actions { margin-left: 8px; }
/* 删除提示小字 */
.delete-hint { font-size: 11px; color: #999; margin-top: 12px; display: flex; align-items: center; gap: 4px; }
.delete-hint code { background: #f0f5ff; padding: 1px 4px; border-radius: 3px; color: #0052D9; }
/* 新增函数表单行 */
.add-func-form .form-row { margin-bottom: 12px; }
.add-func-form label { font-size: 13px; font-weight: 500; color: #666; display: block; margin-bottom: 4px; }
/* 编辑字段间距 */
.edit-func .edit-field { margin-bottom: 14px; }
.edit-func label { font-size: 13px; font-weight: 500; color: #666; display: block; margin-bottom: 4px; }
/* 定义 JSON 编辑器样式 */
.func-json-editor { width: 100%; border: 1px solid #ddd; border-radius: 8px; padding: 12px; font-family: "SF Mono", monospace; font-size: 12px; line-height: 1.6; resize: vertical; outline: none; }
/* 编辑器聚焦态 */
.func-json-editor:focus { border-color: #0052D9; }
</style>
