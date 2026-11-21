<!--
  AI 调整敏感权限配置页（策略库 → 敏感文件 Tab）
  数据流：GET/PUT /api/translator/sensitive/config（保存前红线校验、版本自增），
         POST /api/translator/sensitive/generate（流式 AI 建议）。
  设计要点：AI 只出建议（add/narrow/remove），采纳与保存均为显式人工动作；
  保存经红线校验（如按扩展名收录 *.pem 即阻断），每版可回溯。
-->
<template>
  <div class="sens">
    <!-- 页头卡片：判定模型说明 + AI 参数入口 + AI 建议面板开关 -->
    <div class="hero-card">
      <!-- 盾形图标：与平台安全语义一致的视觉锚点 -->
      <div class="hero-icon"><t-icon name="secured" size="30px" /></div>
      <!-- 标题 + 副标题：一句话回答「本页配置什么、判定怎么生效」 -->
      <div class="hero-body">
        <h3>敏感文件配置 <span class="hero-sub">哪些资源算敏感、什么动作才成立</span></h3>
        <p>按「敏感分组」管理：路径命中分组 + 动作性质相符，才会被判为敏感越权。可以人工维护，也可以让 AI 依据业务需求给出建议；
           <b>AI 只出建议，是否采纳由你决定</b>，保存前会做字段与红线校验。</p>
      </div>
      <div class="hero-actions">
        <!-- AI 参数按钮：打开独立抽屉配置模型/端点（与 IR 翻译模型隔离） -->
        <t-button theme="default" variant="outline" @click="drawer = true">
          <template #icon><t-icon name="setting-1" /></template>AI 参数
        </t-button>
        <!-- AI 建议开关：展开/收起生成面板，不丢失已生成的建议 -->
        <t-button theme="primary" variant="outline" @click="aiPanel = !aiPanel">
          <template #icon><t-icon name="bulb" /></template>AI 生成建议
        </t-button>
      </div>
    </div>

    <!-- 统计行：分组总数 / critical / high / any 匹配数 / 配置版本（每次合法保存自增） -->
    <div class="stat-row">
        <!-- 五个统计格实时反映 groups 与 meta：改动后保存即刷新 -->
        <!-- 分组数：当前生效的敏感分组总量 -->
      <div class="stat"><div class="n">{{ groups.length }}</div><div class="l">敏感分组</div></div>
      <div class="stat"><div class="n">{{ countBy('critical') }}</div><div class="l">critical</div></div>
<!-- critical 分组数：实时统计 -->
      <div class="stat"><div class="n">{{ countBy('high') }}</div><div class="l">high</div></div>
<!-- high 分组数：实时统计 -->
      <div class="stat"><div class="n">{{ countMatch('any') }}</div><div class="l">读到即成立（any）</div></div>
<!-- any（读到即成立）匹配数 + 配置版本（每次合法保存自增） -->
      <div class="stat"><div class="n">{{ meta.version || '-' }}</div><div class="l">配置版本</div></div>
    </div>

    <!-- 判定模型折叠说明：三条件（资源性质+动作性质+主体越界）与五条红线，改动前必读 -->
    <details class="fold">
      <summary>判定模型与红线（改动前必读）</summary>
      <div class="fold-body">
        <p><b>判定三条件（同时满足才算敏感越权）：</b></p>
        <ol>
          <!-- 条件一（资源性质）：prefixes 前缀匹配与 globs 通配的边界语义 -->
          <li><b>资源性质</b>：路径命中某分组（<code>prefixes</code> 用 startswith；<code>globs</code> 中 <code>*</code> 不跨路径分隔符，<code>**</code> 跨目录）</li>
          <!-- 条件二（动作性质）：any 读即成立（凭据）；write_only 仅写入成立（持久化面/二进制目录） -->
          <li><b>动作性质</b>：分组 <code>match</code> 与实际动作相符 —— <code>any</code> 读到即成立（凭据类）；<code>write_only</code> 仅在观测到 write/create/delete 时成立（持久化面、二进制目录，读它们是常规行为）</li>
          <li><b>主体越界</b>：由分析器判定，不在此配置表达</li>
          <!-- 条件三（主体越界）：由分析器层判定，本页不表达 -->
        </ol>
        <!-- 红线区：与后端 validate_config 的五条强制/提示规则一一对应 -->
        <p class="warn-line"><b>红线：</b>① 不要按扩展名收 <code>*.pem</code> / <code>*.crt</code>（公开 CA 证书包会误判为私钥材料），私钥容器只收 <code>.p12</code> / <code>.pfx</code>；
          ② 不要用放宽敏感规则来压误报（误报要修根因，如 IR 授权缺失）；③ 前缀会连带命中，收窄优先用精确 glob；
          ④ 每条分组必须带 <code>reason</code>（威胁语义）与 <code>basis</code>（公开依据）；⑤ <code>severity</code> 只影响展示与排序，不参与判定。</p>
      </div>
    </details>

    <!-- AI 建议面板（aiPanel 控制显隐）：需求输入 → 流式生成 → 建议卡片逐条采纳（合并到本地） -->
    <section v-if="aiPanel" class="panel ai-panel">
      <!-- 面板头：灯泡图标 + 「独立模型参数」提示（AI 配置与 IR 翻译模型隔离） -->
      <div class="panel-head"><t-icon name="bulb" /> AI 建议生成（独立模型参数）</div>
      <!-- 需求输入区：占位示例覆盖「新增分组」与「收窄误报」两类典型写法 -->
      <label class="fi"><span>业务需求 / 改动意图</span>
        <t-textarea v-model="requirement" :autosize="{ minRows: 3, maxRows: 8 }"
                    placeholder="例：新增数据库备份目录为敏感资源，仅落盘写入才成立；近期发现读取 /etc/environment 的误报，请给出收窄建议" />
      </label>
      <div class="row-actions">
        <!-- 生成按钮：loading 期间禁用；需求为空时不可点；副文本强调只产出建议不落盘 -->
        <t-button theme="primary" :loading="aiBusy" :disabled="!requirement.trim()" @click="doGenerate">
          <template #icon><t-icon name="play" /></template>生成建议
        </t-button>
        <span class="dim">生成只产出建议，不会自动修改配置</span>
      </div>
<!-- AI 流式过程文本：终端风格暗色块，实时刷新 -->
      <div v-if="aiText" class="stream"><pre>{{ aiText }}</pre></div>
      <div v-if="suggestions.length" class="sug-list">
        <div v-for="(s, i) in suggestions" :key="i" class="sug">
          <!-- 建议卡头部：动作三色标签（add 蓝/narrow 黄/remove 红）+ 分组名 + 匹配/级别 -->
          <div class="sug-head">
            <t-tag :theme="actionTheme(s.action)" size="small" variant="light">{{ s.action }}</t-tag>
            <b>{{ s.group?.title || s.id || '未命名' }}</b>
            <span class="dim">{{ s.group?.match }} · {{ s.group?.severity }}</span>
          </div>
          <!-- 建议正文：rationale 是采纳决策的核心依据 -->
          <div class="dim">理由：{{ s.rationale || '—' }}</div>
          <!-- 建议的 globs 预览：等宽字体直接展示目标路径模式，采纳前可核对 -->
          <div v-if="s.group?.globs?.length" class="mono dim">globs: {{ s.group.globs.join(' , ') }}</div>
          <div class="row-actions">
            <!-- 采纳按钮：合并到本地 groups，之后仍需人工点「保存配置」落盘 -->
            <t-button size="small" theme="primary" variant="outline" @click="adopt(s)">采纳（合并到本地）</t-button>
          </div>
        </div>
      </div>
      <!-- AI 总结：done 事件随建议一起返回的一句话归纳 -->
      <div v-if="aiSummary" class="dim">AI 总结：{{ aiSummary }}</div>
    </section>

    <!-- 敏感分组管理面板：头部操作（重载/新增/保存）+ 卡片网格 + 校验结果区 -->
    <section class="panel">
      <!-- 分组面板头：图标 + 分组计数 + 右侧三按钮（重载/新增/保存） -->
      <div class="panel-head">
        <!-- 面板头首行：图标 + 分组计数 -->
        <t-icon name="app" /> 敏感分组（{{ groups.length }}）
        <!-- 头部动作区：margin-left:auto 推到右侧；重载放弃本地修改回到服务端版本 -->
        <div class="head-actions">
          <t-button size="small" theme="default" variant="outline" @click="reload">重新加载</t-button>
          <!-- 重新加载：放弃本地修改、回到服务端版本 -->
          <!-- 新增：空表单打开对话框 -->
          <t-button size="small" theme="primary" variant="outline" @click="openNew">
            <template #icon><t-icon name="add" /></template>新增分组
          </t-button>
          <!-- 保存：唯一落盘入口，经红线校验 + 版本自增 -->
          <t-button size="small" theme="primary" :loading="saving" @click="save">保存配置</t-button>
        </div>
      </div>

      <!-- 分组卡片网格：severity/match/ATT&CK 标签行 + 路径规则折叠 + reason/basis 必填可视化 -->
        <!-- 分组卡片循环：key 优先用 id，未保存的新增退化为索引 -->
      <div class="grid">
        <div v-for="(g, i) in groups" :key="g.id || i" class="gcard">
          <!-- 卡片头：severity 双色标签（critical 红/high 黄）+ 标题 + match + 穿透标记 -->
          <div class="g-head">
            <t-tag :theme="g.severity === 'critical' ? 'danger' : 'warning'" size="small" variant="light">
              {{ g.severity }}
            </t-tag>
            <!-- 分组标题（缺 title 时回退 id）与 match 标签 -->
            <b>{{ g.title || g.id }}</b>
            <t-tag size="small" variant="outline">{{ g.match }}</t-tag>
            <!-- 穿透运行时标记：凭据类分组的特殊能力 -->
            <t-tag v-if="g.override_runtime" size="small" theme="danger" variant="outline">穿透运行时</t-tag>
          <!-- gid：等宽字体展示技术标识 -->
          </div>
          <!-- ATT&CK 编号：有值才渲染，供报告与威胁狩猎引用 -->
          <div class="dim gid">{{ g.id }}</div>
          <div v-if="g.attck?.length" class="dim">ATT&amp;CK：{{ g.attck.join(' · ') }}</div>
          <!-- 路径规则折叠块：prefixes（startswith）与 globs（* 不跨分隔符 / ** 跨目录） -->
          <details class="g-detail">
            <!-- summary 显示路径规则条数（prefixes+globs） -->
            <summary>路径规则（{{ (g.prefixes || []).length + (g.globs || []).length }}）</summary>
            <!-- prefixes/globs 等宽展示：与判定器的两种路径语义对应 -->
            <div v-if="g.prefixes?.length" class="mono">prefixes: {{ g.prefixes.join(' , ') }}</div>
            <div v-if="g.globs?.length" class="mono">globs: {{ g.globs.join(' , ') }}</div>
          </details>
          <!-- reason/basis 缺失显式标注：与后端「必填即阻断」校验同一口径 -->
          <div class="g-reason">{{ g.reason || '（缺少 reason）' }}</div>
          <!-- basis：公开依据（ATT&CK/CIS 等），缺失时显式标注 -->
          <div class="dim">依据：{{ g.basis || '（缺少 basis）' }}</div>
          <!-- 卡片操作：编辑/删除均为本地操作，保存后落盘 -->
          <div class="g-ops">
            <!-- 编辑：按索引回填表单打开对话框 -->
            <t-button size="small" variant="text" theme="primary" @click="openEdit(i)">编辑</t-button>
            <t-button size="small" variant="text" theme="danger" @click="removeGroup(i)">删除</t-button>
          </div>
        </div>
      </div>

      <!-- 校验结果区：E 级错误阻断保存、W 级警告可带过——与后端 validate_config 双通道一致；
           渲染顺序 E 红条在前、W 黄条在后 -->
      <div v-if="validation && (validation.errors?.length || validation.warnings?.length)" class="validate">
        <!-- E 级错误条：阻断保存，修复后重试 -->
        <div v-for="e in validation.errors || []" :key="e" class="v err">E · {{ e }}</div>
        <!-- W 级警告条：可带过但应知晓 -->
        <div v-for="w in validation.warnings || []" :key="w" class="v warn">W · {{ w }}</div>
      </div>
    </section>

    <!-- 分组编辑/新增对话框（头部随 editing 双态切换：新增/编辑）：字段与后端结构一一对应、
         顺序便于对照 JSON，多值字段按行编辑；提交仅合并本地（commitEdit），落盘统一走「保存配置」 -->
    <t-dialog v-model:visible="editDlg" :header="editing === null ? '新增敏感分组' : '编辑敏感分组'"
              width="720px" :confirm-btn="{ content: '确定', theme: 'primary' }" @confirm="commitEdit">
      <div class="edit-form">
        <!-- 基础字段双列网格：id/title（id 正则约束与后端 ID_RE 一致，新增时查重） -->
        <div class="grid2">
          <!-- id 与判定器索引一致：小写字母/数字/下划线，新增时前端查重 -->
          <label class="fi"><span>id（小写字母/数字/下划线）</span><t-input v-model="form.id" placeholder="如 db_backup" /></label>
          <label class="fi"><span>title</span><t-input v-model="form.title" placeholder="如 数据库备份目录" /></label>
        </div>
        <!-- 判定字段双列网格：severity（critical/high）/ match（any/write_only） -->
        <div class="grid2">
          <!-- severity 只影响展示排序，不参与判定（红线⑤） -->
          <label class="fi"><span>severity</span>
            <t-select v-model="form.severity" :options="[{label:'critical',value:'critical'},{label:'high',value:'high'}]" />
          </label>
          <!-- match 是判定三条件之二：any 读到即成立 / write_only 仅写入成立 -->
          <label class="fi"><span>match</span>
            <t-select v-model="form.match"
                      :options="[{label:'any（读到即成立）',value:'any'},{label:'write_only（仅写入成立）',value:'write_only'}]" />
          </label>
        </div>
        <!-- override_runtime：凭据类建议开启——可穿透「运行时白名单」的放宽判定 -->
        <label class="fi"><span>override_runtime（凭据类建议开启，可穿透运行时白名单）</span>
          <t-select v-model="form.override_runtime" :options="[{label:'否',value:false},{label:'是',value:true}]" />
        </label>
        <!-- ATT&CK 编号：供威胁狩猎与报告对齐（如 T1552.001 凭据文件） -->
        <label class="fi"><span>ATT&amp;CK 编号（逗号分隔）</span>
          <t-input v-model="attckText" placeholder="如 T1552.001, T1558" />
        </label>
        <!-- prefixes 文本域：startswith 语义，整目录前缀会连带命中（红线③） -->
        <label class="fi"><span>prefixes（每行一条，startswith 语义）</span>
          <t-textarea v-model="prefixText" :autosize="{ minRows: 2, maxRows: 6 }" placeholder="/etc/" />
        </label>
        <!-- 路径规则编辑：prefixes/globs 文本域，每行一条，保存时按行拆数组 -->
        <label class="fi"><span>globs（每行一条，* 不跨分隔符，** 跨目录）</span>
          <t-textarea v-model="globText" :autosize="{ minRows: 3, maxRows: 10 }" placeholder="/etc/shadow&#10;**/.ssh/**" />
        </label>
        <!-- reason/basis 必填：缺任一后端按 E 级阻断保存（红线④） -->
        <label class="fi"><span>reason（威胁语义，必填）</span>
          <t-textarea v-model="form.reason" :autosize="{ minRows: 2, maxRows: 6 }" />
        </label>
        <!-- basis 输入：来源须可验证（ATT&CK / CIS / Falco / auditd） -->
        <label class="fi"><span>basis（公开依据，必填：ATT&amp;CK / CIS / Falco / auditd）</span>
          <t-textarea v-model="form.basis" :autosize="{ minRows: 2, maxRows: 6 }" />
        </label>
        <!-- 红线提醒常驻对话框：保存时后端会再次强制校验 -->
        <p class="dim">红线提醒：不要收 <code>*.pem</code> / <code>*.crt</code>；保存时会校验。</p>
      </div>
    </t-dialog>

    <!-- AI 参数抽屉组件：独立于 IR 翻译的模型配置（模型/端点/温度） -->
    <SensitiveConfigDrawer v-model:visible="drawer" />
  </div>
</template>

<script setup>
// 本页状态与动作：分组加载/保存/校验、AI 建议生成与采纳、编辑对话框表单。
// 组件导入：TDesign 全局消息插件 + AI 参数抽屉子组件。
import { ref, computed, onMounted } from "vue"
import { MessagePlugin } from "tdesign-vue-next"
import SensitiveConfigDrawer from "./SensitiveConfigDrawer.vue"

// 管理员请求头：敏感配置的读写接口需特权验证，token 由登录态注入。
const ADMIN_HEAD = () => ({
  "Content-Type": "application/json",
  "X-Admin-Session": sessionStorage.getItem("clawavc_admin_session") || "",
})

// UI 开关状态：AI 参数抽屉 / AI 建议面板 / 编辑对话框；aiPanel 默认收起（不遮挡人工核对主流程）。
const drawer = ref(false)
const aiPanel = ref(false)

// 配置主体：groups 为敏感分组数组，meta 记录版本/时间/来源；
// validation 三态：null（未校验）/ {errors,warnings}（后端返回）/ 成功时也带 warnings。
const groups = ref([])
const meta = ref({})
// saving：保存按钮 loading（保存期间防重复提交）。
const saving = ref(false)
const validation = ref(null)

// AI 建议状态：requirement 为业务需求输入（生成按钮的禁用条件即 trim 非空），
// suggestions 为结构化建议（含 action/理由），aiText 为流式原始输出（调试可见），
// aiSummary 为 done 事件随建议返回的一句话归纳，展示在建议列表尾部。
const requirement = ref("")
const suggestions = ref([])
const aiText = ref("")
const aiSummary = ref("")
const aiBusy = ref(false)

// 分组编辑对话框状态：editing 为 null 表示新增（提交时 push）、索引表示编辑（按下标替换）；
// attck/prefixes/glob 三类多值字段以文本域编辑、按行互转数组（与对话框占位一致）。
const editDlg = ref(false)
const editing = ref(null)
const attckText = ref("")
const prefixText = ref("")
const globText = ref("")
// emptyForm：新增表单骨架——缺省 write_only/high（保守判定起点）；
// 每次调用产新对象（deep copy 语义），避免多次新增共享引用。
const emptyForm = () => ({ id: "", title: "", severity: "high", match: "write_only",
  override_runtime: false, attck: [], prefixes: [], globs: [], reason: "", basis: "" })
const form = ref(emptyForm())

// 统计与建议动作的纯展示辅助（每次渲染即时计算，规模小无性能问题）：
// countBy/countMatch 按条件计数；actionTheme 建议动作主题色——
// add=蓝(primary)/narrow=黄(warning)/remove=红(danger)，与判定严重度直觉一致。
const countBy = (sev) => groups.value.filter(g => g.severity === sev).length
const countMatch = (m) => groups.value.filter(g => g.match === m).length
const actionTheme = (a) => (a === 'add' ? 'primary' : (a === 'remove' ? 'danger' : 'warning'))

// reload：只读刷新 groups/meta（含版本号），丢弃未保存的本地修改；
// 不做错误提示：首屏静默失败按空态渲染，手动「重新加载」可见错误。
async function reload() {
// 只读拉取：GET 配置接口（无管理员头，敏感配置读取对外开放给登录态）
  const j = await (await fetch("/api/translator/sensitive/config")).json()
// ok 时回填分组与元信息，失败静默（首屏按空态渲染）
  if (j.ok) { groups.value = j.data.sensitive_groups || []; meta.value = j.data.meta || {} }
  validation.value = null
}

// save：本地 groups → 后端保存接口；保存被校验拦截时错误展示在下方校验区。
// 请求体 meta（原版本号）+ groups 全量——后端 version+1 后回传；
// 成功时回写服务端权威数据（含归一化后的 groups），前端不自行推断；
// 服务端保存同时返回 validation：成功响应也可能携带 warning（可带过项）；
// 保存被拦截：errors/warnings 结构与成功时同构，统一展示在页面底部校验区。
async function save() {
  saving.value = true
  try {
// PUT 保存：携带 meta（原版本号）+ 全量分组，后端做红线校验后版本自增
    const r = await fetch("/api/translator/sensitive/config", {
      method: "PUT", headers: ADMIN_HEAD(),
// 请求体：与后端 validate/save 契约一致的三段式结构
      body: JSON.stringify({ meta: meta.value, sensitive_groups: groups.value }),
    })
    const j = await r.json()
// 成功：回写服务端权威数据（含归一化 groups），前端不自行推断
    if (j.ok) {
      MessagePlugin.success("敏感文件配置已保存（版本 " + (j.data.meta?.version || '-') + "）")
// 归一化后的分组回填（后端可能补齐缺省字段）
      groups.value = j.data.sensitive_groups || []
      meta.value = j.data.meta || {}
      validation.value = j.data.validation || null
    } else {
// 失败：errors/warnings 与成功响应同构，统一进底部校验区
      validation.value = { errors: j.errors || [j.error || '保存失败'], warnings: j.warnings || [] }
      MessagePlugin.error("保存被校验拦截，请查看下方提示")
    }
  } finally { saving.value = false }
}

// 打开新增对话框：表单重置为空骨架（缺省 write_only/high）；
// 三类文本域同步清空，防止上次编辑残留。
function openNew() {
  editing.value = null
// 新增表单重置：三文本域同步清空防止上次编辑残留
  form.value = emptyForm()
  attckText.value = ""; prefixText.value = ""; globText.value = ""
  editDlg.value = true
}

// 打开编辑对话框：数组字段转文本（每行一项）便于编辑；
// 深拷贝后合并空骨架：老数据缺新字段时以缺省补齐（向前兼容）。
function openEdit(i) {
  editing.value = i
// 深拷贝后合并空骨架：老数据缺新字段时以缺省补齐（向前兼容）
  const g = JSON.parse(JSON.stringify(groups.value[i]))
  form.value = { ...emptyForm(), ...g }
// 数组字段转文本（每行一项），便于文本域编辑
  attckText.value = (g.attck || []).join(", ")
  prefixText.value = (g.prefixes || []).join("\n")
  globText.value = (g.globs || []).join("\n")
  editDlg.value = true
}

// 提交编辑：文本域转数组、合并进 groups；不直接保存——
// 「合并到本地 → 人工核对 → 显式保存」三段式保证采纳权归人。
// 表单组包：trim 处理 + 布尔强转，三类多值字段逗号/换行拆分 + 空项过滤，保证落库类型稳定；
// 新增查重与替换分支：id 冲突前端拦截，后端校验兜底。
function commitEdit() {
  const g = {
    id: form.value.id.trim(), title: form.value.title.trim(), severity: form.value.severity,
    match: form.value.match, override_runtime: !!form.value.override_runtime,
// 表单组包：trim + 布尔强转；三类多值字段按逗号/换行拆分 + 空项过滤
    attck: attckText.value.split(",").map(s => s.trim()).filter(Boolean),
    prefixes: prefixText.value.split("\n").map(s => s.trim()).filter(Boolean),
    globs: globText.value.split("\n").map(s => s.trim()).filter(Boolean),
    reason: form.value.reason.trim(), basis: form.value.basis.trim(),
  }
  // 新增查重与替换分支：id 冲突前端拦截，后端校验兜底
// 新增分支：id 冲突前端拦截，后端校验兜底
  if (editing.value === null) {
// id 查重：已存在则提示并中断提交
    if (groups.value.some(x => x.id === g.id)) { MessagePlugin.warning("id 已存在"); return }
    groups.value.push(g)
  } else {
    groups.value[editing.value] = g
  }
  editDlg.value = false
}

// 删除分组：仅从本地 groups 移除，保存后生效（可反悔）。
function removeGroup(i) {
  groups.value.splice(i, 1)
}

// doGenerate：请求体携带当前全量配置（AI 的 narrow/remove 建议需要「现状」作为基准）；
// 生成前清空上次结果：aiBusy 控制按钮 loading，防重复提交；
// 响应为 SSE 流：text 事件逐步显示（后端每次发累计文本，前端无需拼接）、
// done 事件一次性交付结构化建议（suggestions 为空时下方有兜底提示）。
async function doGenerate() {
// 生成前清空上次结果；aiBusy 控制按钮 loading 防重复提交
  aiBusy.value = true; aiText.value = ""; suggestions.value = []; aiSummary.value = ""
  try {
    const r = await fetch("/api/translator/sensitive/generate", {
      method: "POST", headers: ADMIN_HEAD(),
      body: JSON.stringify({ requirement: requirement.value, current: { meta: meta.value, sensitive_groups: groups.value } }),
    })
    // 增量解码与分帧：跨 chunk 的半行留在 buf 等下一段，坏 JSON 行安全跳过。
// 增量解码：跨 chunk 半行留 buf 等下一段，坏 JSON 行安全跳过
    const reader = r.body.getReader(); const dec = new TextDecoder()
    let buf = ""
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
// SSE 分帧：按空行切事件，余量回写 buf
      const parts = buf.split("\n\n"); buf = parts.pop() || ""
      for (const p of parts) {
        const line = p.split("\n").find(l => l.startsWith("data: "))
        if (!line) continue
        // 事件三分派：text（过程文本）/ error（失败提示）/ done（建议落地）。
// 事件解析：text/error/done 三分派
        const ev = JSON.parse(line.slice(6))
        if (ev.type === "text") aiText.value = ev.data
        else if (ev.type === "error") MessagePlugin.error(ev.message || "生成失败")
        else if (ev.type === "done") {
// done：结构化建议一次性交付（suggestions + summary）
          suggestions.value = ev.data.suggestions || []
          aiSummary.value = ev.data.summary || ""
        }
      }
    }
    // 兜底提示：既无建议也无过程文本时引导补充需求
    if (!suggestions.value.length && !aiText.value) MessagePlugin.warning("未生成建议，可补充更具体的业务需求")
  } catch (e) { MessagePlugin.error(String(e)) } finally { aiBusy.value = false }
}

// adopt(s)：remove 删本地条目；add/narrow 走浅合并（建议字段优先，未提及字段保留现状）——
// narrow 建议通常只带新 globs，保留原 reason/basis 不丢审计依据；
// 建议缺 id 不采纳：结构化契约不满足时拒绝合并（防半成品分组）；
// 采纳成功提示引导用户显式保存：合并 ≠ 落盘。
function adopt(s) {
  const g = s.group || {}
// 结构化契约校验：缺 id 的建议拒绝采纳（防半成品分组）
  if (!g.id) { MessagePlugin.warning("建议缺少 id，无法采纳"); return }
  const idx = groups.value.findIndex(x => x.id === g.id)
// 定位同 id 分组：决定 add 覆盖还是新增
  if (s.action === "remove") {
    if (idx >= 0) groups.value.splice(idx, 1)
  } else {
// 浅合并：建议字段优先，未提及字段保留现状（narrow 不丢审计依据）
    const merged = { ...(idx >= 0 ? groups.value[idx] : {}), ...g }
    if (idx >= 0) groups.value[idx] = merged
    else groups.value.push(merged)
  }
  MessagePlugin.success(`已采纳：${g.id}（请点「保存配置」落盘）`)
}

// 挂载即加载配置：进入页面即展示当前生效分组与版本。
onMounted(reload)
</script>

<style scoped>
/* 本页样式：页头 hero 卡 + 统计行 + 折叠说明 + AI 面板 + 卡片网格 + 校验提示 */
.sens { display: flex; flex-direction: column; gap: 16px; }
/* hero 卡：深蓝渐变横幅，图标/标题/说明/动作左对齐 */
.hero-card { display: flex; align-items: flex-start; gap: 14px; padding: 18px 20px; border-radius: 14px;
  background: linear-gradient(135deg, #0F172A 0%, #1E3A8A 55%, #2563EB 100%); color: #fff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, .18); }
/* 盾形图标：46px 圆角托盘，深底白标 */
.hero-icon { flex: 0 0 46px; height: 46px; border-radius: 12px; display: grid; place-items: center;
  background: rgba(255, 255, 255, .16); }
/* hero 主体与标题层级：副标题弱化跟随 */
.hero-body { flex: 1; }
.hero-body h3 { margin: 0 0 6px; font-size: 20px; font-weight: 600; }
.hero-sub { font-size: 13px; font-weight: 400; opacity: .85; margin-left: 8px; }
.hero-body p { margin: 0; font-size: 14px; line-height: 1.8; opacity: .92; }
/* hero 动作行：两个入口按钮可换行 */
.hero-actions { display: flex; gap: 10px; flex-wrap: wrap; }
/* 统计行：五格数字卡片（分组数/critical/high/any/版本），窄屏降两列 */
.stat-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
@media (max-width: 900px) { .stat-row { grid-template-columns: repeat(2, 1fr); } }
/* 统计卡：白底圆角 + 居中数字 */
.stat { background: #fff; border: 1px solid #E5E7EB; border-radius: 12px; padding: 12px 14px; text-align: center; }
/* 统计格：数字大号深蓝、标签小号灰 */
/* 统计数字：大号深蓝；标签小号灰 */
.stat .n { font-size: 22px; font-weight: 600; color: #1E3A8A; line-height: 1.3; }
.stat .l { font-size: 12px; color: #8A94A6; }
/* 面板：白底圆角容器；ai-panel 左侧蓝条区分 AI 区块 */
.panel { background: #fff; border: 1px solid #E5E7EB; border-radius: 14px; padding: 18px 20px; }
/* 面板头：图标+标题+右侧动作区，允许换行 */
.panel-head { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: #1F2329; margin-bottom: 14px; flex-wrap: wrap; }
.head-actions { margin-left: auto; display: flex; gap: 8px; flex-wrap: wrap; }
/* AI 面板左侧蓝条：与普通分组面板视觉区分 */
.ai-panel { border-left: 4px solid #2563EB; }
/* 折叠说明：判定三条件与红线，改动前展开阅读 */
/* 折叠说明块：浅底容器 */
.fold { background: #FCFDFF; border: 1px solid #E5E7EB; border-radius: 12px; padding: 12px 16px; }
.fold summary { cursor: pointer; font-weight: 600; color: #1E3A8A; }
/* 折叠正文与红线警示条（黄底） */
.fold-body { font-size: 13.5px; color: #4E5969; line-height: 1.8; }
.warn-line { color: #8A5A00; background: #FEF3E2; border: 1px solid #F3D9AF; border-radius: 8px; padding: 8px 12px; }
/* 分组卡片网格：两列，窄屏单列 */
/* 分组卡片网格：两列，窄屏单列 */
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
/* gcard：分组卡片（severity 标签 + 路径规则折叠 + reason/basis + 操作按钮） */
.gcard { border: 1px solid #E5E7EB; border-radius: 12px; padding: 14px 16px; background: #FCFDFF;
  display: flex; flex-direction: column; gap: 6px; }
/* 卡片头：标签行 flex 换行 */
.g-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 14.5px; }
/* gid 等宽：技术标识与展示字体区分 */
.gid { font-family: "SFMono-Regular", Consolas, monospace; }
/* 路径规则折叠块：summary 手型可点 */
/* 路径规则折叠块：summary 手型可点 */
.g-detail { margin-top: 4px; }
.g-detail summary { cursor: pointer; font-size: 13px; color: #1E3A8A; }
/* reason 行：威胁语义展示 */
.g-reason { font-size: 13.5px; }
/* 卡片操作行：编辑/删除 */
.g-ops { display: flex; gap: 6px; margin-top: 6px; }
.fi { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: #4E5969; margin-bottom: 12px; }
/* 编辑对话框双列网格 + 全宽字段 */
/* 编辑对话框双列网格 */
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.row-actions { display: flex; align-items: center; gap: 10px; margin: 12px 0; flex-wrap: wrap; }
.dim { color: #A6A6A6; font-size: 12.5px; }
.mono { font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; }
/* stream：AI 流式输出的终端风格暗色代码块 */
.stream pre { margin: 10px 0; padding: 12px; background: #0F172A; color: #CBD5E1; border-radius: 8px;
  font-size: 12px; max-height: 240px; overflow: auto; }
/* sug 卡片与头部布局：动作标签 + 标题 + 理由 + 采纳按钮 */
/* 建议列表：纵排卡片 */
.sug-list { display: flex; flex-direction: column; gap: 10px; }
.sug { border: 1px solid #E5E7EB; border-radius: 10px; padding: 12px 14px; background: #FCFDFF; }
.sug-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
/* 校验结果区：E 阻断红 / W 提示黄，纵排 */
.validate { margin-top: 14px; display: flex; flex-direction: column; gap: 6px; }
/* 校验结果区：E 阻断红 / W 提示黄 */
.v { font-size: 13px; }
.v.err { color: #E34D59; }
.v.warn { color: #D97706; }
</style>
