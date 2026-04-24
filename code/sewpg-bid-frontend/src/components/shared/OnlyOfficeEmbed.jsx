import { useEffect, useId, useMemo } from 'react'
import { ONLYOFFICE_CONFIG } from '../../config/onlyoffice'

const buildHostPath = () => {
  const base = import.meta.env.BASE_URL || '/'
  return `${base.endsWith('/') ? base : `${base}/`}onlyoffice-host.html`
}

export default function OnlyOfficeEmbed({
  session,
  mode = 'edit',
  className = '',
  onReady,
  onError,
}) {
  const requestId = useId().replaceAll(':', '')

  const iframeSrc = useMemo(() => {
    const fileUrl = session?.fileUrl || session?.browserFileUrl
    const probeUrl = session?.browserFileUrl || session?.fileUrl
    const config = ONLYOFFICE_CONFIG.getEditorConfig({
      documentKey: session?.documentKey,
      title: session?.title,
      // OnlyOffice Document Server resolves document URLs server-side,
      // so prefer the container-reachable internal URL here.
      fileUrl,
      callbackUrl: session?.callbackUrl,
      userId: session?.user?.id,
      userName: session?.user?.name,
      fileType: session?.fileType,
      documentType: session?.documentType,
    })

    if (mode === 'view') {
      config.editorConfig.mode = 'view'
      if (config.document?.permissions) {
        config.document.permissions.edit = false
        config.document.permissions.review = false
        config.document.permissions.comment = false
      }
    }

    const payload = {
      requestId,
      documentServerUrl: ONLYOFFICE_CONFIG.documentServerUrl,
      config,
      probeDocumentUrl: probeUrl,
    }
    return `${buildHostPath()}#${encodeURIComponent(JSON.stringify(payload))}`
  }, [mode, requestId, session])

  useEffect(() => {
    const handleMessage = (event) => {
      if (event.origin !== window.location.origin) return
      const payload = event.data
      if (!payload || payload.source !== 'onlyoffice-host') return
      if (payload.requestId !== requestId) return

      if (payload.type === 'error') {
        onError?.(payload.message || 'OnlyOffice 运行异常，请检查文档服务状态。')
        return
      }

      if (payload.type === 'ready' || payload.type === 'document-ready') {
        onReady?.(payload)
      }
    }

    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [onError, onReady, requestId])

  return (
    <iframe
      title={mode === 'view' ? 'OnlyOffice 文档预览' : 'OnlyOffice 文档编辑器'}
      src={iframeSrc}
      className={className}
      allow="clipboard-read; clipboard-write"
    />
  )
}
