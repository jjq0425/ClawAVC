<template>
  <div class="db-page">
    <h2>数据运维</h2>

    <!-- Admin Session Bar -->
    <div style="margin-bottom: 16px;">
      <PrivilegeStatus hint="新增/修改/删除需特权验证" @unlock="showPrivDialog = true" />
    </div>

    <PrivilegeDialog v-model="showPrivDialog" @success="onPrivSuccess" />

    <!-- Tables Overview -->
    <div class="tables-card">
      <div class="card-title">数据表</div>
      <div class="tables-grid">
        <div v-for="t in visibleTables" :key="t.name" class="table-chip" :class="{ active: selectedTable === t.name }" @click="selectTable(t.name)">
          <span class="table-name">{{ t.name }}</span>
          <span class="table-count">{{ t.count }}</span>
        </div>
        <t-popup trigger="click" placement="bottom">
          <template #content>
            <div class="hidden-tables-pop">
              <div v-for="t in hiddenTables" :key="t.name" class="table-chip hidden-chip" :class="{ active: selectedTable === t.name }" @click="selectHiddenTable(t.name)">
                <t-icon name="lock-on" size="14px" style="color: #ED7B2F;" />
                <span class="table-name">{{ t.name }}</span>
                <span class="table-count">{{ t.count }}</span>
              </div>
            </div>
          </template>
          <t-button variant="text" size="small" class="more-btn">
            <t-icon name="ellipsis" size="16px" />
          </t-button>
        </t-popup>
      </div>

      <!-- Warning for sensitive tables -->
      <div v-if="isSensitiveTable" class="sensitive-warn">
        <t-icon name="error-circle-filled" size="16px" />
        <span>当前为系统核心表，误操作可能导致平台运行异常，请谨慎修改！</span>
      </div>
    </div>

    <!-- Visual Table Editor -->
    <div v-if="tableData.columns.length" class="editor-card">
      <div class="card-title">
        <span>{{ selectedTable }}</span>
        <div class="editor-actions">
          <t-button size="small" variant="outline" @click="addRow" :disabled="!canWrite">
            <t-icon name="add" /> 新增行
          </t-button>
          <t-button size="small" variant="outline" @click="openDetail" :disabled="!selectedRows.length">
            <t-icon name="browse" /> 查看详情
          </t-button>
          <t-button size="small" theme="danger" variant="outline" @click="markDeleteSelected" :disabled="!canWrite || !hasSelectableForDelete">
            <t-icon name="delete" /> 删除选中
          </t-button>
          <t-button size="small" theme="primary" @click="executeChanges" :disabled="!pendingChanges.length" :loading="executing">
            <t-icon name="play-circle" /> 执行变更 ({{ pendingChanges.length }})
          </t-button>
        </div>
      </div>

      <!-- Editable Table -->
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th class="col-check"><input type="checkbox" @change="toggleAll" :checked="allSelected" /></th>
              <th v-for="col in tableData.columns" :key="col" class="col-header">{{ col }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, ri) in editableRows" :key="ri" :class="{ modified: row._modified, 'is-new': row._new, deleted: row._deleted }">
              <td class="col-check">
                <input type="checkbox" v-model="row._selected" :disabled="row._new" />
              </td>
              <td v-for="col in tableData.columns" :key="col" class="col-cell" @dblclick="startEdit(ri, col)">
                <input
                  v-if="editingCell.row === ri && editingCell.col === col"
                  v-model="row[col]"
                  class="cell-input"
                  @blur="finishEdit(ri, col)"
                  @keydown.enter="finishEdit(ri, col)"
                  @keydown.escape="cancelEdit(ri, col)"
                  autofocus
                />
                <span v-else class="cell-display" :class="{ null: row[col] === null || row[col] === '' }">
                  {{ (row[col] === null || row[col] === '') ? 'NULL' : truncate(String(row[col])) }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pending Changes Preview -->
      <div v-if="pendingChanges.length" class="pending-card">
        <div class="pending-title">待执行变更 ({{ pendingChanges.length }})</div>
        <div v-for="(change, i) in pendingChanges" :key="i" class="pending-item">
          <t-tag :theme="change.type === 'INSERT' ? 'success' : change.type === 'DELETE' ? 'danger' : 'warning'" size="small">
            {{ change.type }}
          </t-tag>
          <code>{{ change.sql }}</code>
          <t-button size="small" variant="text" theme="danger" @click="revertChange(change)">
            <t-icon name="close" size="14px" />
          </t-button>
        </div>
      </div>
    </div>

    
    <!-- Detail Drawer -->
    <RowDetailDrawer v-model="drawerVisible" :row="detailRow" :columns="tableData.columns" />

    <!-- SQL Console -->
    <details class="sql-section">
      <summary class="sql-toggle">SQL 控制台（高级）</summary>
      <div class="sql-card">
        <textarea v-model="rawSql" class="sql-textarea" placeholder="SELECT * FROM rounds LIMIT 10" rows="3" @keydown.ctrl.enter="executeRawSql" @keydown.meta.enter="executeRawSql"></textarea>
        <div class="sql-actions">
          <t-button theme="primary" size="small" @click="executeRawSql" :loading="rawExecuting">执行</t-button>
          <span class="sql-hint">Ctrl+Enter</span>
        </div>
        <div v-if="rawError" class="sql-error">{{ rawError }}</div>
        <div v-if="rawResult" class="sql-result">
          <pre>{{ JSON.stringify(rawResult, null, 2) }}</pre>
        </div>
      </div>
    </details>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from "vue"
import RowDetailDrawer from "../components/RowDetailDrawer.vue"
import PrivilegeDialog from "../components/PrivilegeDialog.vue"
import PrivilegeStatus from "../components/PrivilegeStatus.vue"
import { MessagePlugin } from "tdesign-vue-next"

const adminSession = ref("")
const adminExpiry = ref(0)
const showPrivDialog = ref(false)

const tables = ref([])
const selectedTable = ref("")
const tableData = ref({ columns: [], rows: [] })
const editableRows = ref([])
const editingCell = ref({ row: -1, col: "" })
const executing = ref(false)

const rawSql = ref("")
const rawExecuting = ref(false)
const rawError = ref("")
const rawResult = ref(null)


const adminValid = computed(() => adminSession.value && Date.now() < adminExpiry.value)
const canWrite = computed(() => adminValid.value)
const allSelected = computed(() => {
  const selectable = editableRows.value.filter(r => !r._new)
  return selectable.length > 0 && selectable.every(r => r._selected)
})
const selectedRows = computed(() => editableRows.value.filter(r => r._selected))
const hasSelectableForDelete = computed(() => editableRows.value.some(r => r._selected && !r._new && !r._deleted))

const pendingChanges = computed(() => {
  const changes = []
  for (const row of editableRows.value) {
    if (row._deleted) {
      const pk = tableData.value.columns[0]
      changes.push({ type: "DELETE", sql: `DELETE FROM ${selectedTable.value} WHERE ${pk} = '${row[pk]}'`, _row: row })
    } else if (row._new) {
      const cols = tableData.value.columns.filter(c => row[c] !== null && row[c] !== "")
      if (cols.length > 0) {
        const vals = cols.map(c => `'${String(row[c]).replace(/'/g, "''")}'`)
        changes.push({ type: "INSERT", sql: `INSERT INTO ${selectedTable.value} (${cols.join(", ")}) VALUES (${vals.join(", ")})`, _row: row })
      }
    } else if (row._modified) {
      const pk = tableData.value.columns[0]
      const sets = Object.keys(row._originalDiff || {}).map(c => `${c} = '${String(row[c]).replace(/'/g, "''")}'`)
      if (sets.length) {
        changes.push({ type: "UPDATE", sql: `UPDATE ${selectedTable.value} SET ${sets.join(", ")} WHERE ${pk} = '${row[pk]}'`, _row: row })
      }
    }
  }
  return changes
})

onMounted(() => {
  fetchTables()
  const saved = sessionStorage.getItem("clawavc_admin_session")
  const savedExpiry = sessionStorage.getItem("clawavc_admin_expiry")
  if (saved && savedExpiry && Date.now() < Number(savedExpiry)) {
    adminSession.value = saved
    adminExpiry.value = Number(savedExpiry)
  }
})


async function fetchTables() {
  try {
    const res = await fetch("/api/db/tables")
    const json = await res.json()
    if (json.ok) tables.value = json.tables
  } catch (e) {}
}

const HIDDEN_TABLES = ["config", "sqlite_sequence"]
const visibleTables = computed(() => tables.value.filter(t => !HIDDEN_TABLES.includes(t.name)))
const hiddenTables = computed(() => tables.value.filter(t => HIDDEN_TABLES.includes(t.name)))
const isSensitiveTable = computed(() => HIDDEN_TABLES.includes(selectedTable.value))

function selectHiddenTable(name) {
  const token = sessionStorage.getItem("clawavc_admin_session")
  if (!token) {
    MessagePlugin.warning("访问系统表需要特权验证")
    return
  }
  selectTable(name)
}

async function selectTable(name) {
  selectedTable.value = name
  const headers = { "Content-Type": "application/json" }
  if (adminSession.value) headers["X-Admin-Session"] = adminSession.value
  try {
    const res = await fetch("/api/db/query", {
      method: "POST",
      headers,
      body: JSON.stringify({ sql: `SELECT * FROM ${name} ORDER BY rowid DESC LIMIT 100` }),
    })
    const json = await res.json()
    if (json.ok) {
      tableData.value = { columns: json.columns, rows: json.rows }
      editableRows.value = json.rows.map(r => ({ ...r, _selected: false, _modified: false, _new: false, _deleted: false, _originalDiff: {} }))
    } else {
      MessagePlugin.error(json.error || "查询失败")
      tableData.value = { columns: [], rows: [] }
      editableRows.value = []
    }
  } catch (e) {
    MessagePlugin.error("连接失败")
  }
}

function addRow() {
  const newRow = { _selected: false, _modified: false, _new: true, _deleted: false, _originalDiff: {} }
  for (const col of tableData.value.columns) newRow[col] = ""
  editableRows.value.unshift(newRow)
}

function markDeleteSelected() {
  for (const row of editableRows.value) {
    if (row._selected && !row._new) {
      row._deleted = true
      // Clear any pending modifications for this row
      row._modified = false
      row._originalDiff = {}
    }
  }
}

function revertChange(change) {
  const row = change._row
  if (!row) return
  if (change.type === "DELETE") {
    row._deleted = false
    row._selected = false
  } else if (change.type === "INSERT") {
    // Remove the new row entirely
    const idx = editableRows.value.indexOf(row)
    if (idx >= 0) editableRows.value.splice(idx, 1)
  } else if (change.type === "UPDATE") {
    // Revert to original values
    const origIdx = editableRows.value.indexOf(row)
    if (origIdx >= 0 && tableData.value.rows[origIdx - countNewRows(origIdx)]) {
      const orig = tableData.value.rows[origIdx - countNewRows(origIdx)]
      for (const col of Object.keys(row._originalDiff)) {
        row[col] = orig[col]
      }
    }
    row._modified = false
    row._originalDiff = {}
  }
}

function countNewRows(beforeIdx) {
  let count = 0
  for (let i = 0; i < beforeIdx; i++) {
    if (editableRows.value[i]._new) count++
  }
  return count
}

function toggleAll(e) {
  const checked = e.target.checked
  for (const row of editableRows.value) {
    if (!row._new) row._selected = checked
  }
}

function startEdit(ri, col) {
  const row = editableRows.value[ri]
  // Don't allow editing deleted rows
  if (row._deleted) return
  // Don't edit PK of existing rows
  if (col === tableData.value.columns[0] && !row._new) return
  if (!canWrite.value) return
  editingCell.value = { row: ri, col }
}

function finishEdit(ri, col) {
  const row = editableRows.value[ri]
  if (!row._new) {
    // Find original row (accounting for new rows inserted at top)
    const origIdx = ri - countNewRows(ri)
    const orig = tableData.value.rows[origIdx]
    if (orig && String(row[col]) !== String(orig[col])) {
      row._modified = true
      row._originalDiff[col] = true
    } else if (orig && String(row[col]) === String(orig[col])) {
      // Reverted this cell, check if any other diffs remain
      delete row._originalDiff[col]
      if (Object.keys(row._originalDiff).length === 0) {
        row._modified = false
      }
    }
  }
  editingCell.value = { row: -1, col: "" }
}

function cancelEdit(ri, col) {
  const row = editableRows.value[ri]
  if (!row._new) {
    const origIdx = ri - countNewRows(ri)
    const orig = tableData.value.rows[origIdx]
    if (orig) row[col] = orig[col]
  }
  editingCell.value = { row: -1, col: "" }
}

async function executeChanges() {
  if (!pendingChanges.value.length) return
  if (!adminValid.value) {
    MessagePlugin.warning("请先验证特权密钥")
    return
  }
  executing.value = true
  let success = 0
  for (const change of pendingChanges.value) {
    try {
      const res = await fetch("/api/db/query", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Admin-Session": adminSession.value },
        body: JSON.stringify({ sql: change.sql }),
      })
      const json = await res.json()
      if (json.ok) success++
      else MessagePlugin.error(`失败: ${json.error}`)
    } catch (e) { MessagePlugin.error("连接失败") }
  }
  if (success > 0) {
    MessagePlugin.success(`执行成功: ${success}/${pendingChanges.value.length}`)
    selectTable(selectedTable.value)
    fetchTables()
  }
  executing.value = false
}

function onPrivSuccess(token) {
  adminSession.value = token
  adminExpiry.value = Number(sessionStorage.getItem("clawavc_admin_expiry"))
}

async function executeRawSql() {
  if (!rawSql.value.trim()) return
  rawExecuting.value = true
  rawError.value = ""
  rawResult.value = null
  try {
    const headers = { "Content-Type": "application/json" }
    if (adminSession.value) headers["X-Admin-Session"] = adminSession.value
    const res = await fetch("/api/db/query", { method: "POST", headers, body: JSON.stringify({ sql: rawSql.value.trim() }) })
    const json = await res.json()
    if (json.ok) rawResult.value = json
    else rawError.value = json.error
  } catch (e) { rawError.value = "连接失败" }
  rawExecuting.value = false
}

const drawerVisible = ref(false)
const detailRow = ref(null)

function openDetail() {
  const selected = editableRows.value.filter(r => r._selected)
  if (selected.length > 1) {
    MessagePlugin.warning("请只选择一行查看详情")
    return
  }
  if (selected.length === 1) {
    detailRow.value = selected[0]
    drawerVisible.value = true
  }
}

function truncate(s) { return s.length > 60 ? s.slice(0, 60) + "..." : s }
</script>

<style scoped>
.db-page { max-width: 1100px; margin: 0 auto; }
.db-page h2 { font-size: 20px; font-weight: 600; margin-bottom: 20px; color: #333; }



.tables-card, .editor-card { background: #fff; border-radius: 12px; padding: 20px; border: 1px solid #eee; margin-bottom: 16px; }
.card-title { font-size: 14px; font-weight: 600; color: #333; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; }
.tables-grid { display: flex; flex-wrap: wrap; gap: 8px; }
.table-chip { padding: 8px 14px; border-radius: 8px; border: 1px solid #eee; cursor: pointer; display: flex; align-items: center; gap: 6px; transition: all 0.2s; }
.table-chip:hover { border-color: #0052D9; background: #f0f5ff; }
.table-chip.active { border-color: #0052D9; background: #f0f5ff; }
.table-chip.privileged { border-color: #ffe0c2; }
.table-name { font-size: 13px; font-weight: 500; }
.table-count { font-size: 11px; color: #999; background: #f3f3f3; padding: 2px 6px; border-radius: 4px; }
.editor-actions { display: flex; gap: 8px; }
.table-wrap { overflow-x: auto; margin-top: 12px; }
.data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.data-table th { background: #f8f9fa; padding: 8px; text-align: left; font-weight: 600; color: #666; border-bottom: 2px solid #eee; white-space: nowrap; }
.data-table td { padding: 6px 8px; border-bottom: 1px solid #f3f3f3; }
.data-table tr:hover td { background: #fafbfc; }
.data-table tr.modified td { background: #fffbe6; }
.data-table tr.is-new td { background: #f0fff8; }
.data-table tr.deleted td { background: #fff5f5; text-decoration: line-through; opacity: 0.6; pointer-events: none; }
.data-table tr.deleted td.col-check { pointer-events: auto; opacity: 1; }
.col-check { width: 32px; text-align: center; }
.cell-display { max-width: 200px; display: inline-block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: default; }
.cell-display.null { color: #ccc; font-style: italic; }
.cell-input { width: 100%; border: 1px solid #0052D9; border-radius: 4px; padding: 2px 6px; font-size: 12px; outline: none; }
.pending-card { margin-top: 12px; background: #fafbfc; border: 1px solid #eee; border-radius: 8px; padding: 12px; }
.pending-title { font-size: 12px; font-weight: 600; color: #666; margin-bottom: 8px; }
.pending-item { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.pending-item code { font-size: 11px; color: #555; background: #fff; padding: 2px 6px; border-radius: 4px; border: 1px solid #eee; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sql-section { margin-top: 16px; }
.sql-toggle { font-size: 13px; color: #666; cursor: pointer; padding: 8px; }
.sql-card { background: #fff; border-radius: 12px; padding: 16px; border: 1px solid #eee; margin-top: 8px; }
.sql-textarea { width: 100%; border: 1px solid #ddd; border-radius: 8px; padding: 10px; font-family: monospace; font-size: 12px; resize: vertical; outline: none; }
.sql-textarea:focus { border-color: #0052D9; }
.sql-actions { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.sql-hint { font-size: 11px; color: #999; }
.sql-error { margin-top: 8px; background: #fff5f5; border-radius: 6px; padding: 8px; font-size: 12px; color: #ff5252; font-family: monospace; }
.sql-result { margin-top: 8px; }
.sql-result pre { background: #f8f9fa; border-radius: 6px; padding: 10px; font-size: 11px; overflow-x: auto; max-height: 300px; }



.more-btn { margin-left: 4px; }
.hidden-tables-pop { display: flex; flex-direction: column; gap: 6px; padding: 4px; }
.hidden-chip { border-color: #ffe8d0 !important; }
.sensitive-warn { margin-top: 12px; display: flex; align-items: center; gap: 8px; background: #fff8e6; border: 1px solid #ffe58f; border-radius: 8px; padding: 10px 14px; font-size: 12px; color: #d48806; }
</style>
