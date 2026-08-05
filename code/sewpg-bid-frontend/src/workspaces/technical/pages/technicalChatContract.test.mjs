import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const apiSource = await readFile(new URL('../../../api/index.js', import.meta.url), 'utf8')
const editorSource = await readFile(new URL('./TechnicalCoCreationEditor.jsx', import.meta.url), 'utf8')

test('技术标 AI 正常回复渲染 Markdown，用户消息和错误消息保持纯文本', () => {
  assert.match(
    editorSource,
    /import MarkdownLite from '\.\.\/\.\.\/\.\.\/components\/shared\/MarkdownLite'/,
  )
  assert.match(
    editorSource,
    /message\.role === 'assistant' && !message\.error \? \(\s*<MarkdownLite content=\{message\.content\} compact \/>\s*\) : \(\s*<div className="whitespace-pre-wrap break-words">\{message\.content\}<\/div>/s,
  )
})

test('技术标 AI 对话 API 使用独立端点和两分钟超时', () => {
  assert.match(
    apiSource,
    /technicalChat:\s*\(projectId, data\)\s*=>\s*request\(`\/technical\/projects\/\$\{projectId\}\/document\/technical-chat`,\s*\{\s*method:\s*'POST',\s*body:\s*data,\s*timeoutMs:\s*2\s*\*\s*60\s*\*\s*1000\s*\}\)/s,
  )
})

test('技术标 AI 对话仅发送当前消息与 sessionId，并支持新对话重置', () => {
  assert.match(editorSource, /technicalDocumentAPI\.technicalChat\(id,\s*\{\s*message,\s*sessionId:\s*chatSessionId,?\s*\}\)/s)
  assert.doesNotMatch(editorSource, /technicalDocumentAPI\.technicalChat[\s\S]*?history\s*:/)
})

test('技术标 AI 对话成功后续接 session 并展示回复与降级模型提示', () => {
  assert.match(editorSource, /if \(response\?\.sessionId\) setChatSessionId\(response\.sessionId\)/)
  assert.match(editorSource, /content:\s*response\?\.reply \|\| '未返回有效建议。'/)
  assert.match(editorSource, /fallbackModelUsed:\s*Boolean\(response\?\.fallbackModelUsed\)/)
  assert.match(editorSource, /const modelLabel = response\?\.providerId && response\?\.modelId[\s\S]*?`\$\{response\.providerId\}\/\$\{response\.modelId\}`/)
  assert.match(editorSource, /if \(response\?\.fallbackModelUsed\)\s*\{[\s\S]*?showToast\?\.\(`系统设置模型不可用，已使用 \$\{modelLabel \|\| 'opencode 默认模型'\} 完成回复。`, 'warning'\)/)
  assert.match(editorSource, /message\.fallbackModelUsed \? `AI助手（\$\{message\.modelLabel \|\| '默认模型'\}）` : 'AI助手'/)
})

test('技术标 AI 对话失败时追加错误气泡并弹出错误提示', () => {
  assert.match(editorSource, /catch \(e\)\s*\{[\s\S]*?setChatMessages\(\(current\) => \[\s*\.\.\.current,\s*\{ role: 'assistant', content: e\?\.message \|\| 'AI 对话失败，请稍后重试。', error: true \},\s*\]\)\s*showToast\?\.\(e\?\.message \|\| 'AI 对话失败', 'error'\)/s)
  assert.match(editorSource, /message\.error \? 'mr-8 bg-error\/10 text-error'/)
})

test('技术标 AI 对话消息变化后滚动到底部', () => {
  assert.match(editorSource, /if \(!chatHistoryRef\.current\) return\s*chatHistoryRef\.current\.scrollTop = chatHistoryRef\.current\.scrollHeight/s)
  assert.match(editorSource, /\}, \[chatMessages, chatLoading\]\)/)
})

test('技术标共创页提供完整对话控件并移除未接入占位', () => {
  assert.doesNotMatch(editorSource, /技术标 AI 对话接口尚未接入/)
  assert.match(editorSource, /ref=\{chatHistoryRef\}/)
  assert.match(editorSource, /Ctrl\/?⌘\s*\+\s*Enter/)
  assert.match(editorSource, />新对话</)
  assert.match(editorSource, />发送给AI</)
  assert.match(editorSource, /不会自动修改 Word/)
})

test('技术标 AI 输入受控，按钮和 Ctrl/Cmd Enter 均调用发送处理', () => {
  assert.match(editorSource, /<textarea[\s\S]*?value=\{chatInput\}\s*onChange=\{\(event\) => setChatInput\(event\.target\.value\)\}/s)
  assert.match(editorSource, /if \(\(event\.metaKey \|\| event\.ctrlKey\) && event\.key === 'Enter'\)\s*\{\s*event\.preventDefault\(\)\s*handleTechnicalChat\(\)/s)
  assert.match(editorSource, /onClick=\{handleTechnicalChat\}\s*disabled=\{chatLoading \|\| !chatInput\.trim\(\)\}/s)
})

test('技术标 AI 面板移除重复的受控应用到 Word 区块', () => {
  assert.doesNotMatch(editorSource, /受控应用到 Word/)
  assert.doesNotMatch(editorSource, /人工确认后写入/)
  assert.doesNotMatch(editorSource, /前往格式设置/)
})

test('切换项目时重置对话并让旧项目请求失效', () => {
  assert.match(editorSource, /const chatRequestVersionRef = useRef\(0\)/)
  assert.match(
    editorSource,
    /useEffect\(\(\) => \{\s*chatRequestVersionRef\.current \+= 1\s*setChatMessages\([^)]+\)\s*setChatInput\(''\)\s*setChatLoading\(false\)\s*setChatSessionId\(''\)[\s\S]*?return \(\) => \{\s*chatRequestVersionRef\.current \+= 1\s*\}\s*\}, \[id\]\)/,
  )
})

test('迟到的成功、失败和 finally 均不能写入当前对话', () => {
  assert.match(editorSource, /const requestVersion = \+\+chatRequestVersionRef\.current/)
  assert.match(editorSource, /const response = await technicalDocumentAPI\.technicalChat[\s\S]*?if \(requestVersion !== chatRequestVersionRef\.current\) return/)
  assert.match(editorSource, /catch \(e\) \{\s*if \(requestVersion !== chatRequestVersionRef\.current\) return/)
  assert.match(editorSource, /finally \{\s*if \(requestVersion === chatRequestVersionRef\.current\) setChatLoading\(false\)\s*\}/)
})

test('生成期间禁止新对话，空闲时重置会话并使旧请求版本失效', () => {
  assert.match(editorSource, /const handleNewTechnicalChat = \(\) => \{\s*if \(chatLoading\) return\s*chatRequestVersionRef\.current \+= 1\s*setChatSessionId\(''\)\s*setChatInput\(''\)\s*setChatLoading\(false\)\s*setChatMessages\(\[\]\)\s*\}/)
  assert.match(editorSource, /onClick=\{handleNewTechnicalChat\}\s*disabled=\{chatLoading\}/)
})

test('消息区和输入框具备可访问语义，长连续文本不会撑破布局', () => {
  assert.match(editorSource, /ref=\{chatHistoryRef\}\s*role="log"\s*aria-live="polite"/)
  assert.match(editorSource, /aria-label="技术标 AI 对话输入"/)
  assert.match(editorSource, /className="whitespace-pre-wrap break-words"/)
})
