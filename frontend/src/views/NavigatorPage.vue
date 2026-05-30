<template>
  <div class="navigator-page">
    <div class="page-top">
      <h2>快捷导航</h2>
      <t-button variant="text" theme="default" @click="openConfig">
        <t-icon name="setting" size="18px" />
      </t-button>
    </div>

    <div v-if="items.length === 0" class="empty-state">
      <t-icon name="link" size="56px" style="color: #ccc;" />
      <p>暂无导航配置</p>
      <p class="sub">点击右上角设置按钮配置导航项</p>
    </div>

    <div v-else class="nav-grid">
      <a v-for="(item, i) in items" :key="i" :href="item.url" target="_blank" rel="noopener" class="nav-card">
        <div class="card-icon">{{ getInitial(item.title) }}</div>
        <div class="card-body">
          <div class="card-title">{{ item.title }}</div>
          <div class="card-url">{{ item.url }}</div>
        </div>
        <t-icon name="jump" size="16px" class="card-arrow" />
      </a>
    </div>

    <!-- Config Dialog -->
    <t-dialog v-model:visible="showConfig" header="导航配置" :footer="false" width="600px">
      <p class="config-hint">配置 JSON 数组，每项包含 url 和 title 字段。</p>
      <t-textarea v-model="configText" :autosize="{ minRows: 8, maxRows: 20 }" :readonly="!privileged" :class="{ locked: !privileged }" placeholder='[{"url": "http://...", "title": "名称"}]' />
      <div class="config-actions">
        <template v-if="privileged">
          <t-button theme="primary" @click="saveConfig" :loading="saving">保存</t-button>
          <t-button variant="outline" @click="showConfig = false">取消</t-button>
        </template>
        <template v-else>
          <PrivilegeDialog v-model:visible="showPrivilege" @verified="onVerified" />
          <t-button theme="warning" @click="showPrivilege = true">特权验证后编辑</t-button>
          <t-button variant="outline" @click="showConfig = false">关闭</t-button>
        </template>
      </div>
    </t-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue"
import { MessagePlugin } from "tdesign-vue-next"
import PrivilegeDialog from "../components/PrivilegeDialog.vue"

const items = ref([])
const showConfig = ref(false)
const showPrivilege = ref(false)
const configText = ref("[]")
const saving = ref(false)

const privileged = ref(!!sessionStorage.getItem("clawavc_admin_session"))

onMounted(() => { loadConfig() })

function openConfig() {
  privileged.value = !!sessionStorage.getItem("clawavc_admin_session")
  showConfig.value = true
}

function onVerified() {
  privileged.value = true
  showPrivilege.value = false
}

async function loadConfig() {
  try {
    const r = await fetch("/api/config/navigator")
    const j = await r.json()
    if (j.ok && j.data) {
      try {
        items.value = JSON.parse(j.data)
        configText.value = JSON.stringify(items.value, null, 2)
      } catch { items.value = [] }
    }
  } catch {}
}

async function saveConfig() {
  saving.value = true
  try {
    const parsed = JSON.parse(configText.value)
    if (!Array.isArray(parsed)) { MessagePlugin.error("必须是 JSON 数组"); saving.value = false; return }
    const r = await fetch("/api/config/navigator", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "" },
      body: JSON.stringify({ value: configText.value })
    })
    const j = await r.json()
    if (j.ok) {
      items.value = parsed
      showConfig.value = false
      MessagePlugin.success("已保存")
    } else { MessagePlugin.error(j.error || "保存失败") }
  } catch (e) { MessagePlugin.error("JSON 格式错误: " + e.message) }
  saving.value = false
}

function getInitial(title) {
  if (!title) return "?"
  return title.charAt(0).toUpperCase()
}
</script>

<style scoped>
.navigator-page { max-width: 900px; margin: 0 auto; padding: 0 16px; }
.page-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }
.page-top h2 { font-size: 20px; font-weight: 600; color: #333; }
.empty-state { text-align: center; padding: 80px 0; color: #999; }
.empty-state .sub { font-size: 12px; color: #ccc; margin-top: 4px; }
.nav-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.nav-card { display: flex; align-items: center; gap: 14px; background: #fff; border: 1px solid #e8ecf0; border-radius: 12px; padding: 18px 20px; text-decoration: none; transition: all 0.2s; cursor: pointer; }
.nav-card:hover { box-shadow: 0 4px 16px rgba(0,82,217,0.1); border-color: #c8dcff; transform: translateY(-2px); }
.card-icon { width: 42px; height: 42px; border-radius: 10px; background: linear-gradient(135deg, #0052D9, #4f8ff7); display: flex; align-items: center; justify-content: center; font-size: 18px; font-weight: 700; color: #fff; flex-shrink: 0; }
.card-body { flex: 1; min-width: 0; }
.card-title { font-size: 15px; font-weight: 600; color: #333; margin-bottom: 4px; }
.card-url { font-size: 11px; color: #999; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-arrow { color: #ccc; flex-shrink: 0; }
.nav-card:hover .card-arrow { color: #0052D9; }
.config-hint { font-size: 12px; color: #999; margin-bottom: 12px; }
.config-actions { margin-top: 16px; display: flex; gap: 10px; justify-content: flex-end; }
.locked :deep(textarea) { background: #f5f7fa !important; color: #999 !important; cursor: not-allowed !important; }
</style>
