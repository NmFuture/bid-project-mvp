import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { coverageAPI, stagesAPI } from '../api'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'

const statusDotClass = {
  full: 'bg-secondary',
  partial: 'bg-tertiary',
  none: 'bg-error',
}

const renderTreeNode = (node, depth = 0) => {
  const hasChildren = Array.isArray(node.children) && node.children.length > 0
  const leftPadding = 12 + depth * 20
  const coverageColor = node.coverage >= 90 ? 'text-secondary' : node.coverage >= 70 ? 'text-tertiary' : 'text-error'

  if (hasChildren) {
    return (
      <div key={node.id} className="flex flex-col gap-1">
        <div
          className="flex items-center justify-between rounded-lg bg-surface-container-low px-3 py-2"
          style={{ paddingLeft: `${leftPadding}px` }}
        >
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-sm text-outline">folder</span>
            <span className="text-sm font-semibold text-on-surface">{node.title}</span>
          </div>
          <span className={`text-sm font-bold ${coverageColor}`}>{node.coverage}%</span>
        </div>
        {node.children.map((child) => renderTreeNode(child, depth + 1))}
      </div>
    )
  }

  return (
    <div
      key={node.id}
      className="flex items-center justify-between rounded-lg px-3 py-2 hover:bg-surface-container-low"
      style={{ paddingLeft: `${leftPadding}px` }}
    >
      <span className="text-sm text-on-surface-variant">{node.title}</span>
      <span className={`w-2.5 h-2.5 rounded-full ${statusDotClass[node.status] || statusDotClass.none}`}></span>
    </div>
  )
}

export default function CoverageHeatmap({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [advancing, setAdvancing] = useState(false)

  const fetchCoverage = useCallback(async () => {
    setLoading(true)
    try {
      const payload = await coverageAPI.get(id)
      setData(payload)
      setError('')
    } catch (e) {
      setError(e?.message || '覆盖热力数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchCoverage()
    }, 0)
    return () => clearTimeout(timer)
  }, [fetchCoverage])

  const partialItems = useMemo(() => data?.partialItems || [], [data?.partialItems])
  const noCoverItems = useMemo(() => data?.noCoverItems || [], [data?.noCoverItems])
  const treeNodes = useMemo(() => data?.tree || [], [data?.tree])

  const handleGoEditor = async () => {
    setAdvancing(true)
    try {
      await stagesAPI.update(id, 8, { status: 'completed' })
      showToast('已进入 S9 人机共创编辑')
      navigate(`/projects/${id}/editor`)
    } catch (e) {
      showToast(e?.message || '进入 S9 失败', 'error')
    } finally {
      setAdvancing(false)
    }
  }

  if (loading) return <div className="animate-shimmer w-full h-96 rounded-xl"></div>

  if (error) {
    return (
      <div className="bg-error-container/20 border border-error/30 rounded-xl p-6 text-sm text-error">
        <p className="font-semibold mb-2">S8 覆盖热力图加载失败</p>
        <p>{error}</p>
        <button
          onClick={fetchCoverage}
          className="mt-4 px-4 py-2 bg-error text-on-error text-xs font-medium rounded-lg"
        >
          重新加载
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <div className="bg-gradient-to-r from-surface-container-low to-surface-container-lowest rounded-xl p-6 shadow-[0_8px_24px_-12px_rgba(0,62,111,0.06)] flex flex-wrap items-center gap-8">
        <div className="flex items-center gap-4">
          <div className="w-20 h-20 rounded-full border-4 border-secondary flex items-center justify-center">
            <span className="text-2xl font-headline font-bold text-secondary">{data?.percentage}%</span>
          </div>
          <div>
            <div className="text-lg font-headline font-bold text-on-surface">全局要求覆盖率</div>
            <div className="text-sm text-on-surface-variant">目录响应树与问题清单已同步</div>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-3 rounded-lg bg-error-container/20 px-4 py-2">
          <span className="material-symbols-outlined text-error text-lg">error</span>
          <div className="text-sm">
            <span className="font-bold text-error">{data?.noCover ?? 0}</span>
            <span className="text-on-surface-variant ml-1">项未覆盖</span>
          </div>
        </div>

        <button
          onClick={handleGoEditor}
          disabled={advancing}
          className="px-4 py-2 bg-secondary text-on-secondary text-sm font-medium rounded-lg hover:bg-secondary/90 transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <span className="material-symbols-outlined text-sm">arrow_forward</span>
          {advancing ? '进入中...' : '进入 S9 人机共创'}
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 min-h-[520px]">
        <div className="lg:col-span-5 bg-surface-container-lowest rounded-xl shadow-[0_8px_24px_-12px_rgba(0,62,111,0.06)] flex flex-col">
          <div className="px-6 py-4 border-b border-surface-container-high flex items-center gap-2">
            <span className="material-symbols-outlined text-primary">account_tree</span>
            <h3 className="text-sm font-semibold text-on-surface">需求响应评分树（按目录章节同步）</h3>
          </div>
          <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-2">
            {treeNodes.length ? treeNodes.map((node) => renderTreeNode(node)) : (
              <div className="text-sm text-outline px-2 py-3">暂无目录评分数据</div>
            )}
          </div>
        </div>

        <div className="lg:col-span-7 bg-surface-container-lowest rounded-xl shadow-[0_8px_24px_-12px_rgba(0,62,111,0.06)] flex flex-col">
          <div className="px-6 py-4 border-b border-surface-container-high flex items-center justify-between">
            <h3 className="text-sm font-semibold text-on-surface">问题清单</h3>
            <span className="text-xs text-outline">部分覆盖 {partialItems.length} 项 · 未覆盖 {noCoverItems.length} 项</span>
          </div>

          <div className="p-6 grid grid-cols-1 xl:grid-cols-2 gap-6">
            <section className="rounded-lg border border-tertiary/25 bg-tertiary-fixed/10">
              <div className="px-4 py-3 border-b border-tertiary/25 flex items-center gap-2">
                <span className="material-symbols-outlined text-tertiary text-sm">warning</span>
                <h4 className="text-sm font-semibold text-on-surface">部分覆盖（{partialItems.length}）</h4>
              </div>
              <div className="p-3 flex flex-col gap-2 max-h-[380px] overflow-y-auto">
                {partialItems.length ? partialItems.map((item) => (
                  <div key={item.id} className="rounded-lg bg-surface-container-low px-3 py-2">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium text-on-surface">{item.title}</div>
                      <span className="text-xs text-outline whitespace-nowrap">{item.id}</span>
                    </div>
                    <div className="text-xs text-on-surface-variant mt-1">{item.nodeTitle || '-'}</div>
                  </div>
                )) : (
                  <div className="text-sm text-outline p-2">暂无部分覆盖项</div>
                )}
              </div>
            </section>

            <section className="rounded-lg border border-error/25 bg-error-container/10">
              <div className="px-4 py-3 border-b border-error/25 flex items-center gap-2">
                <span className="material-symbols-outlined text-error text-sm">error</span>
                <h4 className="text-sm font-semibold text-on-surface">未覆盖（{noCoverItems.length}）</h4>
              </div>
              <div className="p-3 flex flex-col gap-2 max-h-[380px] overflow-y-auto">
                {noCoverItems.length ? noCoverItems.map((item) => (
                  <div key={item.id} className="rounded-lg bg-surface-container-low px-3 py-2">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium text-on-surface">{item.title}</div>
                      <span className="text-xs text-outline whitespace-nowrap">{item.id}</span>
                    </div>
                    <div className="text-xs text-on-surface-variant mt-1">{item.nodeTitle || '-'}</div>
                  </div>
                )) : (
                  <div className="text-sm text-outline p-2">暂无未覆盖项</div>
                )}
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  )
}
