<template>
  <div class="chat-shell">
    <div class="chat-header">
      <h2>公司内部AI助手</h2>
      <p>只基于你有权限访问的内部文档回答</p>
    </div>

    <div class="chat-body">
      <el-card v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
        <div v-if="m.role === 'assistant'">
          <div v-if="m.content" class="message-content" v-html="renderMessage(m.content)"></div>
          <div v-else class="message-content">{{ assistantPlaceholder(i) }}</div>
          <div v-if="m.sources?.length" class="source-actions">
            <el-button size="small" @click="openSources(m)">{{ sourceTriggerLabel(m) }}</el-button>
          </div>
        </div>
        <div v-else class="message-content">{{ m.content }}</div>
      </el-card>
    </div>

    <div v-if="error" class="inline-error">{{ error }}</div>
    <div class="chat-input">
      <el-input v-model="question" type="textarea" :rows="3" placeholder="请输入你的问题" @keydown.enter.exact.prevent="send" />
      <el-button type="primary" :loading="waiting" @click="send">发送</el-button>
    </div>

    <el-divider />
    <div v-if="sources.length">
      <h4>{{ activeSourceTitle }}</h4>
      <el-card v-for="(s, index) in sources" :key="sourceKey(s, index)" class="source-card">
        <div class="source-head">
          <strong>{{ sourceTitle(s) }}</strong>
          <span>{{ sourceLocation(s) }}</span>
        </div>
        <div>{{ sourceSnippet(s) || '该来源暂未返回片段内容。' }}</div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../../api'
import { useRouter } from 'vue-router'

const router = useRouter()
const question = ref('')
const sessionId = ref('')
const messages = ref<any[]>([{ role: 'assistant', content: '你好，我会基于你有权限的内部文档回答。', sources: [] }])
const sources = ref<any[]>([])
const activeSourceTitle = ref('引用来源')
const waiting = ref(false)
const waitSeconds = ref(0)
const error = ref('')
let waitTimer: ReturnType<typeof window.setInterval> | null = null

const waitText = computed(() => {
  if (waitSeconds.value <= 0) return '正在连接知识库'
  return `正在检索知识库并等待模型回答，已等待 ${waitSeconds.value} 秒`
})

function startWaitTimer() {
  stopWaitTimer()
  waiting.value = true
  waitSeconds.value = 0
  waitTimer = window.setInterval(() => {
    waitSeconds.value += 1
  }, 1000)
}

function stopWaitTimer() {
  if (waitTimer !== null) {
    window.clearInterval(waitTimer)
    waitTimer = null
  }
  waiting.value = false
  waitSeconds.value = 0
}

function stripInlineSourceMarkers(value: string) {
  return String(value || '')
    .replace(/\s*\[来源\s*\d+\]/g, '')
    .replace(/\s*（来源\s*\d+）/g, '')
    .replace(/\s*\(来源\s*\d+\)/g, '')
}

function escapeHtml(value: string) {
  return String(value || '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;',
  }[char] || char))
}

function renderMessage(value: string) {
  return escapeHtml(stripInlineSourceMarkers(value)).replace(/\n/g, '<br/>')
}

function assistantPlaceholder(index: number) {
  const isLatest = index === messages.value.length - 1
  if (waiting.value && isLatest) return waitText.value
  return '服务端暂未返回可显示内容，请稍后重试。'
}

function normalizeSources(...values: unknown[]) {
  const arr = values.find((value) => Array.isArray(value) && value.length) as any[] | undefined
  return (arr || []).filter(Boolean).map((source) => ({
    ...source,
    document_title: source.document_title || source.title || source.filename || source.document_id || '未知来源',
    content: source.content || source.snippet || source.excerpt || '',
    view_url: source.view_url || source.url || '',
  }))
}

function readableRequestError(err: any, fallback = '请求失败') {
  const detail = err?.response?.data?.detail || err?.message || fallback
  if (/failed to fetch|network error/i.test(String(detail))) {
    return '请求失败：无法连接到服务，请确认前端 5174 与后端 8000 正常运行后重试。'
  }
  return String(detail || fallback)
}

function fillAssistantMessage(message: any, data: any, overwriteAnswer = false) {
  const nextSources = normalizeSources(data?.sources, data?.citations, data?.references)
  sessionId.value = data?.session_id || sessionId.value
  if (overwriteAnswer || !message.content) message.content = stripInlineSourceMarkers(data?.answer || message.content || '')
  message.sources = nextSources
  message.mode = data?.mode || message.mode
  message.citation_mode = data?.citation_mode || message.citation_mode
  message.summary_mode = Boolean(data?.summary_mode || message.summary_mode)
  message.document_count = Number(data?.document_count || nextSources.length || 0)
}

async function sendWithJsonFallback(text: string, assistantMessage: any) {
  const res = await http.post('/chat', { question: text, session_id: sessionId.value || null })
  fillAssistantMessage(assistantMessage, res.data, true)
}

async function responseErrorMessage(response: Response) {
  try {
    const data = await response.json()
    return data?.detail || data?.message || response.statusText || '请求失败'
  } catch {
    return response.statusText || '请求失败'
  }
}

async function sendWithStream(text: string, assistantMessage: any) {
  const token = localStorage.getItem('token')
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers,
    body: JSON.stringify({ question: text, session_id: sessionId.value || null }),
  })
  if (response.status === 401) {
    router.push('/login')
    throw new Error('登录已过期，请重新登录')
  }
  if (response.status === 404 || response.status === 405 || !response.body) {
    await sendWithJsonFallback(text, assistantMessage)
    return
  }
  if (!response.ok) throw new Error(await responseErrorMessage(response))

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completed = false
  while (true) {
    const { value, done } = await reader.read()
    if (value) buffer += decoder.decode(value, { stream: !done })
    const blocks = buffer.replace(/\r\n/g, '\n').split('\n\n')
    buffer = blocks.pop() || ''
    for (const block of blocks) {
      const parsed = parseSseBlock(block)
      if (!parsed) continue
      if (parsed.event === 'delta') assistantMessage.content += stripInlineSourceMarkers(String(parsed.data?.delta || parsed.data || ''))
      if (parsed.event === 'meta') fillAssistantMessage(assistantMessage, parsed.data)
      if (parsed.event === 'done') {
        fillAssistantMessage(assistantMessage, parsed.data, !assistantMessage.content)
        completed = true
      }
    }
    if (done) break
  }
  if (!completed && !assistantMessage.content) throw new Error('流式响应未完整结束，请稍后重试')
}

function parseSseBlock(block: string): { event: string; data: any } | null {
  const trimmed = block.trim()
  if (!trimmed) return null
  let event = 'message'
  const dataLines: string[] = []
  for (const line of trimmed.split(/\r?\n/)) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
  }
  if (!dataLines.length) return null
  const raw = dataLines.join('\n')
  try {
    return { event, data: JSON.parse(raw) }
  } catch {
    return { event, data: raw }
  }
}

async function send() {
  if (!question.value.trim() || waiting.value) return
  const userText = question.value.trim()
  const userMessage = { role: 'user', content: userText, sources: [] }
  const assistantMessage = { role: 'assistant', content: '', sources: [] }
  messages.value.push(userMessage, assistantMessage)
  question.value = ''
  error.value = ''
  startWaitTimer()
  try {
    await sendWithStream(userText, assistantMessage)
    if (!assistantMessage.content) {
      assistantMessage.content = '本次请求已完成，但服务端没有返回可显示的回答内容。请稍后重试，或缩小问题范围后再试。'
    }
    if (assistantMessage.sources?.length) openSources(assistantMessage)
  } catch (e: any) {
    const detail = readableRequestError(e, '发送失败')
    error.value = detail
    if (e.response?.status === 401) router.push('/login')
    if (!assistantMessage.content) assistantMessage.content = `发送失败：${detail}`
    else assistantMessage.content += `\n\n发送中断：${detail}`
    ElMessage.error(detail)
  } finally {
    stopWaitTimer()
  }
}

function openSources(message: any) {
  sources.value = normalizeSources(message.sources, message.citations, message.references)
  activeSourceTitle.value = isDocumentOverview(message) ? '可读文档范围' : '相关来源'
}

function isDocumentOverview(message: any) {
  return Boolean(message?.citation_mode === 'accessible_documents' || message?.summary_mode)
}

function sourceTriggerLabel(message: any) {
  return isDocumentOverview(message) ? '查看文档清单' : '查看来源'
}

function sourceKey(source: any, index: number) {
  return String(source.chunk_id || source.document_id || source.view_url || source.filename || source.title || index)
}

function sourceTitle(source: any) {
  return String(source.document_title || source.title || source.filename || source.document_id || '未知来源')
}

function sourceSnippet(source: any) {
  return String(source.content || source.snippet || source.excerpt || '')
}

function sourceLocation(source: any) {
  if (source.page_number === 0 || source.page_number) return `第 ${source.page_number} 页`
  if (source.chunk_index === 0 || source.chunk_index) return `片段 ${source.chunk_index}`
  return '位置未知'
}

onUnmounted(() => {
  stopWaitTimer()
})
</script>
