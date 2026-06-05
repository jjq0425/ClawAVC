/**
 * JSON/JSONL 语法高亮工具
 */

/**
 * 检测内容是否为 JSONL 格式
 */
export function isJsonl(content) {
  if (!content || typeof content !== 'string') return false
  
  const lines = content.trim().split('\n')
  if (lines.length === 0) return false
  
  // 如果有多行，检查大部分行是否为有效 JSON
  if (lines.length >= 2) {
    const validJsonLines = lines.filter(line => {
      if (!line.trim()) return false
      try {
        JSON.parse(line)
        return true
      } catch {
        return false
      }
    })
    // 如果超过一半的行是有效 JSON，认为是 JSONL
    return validJsonLines.length > lines.length / 2
  }
  
  // 单行时，检查是否为有效 JSON（如果是，走 JSON 处理）
  try {
    JSON.parse(lines[0])
    return true
  } catch {
    return false
  }
}

/**
 * 解析 JSONL 内容为行数组
 */
export function parseJsonl(content) {
  if (!content) return []
  
  return content.split('\n').filter(line => line.trim())
}

/**
 * 格式化单个 JSON 对象为 HTML
 */
export function formatJsonToJsonHtml(jsonStr) {
  try {
    const obj = JSON.parse(jsonStr)
    const formatted = JSON.stringify(obj, null, 2)
    return syntaxHighlight(formatted)
  } catch {
    return escapeHtml(jsonStr)
  }
}

/**
 * 将 JSONL 转换为高亮的 HTML
 */
export function jsonlToHtml(content) {
  if (!content) return ''
  
  const lines = parseJsonl(content)
  if (lines.length === 0) return ''
  
  let html = '<div class="jsonl-container">'
  lines.forEach((line, index) => {
    html += `<div class="jsonl-line">`
    html += `<span class="line-number">${index + 1}</span>`
    html += `<pre class="json-line">${formatJsonToJsonHtml(line)}</pre>`
    html += `</div>`
  })
  html += '</div>'
  
  return html
}

/**
 * 将 JSON 转换为高亮的 HTML
 */
export function jsonToJsonHtml(content) {
  try {
    const obj = JSON.parse(content)
    const formatted = JSON.stringify(obj, null, 2)
    return syntaxHighlight(formatted)
  } catch {
    return escapeHtml(content)
  }
}

/**
 * 语法高亮处理
 */
function syntaxHighlight(json) {
  if (!json) return ''
  
  // 转义 HTML 特殊字符
  json = escapeHtml(json)
  
  // 语法高亮 - 使用更精确的正则
  // 1. 处理字符串值（带引号的）
  json = json.replace(/("(?:[^"\\]|\\.)*")/g, '<span class="json-string">$1</span>')
  
  // 2. 处理数字
  json = json.replace(/(\b\d+\.?\d*)\b/g, '<span class="json-number">$1</span>')
  
  // 3. 处理布尔值和 null
  json = json.replace(/\b(true|false)\b/g, '<span class="json-boolean">$1</span>')
  json = json.replace(/\bnull\b/g, '<span class="json-null">$1</span>')
  
  // 4. 处理 JSON 结构符号
  json = json.replace(/\{/g, '<span class="json-brace">{</span>')
  json = json.replace(/\}/g, '<span class="json-brace">}</span>')
  json = json.replace(/\[/g, '<span class="json-bracket">[</span>')
  json = json.replace(/\]/g, '<span class="json-bracket">]</span>')
  
  // 5. 处理冒号
  json = json.replace(/:/g, '<span class="json-colon">:</span>')
  
  // 6. 处理逗号
  json = json.replace(/,/g, '<span class="json-comma">,</span>')
  
  return json
}

/**
 * HTML 轌转义
 */
function escapeHtml(str) {
  if (!str) return ''
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

/**
 * 获取内容的显示格式
 */
export function getContentFormat(content) {
  if (!content) return 'empty'
  
  const trimmed = content.trim()
  
  // 检查是否为 JSONL
  if (isJsonl(trimmed)) {
    return 'jsonl'
  }
  
  // 检查是否为 JSON
  try {
    JSON.parse(trimmed)
    return 'json'
  } catch {
    return 'text'
  }
}
