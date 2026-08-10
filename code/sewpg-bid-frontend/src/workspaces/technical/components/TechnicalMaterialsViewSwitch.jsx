import MaterialsViewSwitch from '../../shared/components/MaterialsViewSwitch'

// 薄封装：技术标组（原始素材/Wiki/证书台账/规则）+ 共享组（业绩库），
// 渲染逻辑统一在 shared/components/MaterialsViewSwitch。
export default function TechnicalMaterialsViewSwitch({
  active = 'raw',
  title = '',
  subtitle = '',
  actions = null,
  meta = null,
  basePath = '/workspace/tech/materials',
}) {
  const base = String(basePath || '/workspace/tech/materials').replace(/\/+$/, '')
  const groups = [
    {
      key: 'tech',
      label: '技术标',
      icon: 'engineering',
      items: [
        { key: 'raw', label: '原始素材', to: `${base}/raw` },
        { key: 'wiki', label: 'Wiki', to: `${base}/wiki` },
        { key: 'certificates', label: '证书台账', to: `${base}/certificates` },
        { key: 'rules', label: '规则', to: `${base}/rules` },
      ],
    },
    {
      key: 'shared',
      label: '共享',
      icon: 'database',
      items: [
        { key: 'performance', label: '业绩库', to: '/workspace/shared/materials/performance' },
      ],
    },
  ]
  return (
    <MaterialsViewSwitch
      active={active}
      title={title}
      subtitle={subtitle}
      actions={actions}
      meta={meta}
      groups={groups}
    />
  )
}
