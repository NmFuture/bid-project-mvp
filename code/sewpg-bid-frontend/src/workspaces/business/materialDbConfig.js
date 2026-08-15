import { businessMaterialsAPI } from '../../api'
import BusinessMaterialsViewSwitch from './components/BusinessMaterialsViewSwitch'
import { createFolderDeleteProtection } from '../shared/components/materialDbUtils'

// 商务标素材库配置：与合并前 BusinessMaterialDB 的常量与行为开关一一对应。
const PROTECTED_DELETE_FOLDER_PATHS = new Set([
  '商务标',
  '商务标/通用素材',
  '商务标/客户素材',
  '商务标/项目素材',
])

const isFolderDeleteProtected = createFolderDeleteProtection({
  bidType: '商务标',
  protectedPaths: PROTECTED_DELETE_FOLDER_PATHS,
  standardProtectedPaths: new Set([
    '商务标/通用素材/资格审查与基础证明',
    '商务标/通用素材/财务信用与合规声明',
    '商务标/通用素材/制造商与供应链材料',
    '商务标/通用素材/机型认证与测试报告',
    '商务标/通用素材/企业能力与供货业绩',
    '商务标/通用素材/表单模板与过程稿',
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
  customerTierDirs: ['客户素材'],
  projectTierDirs: ['项目素材'],
  // 商务标额外整层保护客户/项目档位的直接子目录（3 段路径）
  protectTierRoot: true,
})

// 商务标后端对删除保护目录同样禁止重命名（根目录、默认档位与自动预置目录），两口径一致
const isFolderRenameProtected = isFolderDeleteProtected

const businessMaterialDbConfig = {
  bidType: '商务标',
  workspace: 'business',
  trackName: '商务',
  pageTitle: '商务标素材库',
  rootPath: '商务标/通用素材',
  rootLabels: {
    商务标: '商务标',
    通用素材: '通用素材',
    客户素材: '客户素材',
    项目素材: '项目素材',
    标准模板: '通用素材',
    客户定制: '客户素材',
    项目定制: '项目素材',
  },
  rootPaths: ['商务标'],
  tierDirMap: {
    通用素材: 'standard',
    客户素材: 'customer',
    项目素材: 'project',
  },
  tierOptions: [
    { value: 'standard', label: '通用素材', description: '大部分标书都会复用的基础资料。' },
    { value: 'customer', label: '客户素材', description: '只面向某个客户复用的专属资料。' },
    { value: 'project', label: '项目素材', description: '只在当前项目使用的补充资料。' },
  ],
  materialKindOptions: [
    { value: 'fixed', label: '固定素材' },
    { value: 'ai_fill', label: 'AI填写' },
    { value: 'other', label: '其他' },
  ],
  materialsAPI: businessMaterialsAPI,
  projectsAPI: null,
  viewSwitch: BusinessMaterialsViewSwitch,
  pipelineProgress: null,
  isFolderDeleteProtected,
  isFolderRenameProtected,
  splitPreviewMethod: 'previewBusinessSplit',
  splitConfirmMethod: 'confirmBusinessSplit',
  features: {
    bulkMode: false,
    autoTags: false,
    deleteFolderButton: true,
    tierUpload: true,
    uploadAfterSplit: true,
    linkedProjectFlow: false,
    sortLibrary: false,
    expandOnEveryLoad: true,
    reloadOnFolderSelect: true,
    searchDebounce: false,
  },
}

export default businessMaterialDbConfig
