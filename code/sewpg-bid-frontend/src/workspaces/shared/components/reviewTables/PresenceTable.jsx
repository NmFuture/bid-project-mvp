const presenceLabel = (status) => (status === 'present' ? '有明确要求' : '未识别')

// 技术标/商务标逐字相同的供货范围/专题方案识别表，原样合一。
export default function PresenceTable({ title = '专题方案 / 供货范围 / 考核条款', rows = [], showEvidenceLocationColumn = true }) {
  return (
    <div className="border border-surface-container-high rounded-md overflow-hidden bg-white">
      <div className="px-4 py-3 border-b border-surface-container-high bg-surface-container-low">
        <h4 className="text-sm font-semibold text-on-surface">{title}</h4>
      </div>
      <div className="overflow-x-auto" role="region" aria-label={`${title}，可横向滚动`} tabIndex={0}>
        <table className="w-full text-sm min-w-[860px]">
          <thead>
            <tr className="border-b border-surface-container-high">
              <th className="px-4 py-2 text-center font-semibold text-on-surface">项目</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface">识别结果</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface">摘要</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface">来源</th>
              {showEvidenceLocationColumn ? (
                <th className="px-4 py-2 text-center font-semibold text-on-surface">证据位置</th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const evidence = Array.isArray(row.item?.evidences) ? row.item.evidences[0] : null
              return (
                <tr key={row.label} className="border-b border-surface-container-high last:border-b-0">
                  <td className="px-4 py-2 text-on-surface font-medium whitespace-nowrap">{row.label}</td>
                  <td className="px-4 py-2 whitespace-nowrap">
                    <span className={`text-xs px-2 py-0.5 rounded-md font-semibold ${row.item?.status === 'present' ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
                      {presenceLabel(row.item?.status)}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-on-surface-variant min-w-[340px]">{row.item?.summary || '未识别到明确要求。'}</td>
                  <td className="px-4 py-2 text-on-surface-variant min-w-[180px]">{evidence?.sourceFile || '-'}</td>
                  {showEvidenceLocationColumn ? (
                    <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{evidence?.evidenceLocation || '-'}</td>
                  ) : null}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
