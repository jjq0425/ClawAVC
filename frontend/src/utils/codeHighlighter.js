// 轻量级 shell 代码高亮：先转义防 XSS，再对注释 / 关键字 / 字符串着色。
// 注释采用「行内分离」策略（先剥离 # 之后的注释段，再对代码段着色），避免嵌套与配色串色。

const SHELL_KEYWORDS = [
  "setsebool", "chcon", "chmod", "chown", "sudo", "echo", "export", "source",
  "if", "then", "else", "elif", "fi", "for", "in", "do", "done", "while",
  "case", "esac", "function", "return", "exit", "cd", "cat", "grep", "mkdir",
  "rm", "cp", "mv", "ln", "mount", "umount", "iptables", "sysctl", "semanage",
  "getenforce", "setenforce", "tee", "awk", "sed", "sort", "uniq", "head",
  "tail", "wc", "ps", "kill", "systemctl", "id", "whoami", "touch", "ls",
  "find", "read", "printf", "test",
]

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
}

function highlightCode(code) {
  // 关键字（命令名）
  code = code.replace(
    new RegExp("\\b(" + SHELL_KEYWORDS.join("|") + ")\\b", "g"),
    '<span class="tok-keyword">$1</span>'
  )
  // 字符串（转义后的双/单引号包裹段）
  code = code.replace(
    /(&quot;[^&]*?&quot;|&#39;[^&]*?&#39;)/g,
    '<span class="tok-string">$1</span>'
  )
  return code
}

function highlightLine(line) {
  const esc = escapeHtml(line)
  // 定位注释起点：第一个前面是行首或空白的 '#'
  let cidx = -1
  const re = /(^|\s)#/g
  let m
  if ((m = re.exec(esc))) {
    cidx = m.index + m[1].length
  }
  let codePart = esc
  let commentPart = ""
  if (cidx >= 0) {
    codePart = esc.slice(0, cidx)
    commentPart = esc.slice(cidx)
  }
  return (
    highlightCode(codePart) +
    (commentPart ? `<span class="tok-comment">${commentPart}</span>` : "")
  )
}

export function highlightShell(src) {
  if (src == null) return ""
  return String(src)
    .split("\n")
    .map(highlightLine)
    .join("\n")
}

export default { highlightShell }
