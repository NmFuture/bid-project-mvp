import { ENV } from './env'

// OnlyOffice Document Server 配置（环境变量驱动）

export const loadOnlyOfficeScript = (src) =>
  new Promise((resolve, reject) => {
    if (typeof window === 'undefined') {
      reject(new Error('OnlyOffice 仅支持浏览器环境'))
      return
    }

    if (window.DocsAPI) {
      resolve(window.DocsAPI)
      return
    }

    const existing = document.querySelector(`script[data-onlyoffice-script="1"][src="${src}"]`)
    if (existing) {
      existing.addEventListener('load', () => resolve(window.DocsAPI), { once: true })
      existing.addEventListener('error', () => reject(new Error('OnlyOffice 脚本加载失败')), { once: true })
      return
    }

    const script = document.createElement('script')
    script.src = src
    script.async = true
    script.dataset.onlyofficeScript = '1'
    script.onload = () => resolve(window.DocsAPI)
    script.onerror = () => reject(new Error('OnlyOffice 脚本加载失败'))
    document.body.appendChild(script)
  })

export const ONLYOFFICE_CONFIG = {
  // OnlyOffice Document Server 地址（从环境变量读取）
  documentServerUrl: ENV.ONLYOFFICE_DOCUMENT_SERVER_URL,

  // API 脚本路径
  apiScriptUrl: '/web-apps/apps/api/documents/api.js',

  // 获取完整的编辑器配置
  getEditorConfig: ({
    documentKey,
    title,
    fileUrl,
    callbackUrl,
    userId,
    userName,
    fileType = 'docx',
    documentType,
  }) => {
    const normalizedFileType = String(fileType || 'docx').toLowerCase()
    const resolvedDocumentType = documentType
      || (normalizedFileType === 'pdf'
        ? 'pdf'
        : ['xls', 'xlsx', 'csv'].includes(normalizedFileType)
          ? 'cell'
          : ['ppt', 'pptx'].includes(normalizedFileType)
            ? 'slide'
            : 'word')

    return {
      document: {
        fileType: normalizedFileType,
      key: documentKey,
      title: title || '投标文件.docx',
      url: fileUrl,
      permissions: {
        comment: true,
        download: true,
        edit: true,
        print: true,
        review: true,
      },
    },
      documentType: resolvedDocumentType,
    editorConfig: {
      callbackUrl: callbackUrl,
      lang: 'zh-CN',
      mode: 'edit',
      user: {
        id: userId || 'user-1',
        name: userName || '当前用户',
      },
      customization: {
        autosave: true,
        chat: false,
        comments: true,
        compactHeader: false,
        compactToolbar: true,
        forcesave: true,
        help: false,
        hideRightMenu: false,
        logo: {
          image: '',
          imageEmbedded: '',
          url: '',
        },
        reviewDisplay: 'markup',
        toolbarNoTabs: false,
        uiTheme: 'theme-light',
      },
    },
    height: '100%',
    width: '100%',
    type: 'desktop',
    }
  },

  // 检查 OnlyOffice 是否可用
  isAvailable: async () => {
    try {
      const response = await fetch(
        `${ENV.ONLYOFFICE_DOCUMENT_SERVER_URL}${ENV.ONLYOFFICE_HEALTHCHECK_PATH}`,
        {
          method: 'GET',
          signal: AbortSignal.timeout(3000),
        },
      )
      return response.ok
    } catch {
      return false
    }
  },
}
