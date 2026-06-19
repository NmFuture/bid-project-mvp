# 商务素材模块 UI 修复 Handoff

> **用途**：把"原始素材 / Wiki / 业绩库"三页的 UI 评审结论交接给后续修复 Agent（Codex）。
> 本文档**自包含**——不依赖任何对话上下文即可执行。每条问题都给出 `file:line`、现象、原因、具体改法。
> 评审方式：真实浏览器截图 + 像素级测量 + 逐维度 66-agent 评审并对照源码对抗式验证（47 条确认，3 条驳回）。
> 评审日期：2026-06-04 · 视口基准：1280px · 登录身份：商务标主管（business）。

---

## 0. 给修复 Agent 的执行须知（务必先读）

### 0.1 三个页面与路由
| 页面 | URL | 源文件 |
|---|---|---|
| 原始素材 | `/workspace/business/materials/raw` | `src/workspaces/business/pages/BusinessMaterialDB.jsx`（2483 行） |
| Wiki | `/workspace/business/materials/wiki` | `src/workspaces/business/pages/BusinessMaterialWiki.jsx`（264 行） |
| 业绩库 | `/workspace/shared/materials/performance` | `src/workspaces/business/pages/BusinessPerformanceLibrary.jsx`（679 行） |

三页共用顶部头/切换栏 `src/workspaces/business/components/BusinessMaterialsViewSwitch.jsx`。
Wiki 内容渲染用 `src/components/shared/MarkdownLite.jsx`。
全页状态用 `src/components/states/PageState.jsx`（`PageLoading/PageEmpty/PageError`，居中卡片，`min-h-[40vh]`）。
容器是 `src/components/layout/AppShell.jsx`。

### 0.2 ⚠️ 必须先理解的全局规则（`src/index.css`）—— 很多"看起来的字号/阴影 bug"其实是这里造成的，改之前务必对照
- **Tailwind v4**，无 `tailwind.config.js`，主题写在 `@theme {}`（`index.css:16-104`）。
- **字号被收口**（`:87-104`）：`--text-base == --text-sm == 0.875rem`（14px）；`--text-lg = 1rem`（16px）；`--text-xl / 2xl / 3xl / 4xl` **全部 = 1.125rem**（18px）。→ 写 `text-2xl` 不会变大，只有 18px。
- **`@layer utilities`**（`:150-178`）：`.text-[10px]` 和 `.text-[11px]` 被**全局上调为 12px**；`.text-[16px]` 有显式规则会生效。→ 想要 <12px 的字号，写 `text-[10px]` 是**无效**的。
- **字重映射**（`:151-160`）：`font-bold / font-semibold / font-extrabold` 全 = 600；`font-medium` = 500。
- **全局表格**（`:217-247`）：`table thead th` 和 `tbody td` 被**强制 `height:40px`**，th `font-weight:500`，并加了斑马纹/hover 底色。→ 紧凑小表会被撑松，需要 `!h-auto` 才能覆盖。
- **`main` 内阴影被压平**（`:255-258`）：`main [class*="shadow"] { box-shadow: 0 1px 2px rgba(17,34,51,.06) !important }`。→ 弹窗写 `shadow-2xl` 也会退化成发丝阴影。绕开方式：套已有的 `.wizard-modal-surface`（`:274-277` 有强阴影白名单）或用内联 `style={{boxShadow:...}}`。
- **动画/降级**：`.animate-fade-in`（`:547-549`）= `opacity 0→1 + translateY(8px→0)`，0.3s；`prefers-reduced-motion` 已全局兜底（`:559-573`），新增 `animate-float-in` 等**无需**再单独处理降级。
- **按钮按下位移**：`button:active { transform: translateY(1px) }`（`:187-190`，全局，正常预期内）。

### 0.3 设计 token 速查（改颜色时用这些，别引入未定义 token）
- 主色：`primary` `#0068b7`，`primary-container` `#69c0ff`，`on-primary` 白，`on-primary-container` `#004d87`。
- 成功/绿：`secondary` `#14a83b`，`secondary-container` `#e6f8ec`，`on-secondary-container` `#0f6f2a`。
- 信息/青（项目里当 warning 用）：`tertiary` `#18b7d9`，`tertiary-container` `#e2f8fd`，`on-tertiary-container` `#0a6d80`。
- 错误：`error` `#c54040`，`error-container` `#fde7e7`，`on-error-container` `#8c2222`。
- 文本：`on-surface` `#2a4258`，`on-surface-variant` `#60758a`，`outline` `#95a7ba`，`outline-variant` `#c4d0dc`。
- ❌ **不存在 `--color-warning`**——任何 `bg-warning/*` 都是透明失效的，必须换 token。

### 0.4 验收方式（每改一页都跑一遍）
1. `cd code/sewpg-bid-frontend && npm run dev`（或确认已有 dev server，本机评审时跑在 `http://localhost/`）。
2. 用浏览器分别打开三个 URL，先登录（登录页有"选择身份登录"快捷入口，点"马哥 / 商务标主管"即可直接进 business 工作区）。
3. 至少在 **1280px** 和 **1440px** 两个宽度下检查；P0-A（业绩库表格溢出）必须在 1280px 下确认操作列可达。
4. 控制台必须 **0 error / 0 warning**（评审基线即为 0）。
5. 不要破坏现有交互逻辑，本次修复**只动 UI/className/布局**，不改数据流与 API。

### 0.5 改动纪律
- 这是行为保持型 UI 修复：**只改样式/布局/className/极少量渲染结构**，不改业务逻辑、不改 API、不改 props 契约。
- 每完成一个"修复批次"（见 §4 顺序）单独提交，commit message 用约定式：`fix(materials-ui): <简述>`。
- 改全局 `index.css` 规则前要评估影响面（`grep` 其它页面是否依赖该行为），优先用"白名单类/局部覆盖"而非直接删全局规则。

---

## 1. 🔴 必修（P0 / P1）

> 标 **[实测]** 的是有像素测量数据支撑的硬伤；标 **[验证]** 的是 reviewer 报告并经对照源码确认。

### P0-A · 业绩库主表右侧整列被裁切，操作按钮点不到 **[实测]**
- **文件**：`BusinessPerformanceLibrary.jsx:394`（外层 section）、`:400`（`<table class="... min-w-[1380px]">`）、`:408`（操作列 th `w-[230px]`）、`:460-471`（每行操作按钮）。
- **现象**：表 `min-w-[1380px]` 装在 clientWidth 仅 **1120px**、`overflow-x:auto` 的 section 里。实测（视口 1280）：操作列表头 `left=1269 / right=1499`，即 230px 的操作列只有 11px 露在视口内；`明细 / 上传合同 / 启用·停用 / 删除` 每行都在视口外，状态列也被切掉。内层横向滚动条无视觉提示，用户在常见 1280–1366 笔记本上根本发现不了、也点不到核心操作。
- **原因**：强制 `min-w-[1380px]` + 多列无 `truncate`（见 P1-G）把表撑得过宽；操作列没做"常驻可见"处理。
- **改法（任选其一，推荐组合 ①+②）**：
  1. 收窄表：给型号/时间等列加 `truncate`（见 P1-G），把 `min-w-[1380px]` 降到约 `min-w-[1100px]`。
  2. 操作列常驻：操作 `<th>`（`:408`）和每行操作 `<td>`（`:460`）加 `sticky right-0 z-10 bg-white`（hover/斑马行也要给对应 sticky 背景，避免透出底行）。
  3. 兜底：窄屏把行内 4 个操作收进一个常驻 `more_vert` 下拉菜单。
- **验收**：1280px 下不横向滚动即可看到并点到每行的"删除/明细"等按钮。

---

### P0-B · 全局 `main [class*="shadow"]` 压平所有弹窗阴影 **[验证]**
- **文件**：规则在 `index.css:255-258`；受影响弹窗/浮层：
  - 原始素材：标签筛选下拉 `DB.jsx:624`、上传弹窗 `:1962`、冲突弹窗 `:2244`、标签编辑弹窗 `:2280`、切分弹窗 `:2345`。
  - 业绩库：导入预览弹窗 `:492`、删除弹窗 `:549`、明细弹窗 `:584`。
- **现象**：这些 `shadow-2xl` / `shadow-[0_12px_28px...]` 全退化成 1px 发丝阴影，浮层贴着白底/遮罩、毫无悬浮层级。
- **改法**：弹窗卡片根节点套已有白名单类 **`.wizard-modal-surface`**（`index.css:274-277` 命中强阴影），或直接用内联 `style={{ boxShadow: '0 12px 28px -16px rgba(0,62,111,.28)' }}` 绕开 `[class*=shadow]` 选择器。标签筛选下拉（`DB.jsx:624`）另加 `border-outline-variant` + `bg-surface-container-low` 与白页拉开。
- **注意**：不要直接删 `index.css:255-258`（其它页面可能依赖"扁平化"），用局部覆盖。

---

### P0-C · 字号收口吞掉弹窗/Wiki 标题层级 **[验证]**
- **文件**：规则 `index.css:88-92,163-167`；受影响：弹窗标题 `DB.jsx:2246`（冲突弹窗 h3 `text-base`）、`:2283`（标签编辑 h3 `text-base`）；Wiki `MarkdownLite.jsx:117-122`（compact 档 h1=15px / h2=14px / h3=13px，h3 与正文同号）。
- **现象**：`text-base` 渲染成 14px，与正文同号，标题失去层级；Wiki 文档 h1/h2/h3 拍平。
- **改法**：
  - 弹窗 `<h3>`（`DB:2246/2283`）改 `text-lg`（=16px，对齐同文件 `:1964/:2348` 的 h2）。
  - `MarkdownLite.jsx` compact 样式（`:116-123`）梯度拉开：h1 `text-lg font-bold`（16）、h2 `text-[15px] font-semibold`、h3 `text-[14px] font-semibold`、root `text-[13px]`。

---

### P1-D · Wiki 双栏固定高不等 + 内容区滚动失效 **[实测]**
- **文件**：`BusinessMaterialWiki.jsx:235`（grid）、`:236`（左树 `min-h-[720px] max-h-[720px]`）、`:253-255`（右内容 `min-h-[520px]`，且 `:255` 写了 `overflow-y-auto` 但无 max-height 永不触发）。
- **现象**：实测树=**720px**、内容卡=**522px**，恒定 **198px** 高度差，右下大片空白；左树内部滚、右栏整页滚，滚动模型割裂。
- **改法**：内容容器（`:254` 的 `min-h-[520px]` 那层）改为 `max-h-[720px] min-h-[520px] overflow-hidden`；grid（`:235`）加 `xl:items-stretch`；内容卡用 `flex-1 flex flex-col`、内部正文区 `flex-1 overflow-y-auto` 真正启用内滚，做到两栏等高。

---

### P1-E · Wiki 在 xl 以下单列时 720px 高树霸占首屏 **[验证]**
- **文件**：`BusinessMaterialWiki.jsx:235-236`。
- **现象**：<1280px（常见笔记本/平板）退化单列，720px 固定高树占满首屏，要滚一整屏才见正文。
- **改法**：固定高仅并排时生效——`:236` 改 `max-h-[420px] xl:min-h-[720px] xl:max-h-[720px]`（或 `max-h-[40vh] xl:max-h-[720px]`）。

---

### P1-F · Wiki 内容面板无头部 + 空态只在左上角一行淡字 **[验证]**
- **文件**：`BusinessMaterialWiki.jsx:252-259`；`MarkdownLite.jsx:133-134`（空内容只渲染一行"暂无内容"）。
- **现象**：选中节点后右栏是光秃白盒，不显示标题/路径/更新时间（`normalizeNode` 在 `:14-24` 已备好 `title/pathText/updatedAt` 却没用）；空内容时 520px 白盒只有左上角一行灰字，与全站居中 `PageEmpty`（`PageState.jsx:13-44`，本文件 `:201-208` 已在用）风格自相矛盾。
- **改法**：正文区前插入与左侧同风格头部条（`selectedNode.title` `text-[14px] font-semibold` + `selectedNode.pathText` `text-[12px] text-outline` + 更新时间）；空内容改居中空态（`flex min-h-[440px] items-center justify-center` + `description` 图标 + `text-sm text-on-surface-variant`），或直接复用 `PageEmpty` 风格。

---

### P1-G · 原始素材：文件名被 chip 挤没 **[验证]**
- **文件**：`BusinessMaterialDB.jsx:842`（文件名 span）、`:843-850`（状态/类型 chip，`shrink-0`）、`:851-867`（标签组 `max-w-[14rem] shrink-0`）。所在面板宽度约 30rem（`:1870` grid 轨道 `minmax(30rem,40rem)`）。
- **现象**：文件名（主键信息）被一堆 `shrink-0` chip 挤到只剩几十像素，被 truncate 成"商务承诺函承…"。
- **改法**：文件名 span（`:842`）改 `min-w-0 flex-1 basis-32 truncate`；标签组（`:851-853`）`max-w-[14rem] shrink-0` 改 `min-w-0 shrink max-w-[10rem]`，让标签先收缩；可选：窄屏 `hidden xl:inline-flex` 隐藏标签组。

---

### P1-H · 原始素材：核心操作全 hover 才出现 + hover 抖动 **[验证]**（对应"画面抖动"诉求）
- **文件**：`BusinessMaterialDB.jsx:868`（操作按钮容器 `hidden ... group-hover:inline-flex`）、`:869-921`（重命名/编辑标签/切分/删除 4 个按钮）、`:785-798`（文件夹删除按钮同款 `hidden ... group-hover:inline-flex`）。
- **现象**：4 个核心操作只在 hover 出现——**触屏完全不可达**；hover 瞬间插入约 96px，触发同行文件名二次截断 + 整行布局回流抖动。
- **改法**：操作容器（`:868`）改 `flex shrink-0 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity`，并**预留固定宽度**（如外层 `w-24` 或给容器 `min-w-[6rem]`），让按钮用 `opacity` 显隐而非 `display` 增删，消除回流。文件夹删除按钮（`:785-798`）同样改 `flex`（非 `inline-flex`）+ opacity 方案。更稳妥：每行常驻一个 `more_vert` 菜单入口。
- **验收**：hover 文件行时，文件名宽度不跳动；触屏（或键盘 focus）下操作可达。

---

### P1-I · 原始素材：风险提示用未定义的 `bg-warning/10` **[验证]**
- **文件**：`BusinessMaterialDB.jsx:2442`（切分片段风险提示块 `bg-warning/10`）；同病：`BusinessCoCreationEditor.jsx:480`。
- **现象**：`--color-warning` 未定义 → 背景透明失效，告警块退化成无底色普通文本，看不出是风险提示。
- **改法**：两处统一改 `border border-tertiary/30 bg-tertiary-container/60 text-on-tertiary-container`（项目里 tertiary 即承担 warning 语义）。

---

### P1-J · 原始素材：首屏加载态硬切（CLS）+ 整页入场位移 **[验证]**（对应"画面抖动"诉求）
- **文件**：`BusinessMaterialDB.jsx:1825-1842`（loading return `PageLoading`，`min-h-[40vh]` 小卡片）、`:1844`（内容根 `animate-fade-in`）、`:1870`（内容 `min-h-[680px]` 双栏）。
- **现象**：loading 时是 40vh 小卡片，完成后切到 680px 双栏，整组件替换造成首屏高度跳变；根节点 `animate-fade-in` 的 `translateY(8px)` 让整页入场上移。
- **改法**：始终渲染外层 `MaterialsViewSwitch` + 工具栏 + `min-h-[680px] xl:min-h-[calc(100vh-12rem)]` 的 grid 容器，仅在 grid 内部切换 spinner ↔ 内容；根节点入场动画用纯 opacity（去掉 translateY，可新建 `.animate-fade-in-soft` 只做 opacity，或直接去掉根节点动画）。

---

### P1-K · 业绩库：列表/明细加载抖动与无反馈 **[验证]**（对应"画面抖动"诉求）
- **文件**：`BusinessPerformanceLibrary.jsx:156-181`（query/loadCategories，每次 filter 变更重拉）、`:394-396`（loading 时整表替换成单行"加载中..."）；明细弹窗 `:259-269`（openDetail）、`:582`（`detail &&` 控制显隐）、`:592-594`（`detailLoading ? 加载中`）。
- **现象**：
  - 筛选/排序/翻页每次都把整表替换成单行"加载中…"，逐字符输入时整表塌一行再弹回，剧烈闪烁。
  - 明细弹窗 `detailLoading` 分支**不可达**（弹窗由 `detail &&` 控制，而 `detail` 直到请求返回才赋值）→ 点击后一段死时间再"砰"地满数据弹出。
- **改法**：
  - 拆 `loading`（首次）/`refreshing`（重拉）两态；refetch 时保持 `<table>` 挂载并加 `opacity-60 pointer-events-none` 遮罩；仅 `items.length===0 && loading` 时才显示满屏"加载中"。文本输入加 ~300ms 防抖。
  - 明细：新增 `detailOpen` 开关控制显隐；`openDetail` 先 `setDetailOpen(true); setDetail(null); setDetailLoading(true)`，await 后填充；加载分支用骨架/居中 spinner 占位。

---

### P1-L · 长文本不截断撑破单元格（业绩库为主，原始素材有同类）**[验证]**
- **文件**：业绩库 `BusinessPerformanceLibrary.jsx:419-421`（类别名按钮）、`:438-446`（型号列/时间列 `max-w-[16rem]` 无 truncate）、`:422-426`（标签组 20 个堆多行）。
- **现象**：长型号串/年份串/类别名换行成多行，与全局 `td height:40px`（`index.css:230`）冲突，行高参差；20 个标签盖过主标题。
- **改法**：型号/时间 `div` 加 `truncate` + `title=`；类别名 button（`:419`）加 `block max-w-[18rem] truncate` + `title=`；标签列表态只显 `slice(0,3)` + `+N`（`title` 放全文），容器加 `overflow-hidden`，全量标签放明细弹窗。

---

## 2. 🟡 建议优化（P2，已验证，按主题归类）

### 2.1 颜色 / 对比度
| 位置 | 现象 | 改法 |
|---|---|---|
| `BusinessPerformanceLibrary.jsx:386` | 导入按钮 hover 落浅蓝 `primary-container`，白字对比 ~1.7:1 看不清 | 删 `hover:bg-primary-container`，改 `hover:brightness-95`（或 `hover:bg-on-primary-container`） |
| `BusinessMaterialWiki.jsx:217-230` | "刷新Wiki"主操作用绿色 `secondary-container`，违背蓝主色；相邻两按钮一个 `hover:opacity-90` 一个 `hover:bg-surface-dim` 不一致 | 主操作改 `bg-primary text-on-primary hover:bg-primary-container`；两按钮统一用 bg 过渡 |
| `BusinessMaterialWiki.jsx:244` | "正在同步…"提示 `text-outline` 配灰底 ~2.0:1 | 改 `text-on-surface`，前置 `animate-spin` 小 spinner |
| `BusinessMaterialDB.jsx:1937` | 预览"异常"态 chip 中性灰，未用 error 色 | 增 error 分支：异常 `bg-error-container text-on-error-container`，可预览 `bg-secondary-container ...`，其余灰 |
| `BusinessPerformanceLibrary.jsx:466,469` | 停用/删除 `bg-error-container/40` 白底近乎透明像文字链接 | `bg-error-container/70 ring-1 ring-error/25 hover:bg-error-container` |
| `BusinessPerformanceLibrary.jsx:462` | "明细"按钮 hover `surface-container-high→surface-dim` 几乎无变化 | `hover:bg-surface-container-highest hover:text-primary` |
| `BusinessMaterialDB.jsx:1762/1765/1768` | 工具栏次级按钮灰底灰字无边框，像禁用态 | 加 `ring-1 ring-inset ring-outline-variant/60` 或文字提到 `text-on-surface` |

### 2.2 做工 / 一致性
- **死代码 `scale` plumbing**：`BusinessMaterialDB.jsx:689/698-699/749/831/949/1905`，`scale` 全程硬编码 100，`Math.max/min(...)` 恒等于 13/12.5px，绕过字号 token 且未来接缩放会逐行 reflow。→ 移除 `scale` plumbing，树统一固定 class。
- **树内碎片字号**：`BusinessMaterialDB.jsx:749`(文件夹13)/`:782`(计数12)/`:831`(文件12.5)，三档"近似不等"。→ 整棵树统一一个字号 class（如全 `text-sm`/14px）。
- **三卡边框/圆角不一致**：Wiki `:236/:253` 用 `rounded-xl border-surface-container-high`，而 `BusinessMaterialsViewSwitch.jsx:23` 用 `rounded-lg border-outline-variant/45`。→ 统一为 `rounded-lg border-outline-variant/45`。
- **关闭按钮用小写字母 `x`**：`BusinessPerformanceLibrary.jsx:498,590`，与 material-symbols 体系不一致。→ 改 `<span class="material-symbols-outlined text-base">close</span>` + `aria-label` + 热区 padding。
- **checkbox 缺品牌色**：`BusinessMaterialDB.jsx:2134`(上传后切分)、`:2401`(切分勾选) 无 `accent-primary`（对比 `:644` 已用品牌蓝）。→ 统一加 `h-4 w-4 accent-primary`。
- **MarkdownLite 小表被全局撑松**：`MarkdownLite.jsx:177,188` 的 th/td 命中全局 `height:40px font-weight:500`。→ th/td 加 `!h-auto`、th 加 `!font-normal`、`py-1.5 leading-[1.6]`。
- **Wiki 面板标题/图标偏小**：`:240`"目录树" `text-[13px]` 与节点同号（提到 `text-[14px] font-semibold`）；`:166-175` 树图标 `text-[15px]` 孤值（统一 `text-[16px]`，index.css 对 16px 有显式规则会生效）。
- **Wiki 树节点 hover 双层底色**：`:149-169`，`transition-all` + chevron 嵌套各有 hover 底色。→ `transition-all`→`transition-colors`；chevron hover 改 `hover:text-on-surface` 去底色。
- **原始素材文件夹计数 `x/y` 含义模糊、空目录显 `0`**：`:782-784`。→ 始终 `${displayFileCount}/${node.fileCount}` + 模式感知 `title`；空态渲染 `-`。
- **切分片段 `fragment.id` 长徽标抢标题宽**：`:2410-2412`。→ 加 `max-w-[8rem] truncate shrink-0` + `title=`，或 `sr-only` 隐藏。
- **上传清单文件名尾部截断砍掉关键名**：`:2205-2214`。→ 左 span 加 `min-w-0 flex-1` + `title=`，大小 span 加 `shrink-0`。
- **业绩库明细弹窗动态字段/型号列无 truncate**：`:637,665`（与预览表 `:531` 不一致）。→ 加 `truncate` + `title=`。
- **业绩库三弹窗硬切无入场动画**：`:491-492/548-549/583-584`。→ overlay 加 `transition-opacity`、卡片加 `animate-float-in`（reduced-motion 已兜底）。

### 2.3 死类提醒（需确认意图）
- `AppShell.jsx:260`（`main` 上的 `workspace-shell-main`）与 `:262`（`<div class="workspace-shell-frame">`）这两个 class **在任何 CSS 文件里都没有定义**（grep 全仓为空）。
- → 要么是删除遗留的空类（应清掉），要么是本应实现的容器样式（如内容最大宽度/居中）漏写了。**修复前先和负责人确认意图**，别盲目删——也别盲目补样式。

---

## 3. 被驳回的误报（不要修，避免重复劳动）
对抗式验证阶段有 3 条被驳回，典型是把"全局已收口的字号/已被覆盖的样式"当成 bug。修复时若遇到类似"`text-2xl` 太大""`text-[10px]` 太小"的直觉，请先回看 §0.2——大概率是无效改动。

---

## 4. 建议修复顺序（杠杆从高到低，建议按批次提交）

| 批次 | 内容 | 涉及条目 | 提交信息建议 |
|---|---|---|---|
| 1 | 业绩库主表溢出（截列不可点） | P0-A | `fix(materials-ui): keep performance table action column reachable at 1280px` |
| 2 | 全局 shadow / 字号收口影响面（白名单/局部覆盖） | P0-B, P0-C | `fix(materials-ui): restore dialog elevation and heading hierarchy` |
| 3 | 原始素材树行重构（文件名可读 + 触屏可达 + hover 不抖） | P1-G, P1-H | `fix(materials-ui): rework raw material tree row layout and actions` |
| 4 | 业绩库列表稳定性 + 明细加载态 | P1-K | `fix(materials-ui): stabilize performance list refetch and detail modal` |
| 5 | Wiki 双栏等高/滚动 + 响应式矮树 + 内容头部/空态 | P1-D, P1-E, P1-F | `fix(materials-ui): balance wiki two-column layout and content panel` |
| 6 | 长文本批量 `truncate+title` + 颜色/对比度修正 | P1-L, 2.1 | `fix(materials-ui): truncate overflow cells and fix low-contrast states` |
| 7 | 首屏 CLS / 入场动画统一 + warning token | P1-I, P1-J, 2.2 动画项 | `fix(materials-ui): reduce layout shift and unify entrance animation` |
| 8 | 收尾打磨（死代码 scale、关闭按钮、碎片字号、边框 token、死类确认） | 2.2 其余 + 2.3 | `chore(materials-ui): polish typography, borders and dead code` |

每批次完成后按 §0.4 验收（两个宽度 + 控制台 0 报错），P0-A 额外在 1280px 下确认操作列可达。

---

## 5. 文件清单（修复会触及）
- `src/workspaces/business/pages/BusinessMaterialDB.jsx`
- `src/workspaces/business/pages/BusinessMaterialWiki.jsx`
- `src/workspaces/business/pages/BusinessPerformanceLibrary.jsx`
- `src/components/shared/MarkdownLite.jsx`
- `src/components/states/PageState.jsx`（如复用空态）
- `src/components/layout/AppShell.jsx`（仅 §2.3 死类确认）
- `src/index.css`（仅 P0-B/P0-C 局部覆盖，慎改全局行）
- `src/workspaces/business/pages/BusinessCoCreationEditor.jsx:480`（与 P1-I 同 `bg-warning` 问题，顺手一起改）
