// 技术标/商务标共用的评分细则表：props 签名两侧完全一致，
// 头部计数与 headerAction 并列展示（技术标不传 headerAction，布局等价），
// 得分点列兼容 scorePoint / scoringStandard 两种字段名（技术标数据无 scoringStandard，取值不变）。
export default function ScoringCriteriaTable({
  title,
  rows = [],
  emptyText = '未识别到相关评分细则。',
  showEvidenceLocationColumn = true,
  showSourceColumns = true,
  showCount = true,
  showScoreColumn = true,
  showRequirementColumn = true,
  showProofRequirementColumn = true,
  scoringItemAlign = 'center',
  headerAction = null,
}) {
  const emptyColSpan = 2
    + (showScoreColumn ? 1 : 0)
    + (showRequirementColumn ? 1 : 0)
    + (showProofRequirementColumn ? 1 : 0)
    + (showSourceColumns ? 2 : 0)
    + (showEvidenceLocationColumn ? 1 : 0)

  return (
    <div className="border border-surface-container-high rounded-md overflow-hidden bg-white">
      <div className="px-4 py-3 border-b border-surface-container-high bg-surface-container-low flex items-center justify-between">
        <h4 className="text-sm font-semibold text-on-surface">{title}</h4>
        <div className="flex items-center gap-2">
          {showCount ? <span className="text-xs text-outline">{rows.length} 条</span> : null}
          {headerAction}
        </div>
      </div>
      <div className="overflow-x-auto" role="region" aria-label={`${title}，可横向滚动`} tabIndex={0}>
        <table className={`business-scoring-table w-full table-fixed text-sm ${showSourceColumns ? 'min-w-[980px]' : 'min-w-[860px]'}`}>
          <colgroup>
            <col className="w-16" />
            <col className={showSourceColumns ? 'w-44' : 'w-52'} />
            {showScoreColumn ? <col className="w-32" /> : null}
            {showRequirementColumn ? <col className="w-96" /> : null}
            {showProofRequirementColumn ? <col className="w-72" /> : null}
            {showSourceColumns ? (
              <>
                <col className="w-56" />
                <col className="w-48" />
              </>
            ) : null}
            {showEvidenceLocationColumn ? <col className="w-44" /> : null}
          </colgroup>
          <thead>
            <tr className="border-b border-surface-container-high">
              <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">序号</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">评分/审查项</th>
              {showScoreColumn ? <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">分值</th> : null}
              {showRequirementColumn ? <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">得分点/要求</th> : null}
              {showProofRequirementColumn ? <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">证明材料要求</th> : null}
              {showSourceColumns ? (
                <>
                  <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">来源</th>
                  <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">章节</th>
                </>
              ) : null}
              {showEvidenceLocationColumn ? (
                <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">证据位置</th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {rows.length ? rows.map((item, index) => (
              <tr key={item.id || `${title}-${index}`} className="border-b border-surface-container-high last:border-b-0">
                <td className="px-4 py-2 text-center text-on-surface-variant whitespace-nowrap">{item.order || index + 1}</td>
                <td className={`business-scoring-text-cell px-4 py-2 text-on-surface font-medium align-middle ${scoringItemAlign === 'left' ? 'text-left' : 'text-center'}`}>{item.scoringItem || '-'}</td>
                {showScoreColumn ? <td className="business-scoring-text-cell px-4 py-2 text-center text-primary align-top">{item.score || '-'}</td> : null}
                {showRequirementColumn ? <td className="business-scoring-text-cell px-4 py-2 text-on-surface-variant align-top">{item.scorePoint || item.scoringStandard || '-'}</td> : null}
                {showProofRequirementColumn ? <td className="business-scoring-text-cell px-4 py-2 text-on-surface-variant align-top">{item.proofRequirement || '-'}</td> : null}
                {showSourceColumns ? (
                  <>
                    <td className="business-scoring-text-cell px-4 py-2 text-on-surface-variant align-top">{item.sourceFile || '-'}</td>
                    <td className="business-scoring-text-cell px-4 py-2 text-on-surface-variant align-top">{item.section || '-'}</td>
                  </>
                ) : null}
                {showEvidenceLocationColumn ? (
                  <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{item.evidenceLocation || '-'}</td>
                ) : null}
              </tr>
            )) : (
              <tr>
                <td className="px-4 py-3 text-outline" colSpan={emptyColSpan}>{emptyText}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
