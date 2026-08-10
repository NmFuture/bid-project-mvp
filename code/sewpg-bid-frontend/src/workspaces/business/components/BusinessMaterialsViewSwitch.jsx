import MaterialsViewSwitch from '../../shared/components/MaterialsViewSwitch'

// 薄封装：商务标组（原始素材/Wiki）+ 共享组（业绩库），
// 渲染逻辑统一在 shared/components/MaterialsViewSwitch。
export default function BusinessMaterialsViewSwitch({
  active = 'raw',
  title = '',
  subtitle = '',
  actions = null,
  meta = null,
  basePath = '/workspace/business/materials',
}) {
  const base = String(basePath || '/workspace/business/materials').replace(/\/+$/, '')
  const groups = [
    {
      key: 'business',
      label: '商务标',
      icon: 'request_quote',
      items: [
        { key: 'raw', label: '原始素材', to: `${base}/raw` },
        { key: 'wiki', label: 'Wiki', to: `${base}/wiki` },
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
