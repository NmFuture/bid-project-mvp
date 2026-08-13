// 解析证据校验横幅：把后端记下的未通过项摊开给人看。
// 只做提示，不禁用任何后续操作——解析结果是否可用由人判断。

const ListBlock = ({ label, items }) => {
  if (!items.length) return null
  return (
    <div className="flex flex-col gap-1">
      <p className="font-semibold">{label}</p>
      <ul className="ml-4 list-disc space-y-0.5">
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </div>
  )
}

export default function ParseValidationNotice({ summary }) {
  if (!summary || summary.passed) return null

  const { errors, missingTargets, repairedShards, failedShards } = summary
  const issueCount = errors.length + missingTargets.length

  return (
    <div
      role="alert"
      className="flex flex-col gap-2 rounded-md border border-error/30 bg-error-container/20 px-3 py-2 text-sm text-error"
    >
      <p className="font-semibold">
        {issueCount
          ? `有 ${issueCount} 处内容未通过证据校验，请人工复核后再使用`
          : '本次解析未完成证据校验，请人工复核后再使用'}
      </p>
      <p className="text-on-surface-variant">
        这些内容填了值，但在它引用的原文里找不到对应文字。解析结果仍可继续使用，是否采用请自行判断。
      </p>
      <ListBlock label="未通过的内容" items={errors} />
      <ListBlock label="缺少的解析目标" items={missingTargets} />
      <ListBlock label="未完成的解析分片" items={failedShards} />
      {repairedShards.length ? (
        <p className="text-on-surface-variant">
          已自动重跑并修复：{repairedShards.join('、')}
        </p>
      ) : null}
    </div>
  )
}
