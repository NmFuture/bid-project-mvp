import { useCallback, useEffect, useState } from 'react'
import { technicalGapsAPI } from '../../../api'
import Button from '../../../components/ui/Button'
import { Dialog, DialogFooter, DialogHeader } from '../../../components/ui/Dialog'

// 一键填写是一路跑到底的，没人会在中途停下来看理由。这个弹窗不是关口是查看入口：
// AI 选完直接用，人想核对再打开；理由列存在的意义是事后能回溯「当时凭什么选了这份」。

// 兼容单值写法：后端 normalize_material_names 同口径，AI 偶尔仍回 materialName
const materialNamesOf = (pick) => {
  const many = Array.isArray(pick?.materialNames) ? pick.materialNames : []
  const single = String(pick?.materialName || '').trim()
  return single && !many.includes(single) ? [...many, single] : many
}

export default function TechnicalBrandPicksModal({ projectId, onClose, showToast }) {
  const [data, setData] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [busy, setBusy] = useState('')

  const load = useCallback(async () => {
    setLoadError('')
    try {
      const payload = await technicalGapsAPI.brandPicks(projectId)
      setData({
        ...payload,
        picks: Array.isArray(payload?.picks) ? payload.picks : [],
        components: payload?.components && typeof payload.components === 'object' ? payload.components : {},
      })
    } catch (e) {
      setLoadError(e?.message || '品牌选取结果加载失败')
    }
  }, [projectId])

  useEffect(() => {
    load()
  }, [load])

  // 选取跑在 worker 队列里（素材匹配完成时已自动排过一次），打开弹窗时若还在跑就轮询，
  // 人不需要点任何按钮——点击本身不承载审批含义，不该让人多点一下。
  const running = ['queued', 'running'].includes(String(data?.status || ''))
  useEffect(() => {
    if (!running) return undefined
    const timer = window.setInterval(load, 3000)
    return () => window.clearInterval(timer)
  }, [running, load])

  // 候选是权威列表：AI 和人都只能从这里选，选一个库里没有的等于往标书里插不存在的证书
  const components = data?.components || {}
  const componentNames = Object.keys(components)
  const pickByComponent = new Map((data?.picks || []).map((pick) => [pick.component, pick]))

  // 一个部件可以选多份：品牌清单投几个品牌就放几份证书，勾选即多选
  const toggleMaterial = (component, materialName) => {
    const current = pickByComponent.get(component) || { component, brand: '', reason: '' }
    const selected = materialNamesOf(current)
    const nextSelected = selected.includes(materialName)
      ? selected.filter((name) => name !== materialName)
      : [...selected, materialName]
    const next = componentNames.map((name) => {
      const pick = name === component ? { ...current, materialNames: nextSelected } : pickByComponent.get(name)
      return pick || { component: name, brand: '', materialNames: [], reason: '' }
    })
    setData({ ...data, picks: next })
  }

  const handleRegenerate = async () => {
    setBusy('regenerate')
    try {
      const payload = await technicalGapsAPI.regenerateBrandPicks(projectId)
      setData(payload)
      showToast?.(payload?.error ? `品牌选取未完成：${payload.error}` : '已按当前品牌清单重新选取')
    } catch (e) {
      showToast?.(e?.message || '品牌选取失败', 'error')
    } finally {
      setBusy('')
    }
  }

  const handleSave = async () => {
    setBusy('save')
    try {
      await technicalGapsAPI.saveBrandPicks(projectId, {
        picks: componentNames.map((name) => {
          const pick = pickByComponent.get(name) || {}
          return {
            component: name,
            brand: String(pick.brand || ''),
            materialNames: materialNamesOf(pick),
            reason: String(pick.reason || ''),
          }
        }),
      })
      showToast?.('部件认证选取已保存，下次填写按这一版取证书')
      onClose?.()
    } catch (e) {
      showToast?.(e?.message || '保存失败', 'error')
    } finally {
      setBusy('')
    }
  }

  return (
    <Dialog open onClose={busy ? undefined : onClose} size="lg">
      <DialogHeader onClose={busy ? undefined : onClose}>
        <h3 className="text-lg font-headline font-semibold text-on-surface">部件认证 · 品牌选取</h3>
        <p className="mt-1 text-xs text-outline">
          按本项目投的品牌，从素材库的部件认证里选出该插哪一份。品牌以项目短名单下的大部件品牌清单为准；
          清单里投什么就放什么，库里没有对应品牌的证书就空着并提示缺少，交人工判断。
        </p>
      </DialogHeader>
      <div className="min-h-0 flex-1 overflow-auto">
        {loadError ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-6">
            <p className="text-sm text-error">{loadError}</p>
            <Button type="button" size="sm" variant="quiet" onClick={load}>
              重试
            </Button>
          </div>
        ) : data === null ? (
          <p className="p-6 text-sm text-outline">正在加载...</p>
        ) : running ? (
          <p className="p-6 text-sm text-outline">
            {data.message || '正在按品牌清单选取部件认证...'}（结果出来会自动刷新，可以先关掉）
          </p>
        ) : !componentNames.length ? (
          <p className="p-6 text-sm text-outline">
            项目素材范围内没有部件认证目录（认证证书/部件认证/…），这一步暂时用不上。
          </p>
        ) : (
          <div className="space-y-3 p-4">
            {data.error ? (
              <p className="rounded border border-error/40 bg-error/5 px-3 py-2 text-xs text-error">{data.error}</p>
            ) : null}
            <table className="w-full table-fixed border-collapse text-xs">
              <thead>
                <tr>
                  {['部件', '本项目投的品牌', '选中的证书', '判断依据'].map((label, index) => (
                    <th
                      key={label}
                      className={`border-b border-outline-variant/60 bg-surface-container-low px-2 py-2 text-left font-semibold text-on-surface-variant ${
                        ['w-[12%]', 'w-[16%]', 'w-[42%]', 'w-[30%]'][index]
                      }`}
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {componentNames.map((component) => {
                  const pick = pickByComponent.get(component) || {}
                  const candidates = components[component] || []
                  return (
                    <tr key={component} className="odd:bg-surface-container-lowest even:bg-surface-container-low/40">
                      <td className="border-b border-outline-variant/40 px-2 py-2 align-top text-on-surface">{component}</td>
                      <td className="border-b border-outline-variant/40 px-2 py-2 align-top text-on-surface">
                        {pick.brand || <span className="text-outline">—</span>}
                      </td>
                      <td className="border-b border-outline-variant/40 px-2 py-2 align-top">
                        {candidates.length ? (
                          <div className="space-y-1">
                            {candidates.map((name) => (
                              <label key={name} className="flex cursor-pointer items-start gap-1.5 leading-5">
                                <input
                                  type="checkbox"
                                  className="mt-0.5 shrink-0 cursor-pointer"
                                  checked={materialNamesOf(pick).includes(name)}
                                  disabled={Boolean(busy)}
                                  onChange={() => toggleMaterial(component, name)}
                                />
                                <span className="min-w-0 break-all text-on-surface">{name}</span>
                              </label>
                            ))}
                          </div>
                        ) : (
                          <span className="text-outline">候选目录里没有证书</span>
                        )}
                        {!materialNamesOf(pick).length ? (
                          <p className="mt-1 text-[11px] text-outline">一个都没勾＝这一栏空着，交人工</p>
                        ) : null}
                      </td>
                      <td className="border-b border-outline-variant/40 px-2 py-2 align-top text-on-surface-variant">
                        {pick.reason || <span className="text-outline">—</span>}
                        {pick.source === 'manual' ? (
                          <span className="ml-1 rounded bg-surface-container-high px-1 text-[10px] text-outline">人工</span>
                        ) : null}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {data.brandListName ? (
              <p className="text-[11px] text-outline">
                依据品牌清单：{data.brandListName}
                {data.generatedAt ? ` · ${data.generatedAt}` : ''}
              </p>
            ) : null}
          </div>
        )}
      </div>
      <DialogFooter>
        <Button type="button" variant="quiet" size="sm" onClick={handleRegenerate} disabled={Boolean(busy) || running}>
          {busy === 'regenerate' || running ? '选取中...' : '重新问一次 AI'}
        </Button>
        <div className="flex-1" />
        <Button type="button" variant="quiet" size="sm" onClick={onClose} disabled={Boolean(busy)}>
          取消
        </Button>
        <Button type="button" variant="primary" size="sm" onClick={handleSave} disabled={Boolean(busy) || running || !componentNames.length}>
          {busy === 'save' ? '保存中...' : '保存'}
        </Button>
      </DialogFooter>
    </Dialog>
  )
}
