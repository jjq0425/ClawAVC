<template>
  <div class="export-page">
    <h2>数据导出</h2>
    <p class="page-desc">导出非特权表数据，支持 SQL 筛选后以多种格式导出</p>

    <!-- Step 1: Select table -->
    <div class="export-card">
      <div class="card-title">1. 选择数据表</div>
      <div class="tables-grid" v-if="tables.length">
        <div
          v-for="t in exportableTables"
          :key="t.name"
          class="table-chip"
          :class="{ active: selectedTable === t.name }"
          @click="selectTable(t.name)"
        >
          <span class="table-name">{{ t.name }}</span>
          <span class="table-count">{{ t.count }} 行</span>
        </div>
      </div>
      <div v-else class="loading-hint">加载中...</div>
    </div>

    <!-- Step 2: SQL filter -->
    <div class="export-card" v-if="selectedTable">
      <div class="card-title">2. SQL 筛选（可选）</div>
      <p class="hint">默认导出整表数据，可编辑 SQL 进行筛选。仅支持 SELECT 语句。</p>
      <div class="sql-area">
        <textarea
          v-model="sql"
          class="sql-input"
          rows="4"
          spellcheck="false"
          placeholder="SELECT * FROM table_name WHERE ..."
        ></textarea>
        <div class="sql-actions">
          <t-button size="small" variant="outline" @click="resetSql">重置</t-button>
          <t-button size="small" theme="primary" @click="previewData" :loading="previewing">
            预览数据
          </t-button>
        </div>
      </div>
      <div v-if="previewError" class="error-msg">{{ previewError }}</div>
    </div>

    <!-- Step 3: Preview -->
    <div class="export-card" v-if="previewRows.length > 0">
      <div class="card-title">
        3. 数据预览
        <span class="preview-count">共 {{ previewRows.length }} 条记录</span>
      </div>
      <div class="preview-table-wrapper">
        <table class="preview-table">
          <thead>
            <tr>
              <th v-for="col in previewColumns" :key="col">{{ col }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, idx) in previewRows.slice(0, 50)" :key="idx">
              <td v-for="col in previewColumns" :key="col">{{ row[col] ?? '' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="previewRows.length > 50" class="preview-hint">
        仅展示前 50 行，导出将包含全部 {{ previewRows.length }} 条数据
      </div>
    </div>

    <!-- Step 4: Export format -->
    <div class="export-card" v-if="previewRows.length > 0">
      <div class="card-title">4. 选择导出格式</div>
      <div class="format-options">
        <div
          v-for="fmt in formats"
          :key="fmt.value"
          class="format-chip"
          :class="{ active: selectedFormat === fmt.value }"
          @click="selectedFormat = fmt.value"
        >
          <span class="format-icon">{{ fmt.icon }}</span>
          <span class="format-label">{{ fmt.label }}</span>
          <span class="format-ext">.{{ fmt.value }}</span>
        </div>
      </div>
      <div class="export-actions">
        <t-button theme="primary" size="large" @click="doExport" :loading="exporting">
          <template #icon><t-icon name="download" /></template>
          导出 {{ selectedFormat.toUpperCase() }} 文件
        </t-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'

const route = useRoute()
const API = '/api'
const tables = ref([])
const selectedTable = ref('')
const sql = ref('')
const previewing = ref(false)
const exporting = ref(false)
const previewColumns = ref([])
const previewRows = ref([])
const previewError = ref('')
const selectedFormat = ref('csv')

// Sensitive/privileged tables that cannot be exported
const SENSITIVE_TABLES = ['config', 'sqlite_sequence']

const formats = [
  { value: 'csv', label: 'CSV', icon: '📊' },
  { value: 'xlsx', label: 'Excel', icon: '📗' },
  { value: 'txt', label: 'TXT', icon: '📄' },
  { value: 'json', label: 'JSON', icon: '📋' },
  { value: 'jsonl', label: 'JSONL', icon: '📜' },
]

const exportableTables = ref([])

onMounted(async () => {
  try {
    const res = await fetch(`${API}/db/tables`)
    const data = await res.json()
    if (data.ok) {
      tables.value = data.tables
      exportableTables.value = data.tables.filter(
        t => !SENSITIVE_TABLES.includes(t.name.toLowerCase())
      )
      // Auto-select table from query param (from DatabasePage)
      const queryTable = route.query.table
      if (queryTable && exportableTables.value.some(t => t.name === queryTable)) {
        selectTable(queryTable)
      }
    }
  } catch (e) {
    MessagePlugin.error('获取表列表失败')
  }
})

function selectTable(name) {
  selectedTable.value = name
  sql.value = `SELECT * FROM [${name}]`
  previewRows.value = []
  previewColumns.value = []
  previewError.value = ''
}

function resetSql() {
  if (selectedTable.value) {
    sql.value = `SELECT * FROM [${selectedTable.value}]`
  }
  previewRows.value = []
  previewColumns.value = []
  previewError.value = ''
}

async function previewData() {
  if (!sql.value.trim()) {
    MessagePlugin.warning('请输入 SQL 语句')
    return
  }
  const upper = sql.value.trim().toUpperCase()
  if (!upper.startsWith('SELECT')) {
    previewError.value = '仅支持 SELECT 查询语句'
    return
  }
  // Block sensitive tables
  for (const t of SENSITIVE_TABLES) {
    if (upper.includes(t.toUpperCase())) {
      previewError.value = `不允许访问特权表: ${t}`
      return
    }
  }

  previewing.value = true
  previewError.value = ''
  try {
    const res = await fetch(`${API}/db/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sql: sql.value.trim() }),
    })
    const data = await res.json()
    if (data.ok) {
      previewColumns.value = data.columns || []
      previewRows.value = data.rows || []
      if (previewRows.value.length === 0) {
        previewError.value = '查询结果为空'
      }
    } else {
      previewError.value = data.error || '查询失败'
      previewRows.value = []
      previewColumns.value = []
    }
  } catch (e) {
    previewError.value = '请求失败: ' + e.message
  } finally {
    previewing.value = false
  }
}

function doExport() {
  if (previewRows.value.length === 0) return
  exporting.value = true
  try {
    const filename = `${selectedTable.value || 'export'}_${formatTimestamp()}`
    switch (selectedFormat.value) {
      case 'csv':
        exportCSV(filename)
        break
      case 'xlsx':
        exportXLSX(filename)
        break
      case 'txt':
        exportTXT(filename)
        break
      case 'json':
        exportJSON(filename)
        break
      case 'jsonl':
        exportJSONL(filename)
        break
    }
    MessagePlugin.success(`已导出 ${previewRows.value.length} 条数据`)
  } catch (e) {
    MessagePlugin.error('导出失败: ' + e.message)
  } finally {
    exporting.value = false
  }
}

function formatTimestamp() {
  const now = new Date()
  return `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}_${String(now.getHours()).padStart(2,'0')}${String(now.getMinutes()).padStart(2,'0')}`
}

// --- CSV Export ---
function exportCSV(filename) {
  const cols = previewColumns.value
  const rows = previewRows.value
  const lines = []
  lines.push(cols.map(c => csvEscape(c)).join(','))
  for (const row of rows) {
    lines.push(cols.map(c => csvEscape(String(row[c] ?? ''))).join(','))
  }
  const bom = '\uFEFF'
  downloadBlob(bom + lines.join('\n'), `${filename}.csv`, 'text/csv;charset=utf-8')
}

function csvEscape(val) {
  if (val.includes(',') || val.includes('"') || val.includes('\n')) {
    return `"${val.replace(/"/g, '""')}"`
  }
  return val
}

// --- TXT Export (tab-separated) ---
function exportTXT(filename) {
  const cols = previewColumns.value
  const rows = previewRows.value
  const lines = []
  lines.push(cols.join('\t'))
  for (const row of rows) {
    lines.push(cols.map(c => String(row[c] ?? '').replace(/\t/g, ' ')).join('\t'))
  }
  downloadBlob(lines.join('\n'), `${filename}.txt`, 'text/plain;charset=utf-8')
}

// --- JSON Export ---
function exportJSON(filename) {
  const json = JSON.stringify(previewRows.value, null, 2)
  downloadBlob(json, `${filename}.json`, 'application/json;charset=utf-8')
}

// --- JSONL Export (one JSON object per line) ---
function exportJSONL(filename) {
  const lines = previewRows.value.map(row => JSON.stringify(row))
  downloadBlob(lines.join('\n'), `${filename}.jsonl`, 'application/x-jsonlines;charset=utf-8')
}

// --- XLSX Export (lightweight, no external dependency) ---
function exportXLSX(filename) {
  const cols = previewColumns.value
  const rows = previewRows.value

  // Build a simple xlsx using XML (SpreadsheetML)
  const escXml = (s) => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')

  let sheetData = '<row>'
  for (const c of cols) {
    sheetData += `<c t="inlineStr"><is><t>${escXml(c)}</t></is></c>`
  }
  sheetData += '</row>'

  for (const row of rows) {
    sheetData += '<row>'
    for (const c of cols) {
      const val = row[c] ?? ''
      const numVal = Number(val)
      if (val !== '' && !isNaN(numVal) && String(numVal) === String(val)) {
        sheetData += `<c><v>${numVal}</v></c>`
      } else {
        sheetData += `<c t="inlineStr"><is><t>${escXml(String(val))}</t></is></c>`
      }
    }
    sheetData += '</row>'
  }

  const sheet = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetData>${sheetData}</sheetData>
</worksheet>`

  const workbook = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>
</workbook>`

  const contentTypes = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>`

  const rels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`

  const workbookRels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>`

  // Use JSZip-like manual ZIP construction via Blob
  // For simplicity, use the browser's compression stream if available, otherwise fallback
  // Actually, let's build the zip manually using a minimal approach
  const files = {
    '[Content_Types].xml': contentTypes,
    '_rels/.rels': rels,
    'xl/workbook.xml': workbook,
    'xl/_rels/workbook.xml.rels': workbookRels,
    'xl/worksheets/sheet1.xml': sheet,
  }

  buildZipAndDownload(files, `${filename}.xlsx`)
}

// Minimal ZIP builder (no compression, store-only for compatibility)
function buildZipAndDownload(files, filename) {
  const enc = new TextEncoder()
  const entries = Object.entries(files).map(([name, content]) => ({
    name: enc.encode(name),
    data: enc.encode(content),
  }))

  let offset = 0
  const localHeaders = []
  const centralHeaders = []

  for (const entry of entries) {
    const localHeader = buildLocalFileHeader(entry.name, entry.data)
    centralHeaders.push(buildCentralDirHeader(entry.name, entry.data, offset))
    localHeaders.push(localHeader)
    offset += localHeader.byteLength + entry.data.byteLength
  }

  let centralOffset = offset
  let centralSize = 0
  for (const ch of centralHeaders) centralSize += ch.byteLength

  const endRecord = buildEndOfCentralDir(entries.length, centralSize, centralOffset)

  // Assemble
  const totalSize = offset + centralSize + endRecord.byteLength
  const buffer = new Uint8Array(totalSize)
  let pos = 0

  for (let i = 0; i < entries.length; i++) {
    buffer.set(new Uint8Array(localHeaders[i]), pos)
    pos += localHeaders[i].byteLength
    buffer.set(entries[i].data, pos)
    pos += entries[i].data.byteLength
  }
  for (const ch of centralHeaders) {
    buffer.set(new Uint8Array(ch), pos)
    pos += ch.byteLength
  }
  buffer.set(new Uint8Array(endRecord), pos)

  const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function buildLocalFileHeader(name, data) {
  const crc = crc32(data)
  const buf = new ArrayBuffer(30 + name.byteLength)
  const view = new DataView(buf)
  view.setUint32(0, 0x04034b50, true) // signature
  view.setUint16(4, 20, true) // version needed
  view.setUint16(6, 0, true)  // flags
  view.setUint16(8, 0, true)  // compression: store
  view.setUint16(10, 0, true) // mod time
  view.setUint16(12, 0, true) // mod date
  view.setUint32(14, crc, true)
  view.setUint32(18, data.byteLength, true) // compressed size
  view.setUint32(22, data.byteLength, true) // uncompressed size
  view.setUint16(26, name.byteLength, true) // filename length
  view.setUint16(28, 0, true) // extra field length
  new Uint8Array(buf).set(name, 30)
  return buf
}

function buildCentralDirHeader(name, data, offset) {
  const crc = crc32(data)
  const buf = new ArrayBuffer(46 + name.byteLength)
  const view = new DataView(buf)
  view.setUint32(0, 0x02014b50, true)
  view.setUint16(4, 20, true)
  view.setUint16(6, 20, true)
  view.setUint16(8, 0, true)
  view.setUint16(10, 0, true)
  view.setUint16(12, 0, true)
  view.setUint16(14, 0, true)
  view.setUint32(16, crc, true)
  view.setUint32(20, data.byteLength, true)
  view.setUint32(24, data.byteLength, true)
  view.setUint16(28, name.byteLength, true)
  view.setUint16(30, 0, true)
  view.setUint16(32, 0, true)
  view.setUint16(34, 0, true)
  view.setUint16(36, 0, true)
  view.setUint32(38, 0, true)
  view.setUint32(42, offset, true)
  new Uint8Array(buf).set(name, 46)
  return buf
}

function buildEndOfCentralDir(count, size, offset) {
  const buf = new ArrayBuffer(22)
  const view = new DataView(buf)
  view.setUint32(0, 0x06054b50, true)
  view.setUint16(4, 0, true)
  view.setUint16(6, 0, true)
  view.setUint16(8, count, true)
  view.setUint16(10, count, true)
  view.setUint32(12, size, true)
  view.setUint32(16, offset, true)
  view.setUint16(20, 0, true)
  return buf
}

// CRC32 implementation
function crc32(data) {
  let crc = 0xFFFFFFFF
  for (let i = 0; i < data.byteLength; i++) {
    crc ^= data[i]
    for (let j = 0; j < 8; j++) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xEDB88320 : 0)
    }
  }
  return (crc ^ 0xFFFFFFFF) >>> 0
}

function downloadBlob(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.export-page {
  max-width: 960px;
  margin: 0 auto;
  padding: 0 24px 48px;
}
.export-page h2 {
  font-size: 22px;
  font-weight: 600;
  color: #333;
  margin-bottom: 4px;
}
.page-desc {
  font-size: 14px;
  color: #888;
  margin-bottom: 24px;
}
.export-card {
  background: #fff;
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 16px;
  border: 1px solid #eee;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #333;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.preview-count {
  font-size: 12px;
  font-weight: 400;
  color: #888;
  background: #f5f7fa;
  padding: 2px 10px;
  border-radius: 10px;
}
.tables-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.table-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid #e5e5e5;
  cursor: pointer;
  transition: all 0.2s;
  background: #fafafa;
}
.table-chip:hover {
  border-color: #0052D9;
  background: #f0f5ff;
}
.table-chip.active {
  border-color: #0052D9;
  background: #0052D9;
  color: #fff;
}
.table-chip.active .table-count {
  color: rgba(255,255,255,0.8);
}
.table-name {
  font-size: 13px;
  font-weight: 500;
}
.table-count {
  font-size: 11px;
  color: #aaa;
}
.loading-hint {
  color: #aaa;
  font-size: 13px;
}
.hint {
  font-size: 13px;
  color: #888;
  margin-bottom: 12px;
}
.sql-area {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.sql-input {
  width: 100%;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 13px;
  padding: 12px;
  border: 1px solid #ddd;
  border-radius: 8px;
  resize: vertical;
  background: #fafafa;
  outline: none;
  transition: border-color 0.2s;
  box-sizing: border-box;
}
.sql-input:focus {
  border-color: #0052D9;
  background: #fff;
}
.sql-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
.error-msg {
  color: #d54941;
  font-size: 13px;
  margin-top: 10px;
  padding: 8px 12px;
  background: #fff1f0;
  border-radius: 6px;
}
.preview-table-wrapper {
  overflow-x: auto;
  border-radius: 8px;
  border: 1px solid #eee;
}
.preview-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.preview-table th {
  background: #f5f7fa;
  padding: 8px 12px;
  text-align: left;
  font-weight: 600;
  color: #555;
  white-space: nowrap;
  border-bottom: 1px solid #eee;
}
.preview-table td {
  padding: 6px 12px;
  border-bottom: 1px solid #f0f0f0;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #333;
}
.preview-table tr:hover td {
  background: #f9fbff;
}
.preview-hint {
  font-size: 12px;
  color: #888;
  margin-top: 10px;
  text-align: center;
}
.format-options {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 20px;
}
.format-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  border-radius: 10px;
  border: 2px solid #e5e5e5;
  cursor: pointer;
  transition: all 0.2s;
  background: #fafafa;
}
.format-chip:hover {
  border-color: #0052D9;
  background: #f0f5ff;
}
.format-chip.active {
  border-color: #0052D9;
  background: #f0f5ff;
}
.format-icon {
  font-size: 20px;
}
.format-label {
  font-size: 14px;
  font-weight: 500;
  color: #333;
}
.format-ext {
  font-size: 11px;
  color: #aaa;
}
.export-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
