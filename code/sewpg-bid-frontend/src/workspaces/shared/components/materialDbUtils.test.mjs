import test from 'node:test'
import assert from 'node:assert/strict'

import {
  ALLOWED_EXTENSIONS,
  buildDefaultCollapsedMap,
  canPreview,
  canPreviewCleaned,
  canPreviewOriginal,
  cleanedPreviewBlockedMessage,
  collectCollapsiblePaths,
  createFolderDeleteProtection,
  createFolderRenameProtection,
  customerLabel,
  customerOptionMatches,
  displayFolderName,
  ensureMaterialRootNodes,
  expandPathInMap,
  extOf,
  filterTreeByMatchedFiles,
  flattenTreePaths,
  getVisibleFileCount,
  groupFilesByFolderPath,
  identityKey,
  listItems,
  materialTierFromRootPath,
  normalizeCustomerOptions,
  normalizePath,
  normalizeProjectOptions,
  normalizeTagList,
  normalizeTagOptions,
  normalizeTreeNodes,
  parentPath,
  pathMatchesBidType,
  pickDefaultFolder,
  projectLabel,
  safeMessage,
  statusColor,
  tagInputPreview,
  toSizeLabel,
} from './materialDbUtils.js'

// 两轨目录保护配置，取值与合并前 TechnicalMaterialDB / BusinessMaterialDB 常量一致
const TECHNICAL_PROTECTION = {
  bidType: '技术标',
  protectedPaths: new Set(['技术标', '技术标/标准文件', '技术标/客户定制', '技术标/项目定制']),
  standardProtectedPaths: new Set([
    '技术标/通用素材/资格审查与基础证明',
    '技术标/通用素材/财务信用与合规声明',
    '技术标/通用素材/制造商与供应链材料',
    '技术标/通用素材/机型认证与测试报告',
    '技术标/通用素材/企业能力与供货业绩',
    '技术标/通用素材/表单模板与过程稿',
  ]),
  customerProtectedNames: new Set(['客户准入与专项证明', '客户专用响应口径', '客户模板与历史文件']),
  projectProtectedNames: new Set(['招标要求与专项证明', '资格审查与商务响应成册', '项目过程稿与澄清文件']),
  customerTierDirs: ['客户定制', '客户素材'],
  projectTierDirs: ['项目定制', '项目素材'],
  protectTierRoot: false,
}

const BUSINESS_PROTECTION = {
  bidType: '商务标',
  protectedPaths: new Set(['商务标', '商务标/通用素材', '商务标/客户素材', '商务标/项目素材']),
  standardProtectedPaths: new Set([
    '商务标/通用素材/资格审查与基础证明',
    '商务标/通用素材/财务信用与合规声明',
    '商务标/通用素材/制造商与供应链材料',
    '商务标/通用素材/机型认证与测试报告',
    '商务标/通用素材/企业能力与供货业绩',
    '商务标/通用素材/表单模板与过程稿',
  ]),
  customerProtectedNames: new Set(['客户准入与专项证明', '客户专用响应口径', '客户模板与历史文件']),
  projectProtectedNames: new Set(['招标要求与专项证明', '资格审查与商务响应成册', '项目过程稿与澄清文件']),
  customerTierDirs: ['客户素材'],
  projectTierDirs: ['项目素材'],
  protectTierRoot: true,
}

const isTechnicalDeleteProtected = createFolderDeleteProtection(TECHNICAL_PROTECTION)
const isBusinessDeleteProtected = createFolderDeleteProtection(BUSINESS_PROTECTION)
const isTechnicalRenameProtected = createFolderRenameProtection(TECHNICAL_PROTECTION.protectedPaths)

test('normalizeTagList 拆分、去空白、去重（大小写不敏感）、截断 40 字、上限 20 个', () => {
  assert.deepEqual(normalizeTagList('资质，承诺函;商务附件\n资质'), ['资质', '承诺函', '商务附件'])
  assert.deepEqual(normalizeTagList(['Tag', 'tag', ' TAG ']), ['Tag'])
  assert.deepEqual(normalizeTagList(['a  b', 'a b']), ['a b'])
  assert.deepEqual(normalizeTagList(''), [])
  assert.deepEqual(normalizeTagList(null), [])
  assert.equal(normalizeTagList('x'.repeat(50))[0].length, 40)
  assert.equal(normalizeTagList(Array.from({ length: 30 }, (_, i) => `t${i}`)).length, 20)
})

test('normalizeTagOptions 与 normalizeTagList 同逻辑但上限 100 个', () => {
  assert.equal(normalizeTagOptions(Array.from({ length: 150 }, (_, i) => `t${i}`)).length, 100)
  assert.deepEqual(normalizeTagOptions('a,b，c；d\ne'), ['a', 'b', 'c', 'd', 'e'])
})

test('tagInputPreview 合并已提交标签与草稿，整体再走 20 上限', () => {
  assert.deepEqual(tagInputPreview(['甲'], '乙，丙'), ['甲', '乙', '丙'])
  assert.deepEqual(tagInputPreview(['甲'], '甲'), ['甲'])
  assert.deepEqual(tagInputPreview('', ''), [])
})

test('extOf / toSizeLabel / safeMessage / statusColor', () => {
  assert.equal(extOf('a.DOCX'), 'docx')
  assert.equal(extOf('noext'), '')
  assert.equal(extOf(''), '')
  assert.equal(toSizeLabel(0), '-')
  assert.equal(toSizeLabel(512), '512 B')
  assert.equal(toSizeLabel(2048), '2.0 KB')
  assert.equal(toSizeLabel(5 * 1024 * 1024), '5.00 MB')
  assert.equal(toSizeLabel(2 * 1024 * 1024 * 1024), '2.00 GB')
  assert.equal(safeMessage({ payload: { detail: 'd' }, message: 'm' }, 'f'), 'd')
  assert.equal(safeMessage({ message: 'm' }, 'f'), 'm')
  assert.equal(safeMessage(null, 'f'), 'f')
  assert.equal(statusColor('running'), 'bg-primary/10 text-primary')
  assert.equal(statusColor('success'), 'bg-secondary-container text-on-secondary-container')
  assert.equal(statusColor('failed'), 'bg-error-container text-on-error-container')
  assert.equal(statusColor('pending'), 'bg-surface-container-high text-on-surface-variant')
})

test('预览资格判定与阻断文案', () => {
  assert.equal(canPreviewCleaned({ cleanStatus: 'cleaned', hasCleanedWord: true }), true)
  assert.equal(canPreviewCleaned({ cleanStatus: 'cleaned', hasCleanedWord: false }), false)
  assert.equal(canPreviewOriginal({ name: 'a.pdf' }), true)
  assert.equal(canPreviewOriginal({ name: 'a.xlsx' }), true)
  assert.equal(canPreviewOriginal({ name: 'a.docx' }), false)
  assert.equal(canPreview({ name: 'a.docx', cleanStatus: 'cleaned', hasCleanedWord: true }), true)
  assert.equal(canPreview({ name: 'a.docx', cleanStatus: 'pending' }), false)
  assert.equal(cleanedPreviewBlockedMessage(null), '选择已清洗文件后预览。')
  assert.equal(cleanedPreviewBlockedMessage({ cleanStatus: 'original_only' }), '该类型暂不支持在线预览，可下载查看。')
  assert.equal(cleanedPreviewBlockedMessage({ cleanStatus: 'failed' }), '清洗失败，暂无预览。')
  assert.equal(cleanedPreviewBlockedMessage({ cleanStatus: 'cleaning' }), '清洗中，完成后可预览。')
  assert.equal(cleanedPreviewBlockedMessage({ cleanStatus: 'pending' }), '等待清洗，完成后可预览。')
  assert.equal(cleanedPreviewBlockedMessage({ cleanStatus: 'cleaned', hasCleanedWord: false }), '清洗文件丢失，请联系管理员重新处理。')
  assert.equal(cleanedPreviewBlockedMessage({ cleanStatus: 'other' }), '暂无清洗稿。')
})

test('路径 helpers：normalizePath / parentPath / pathMatchesBidType', () => {
  assert.equal(normalizePath('/技术标/标准文件/'), '技术标/标准文件')
  assert.equal(normalizePath(''), '')
  assert.equal(parentPath('技术标/标准文件/机型A'), '技术标/标准文件')
  assert.equal(parentPath('技术标'), '')
  assert.equal(parentPath(''), '')
  assert.equal(pathMatchesBidType('技术标/标准文件', '技术标'), true)
  assert.equal(pathMatchesBidType('商务标/通用素材', '技术标'), false)
  assert.equal(pathMatchesBidType('', '技术标'), false)
})

test('displayFolderName 按根标签映射改名，未命中回退原名', () => {
  const labels = { 商务标: '商务标', 标准模板: '通用素材', 客户定制: '客户素材' }
  assert.equal(displayFolderName('标准模板', '商务标/标准模板', labels), '通用素材')
  assert.equal(displayFolderName('客户定制', '', labels), '客户素材')
  assert.equal(displayFolderName('其他目录', '商务标/其他目录', labels), '其他目录')
})

test('materialTierFromRootPath 按根路径与档位目录名推导层级', () => {
  const roots = ['商务标']
  const tierMap = { 通用素材: 'standard', 客户素材: 'customer', 项目素材: 'project' }
  assert.equal(materialTierFromRootPath('商务标/通用素材/机型A', roots, tierMap), 'standard')
  assert.equal(materialTierFromRootPath('商务标/客户素材/客户A', roots, tierMap), 'customer')
  assert.equal(materialTierFromRootPath('商务标/项目素材/项目A', roots, tierMap), 'project')
  assert.equal(materialTierFromRootPath('客户素材/客户A', roots, tierMap), 'customer')
  assert.equal(materialTierFromRootPath('商务标', roots, tierMap), '')
})

test('normalizeTreeNodes / ensureMaterialRootNodes 规整目录树', () => {
  const nodes = normalizeTreeNodes([
    { path: '技术标', name: '技术标', directFileCount: '2', children: [{ name: '标准文件', path: '技术标/标准文件' }] },
  ])
  assert.equal(nodes[0].directFileCount, 2)
  assert.equal(nodes[0].children[0].fileCount, 0)
  const ensured = ensureMaterialRootNodes([], '商务标')
  assert.deepEqual(ensured, [{ id: '商务标', name: '商务标', path: '商务标', directFileCount: 0, fileCount: 0, children: [] }])
  const kept = ensureMaterialRootNodes([{ path: '商务标', name: '商务标', children: [] }], '商务标')
  assert.equal(kept[0].path, '商务标')
})

test('树展开 helpers：flatten/collect/buildDefault/expand', () => {
  const tree = [
    {
      path: '技术标',
      directFileCount: 1,
      children: [
        { path: '技术标/标准文件', directFileCount: 0, children: [{ path: '技术标/标准文件/机型A', directFileCount: 3, children: [] }] },
        { path: '技术标/客户定制', directFileCount: 0, children: [] },
      ],
    },
  ]
  assert.deepEqual(flattenTreePaths(tree), ['技术标', '技术标/标准文件', '技术标/标准文件/机型A', '技术标/客户定制'])
  assert.deepEqual(collectCollapsiblePaths(tree), ['技术标', '技术标/标准文件', '技术标/标准文件/机型A'])
  assert.deepEqual(buildDefaultCollapsedMap(tree), { 技术标: false, '技术标/标准文件': true, '技术标/标准文件/机型A': true })
  const map = buildDefaultCollapsedMap(tree)
  expandPathInMap(map, '技术标/标准文件/机型A')
  assert.equal(map['技术标'], false)
  assert.equal(map['技术标/标准文件'], false)
  assert.equal(map['技术标/标准文件/机型A'], false)
})

test('pickDefaultFolder 优先根路径，其次同 bidType 的第一条路径', () => {
  const tree = [{ path: '技术标', children: [{ path: '技术标/标准文件', children: [] }] }]
  assert.equal(pickDefaultFolder(tree, '技术标', '技术标/标准文件'), '技术标/标准文件')
  assert.equal(pickDefaultFolder(tree, '技术标', '技术标/不存在'), '技术标')
  assert.equal(pickDefaultFolder([], '技术标', '技术标/标准文件'), '')
})

test('groupFilesByFolderPath 按目录归组并按中文名排序；filterTreeByMatchedFiles 过滤空目录', () => {
  const grouped = groupFilesByFolderPath([
    { id: '1', name: '乙', folderPath: '/技术标/标准文件/' },
    { id: '2', name: '甲', folderPath: '技术标/标准文件' },
    { id: '3', name: '无目录', folderPath: '' },
  ])
  assert.deepEqual(grouped.get('技术标/标准文件').map((f) => f.name), ['甲', '乙'])
  assert.equal(grouped.size, 1)

  const tree = [
    { path: '技术标', fileCount: 2, directFileCount: 0, children: [{ path: '技术标/标准文件', fileCount: 2, directFileCount: 2, children: [] }] },
  ]
  const filtered = filterTreeByMatchedFiles(tree, grouped)
  assert.equal(filtered.length, 1)
  assert.equal(filtered[0].children[0].directFileCount, 2)
  // getVisibleFileCount 只累加顶层节点的 fileCount（根节点已含子树合计）
  assert.equal(getVisibleFileCount(tree), 2)
})

test('技术标删除保护：根/档位目录、标准预置目录、客户与项目预置目录', () => {
  assert.equal(isTechnicalDeleteProtected('技术标'), true)
  assert.equal(isTechnicalDeleteProtected('技术标/标准文件'), true)
  assert.equal(isTechnicalDeleteProtected('技术标/通用素材/资格审查与基础证明'), true)
  assert.equal(isTechnicalDeleteProtected('技术标/客户定制/客户A/客户准入与专项证明'), true)
  assert.equal(isTechnicalDeleteProtected('技术标/客户素材/客户A/客户模板与历史文件'), true)
  assert.equal(isTechnicalDeleteProtected('技术标/项目定制/项目A/招标要求与专项证明'), true)
  // 技术标不保护档位的直接子目录（3 段）
  assert.equal(isTechnicalDeleteProtected('技术标/客户定制/客户A'), false)
  assert.equal(isTechnicalDeleteProtected('技术标/标准文件/机型A'), false)
  assert.equal(isTechnicalDeleteProtected('商务标'), false)
})

test('商务标删除保护：额外整层保护客户/项目档位的直接子目录', () => {
  assert.equal(isBusinessDeleteProtected('商务标'), true)
  assert.equal(isBusinessDeleteProtected('商务标/通用素材'), true)
  assert.equal(isBusinessDeleteProtected('商务标/通用素材/表单模板与过程稿'), true)
  assert.equal(isBusinessDeleteProtected('商务标/客户素材/客户A'), true)
  assert.equal(isBusinessDeleteProtected('商务标/项目素材/项目A'), true)
  assert.equal(isBusinessDeleteProtected('商务标/客户素材/客户A/客户专用响应口径'), true)
  assert.equal(isBusinessDeleteProtected('商务标/通用素材/自定义目录'), false)
  assert.equal(isBusinessDeleteProtected('商务标/客户素材/客户A/普通目录'), false)
  // 商务标的档位目录不叫 客户定制
  assert.equal(isBusinessDeleteProtected('商务标/客户定制/客户A'), false)
})

test('技术标重命名保护只覆盖根与三个默认档位目录（商务轨则与删除保护一致）', () => {
  assert.equal(isTechnicalRenameProtected('技术标'), true)
  assert.equal(isTechnicalRenameProtected('技术标/项目定制'), true)
  assert.equal(isTechnicalRenameProtected('技术标/通用素材/资格审查与基础证明'), false)
  assert.equal(isTechnicalRenameProtected('/技术标/标准文件/'), true)
})

test('identityKey 忽略大小写、空白与标点', () => {
  assert.equal(identityKey(' 金风科技（北京）有限公司 '), '金风科技北京有限公司')
  assert.equal(identityKey('ABC-Def'), 'abcdef')
  assert.equal(identityKey(''), '')
})

test('normalizeCustomerOptions 合并客户与项目来源并按中文名排序', () => {
  const options = normalizeCustomerOptions(
    [{ customerId: 'C1', name: '乙客户', aliases: ['乙'] }],
    [{ projectId: 'P1', customerId: 'C2', customerName: '甲客户', identity: {} }],
  )
  assert.deepEqual(options.map((o) => o.name), ['甲客户', '乙客户'])
  assert.equal(options[1].aliases.includes('乙'), true)
  // 同 customerId 合并别名
  const merged = normalizeCustomerOptions(
    [{ customerId: 'C1', name: '甲', aliases: ['A'] }],
    [{ customerId: 'C1', customerName: '甲', customerAliases: ['B'] }],
  )
  assert.equal(merged.length, 1)
  assert.deepEqual(merged[0].aliases, ['A', 'B'])
})

test('normalizeProjectOptions 规整项目身份字段并丢弃无 id 项', () => {
  const options = normalizeProjectOptions([
    { projectId: 'P1', projectCode: 'CODE-1', projectName: '项目一', customerId: 'C1', customerName: '客户一' },
    { name: '无ID' },
    { id: 'P2', identity: { projectCode: 'CODE-2', projectName: '项目二', customerCanonicalName: '客户二' } },
  ])
  assert.equal(options.length, 2)
  assert.equal(options[0].projectCode, 'CODE-1')
  assert.equal(options[1].name, '项目二')
  assert.equal(options[1].customerCanonicalName, '客户二')
})

test('customerOptionMatches / customerLabel / projectLabel / listItems', () => {
  const option = { customerId: 'C1', name: '金风科技', customerCanonicalName: '金风科技股份有限公司', aliases: ['金风'] }
  assert.equal(customerOptionMatches(option, '金风'), true)
  assert.equal(customerOptionMatches(option, '金风科技(北京)'), true)
  assert.equal(customerOptionMatches(option, '无关公司'), false)
  assert.equal(customerOptionMatches(option, ''), false)
  assert.equal(customerLabel(option), '金风科技 / C1')
  assert.equal(customerLabel({ name: '甲' }), '甲')
  assert.equal(projectLabel({ id: 'P1', projectCode: 'C1', name: '项目一', customerCanonicalName: '客户一' }), '项目一（P1 / C1 / 客户一）')
  assert.equal(projectLabel({ id: 'P1', projectCode: 'P1', name: '项目一' }), '项目一（P1）')
  assert.deepEqual(listItems([1]), [1])
  assert.deepEqual(listItems({ items: [2] }), [2])
  assert.deepEqual(listItems(null), [])
})

test('上传扩展名白名单与合并前一致', () => {
  const expected = ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'xlsm', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff']
  assert.deepEqual([...ALLOWED_EXTENSIONS], expected)
})
