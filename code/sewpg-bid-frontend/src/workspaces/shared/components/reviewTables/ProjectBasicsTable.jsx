import {
  PROJECT_BASIC_FIELDS,
  resolveBusinessProjectBasicValue,
  resolveTechnicalProjectBasicValue,
  sourceValue,
} from './reviewTableValues.js'

// 两侧 ProjectBasicsTable 的样式/取值差异收敛为 variant：
// technical 保留字段行 label 覆盖与「解析内容」表头；business 用固定 label、「识别结果」表头、
// business-core-text-cell 换行样式，且截止时间走 formatBidDeadline 归一化。
const VARIANT_STYLES = {
  technical: {
    headerClassName: 'px-4 py-3 border-b border-surface-container-high bg-surface-container-low',
    headerCellClassName: 'px-4 py-2 text-center font-semibold text-on-surface',
    valueHeader: '解析内容',
    labelCellClassName: 'px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap',
    textCellClassName: '',
    valueColClassName: 'w-[26rem]',
    sourceColClassName: 'w-72',
    resolveValue: resolveTechnicalProjectBasicValue,
    useFieldLabel: true,
  },
  business: {
    headerClassName: 'px-4 py-3 border-b border-surface-container-high bg-surface-container-low flex items-center justify-between',
    headerCellClassName: 'px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap',
    valueHeader: '识别结果',
    labelCellClassName: 'px-4 py-2 text-on-surface font-medium whitespace-nowrap',
    textCellClassName: 'business-core-text-cell',
    valueColClassName: 'w-[28rem]',
    sourceColClassName: 'w-56',
    resolveValue: resolveBusinessProjectBasicValue,
    useFieldLabel: false,
  },
}

function ProjectBasicsTableBase({ title, fields = [], variant }) {
  const styles = VARIANT_STYLES[variant]
  const fieldsByKey = new Map(
    fields
      .filter((field) => field && typeof field === 'object')
      .map((field) => [String(field.key || field.fieldKey || ''), field]),
  )
  const normalizedFields = PROJECT_BASIC_FIELDS.map(([key, label]) => {
    const field = fieldsByKey.get(key) || {}
    return {
      key,
      constantLabel: label,
      label,
      ...field,
      value: field.value ?? '',
    }
  })
  const textCellPrefix = styles.textCellClassName ? `${styles.textCellClassName} ` : ''

  return (
    <div className="border border-surface-container-high rounded-md overflow-hidden bg-white">
      <div className={styles.headerClassName}>
        <h4 className="text-sm font-semibold text-on-surface">{title}</h4>
      </div>
      <div className="overflow-x-auto" role="region" aria-label={`${title}，可横向滚动`} tabIndex={0}>
        <table className="w-full table-fixed text-sm min-w-[720px]">
          <colgroup>
            <col className="w-44" />
            <col className={styles.valueColClassName} />
            <col className={styles.sourceColClassName} />
          </colgroup>
          <thead>
            <tr className="border-b border-surface-container-high">
              <th className={styles.headerCellClassName}>字段</th>
              <th className={styles.headerCellClassName}>{styles.valueHeader}</th>
              <th className={styles.headerCellClassName}>来源</th>
            </tr>
          </thead>
          <tbody>
            {normalizedFields.map((field) => {
              const { text, found } = styles.resolveValue(field.key, field)
              return (
                <tr key={field.key} className="border-b border-surface-container-high last:border-b-0">
                  <td className={styles.labelCellClassName}>{styles.useFieldLabel ? field.label : field.constantLabel}</td>
                  <td className={`${textCellPrefix}px-4 py-2 ${found ? 'text-primary font-medium' : 'text-outline'}`}>
                    {text}
                  </td>
                  <td className={`${textCellPrefix}px-4 py-2 text-on-surface-variant`}>{sourceValue(field)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function ProjectBasicsTable({ title, fields = [] }) {
  return <ProjectBasicsTableBase title={title} fields={fields} variant="technical" />
}

export function BusinessProjectBasicsTable({ title, fields = [] }) {
  return <ProjectBasicsTableBase title={title} fields={fields} variant="business" />
}
