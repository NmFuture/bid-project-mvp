import { useState, useEffect } from 'react'
import { materialsAPI } from '../../api'

export default function MaterialSelectModal({ onClose, onSelected }) {
  const [materials, setMaterials] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [keyword, setKeyword] = useState('')
  const [selectedId, setSelectedId] = useState(null)

  useEffect(() => {
    let mounted = true
    materialsAPI.structured.list()
      .then((d) => {
        if (!mounted) return
        setMaterials(d?.items || [])
        setError('')
      })
      .catch((e) => {
        if (!mounted) return
        setMaterials([])
        setError(e?.message || '素材列表加载失败')
      })
      .finally(() => {
        if (mounted) setLoading(false)
      })
    return () => {
      mounted = false
    }
  }, [])

  const normalizedKeyword = keyword.trim()
  const filtered = materials.filter((m) => {
    const name = String(m?.name || '')
    const type = String(m?.type || '')
    if (!normalizedKeyword) return true
    return name.includes(normalizedKeyword) || type.includes(normalizedKeyword)
  })

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog-content w-full max-w-2xl animate-fade-in" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-surface-container-high">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-primary">inventory_2</span>
            <h2 className="text-lg font-headline font-bold text-on-surface">从素材库选择</h2>
          </div>
          <button onClick={onClose} className="text-on-surface-variant hover:text-primary transition-colors">
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        <div className="p-6 flex flex-col gap-4">
          <div className="relative">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-outline text-lg">search</span>
            <input
              className="w-full h-11 pl-10 pr-4 bg-surface-container-highest border-none rounded-lg text-sm focus:ring-2 focus:ring-primary/30 transition-all placeholder:text-outline"
              placeholder="搜索文档名称或类型..."
              value={keyword}
              onChange={e => setKeyword(e.target.value)}
            />
          </div>

          <div className="flex-1 overflow-y-auto max-h-[400px] border border-surface-container-high rounded-xl">
            {loading ? (
              <div className="p-4 flex flex-col gap-3">
                <div className="h-12 bg-surface-container-low rounded animate-pulse"></div>
                <div className="h-12 bg-surface-container-low rounded animate-pulse"></div>
              </div>
            ) : error ? (
              <div className="p-8 text-center text-error text-sm">{error}</div>
            ) : filtered.length === 0 ? (
              <div className="p-8 text-center text-outline text-sm">暂无匹配素材</div>
            ) : (
              <div className="flex flex-col text-sm">
                {filtered.map(m => (
                  <label key={m.id} className={`flex items-center gap-3 p-4 cursor-pointer border-b last:border-0 border-surface-container-high/50 hover:bg-surface-container-low transition-colors ${selectedId === m.id ? 'bg-primary/5' : ''}`}>
                    <input 
                      type="radio" 
                      name="material_select" 
                      className="w-4 h-4 text-primary focus:ring-primary"
                      checked={selectedId === m.id}
                      onChange={() => setSelectedId(m.id)}
                    />
                    <span className={`material-symbols-outlined ${selectedId === m.id ? 'text-primary' : 'text-outline'}`}>{m.icon}</span>
                    <div className="flex-1">
                      <div className="font-medium text-on-surface">{m.name}</div>
                      <div className="flex items-center gap-2 text-xs text-outline mt-1">
                        <span className="bg-surface-container-high px-1.5 rounded">{m.type}</span>
                        <span>{m.version}</span>
                        <span>{m.updatedAt}</span>
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="px-6 py-4 border-t border-surface-container-high flex justify-end gap-3 bg-surface-container-low rounded-b-xl">
          <button onClick={onClose} className="px-5 py-2.5 text-sm font-medium text-on-surface-variant hover:bg-surface-container-high rounded-lg transition-colors">
            取消
          </button>
          <button
            disabled={!selectedId}
            onClick={() => onSelected(materials.find(m => m.id === selectedId))}
            className="px-6 py-2.5 bg-primary text-on-primary font-medium rounded-lg hover:bg-primary-container transition-colors disabled:opacity-50"
          >
            确认选择
          </button>
        </div>
      </div>
    </div>
  )
}
