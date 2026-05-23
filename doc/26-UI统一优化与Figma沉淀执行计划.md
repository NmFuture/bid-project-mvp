# UI统一优化与Figma沉淀执行计划

> 目标：在不推倒重做现有产品的前提下，统一当前前端界面的按钮、表单、表格、卡片、弹窗、状态标签、页面层级和交互样式，并将最终稳定下来的代码规范沉淀到 Figma，形成后续新增页面可复用的 UI Kit。

## 一、结论

当前阶段建议采用：

```text
代码侧先统一 -> 用户审核样板页 -> 批量推广到全站 -> Figma沉淀规范
```

不建议一开始就把现有产品全部搬到 Figma 重画。原因是当前产品已有可运行界面，主要问题是同层级组件不一致、样式散落、控件规范不稳定。这类问题直接在代码组件层收敛效率最高。

Figma 应该在两个节点介入：

1. 样板页确认后，用来固化视觉方向。
2. 全站统一后，用来沉淀 UI Kit、变量、组件和页面模板。

本轮范围限定为：

```text
只优化商务标链路；技术标链路暂不改动。
```

后续商务标和技术标会完全隔离。技术标页面后续可以参考商务标链路沉淀出的基础组件规范和 Figma UI Kit，但不进入第一轮改造范围。本轮不再为当前共用页面做复杂兼容改造，优先选择商务标专属页面推进。

## 二、你应该在哪些阶段介入

你不需要每个细节都介入，但需要在关键节点拍板。

| 阶段 | 是否需要你介入 | 你要看什么 | 建议方式 |
|---|---:|---|---|
| 阶段0：UI盘点 | 轻度介入 | 当前问题清单是否符合你的直觉 | 看一份问题列表即可 |
| 阶段1：统一规则草案 | 需要介入 | 主色、按钮层级、页面密度、圆角、表格风格 | 确认方向，不逐像素审 |
| 阶段2：样板页改造 | 强烈建议介入 | 1-3个核心页面是否符合预期 | 先审截图或本地页面 |
| 阶段3：全站批量统一 | 轻度介入 | 是否有明显跑偏页面 | 抽查核心流程 |
| 阶段4：Figma沉淀 | 需要介入 | Figma UI Kit 是否可以作为后续标准 | 确认组件命名和规范完整性 |
| 阶段5：最终验收 | 需要介入 | 产品整体一致性、业务可用性 | 走一遍主流程 |

推荐你的主要介入点是：

```text
先审核样板页，再允许批量统一；最后审核 Figma UI Kit。
```

也就是说，你的判断是对的：应该先审核统一修改后的界面方向，再沉淀到 Figma。不要先审核一套脱离代码的 Figma 全量设计稿。

## 三、总体执行路径

```text
阶段0：现状扫描
  ↓
阶段1：制定轻量设计规范
  ↓
阶段2：改造样板页
  ↓
用户审核样板页
  ↓
阶段3：批量统一全站
  ↓
阶段4：沉淀到 Figma UI Kit
  ↓
阶段5：建立长期维护规则
```

## 四、阶段0：现状扫描

### 目标

找出当前 UI 不统一的来源，避免凭感觉改界面。

### 扫描范围

前端目录：

```text
code/sewpg-bid-frontend/src
```

重点文件和目录：

```text
src/index.css
src/App.css
src/components/layout
src/components/shared
src/components/modals
src/components/states
src/pages
```

### 重点检查项

- 按钮：颜色、尺寸、高度、圆角、文字、图标、禁用态、加载态是否一致。
- 输入控件：输入框、下拉框、搜索框、文本域高度和边框是否一致。
- 页面标题区：标题、说明、右侧操作按钮、面包屑是否统一。
- 表格：表头、行高、空状态、分页、行操作按钮是否统一。
- 卡片：边框、阴影、圆角、内边距、标题区是否统一。
- 弹窗：宽度、标题、底部按钮、关闭方式、危险操作样式是否统一。
- 状态标签：成功、警告、错误、处理中、AI生成等状态是否统一。
- 间距：页面区块、工具栏、表单项、按钮组之间是否有统一 spacing。
- 字体：标题、正文、说明、表格、标签是否回到 18 / 16 / 14 / 12 的企业规范。
- 颜色：是否存在过多散落的硬编码颜色。

### 产出

生成一份 UI 问题清单，建议文件：

```text
doc/27-UI现状扫描与问题清单.md
```

### 你的介入

此阶段你只需要确认：

- 问题清单是否覆盖了你肉眼看到的主要问题。
- 哪些页面最影响客户观感。

## 五、阶段1：制定轻量设计规范

### 目标

先确定一套足够落地的 UI 标准，避免每个页面单独发挥。

### 建议规范

#### 1. 色彩

沿用当前代码中的企业色方向，以 `src/index.css` 中的 token 为基础收口：

```text
primary: #0068b7
secondary: #14a83b
tertiary / ai: #18b7d9
error: #c54040
surface: #ffffff
surface-low: #f1f5f9
text-main: #2a4258
text-muted: #60758a
outline: #95a7ba
outline-light: #c4d0dc
```

不建议现阶段引入大面积紫色、渐变、深色主题或装饰性背景。这个项目是内部 B 端投标工具，应保持专业、清晰、稳定。

#### 2. 字号

建议固定为：

```text
页面主标题：18px / 600
区块标题：16px / 600
正文与表格：14px / 400-500
辅助说明：12px / 400
```

#### 3. 圆角

建议：

```text
按钮、输入框：6px
卡片、弹窗、表格容器：8px
标签、徽标：999px 或 4px，按类型固定
```

#### 4. 间距

基于 4px 栅格：

```text
4 / 8 / 12 / 16 / 20 / 24 / 32
```

#### 5. 按钮层级

至少统一以下类型：

```text
primary：页面主操作，例如新建、保存、下一步、生成
secondary：同级次操作，例如取消、返回、查看
ghost：弱操作，例如展开、筛选、辅助入口
danger：删除、清空、撤销等破坏性操作
icon：仅图标工具按钮，例如刷新、关闭、下载
```

按钮高度建议：

```text
sm: 32px
md: 36px
lg: 40px
```

默认优先使用 `md`。

### 产出

生成一份轻量规范文件，建议文件：

```text
doc/28-UI轻量设计规范.md
```

### 你的介入

你需要确认：

- 是否认可整体视觉气质：专业、克制、信息密度较高。
- 主按钮颜色和层级是否符合客户预期。
- 页面是否应该更紧凑，还是更留白。

这一阶段不需要你逐个页面审，只需要确认方向。

## 六、阶段2：样板页改造

### 目标

先选 2-3 个最有代表性的商务标页面做样板，验证统一方案是否有效。

### 建议样板页

优先选择：

```text
BusinessGapRecognition.jsx     商务标缺口识别，核心业务判断页
MaterialDB.jsx                 素材库，商务标素材复用和表格筛选密集页
```

如果希望先控制范围，可以先做：

```text
BusinessGapRecognition.jsx
```

`BusinessTenderReview.jsx` 当前复用 `TenderReview.jsx`，而商务标和技术标后续会完全拆分。因此第二阶段暂不深改商务审核页，等拆分完成后再作为商务标专属页面统一；若拆分前必须推进，则新建商务标专属 View，不在共用 `TenderReview.jsx` 中做大量视觉改造。

项目列表和项目驾驶舱属于商务标入口时可以轻量调整入口状态和商务标标识，但不作为第一轮主要样板页。技术标专属页面暂不改动。

### 代码改造重点

建立或收敛基础组件：

```text
src/components/ui/Button.jsx
src/components/ui/IconButton.jsx
src/components/ui/Input.jsx
src/components/ui/Select.jsx
src/components/ui/Textarea.jsx
src/components/ui/Card.jsx
src/components/ui/Badge.jsx
src/components/ui/Dialog.jsx
src/components/ui/Toolbar.jsx
```

已有共享组件也要纳入统一：

```text
src/components/shared/PageHeader.jsx
src/components/shared/StatusBadge.jsx
src/components/shared/DataCard.jsx
src/components/shared/FilterBar.jsx
src/components/shared/EmptyState.jsx
src/components/shared/Pagination.jsx
```

### 商务标 S3 素材匹配专项调整

本阶段新增一个产品逻辑专项，只作用于商务标 `BusinessGapRecognition.jsx` 及商务标素材库。

#### 目标

将 S3 从“多选候选素材 + 选择素材处理方式”调整为“按素材类型直接行动”：

```text
固定素材候选直接选择
人工指定素材库材料
人工上传补充
AI 填表
```

#### 前端交互

- 候选素材只展示匹配度最高的前 4 个。
- 候选素材改为单选，不再展示复选框和“全选候选”。
- 候选素材卡片右侧保留“预览”和“选择”。
- 候选预览优先打开原素材，Word/Excel/PPT 使用 OnlyOffice，图片直接预览，PDF 使用原件嵌入；不再默认展示清洗稿文本快照。
- 当前“AI 自主填写”从前端处理方式中下线，替换为“AI 填表”动作入口。

#### 素材库配套

- 商务标原始素材上传和编辑时增加“素材类型”：

```text
固定素材
其他
```

- 固定素材表示原件可直接挂载/嵌入投标文件，例如证书、扫描件、成品附件、完整声明文件等。
- 其他素材表示可作为 AI 填表、人工判断或后续提取的来源。
- 技术标素材暂不引入该字段的界面调整。

#### AI 填表能力

- 新增 S3“AI 填表”弹窗。
- 左侧选择当前目录任务下的待填表模板/附件。
- 右侧从商务素材库多选数据来源文件。
- 提交后由后端创建填表任务，调用商务标填表 skill，生成填表产物并回挂到当前任务。
- 第一版允许同步执行并返回结果；后续如果填表耗时较长，再升级为异步任务队列。

#### 执行顺序

1. 候选素材展示、单选和原素材预览。
2. 原始素材库增加“固定素材/其他”标签。
3. S3 任务动作区替换旧“素材处理方式”。
4. 新增 AI 填表弹窗、接口和 skill 骨架。
5. 构建、后端测试、Docker rebuild/restart、浏览器验收。

### 验收方式

样板页完成后，建议同时提供：

1. 本地可访问页面。
2. 桌面截图。
3. 关键组件截图。
4. 改造前后差异说明。

### 你的介入

这是你最重要的介入点。

你需要判断：

- 这个方向是否比当前界面统一。
- 按钮、表格、弹窗、卡片是否符合“同层级一致”。
- 页面信息密度是否适合内部业务人员长期使用。
- 是否有明显不符合甲方审美或业务习惯的地方。

只有样板页通过后，才进入全站批量统一。

## 七、阶段3：全站批量统一

### 目标

把样板页确认过的组件和样式推广到商务标链路页面。

### 迁移顺序

建议按照业务重要性排序：

1. 商务标缺口识别和审核页面。
2. 商务标素材库、Wiki库、素材选择弹窗。
3. 商务标解析、目录、生成、导出相关入口页面。
4. 商务标项目入口状态，例如项目列表、项目驾驶舱中的商务标卡片或阶段入口。
5. 审计日志、设置页中与商务标链路直接相关的部分。

### 页面范围

第一轮主要覆盖商务标相关页面：

```text
src/pages/BusinessGapRecognition.jsx
src/pages/MaterialDB.jsx
src/pages/MaterialWiki.jsx
src/components/modals/MaterialSelectModal.jsx
src/components/modals/AuditDetailModal.jsx
```

暂缓覆盖：

```text
src/pages/BusinessTenderReview.jsx
src/pages/TenderReview.jsx
```

原因：商务审核页当前和技术标共用 `TenderReview.jsx`。后续商务/技术完全隔离前，不在共用文件里做大规模 UI 改造。

以下页面仅在影响商务标入口或公共组件时做最小必要调整：

```text
src/pages/ProjectList.jsx
src/pages/ProjectCockpit.jsx
src/pages/AuditLog.jsx
src/pages/Settings.jsx
```

以下技术标页面第一轮暂不改动：

```text
src/pages/GapRecognition.jsx
src/pages/TenderReview.jsx
src/pages/OutlineReview.jsx
src/pages/ParseResult.jsx
src/pages/GenerateProgress.jsx
src/pages/CoCreationEditor.jsx
src/pages/FinalExport.jsx
```

### 统一原则

- 页面不重新设计业务结构，只统一控件和视觉语言。
- 优先替换重复样式为共享组件。
- 不做大范围交互重构，避免影响主流程。
- 保留已有功能和接口调用逻辑。
- 每完成一组页面，运行构建检查。
- 公共组件调整必须向后兼容，不能意外改变技术标页面。
- 对当前技术/商务共用页面，优先等待拆分；若必须提前改商务标，则新建商务标专属 View，而不是在共用页面里堆复杂分支。

### 验收方式

- `npm run build`
- `npm run lint`
- 本地页面人工走查
- 截图比对核心流程
- Docker 版本最终重建验证

### 你的介入

此阶段你只需要抽查：

- 核心流程是否顺畅。
- 是否出现某些页面明显跑偏。
- 是否有业务按钮层级被误判，例如本应是主操作却变成弱按钮。

## 八、阶段4：沉淀到 Figma UI Kit

### 目标

将代码里已经验证可用的 UI 规范同步到 Figma，形成后续设计和开发共用的标准。

### 推荐 Figma 文件

```text
SEWPG Bid Platform UI Kit
```

### 推荐页面结构

```text
00 Cover
01 Foundations
02 Components
03 Patterns
04 Screens
05 Changelog
```

### Foundations 内容

```text
Colors
Typography
Spacing
Radius
Shadow
Icons
Layout
```

### Components 内容

```text
Button
IconButton
Input
Select
Textarea
Search
Checkbox
Radio
Tabs
Badge
StatusBadge
Card
Table
Pagination
Dialog
Drawer
Toast
EmptyState
Progress
StageNav
PageHeader
FilterBar
Toolbar
```

### Patterns 内容

```text
页面标题区
表格筛选区
列表操作栏
文件上传区
项目阶段进度区
审核确认区
AI生成结果区
素材选择弹窗
导出确认弹窗
```

### Screens 内容

只沉淀代表性页面，不需要全量搬运：

```text
项目列表
项目驾驶舱
素材库
目录审核
生成进度
最终导出
```

### Figma 同步方式

建议从代码提炼以下内容，再写入 Figma：

1. 从 `src/index.css` 提取 tokens。
2. 从 `src/components/ui` 和 `src/components/shared` 提取组件状态。
3. 根据样板页截图建立 Figma 页面模板。
4. 在 Figma 中创建变量和组件变体。
5. 标注组件使用规则和禁用场景。

### 你的介入

你需要确认：

- Figma 文件是否能作为“以后新增页面的标准”。
- 组件命名是否容易理解。
- 设计师、开发、业务评审是否都能看懂。

不建议你逐像素审核每一个 Figma 组件；重点看完整性和可复用性。

## 九、阶段5：长期维护规则

### 目标

防止后续新增页面再次出现按钮、卡片、表格各写各的情况。

### 建议规则

1. 新页面必须优先使用 `src/components/ui` 和 `src/components/shared`。
2. 禁止在页面里随意硬编码主按钮颜色、表格样式、弹窗按钮区样式。
3. 新增组件前先确认现有组件是否可扩展。
4. 新增页面如果涉及新模式，先同步到 Figma Patterns。
5. 每次 UI 规范变化，都要同时更新代码 token 和 Figma UI Kit。

### 可增加的工程约束

后续可以考虑：

- 增加 Storybook 或轻量组件预览页。
- 增加 Playwright 截图回归。
- 增加 CSS token 使用检查。
- 在 PR 模板里加入 UI 规范检查项。

## 十、建议的第一轮执行范围

第一轮不要贪多，建议 3-5 天内完成一个闭环：

### Day 1

- 扫描 UI 现状。
- 输出问题清单。
- 确定轻量设计规范。

### Day 2

- 建立基础 UI 组件。
- 改造 `BusinessGapRecognition.jsx`。

### Day 3

- 继续收敛 `BusinessGapRecognition.jsx` 内的弹窗、任务卡和状态标签。
- 生成截图。
- 由你审核样板页。

### Day 4

- 根据审核意见调整规范。
- 开始批量迁移核心流程页面。

### Day 5

- 完成第一批页面统一。
- 运行构建和本地验证。
- 提炼 Figma UI Kit 初稿结构。

## 十一、风险与控制

### 风险1：改 UI 时影响业务功能

控制方式：

- 样式和组件迁移优先，不改接口逻辑。
- 每组页面改完跑构建。
- 核心流程做人工走查。

### 风险2：统一后页面变得太“模板化”

控制方式：

- 统一基础控件，不强行抹平业务页面结构。
- 对核心业务区保留必要的信息层级差异。

### 风险3：Figma 和代码再次脱节

控制方式：

- 先以代码中已验证的组件为准。
- Figma 记录“已落地规范”，不是幻想稿。
- 后续新增页面再走 Figma 与代码同步流程。

### 风险4：一次性改动过大，不容易验收

控制方式：

- 先样板页。
- 再核心流程。
- 最后低频页面。
- 每一轮都有可截图、可访问、可构建的验收结果。

## 十二、最终产出清单

代码侧：

```text
src/components/ui/*
src/components/shared/* 统一调整
src/index.css token 收口
核心 pages 样式迁移
```

文档侧：

```text
doc/27-UI现状扫描与问题清单.md
doc/28-UI轻量设计规范.md
doc/29-UI统一改造验收记录.md
```

Figma 侧：

```text
SEWPG Bid Platform UI Kit
Foundations
Components
Patterns
Representative Screens
```

## 十三、当前推荐决策

建议现在按以下方式启动：

1. 先进行 UI 现状扫描。
2. 产出问题清单和轻量规范。
3. 新增基础 UI 组件，并改造 `BusinessGapRecognition` 作为第一个商务标样板页。
4. 你审核样板页。
5. 审核通过后批量统一商务标链路。
6. `BusinessTenderReview` 等商务/技术拆分后再统一；若必须提前推进，则新建商务标专属 View。
7. 统一结果稳定后再沉淀到 Figma。

你的介入顺序建议是：

```text
确认规范方向 -> 审核样板页 -> 抽查全站统一效果 -> 审核Figma UI Kit
```

这是当前最便捷、高效、统一，也最不容易返工的路径。
