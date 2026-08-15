import { technicalMaterialsAPI, technicalProjectsAPI } from '../../api'
import TechnicalMaterialsViewSwitch from './components/TechnicalMaterialsViewSwitch'
import MaterialPipelineProgress from './components/MaterialPipelineProgress'
import { createFolderDeleteProtection, createFolderRenameProtection } from '../shared/components/materialDbUtils'

// 技术标素材库配置：与合并前 TechnicalMaterialDB 的常量与行为开关一一对应。
const PROTECTED_DELETE_FOLDER_PATHS = new Set([
  '技术标',
  '技术标/标准文件',
  '技术标/客户定制',
  '技术标/项目定制',
])

const isFolderDeleteProtected = createFolderDeleteProtection({
  bidType: '技术标',
  protectedPaths: PROTECTED_DELETE_FOLDER_PATHS,
  standardProtectedPaths: new Set([
    '技术标/通用素材/资格审查与基础证明',
    '技术标/通用素材/财务信用与合规声明',
    '技术标/通用素材/制造商与供应链材料',
    '技术标/通用素材/机型认证与测试报告',
    '技术标/通用素材/企业能力与供货业绩',
    '技术标/通用素材/表单模板与过程稿',
  ]),
  customerProtectedNames: new Set([
    '客户准入与专项证明',
    '客户专用响应口径',
    '客户模板与历史文件',
  ]),
  projectProtectedNames: new Set([
    '招标要求与专项证明',
    '资格审查与商务响应成册',
    '项目过程稿与澄清文件',
  ]),
  customerTierDirs: ['客户定制', '客户素材'],
  projectTierDirs: ['项目定制', '项目素材'],
  protectTierRoot: false,
})

// 重命名保护口径与后端一致：仅根目录和三个默认档位目录（标准文件/客户定制/项目定制）禁止改名
const isFolderRenameProtected = createFolderRenameProtection(PROTECTED_DELETE_FOLDER_PATHS)

const technicalMaterialDbConfig = {
  bidType: '技术标',
  workspace: 'tech',
  trackName: '技术',
  pageTitle: '技术标素材库',
  rootPath: '技术标/标准文件',
  rootLabels: {
    技术标: '技术标',
    标准文件: '标准文件',
    客户定制: '客户定制',
    项目定制: '项目定制',
  },
  rootPaths: ['技术标'],
  tierDirMap: {},
  tierOptions: null,
  materialKindOptions: [
    { value: 'fixed', label: '可复用素材' },
    { value: 'ai_fill', label: '待填写模板' },
    { value: 'other', label: '补充素材' },
  ],
  materialsAPI: technicalMaterialsAPI,
  projectsAPI: technicalProjectsAPI,
  viewSwitch: TechnicalMaterialsViewSwitch,
  pipelineProgress: MaterialPipelineProgress,
  isFolderDeleteProtected,
  isFolderRenameProtected,
  splitPreviewMethod: 'previewTechnicalSplit',
  splitConfirmMethod: 'confirmTechnicalSplit',
  features: {
    // 多选框架（批量删除/批量打标签）
    bulkMode: true,
    // 工具栏「自动打标签」按钮（raw.autoTags 仅技术轨 API 提供）
    autoTags: true,
    // 工具栏「删除文件夹」按钮（技术轨无此按钮，目录删除走树内按钮）
    deleteFolderButton: false,
    // 素材层级上传流（商务轨）
    tierUpload: false,
    uploadAfterSplit: false,
    // 解析页「确认参与」联动：folder/projectId 定位、素材归集进度轮询、项目横幅
    linkedProjectFlow: true,
    // 目录树与文件列表按名称排序（utils/materialSort）
    sortLibrary: true,
    // 每次重载都强制展开当前目录（商务轨原行为）；技术轨仅首次加载展开
    expandOnEveryLoad: false,
    // 选中目录变化触发整库重载（商务轨原行为）；技术轨刻意不触发
    reloadOnFolderSelect: false,
    // 标题筛选 400ms 防抖（商务轨原行为为逐键即改）
    searchDebounce: true,
  },
}

export default technicalMaterialDbConfig
