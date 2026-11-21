<template>
<!-- 审计日志页：筛选栏 + round 卡片流 + 分页 -->
  <div class="logs-tab">
    <!-- Filter Bar -->
<!-- 筛选栏：关键字/round_id/时间区间 + 连接状态 -->
    <div class="filter-bar">
<!-- 按 user_query 关键字搜索 -->
      <t-input v-model="filters.query" placeholder="搜索 user_query" clearable size="small" style="width: 200px;" />
<!-- 按 round_id 搜索 -->
      <t-input v-model="filters.round_id" placeholder="搜索 round_id" clearable size="small" style="width: 160px;" />
<!-- 时间区间选择（含时分秒） -->
      <t-date-range-picker v-model="filters.dateRange" enable-time-picker size="small" style="width: 320px;" />
<!-- 查询按钮：按筛选条件重拉 -->
      <t-button theme="primary" size="small" @click="fetchRounds" :loading="loading">查询</t-button>
<!-- 重置：清空条件并回第一页 -->
      <t-button size="small" variant="outline" @click="resetFilters">重置</t-button>
<!-- 右侧状态区：连接指示灯 + 总数 -->
      <div class="filter-right">
<!-- 连接状态点：绿=实时接收中，灰=等待连接 -->
        <span class="status-dot" :class="connected ? 'online' : 'offline'" />
<!-- 连接状态文字 -->
        <span class="status-text">{{ connected ? '实时接收中' : '等待连接' }}</span>
<!-- 总条数 -->
        <span class="total-text">共 {{ total }} 条</span>
      </div>
    </div>

    <!-- Empty -->
<!-- 空态：暂无数据 -->
    <div v-if="!loading && rounds.length === 0" class="empty-state">
      <t-icon name="time" size="56px" style="color: #ccc;" />
      <p>暂无数据</p>
    </div>

    <!-- Cards -->
<!-- 卡片列表容器：新数据滑入动画 -->
    <transition-group name="card-slide" tag="div" class="rounds-list">
<!-- round 卡片：异常/待判定/正常三态配色 -->
      <div v-for="r in rounds" :key="r.round_id" class="round-card" :class="{ abnormal: (r.overall_score ?? -1) < 0.5 && (r.overall_score ?? -1) >= 0, pending: (r.overall_score ?? -1) < 0 }">
<!-- 卡片头：点击展开/收起 -->
        <div class="card-header" @click="toggleExpand(r.round_id)">
<!-- 得分徽标：绿=合规、橙=异常、灰=待判定 -->
          <div class="score-badge" :class="(r.overall_score ?? -1) < 0 ? 'pending' : (r.overall_score ?? 0) >= 0.5 ? 'pass' : 'fail'"></div>
<!-- 卡片主信息：查询原文 + 元信息 -->
          <div class="card-info">
<!-- 用户查询原文（单行省略） -->
            <div class="query-text">{{ r.user_query || '(无查询)' }}</div>
<!-- 元信息行：round_id/会话/时间/角色 -->
            <div class="card-meta">
              <t-tag size="small" variant="outline">{{ r.round_id }}</t-tag>
              <t-tag v-if="r.session_id" size="small" variant="outline" theme="primary" :title="r.session_id">会话 {{ shortSid(r.session_id) }}</t-tag>
<!-- 起止时间 -->
              <span class="meta-time">{{ fmtTime(r.time_start) }} → {{ fmtTime(r.time_end) }}</span>
<!-- 生效角色标注 -->
              <span v-if="r.role_name" class="meta-role" :title="`角色 ${r.role_name}`">{{ r.role_name }}</span>
            </div>
          </div>
        </div>

<!-- 展开区：三大审计组 -->
        <div v-if="expandedId === r.round_id" class="card-expand">
<!-- 组 1·Access：行为轨迹（用户态 + 内核态） -->
          <details class="group-box access-group" open>
            <summary class="group-title"><t-icon name="play-circle" size="18px" /><span>Access · 行为轨迹</span></summary>
            <div class="group-blocks">
              <div class="sub-block">
<!-- 用户态行为：工具/参数/资源三要素 -->
                <div class="sub-block-header user">用户态行为</div>
<!-- 行为卡片列表 -->
                <div v-if="parseJSON(r.action_json).length" class="action-cards">
<!-- 单条行为：工具名 + 参数 + 资源 -->
                  <div v-for="(act, i) in parseJSON(r.action_json)" :key="i" class="action-chip">
<!-- 工具名行 -->
                    <div class="action-tool"><span class="tool-field">工具：</span><t-tag theme="warning" variant="light" size="small">{{ act.tool }}</t-tag></div>
<!-- 调用参数（JSON 原文） -->
                    <div v-if="act.arguments" class="action-detail"><span class="tool-field">参数：</span><code>{{ JSON.stringify(act.arguments) }}</code></div>
<!-- 访问资源：路径 + 读写动作 -->
                    <div v-if="act.resources && act.resources.length" class="action-detail"><span class="tool-field">资源：</span><span v-for="(res, j) in act.resources" :key="j" class="resource-tag">{{ res.path }} ({{ res.access }})</span></div>
                  </div>
                </div>
                <div v-else class="integrating-hint">（本轮无行为记录）</div>
              </div>
              <div class="sub-block">
<!-- 内核态轨迹：syscall/LSM Hook/资源事实 -->
                <div class="sub-block-header kernel">内核态轨迹</div>
<!-- 内核态三件套容器 -->
                <div class="kernel-sections">
                  <!-- 系统调用序列 -->
<!-- 系统调用序列条目 -->
                  <div class="kernel-item" v-if="r.kernel_syscall_seq">
                    <div class="kernel-item-header">
<!-- 标签：系统调用序列 -->
                      <span class="kernel-item-label">系统调用序列</span>
<!-- 文件路径回显 -->
                      <span class="kernel-item-path">{{ r.kernel_syscall_seq }}</span>
<!-- 下载 syscall 序列文件 -->
                      <t-button size="small" variant="text" theme="primary" @click="downloadKernelFile(r.kernel_syscall_seq, 'syscall_seq', null, r.round_id)">
                        <t-icon name="download" size="14px" />
                        下载
                      </t-button>
<!-- 打开 syscall 详情弹窗 -->
                      <t-button size="small" variant="text" theme="primary" @click="currentSyscallSeqPath = r.kernel_syscall_seq; syscallSeqVisible = true">
                        <t-icon name="browse" size="14px" />
                        查看详情
                      </t-button>
                    </div>
                  </div>
                  
                  <!-- LSM Hook结果 -->
<!-- LSM Hook 结果条目 -->
                  <div class="kernel-item" v-if="r.kernel_lsm_hook_result">
                    <div class="kernel-item-header">
<!-- 标签：LSM Hook -->
                      <span class="kernel-item-label">LSM Hook结果</span>
                      <span class="kernel-item-path">{{ r.kernel_lsm_hook_result }}</span>
<!-- 下载 LSM Hook 结果 -->
                      <t-button size="small" variant="text" theme="primary" @click="downloadKernelFile(r.kernel_lsm_hook_result, 'lsm_hook_result', null, r.round_id)">
                        <t-icon name="download" size="14px" />
                        下载
                      </t-button>
<!-- 打开 LSM Hook 详情弹窗 -->
                      <t-button size="small" variant="text" theme="primary" @click="currentLsmHookPath = r.kernel_lsm_hook_result; lsmHookVisible = true">
                        <t-icon name="browse" size="14px" />
                        查看详情
                      </t-button>
                    </div>
                  </div>
                  
                  <!-- 资源事实 -->
<!-- 资源事实条目（内容内联） -->
                  <div class="kernel-item" v-if="r.kernel_resource_facts">
                    <div class="kernel-item-header resource-facts">
<!-- 标签：资源事实 -->
                      <span class="kernel-item-label">资源事实</span>
<!-- 下载资源事实 JSON -->
                      <t-button size="small" variant="text" theme="primary" @click="downloadKernelFile('resource_facts', 'resource_facts', r.kernel_resource_facts, r.round_id)">
                        <t-icon name="download" size="14px" />
                        下载
                      </t-button>
<!-- 打开资源事实弹窗 -->
                      <t-button size="small" variant="text" theme="primary" @click="openResourceFactsDialog(r.kernel_resource_facts)">
                        <t-icon name="browse" size="14px" />
                        查看详情
                      </t-button>
                    </div>
<!-- 资源事实预览（限 100 字） -->
                    <div class="kernel-item-preview" v-if="getKernelPreview(r.kernel_resource_facts)">
                      {{ getKernelPreview(r.kernel_resource_facts) }}
                    </div>
                  </div>
                  
                  <!-- 无数据提示 -->
                  <div v-if="!r.kernel_syscall_seq && !r.kernel_lsm_hook_result && !r.kernel_resource_facts" class="integrating-hint">（本轮无行为记录）</div>
                </div>
              </div>
            </div>
          </details>

<!-- 组 2·View：意图 - IR 策略 -->
          <details class="group-box view-group" open>
            <summary class="group-title"><t-icon name="file-paste" size="18px" /><span>View · 意图 - IR 策略</span></summary>
            <div class="group-blocks">
<!-- IR 翻译中占位 -->
              <div v-if="r.ir_json === '__loading__'" class="integrating-hint"><t-loading size="small" /> IR 翻译中...</div>
<!-- IR 策略列表 -->
              <div v-else-if="getIRPolicies(r.ir_json).length" class="ir-policies">
<!-- 单条策略：subject + 授权对象 -->
                <div v-for="(policy, i) in getIRPolicies(r.ir_json)" :key="i" class="sub-block">
<!-- 策略主体（场景名） -->
                  <div class="sub-block-header user">{{ policy.subject || 'policy ' + i }}</div>
<!-- 授权对象列表 -->
                  <div class="ir-objects-list">
<!-- 单个对象：类型+标识+动作+参数 -->
                    <div v-for="(obj, j) in (policy.objects || [])" :key="j" class="ir-obj-row">
<!-- 对象类型标签 -->
                      <t-tag :theme="getIRTypeTheme(obj.type)" variant="light" size="small">{{ obj.type }}</t-tag>
<!-- 对象标识（等宽） -->
                      <span class="ir-ident">{{ obj.identifier }}</span>
<!-- 允许动作集合 -->
                      <span v-if="obj.actions" class="ir-act">[{{ obj.actions.join(', ') }}]</span>
<!-- 参数约束组 -->
                      <div v-if="obj.params && obj.params.length" class="ir-params">
<!-- 单个参数：名=值 -->
                        <span v-for="(p, k) in obj.params" :key="k" class="ir-param-chip">{{ p.name }}={{ p.identifier }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else class="integrating-hint">（无 IR 策略数据）</div>
            </div>
          </details>

<!-- 组 3·Compliance：合规判定 -->
          <details class="group-box compliance-group" open>
            <summary class="group-title"><t-icon name="check-circle" size="18px" /><span>Compliance · 合规判定</span></summary>
            <div class="group-blocks">
              <div class="sub-block">
<!-- 用户态四维判定文本 -->
                <div class="sub-block-header user">用户态意图行为一致性检测</div>
<!-- 判定结论（等宽预格式） -->
                <div v-if="r.judge_result" class="judge-box">{{ r.judge_result }}</div>
<!-- 无检测数据占位 -->
                <div v-else class="judge-box empty">（无检测数据）</div>
              </div>
              <div class="sub-block">
<!-- 内核态判定：LSM Hook + syscall 分析 -->
                <div class="sub-block-header kernel">内核态行为意图一致性检测</div>
<!-- LSM Hook 判定文档条目 -->
                <div v-if="r.judge_result_kernel" class="kernel-item">
                  <div class="kernel-item-header kernel-judge">
<!-- 标签：LSM Hook 判断结果 -->
                    <span class="kernel-item-label">LMS Hook判断结果文档</span>
                    <span class="kernel-item-path">{{ r.judge_result_kernel }}</span>
<!-- 下载判定文档 -->
                    <t-button size="small" variant="text" theme="primary" @click="downloadKernelFile(r.judge_result_kernel, 'judge_result', null, r.round_id)">
                      <t-icon name="download" size="14px" />
                      下载
                    </t-button>
<!-- 查看判定文档详情 -->
                    <t-button size="small" variant="text" theme="primary" @click="openKernelJudgeDialog(r.judge_result_kernel)">
                      <t-icon name="browse" size="14px" />
                      查看详情
                    </t-button>
                  </div>
                  <!-- <div class="kernel-item-preview" v-if="getKernelJudgePreview(r.judge_result_kernel)">
                    {{ getKernelJudgePreview(r.judge_result_kernel) }}
                  </div> -->
                </div>
<!-- 系统调用分析判定条目 -->
                <div v-if="r.syscall_judge" class="kernel-item">
                  <div class="kernel-item-header kernel-judge">
<!-- 标签：syscall 分析结果 -->
                    <span class="kernel-item-label">系统调用分析判断结果</span>
<!-- 下载 syscall 分析 JSON -->
                    <t-button size="small" variant="text" theme="primary" @click="downloadSyscallJudge(r.syscall_judge, r.round_id)">
                      <t-icon name="download" size="14px" />
                      下载
                    </t-button>
<!-- 打开 syscall 分析弹窗 -->
                    <t-button size="small" variant="text" theme="primary" @click="openSyscallAnalysisDialog(r.syscall_judge)">
                      <t-icon name="browse" size="14px" />
                      查看详情
                    </t-button>
                  </div>
                </div>
<!-- 内核态无记录占位 -->
                <div v-else-if="!r.judge_result_kernel" class="integrating-hint">（本轮无行为记录）</div>
              </div>
              <div class="sub-block">
<!-- AI 综合研判区：小异入口 -->
                <div class="sub-block-header ai">
                  <span>多维行为轨迹综合研判</span>
                </div>
<!-- 小异引导卡 -->
                <div class="xy-greeting">
<!-- 机器人图标 -->
                  <t-icon name="robot" class="xy-greeting__bot" />
<!-- 引导正文 -->
                  <div class="xy-greeting__main">
<!-- 问候语 + 问问小异按钮 -->
                    <div class="xy-greeting__row">
<!-- 问候语 -->
                      <span class="xy-greeting__hi">嗨，我是小异，帮你做多维行为异常研判～</span>
                      <t-button
                        size="small"
                        theme="primary"
                        variant="outline"
                        class="xy-ask-btn"
                        :loading="askingId === r.round_id"
                        @click="askXiaoYi(r)"
                      >
                        <template #icon><t-icon name="robot" /></template>
                        问问小异
                      </t-button>
                    </div>
<!-- 说明：首点建会话并关联本轮 -->
                    <p class="xy-greeting__desc">
                      把本轮多维行为轨迹交给「小异」做异常分析检测；首次点击自动创建专属对话并关联本轮，之后沿用同一对话。
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </details>
        </div>
      </div>
    </transition-group>

    <!-- 内核态详情弹窗组件 -->
<!-- syscall 序列详情弹窗 -->
    <SyscallSeqDialog v-model="syscallSeqVisible" :file-path="currentSyscallSeqPath" />
<!-- LSM Hook 详情弹窗 -->
    <LsmHookDialog v-model="lsmHookVisible" :file-path="currentLsmHookPath" />
<!-- 资源事实弹窗 -->
    <ResourceFactsDialog v-model="resourceFactsVisible" :content="currentResourceFacts" />
<!-- 判定文档（markdown）弹窗 -->
    <MarkdownDialog v-model="kernelJudgeVisible" :file-path="currentKernelJudgePath" />
<!-- syscall 分析结果弹窗 -->
    <SyscallAnalysisDialog v-model="syscallAnalysisVisible" :json-data="currentSyscallAnalysisData" />

    <!-- Pagination -->
<!-- 分页栏 -->
    <div class="pagination-bar" v-if="total > 0">
<!-- 分页器：10/20/50 + 跳页 -->
      <t-pagination v-model:current="currentPage" v-model:pageSize="pageSize" :total="total" :page-size-options="[10, 20, 50]" show-page-size show-jumper @current-change="fetchRounds" @page-size-change="onPageSizeChange" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue"
import { useRouter } from "vue-router"
// socket 客户端与全局连接状态（筛选栏指示灯）
import socket, { connected } from "../../utils/socket.js"
// 通知插件：筛选态下新数据到达提示
import { NotifyPlugin } from "tdesign-vue-next"
import SyscallSeqDialog from "../../components/dialogs/SyscallSeqDialog.vue"
import LsmHookDialog from "../../components/dialogs/LsmHookDialog.vue"
import ResourceFactsDialog from "../../components/dialogs/ResourceFactsDialog.vue"
import MarkdownDialog from "../../components/dialogs/MarkdownDialog.vue"
import SyscallAnalysisDialog from "../../components/dialogs/SyscallAnalysisDialog.vue"

// 当前页 round 列表
const rounds = ref([])
// 总条数（分页用）
const total = ref(0)
// 查询中标志
const loading = ref(false)
// 当前展开的 round_id（同屏只展开一张）
const expandedId = ref(null)
// 当前页码
const currentPage = ref(1)
// 每页条数
const pageSize = ref(20)
// 筛选条件：关键字/round_id/时间区间
const filters = ref({ query: "", round_id: "", dateRange: [] })
let notificationInstance = null

// 路由：跳转小异研判页
const router = useRouter()
// 正在创建小异会话的 round_id（防连点）
const askingId = ref("")

async function askXiaoYi(r) {
  if (askingId.value) return
  askingId.value = r.round_id
  try {
// 创建或复用该轮的研判会话
    const resp = await fetch("/api/monitor/anomaly-chat-from-round", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ round_id: r.round_id }),
    })
    const j = await resp.json()
    if (j.ok && j.data?.session_id) {
// 跳转研判页并带上会话号
      router.push({ path: "/anomaly-chat", query: { session: j.data.session_id } })
    } else {
      NotifyPlugin.warning({ title: "提示", content: j.error || "创建对话失败" })
    }
  } catch {
    NotifyPlugin.error({ title: "错误", content: "网络错误" })
  } finally {
    askingId.value = ""
  }
}

// 内核态详情弹窗控制
// syscall 弹窗状态
const syscallSeqVisible = ref(false)
// 当前 syscall 文件路径
const currentSyscallSeqPath = ref('')

// LSM Hook 弹窗状态
const lsmHookVisible = ref(false)
// 当前 LSM Hook 文件路径
const currentLsmHookPath = ref('')

// 资源事实弹窗状态
const resourceFactsVisible = ref(false)
// 当前资源事实内容
const currentResourceFacts = ref('')

// 判定文档弹窗状态
const kernelJudgeVisible = ref(false)
// 当前判定文档路径
const currentKernelJudgePath = ref('')

// syscall 分析弹窗状态
const syscallAnalysisVisible = ref(false)
// 当前 syscall 分析数据
const currentSyscallAnalysisData = ref('')

// 打开内核态判断结果弹窗
function openKernelJudgeDialog(filePath) {
  currentKernelJudgePath.value = filePath
  kernelJudgeVisible.value = true
}

// 打开系统调用分析判断结果弹窗
function openSyscallAnalysisDialog(jsonData) {
  currentSyscallAnalysisData.value = jsonData
  syscallAnalysisVisible.value = true
}

// 下载系统调用分析判断结果
function downloadSyscallJudge(jsonData, roundId) {
  const now = new Date()
  const timestamp = now.getFullYear() + 
    String(now.getMonth() + 1).padStart(2, '0') + 
    String(now.getDate()).padStart(2, '0') + '_' +
    String(now.getHours()).padStart(2, '0') +
    String(now.getMinutes()).padStart(2, '0') +
    String(now.getSeconds()).padStart(2, '0')
  
  // 解析 JSON 数据
  let jsonStr = jsonData
  if (typeof jsonData === 'object') {
    jsonStr = JSON.stringify(jsonData, null, 2)
  } else if (typeof jsonData === 'string') {
    // 尝试解析并格式化
    try {
      const parsed = JSON.parse(jsonData)
      jsonStr = JSON.stringify(parsed, null, 2)
    } catch {
      // 如果解析失败，直接使用原始字符串
      jsonStr = jsonData
    }
  }
  
// 内容转 Blob 触发下载
  const blob = new Blob([jsonStr], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  const fileName = roundId ? `syscall_analysis_${roundId}_${timestamp}.json` : `syscall_analysis_${timestamp}.json`
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

// 获取内核态判断结果预览
function getKernelJudgePreview(filePath) {
  if (!filePath) return ''
  // 显示完整路径
  return filePath
}

// 下载内核态文件
function downloadKernelFile(filePath, baseName, content = null, roundId = null) {
  const now = new Date()
  const timestamp = now.getFullYear() + 
    String(now.getMonth() + 1).padStart(2, '0') + 
    String(now.getDate()).padStart(2, '0') + '_' +
    String(now.getHours()).padStart(2, '0') +
    String(now.getMinutes()).padStart(2, '0') +
    String(now.getSeconds()).padStart(2, '0')
  
  // 资源事实是内容而不是文件路径
  if (content) {
    const blob = new Blob([content], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    const fileName = roundId ? `${baseName}_${roundId}_${timestamp}.json` : `${baseName}_${timestamp}.json`
    link.download = fileName
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
    return
  }
  
  // 文件路径下载
  if (!filePath) return
  const link = document.createElement('a')
// 文件路径下载：走后端文件接口
  link.href = `/api/kernel/file?path=${encodeURIComponent(filePath)}`
  const fileName = roundId ? `${baseName}_${roundId}_${timestamp}.jsonl` : `${baseName}_${timestamp}.jsonl`
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

// 通用筛选函数
function matchesFilter(data) {
  if (!data) return false
  const { query, round_id: roundIdFilter, dateRange } = filters.value
// 关键字匹配：不区分大小写
  const matchQuery = !query || (data.user_query || '').toLowerCase().includes(query.toLowerCase())
// round_id 子串匹配
  const matchRoundId = !roundIdFilter || data.round_id?.includes(roundIdFilter)
// 时间区间匹配：起止边界包含
  const matchDateRange = !dateRange?.length || 
    (!dateRange[0] || data.time_start >= dateRange[0]) && 
    (!dateRange[1] || data.time_end <= dateRange[1])
// 三条件全满足才展示
  return matchQuery && matchRoundId && matchDateRange
}

// 挂载：拉首屏 + 订阅实时增量
onMounted(() => {
  fetchRounds()
// 实时事件：新轮次或轮次更新
  socket.on("new_round_info", (data) => {
// 同 round_id 视为更新
    const idx = rounds.value.findIndex(r => r.round_id === data.round_id)
// 更新已有条目
    if (idx >= 0) { rounds.value[idx] = data }
// 新条目：满足筛选才插入
    else if (matchesFilter(data)) { rounds.value.unshift(data); total.value++ }
    
    // 有新消息且处于筛选状态时显示通知
    const { query, round_id: roundIdFilter, dateRange } = filters.value
// 是否处于筛选状态
    const hasFilter = !!(query || roundIdFilter || dateRange?.length === 2)
    if (hasFilter) {
// 提示有更新，建议刷新条件
      notificationInstance = NotifyPlugin.warning({
        title: '温馨提示',
        content: '有更新消息到达，当前处于筛选状态，建议刷新搜索条件查看最新数据',
        duration: 3000,
      })
    }
  })
})

// 拉取当前页数据（含分页偏移）
async function fetchRounds() {
  loading.value = true
// 分页偏移计算
  const offset = (currentPage.value - 1) * pageSize.value
// 查询参数：limit + offset
  const params = new URLSearchParams({ limit: pageSize.value, offset })
  if (filters.value.query) params.set("query", filters.value.query)
  if (filters.value.round_id) params.set("round_id", filters.value.round_id)
// 时间区间：转 time_from/time_to
  if (filters.value.dateRange && filters.value.dateRange.length === 2) {
    params.set("time_from", filters.value.dateRange[0])
    params.set("time_to", filters.value.dateRange[1])
  }
  try {
// 查询接口
    const r = await fetch("/api/rounds?" + params.toString())
    const j = await r.json()
    if (j.ok) { rounds.value = j.data; total.value = j.total }
  } catch {}
  loading.value = false
}

// 重置筛选：清空条件并回第一页
function resetFilters() { filters.value = { query: "", round_id: "", dateRange: [] }; currentPage.value = 1; fetchRounds() }
// 每页条数变更：回第一页重拉
function onPageSizeChange() { currentPage.value = 1; fetchRounds() }
// 展开/收起切换
function toggleExpand(id) { expandedId.value = expandedId.value === id ? null : id }
// 会话号缩写：首 8 + 尾 4
function shortSid(v) { if (!v) return ""; return v.length > 14 ? v.slice(0, 8) + "…" + v.slice(-4) : v }
// 时间格式化：去掉时区后缀
function fmtTime(t) { if (!t) return ""; return t.replace(/\+\d{4}\s*$/, "").trim() }
// 宽容 JSON 解析：失败返回空数组
function parseJSON(str) { try { return JSON.parse(str || "[]") } catch { return [] } }
// 取 IR 策略列表：兼容 level2.policies 与直挂
function getIRPolicies(irStr) { try { const ir = JSON.parse(irStr || "{}"); const level2 = ir.level2 || ir; return level2.policies || [] } catch { return [] } }

// 获取 IR 对象类型的 tag 主题
function getIRTypeTheme(type) {
// 对象类型→标签主题映射
  const themes = {
    'tool': 'primary',
    'file': 'success',
    'network': 'warning'
  }
  return themes[type] || 'default'
}

// 内核态详情查看
function getKernelPreview(content) {
  if (!content) return ''
  // 如果是文件路径，不显示预览
// 路径形态不预览（走下载/弹窗）
  if (content.includes('/')) return ''
  // 如果内容太长，截取前100个字符
// 超长内容截断预览
  if (content.length > 100) {
    return content.substring(0, 100) + '...'
  }
  return content
}

// 打开资源事实弹窗
function openResourceFactsDialog(content) {
  console.log('openResourceFactsDialog called, content type:', typeof content)
  console.log('openResourceFactsDialog content preview:', content?.substring(0, 300))
// 回填内容
  currentResourceFacts.value = content || ''
// 打开弹窗
  resourceFactsVisible.value = true
}
</script>

<style scoped>
/* 页容器：限宽居中 */
.logs-tab { max-width: 1000px; margin: 0 auto; padding-top: 20px; }
/* 筛选栏：白底卡片 */
.filter-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; background: #fff; border-radius: 12px; padding: 14px 18px; margin-bottom: 16px; border: 1px solid #e8ecf0; box-shadow: 0 1px 4px rgba(0,0,0,0.03); }
/* 状态区右对齐 */
.filter-right { margin-left: auto; display: flex; align-items: center; gap: 8px; }
/* 连接状态点基类 */
.status-dot { width: 8px; height: 8px; border-radius: 50%; }
/* 在线：绿色发光 */
.status-dot.online { background: #00a870; box-shadow: 0 0 4px #00a870; }
/* 离线：灰色 */
.status-dot.offline { background: #ccc; }
/* 状态文字 */
.status-text { font-size: 12px; color: #999; }
/* 总条数 */
.total-text { font-size: 12px; color: #666; font-weight: 500; }
/* 空态居中 */
.empty-state { text-align: center; padding: 80px 0; color: #999; }
/* 卡片纵排 */
.rounds-list { display: flex; flex-direction: column; gap: 12px; }
/* round 卡片：白底圆角 */
.round-card { background: #fff; border-radius: 14px; border: 1px solid #e8ecf0; overflow: hidden; transition: all 0.25s; box-shadow: 0 1px 4px rgba(0,0,0,0.03); }
/* hover 抬升效果 */
.round-card:hover { box-shadow: 0 4px 16px rgba(0,82,217,0.08); border-color: #c8dcff; transform: translateY(-1px); }
/* 卡片头布局 */
.card-header { display: flex; align-items: center; gap: 16px; padding: 18px 24px; cursor: pointer; }
/* 得分徽标基类 */
.score-badge { width: 44px; height: 44px; border-radius: 50%; flex-shrink: 0; }
/* 合规：绿渐变 */
.score-badge.pass { background: linear-gradient(135deg, #00c48f, #00a870); box-shadow: 0 2px 8px rgba(0,168,112,0.3); }
/* 异常：橙渐变 */
.score-badge.fail { background: linear-gradient(135deg, #ff9f43, #ED7B2F); box-shadow: 0 2px 8px rgba(237,123,47,0.3); }
/* 待判定：灰 + 脉冲 */
.score-badge.pending { background: linear-gradient(135deg, #a0aec0, #718096); animation: pulse-badge 1.5s ease-in-out infinite; }
@keyframes pulse-badge { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
/* 主信息弹性填充 */
.card-info { flex: 1; min-width: 0; }
/* 查询原文单行省略 */
.query-text { font-size: 14px; font-weight: 500; color: #333; margin-bottom: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* 元信息行 */
.card-meta { display: flex; align-items: center; gap: 8px; }
/* 时间小字 */
.meta-time { font-size: 12px; color: #999; }
/* 角色标注小字 */
.meta-role { font-size: 10px; color: #bbb; padding-left: 6px; border-left: 1px solid #eee; letter-spacing: .2px; user-select: none; }
/* 展开区：浅底分隔 */
.card-expand { padding: 16px 20px 20px; background: #fafbfc; border-top: 1px solid #f0f0f0; }
/* 审计组容器基类 */
.group-box { border-radius: 12px; padding: 0; margin-bottom: 14px; overflow: hidden; border: none; }
/* Access 组：蓝系渐变 */
.group-box.access-group { background: linear-gradient(135deg, #f0f5ff 0%, #fff 100%); box-shadow: 0 2px 8px rgba(0,82,217,0.06); }
/* View 组：绿系渐变 */
.group-box.view-group { background: linear-gradient(135deg, #f0fff8 0%, #fff 100%); box-shadow: 0 2px 8px rgba(0,168,112,0.06); }
/* Compliance 组：橙系渐变 */
.group-box.compliance-group { background: linear-gradient(135deg, #fffbf5 0%, #fff 100%); box-shadow: 0 2px 8px rgba(237,123,47,0.06); }
/* 组标题：可点展开 */
.group-title { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600; padding: 14px 18px; cursor: pointer; user-select: none; list-style: none; }
/* 隐藏默认三角标记 */
.group-title::-webkit-details-marker { display: none; }
/* 组标题文字占满剩余宽度 */
.group-title span { flex: 1; }
.group-box.access-group .group-title { color: #0052D9; }
.group-box.view-group .group-title { color: #00a870; }
.group-box.compliance-group .group-title { color: #ED7B2F; }
/* 组内块纵排 */
.group-blocks { display: flex; flex-direction: column; gap: 10px; padding: 0 18px 18px; }
/* 子块：半透明白底 */
.sub-block { background: rgba(255,255,255,0.7); border-radius: 8px; padding: 14px 16px; border: 1px solid rgba(0,0,0,0.04); }
/* 子块标题基类 */
.sub-block-header { font-size: 12px; font-weight: 600; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid #eee; }
/* 用户态标题蓝 */
.sub-block-header.user { color: #0052D9; }
/* 内核态标题紫 */
.sub-block-header.kernel { color: #722ed1; }
/* AI 研判标题橙 */
.sub-block-header.ai { color: #ED7B2F; display: flex; align-items: center; justify-content: space-between; }
.sub-block-header.ai > span { flex: 1; }
/* 问问小异按钮不收缩 */
.xy-ask-btn { flex: 0 0 auto; }
.xy-greeting {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
/* 机器人图标样式 */
.xy-greeting__bot {
  flex: 0 0 auto;
  font-size: 22px;
  color: #2b6fff;
  line-height: 1.45;
}
/* 引导正文弹性填充 */
.xy-greeting__main { flex: 1; min-width: 0; }
/* 问候行布局 */
.xy-greeting__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
/* 问候语样式 */
.xy-greeting__hi {
  font-size: 13px;
  font-weight: 600;
  color: #1f2a3d;
}
/* 说明文字样式 */
.xy-greeting__desc {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: #97a0b0;
}
/* 行为卡纵排 */
.action-cards { display: flex; flex-direction: column; gap: 8px; }
/* 单条行为卡 */
.action-chip { background: #fafbfc; border: 1px solid #eee; border-radius: 8px; padding: 10px 14px; }
/* 工具名行 */
.action-tool { margin-bottom: 4px; }
/* 字段前缀小字 */
.tool-field { font-size: 11px; color: #888; margin-right: 4px; }
/* 参数/资源行 */
.action-detail { margin-top: 4px; display: flex; align-items: flex-start; flex-wrap: wrap; gap: 4px; }
.action-detail code { font-size: 11px; color: #666; word-break: break-all; }
/* 资源标签样式 */
.resource-tag { font-size: 11px; color: #0052D9; background: #f0f5ff; padding: 2px 6px; border-radius: 4px; margin-right: 4px; flex-shrink: 0; }
/* IR 策略纵排 */
.ir-policies { display: flex; flex-direction: column; gap: 10px; }
/* 授权对象纵排 */
.ir-objects-list { display: flex; flex-direction: column; gap: 6px; }
/* 对象行布局 */
.ir-obj-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; padding: 4px 0; }
/* 对象标识等宽 */
.ir-ident { font-family: "SF Mono", monospace; font-size: 12px; color: #333; font-weight: 500; }
/* 动作集合小字 */
.ir-act { font-size: 11px; color: #999; }
/* 参数约束组 */
.ir-params { display: flex; flex-wrap: wrap; gap: 4px; margin-left: 4px; }
/* 参数徽标 */
.ir-param-chip { font-size: 11px; background: #f0f5ff; color: #0052D9; padding: 1px 6px; border-radius: 4px; }
/* 判定结论框 */
.judge-box { background: #f8f9fa; border-radius: 8px; padding: 14px; font-size: 12px; line-height: 1.8; color: #555; white-space: pre-wrap; font-family: "SF Mono", "Fira Code", monospace; }
/* 空判定占位 */
.judge-box.empty { color: #ccc; font-style: italic; }
/* 分页栏居中 */
.pagination-bar { margin-top: 20px; display: flex; justify-content: center; padding-bottom: 20px; }
/* 新卡滑入动画 */
.card-slide-enter-active { transition: all 0.4s ease-out; }
/* 滑入起点：上移淡入 */
.card-slide-enter-from { opacity: 0; transform: translateY(-16px); }

/* 内核态轨迹样式 */
/* 内核态条目纵排 */
.kernel-sections { display: flex; flex-direction: column; gap: 12px; }
/* 内核态条目卡 */
.kernel-item { background: #f8f9fa; border-radius: 8px; padding: 12px 14px; border: 1px solid #e8ecf0; }
/* 条目头布局 */
.kernel-item-header { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
/* 条目标签 */
.kernel-item-label { font-size: 12px; font-weight: 600; color: #333; min-width: 100px; }
/* 文件路径等宽 */
.kernel-item-path { font-size: 11px; color: #0052D9; font-family: "SF Mono", monospace; word-break: break-all; flex: 1; }
/* 预览文本：三行截断 */
.kernel-item-preview { font-size: 11px; color: #666; margin-top: 8px; padding-top: 8px; border-top: 1px dashed #e8ecf0; max-height: 60px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }
.kernel-item.resource-facts .kernel-item-label { min-width: 80px; }

</style>
