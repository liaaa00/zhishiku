<template>
  <div class="ai-workbench">
    <aside class="ai-sidebar">
      <div class="brand-card">
        <div class="brand-logo">AI</div>
        <div>
          <div class="brand-title">内部 AI 助手</div>
          <div class="brand-subtitle">Knowledge Copilot</div>
        </div>
      </div>

      <button class="new-chat" type="button" @click="newConversation">
        <span>＋</span>
        新建对话
      </button>

      <div class="side-section-title">最近对话</div>
      <div class="session-list">
        <div
          v-for="item in visibleSessions"
          :key="item.id"
          :class="['session-row', { active: item.id === sessionId }]"
        >
          <button
            :class="['session-item', { active: item.id === sessionId }]"
            type="button"
            @click="openSession(item.id)"
          >
            <span class="session-main">{{ item.title || '新的对话' }}</span>
            <span class="session-meta">{{ item.preview || '暂无预览' }}</span>
          </button>
          <button class="session-delete" type="button" title="删除会话" @click.stop="deleteSession(item.id)">×</button>
        </div>
        <div v-if="!sessions.length" class="empty-side">暂无历史对话</div>
      </div>

      <div class="side-footer">
        <button v-if="isAdmin" class="side-action" type="button" @click="router.push('/admin')">后台管理</button>
        <button class="side-action subtle" type="button" @click="logout">退出登录</button>
      </div>
    </aside>

    <main class="ai-main">
      <header class="topbar">
        <div>
          <div class="eyebrow">内部 AI 助手</div>
          <h1>知识库问答</h1>
        </div>
        <div class="topbar-actions">
          <span class="status-pill">可上传文件</span>
          <span class="status-pill dark">引用可查</span>
        </div>
      </header>

      <section ref="chatBodyRef" class="conversation-panel">
        <div v-if="showHero" class="hero-panel">
          <h2>有什么可以帮忙的？</h2>
          <p>可以直接提问，也可以上传文件后让我总结、整理表格或核对引用来源。</p>
          <div class="prompt-grid">
            <button v-for="item in promptCards" :key="item" type="button" @click="askPrompt(item)">{{ item }}</button>
          </div>
        </div>

        <article v-for="message in visibleMessages" :key="message.id" :class="['message-row', message.role]">
          <div class="avatar">{{ message.role === 'assistant' ? 'AI' : '我' }}</div>
          <div class="message-card">
            <div class="message-head">
              <strong>{{ message.role === 'assistant' ? 'AI 助手' : '我' }}</strong>
              <span>{{ formatTime(message.created_at) }}</span>
            </div>

            <div v-if="message.role === 'assistant'" class="assistant-answer-shell">
              <div v-if="showAnswerMeta(message)" class="answer-meta">
                <span class="answer-meta-pill primary">{{ answerModeLabel(message) }}</span>
                <span v-if="message.sources.length" class="answer-meta-pill">{{ sourceBlockCount(message) }}</span>
                <span v-if="message.waitSeconds && message.streaming" class="answer-meta-pill subtle">已等待 {{ message.waitSeconds }} 秒</span>
              </div>

              <div v-if="message.streaming" class="answer-live">
                <div class="answer-live-status">
                  <span class="streaming-dot"></span>
                  <span>{{ message.pendingText || '已连接模型，正在组织回答…' }}</span>
                </div>
                <pre v-if="message.content" class="answer-live-body">{{ message.content }}</pre>
              </div>

              <div v-else class="assistant-answer">
                <div v-if="getStructuredOutline(message).length" class="answer-structure-bar">
                  <div class="answer-outline">
                    <button
                      v-for="item in getStructuredOutline(message)"
                      :key="`${message.id}-${item.index}`"
                      class="answer-outline-chip"
                      type="button"
                      @click="scrollToSection(message, item.index)"
                    >
                      {{ item.title }}
                    </button>
                  </div>
                  <div class="answer-outline-actions">
                    <button type="button" @click="expandAllSections(message)">展开全部</button>
                    <button type="button" @click="collapseSecondarySections(message)">折叠次级</button>
                  </div>
                </div>

                <div class="answer-sections">
                  <section
                    v-for="(block, blockIndex) in getStructuredSections(message)"
                    :id="sectionDomId(message, blockIndex)"
                    :key="`${message.id}-block-${blockIndex}`"
                    :class="['answer-section', block.kind, { 'has-title': !!block.title, collapsed: isSectionCollapsed(message, blockIndex) }]"
                  >
                    <header v-if="block.title" class="answer-section-head">
                      <button
                        type="button"
                        class="answer-section-trigger"
                        :aria-expanded="String(!isSectionCollapsed(message, blockIndex))"
                        @click="toggleSectionCollapse(message, blockIndex)"
                      >
                        <span v-if="block.badge" class="answer-section-badge">{{ block.badge }}</span>
                        <h3>{{ block.title }}</h3>
                      </button>
                      <div class="answer-section-controls">
                        <button
                          v-if="relatedSourceCount(message, block)"
                          type="button"
                          class="section-source-link"
                          @click.stop="openSources(message, blockIndex)"
                        >
                          关联来源 {{ relatedSourceCount(message, block) }}
                        </button>
                        <button
                          type="button"
                          class="section-collapse-button"
                          @click.stop="toggleSectionCollapse(message, blockIndex)"
                        >
                          {{ isSectionCollapsed(message, blockIndex) ? '展开' : '收起' }}
                        </button>
                      </div>
                    </header>
                    <div
                      v-show="!block.title || !isSectionCollapsed(message, blockIndex)"
                      class="message-text markdown section-body"
                      v-html="block.html"
                    ></div>
                  </section>
                </div>
              </div>
            </div>
            <div v-else class="message-text user-text">{{ message.content }}</div>

            <div v-if="message.role === 'assistant' && message.sources.length" class="source-strip">
              <div>
                <strong>{{ sourceBlockTitle(message) }}</strong>
                <span>{{ sourceBlockSubtitle(message) }}</span>
              </div>
              <button type="button" @click="openSources(message)">{{ sourceTriggerLabel(message) }}</button>
            </div>

            <div v-if="message.role === 'assistant' && message.id !== 'welcome'" class="message-actions">
              <button type="button" @click="copyText(stripInlineSourceMarkers(message.content))">复制</button>
              <button type="button" :disabled="message.feedbackSubmitted" @click="openFeedbackDialog(message, 'helpful')">有帮助</button>
              <button type="button" :disabled="message.feedbackSubmitted" @click="openFeedbackDialog(message, 'unhelpful')">不够好</button>
              <button type="button" :disabled="message.feedbackSubmitted" @click="openFeedbackDialog(message, 'user_feedback')">我要补充反馈</button>
              <span v-if="message.feedbackSubmitted">已反馈</span>
            </div>
          </div>
        </article>
      </section>

      <el-dialog
        v-model="feedbackDialogVisible"
        title="提交反馈"
        width="min(560px, calc(100vw - 32px))"
        class="feedback-dialog"
        destroy-on-close
      >
        <div class="feedback-dialog-body">
          <div class="feedback-dialog-intro">
            <strong>{{ feedbackDialogTitle }}</strong>
            <span>请尽量写清楚问题、期望结果，或这条回答哪里有帮助。</span>
          </div>
          <el-input
            v-model="feedbackForm.content"
            type="textarea"
            :autosize="{ minRows: 5, maxRows: 10 }"
            maxlength="2000"
            show-word-limit
            resize="none"
            :placeholder="feedbackPlaceholderOf(feedbackTargetRating)"
          />
        </div>
        <template #footer>
          <div class="feedback-dialog-footer">
            <button type="button" class="dialog-secondary-button" @click="closeFeedbackDialog">取消</button>
            <button type="button" class="dialog-primary-button" :disabled="feedbackSubmitting || !feedbackForm.content.trim()" @click="confirmFeedbackSubmit">
              {{ feedbackSubmitting ? '提交中…' : '提交反馈' }}
            </button>
          </div>
        </template>
      </el-dialog>

      <footer class="composer-shell">
        <div v-if="error" class="inline-error">{{ error }}</div>
        <input
          ref="imageInputRef"
          class="hidden-file-input"
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          multiple
          @change="handleAttachmentInput($event, 'image')"
        />
        <input
          ref="fileInputRef"
          class="hidden-file-input"
          type="file"
          accept=".pdf,.docx,.pptx,.xlsx,.csv,.txt,.md,.markdown,image/png,image/jpeg,image/webp,image/gif"
          multiple
          @change="handleAttachmentInput($event, 'file')"
        />
        <div v-if="pendingAttachments.length" class="attachment-strip" aria-label="已上传附件">
          <article v-for="item in pendingAttachments" :key="item.localId" class="attachment-chip-modern">
            <span class="attachment-icon" aria-hidden="true">{{ attachmentIcon(item) }}</span>
            <span class="attachment-main">
              <strong>{{ item.filename }}</strong>
              <small>{{ attachmentStatusText(item) }}</small>
            </span>
            <button type="button" class="attachment-remove" :disabled="sending" @click="removeAttachment(item.localId)">×</button>
          </article>
        </div>
        <div class="composer">
          <div class="composer-tools">
            <button
              class="attachment-button"
              type="button"
              :class="{ active: attachmentMenuOpen }"
              :disabled="sending || uploadingAttachment"
              title="上传图片或文件"
              @click="toggleAttachmentMenu"
            >
              <span aria-hidden="true">+</span>
            </button>
            <div v-if="attachmentMenuOpen" class="attachment-menu">
              <button type="button" @click="openAttachmentPicker('image')">
                <span class="attachment-menu-icon">▧</span>
                <span><strong>上传图片</strong><small>PNG / JPG / WebP / GIF</small></span>
              </button>
              <button type="button" @click="openAttachmentPicker('file')">
                <span class="attachment-menu-icon">□</span>
                <span><strong>上传文件</strong><small>PDF / Word / PPT / Excel / TXT</small></span>
              </button>
            </div>
          </div>
          <el-input
            v-model="question"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 6 }"
            resize="none"
            :disabled="sending"
            maxlength="2000"
            :placeholder="pendingAttachments.length ? '描述你想基于附件了解什么…' : '输入问题，Shift + Enter 换行'"
            @keydown.enter.exact="onEnter"
          />
          <button class="send-button" type="button" :disabled="sending || (!question.trim() && !readyAttachmentCount)" @click="send">
            <span v-if="sending" class="spinner"></span>
            <span v-else>发送</span>
          </button>
        </div>
        <div class="composer-note">可上传图片或文件后提问；回答会尽量基于可访问资料生成，请结合引用来源核验重要结论。</div>
      </footer>
    </main>

    <aside v-if="sourcePanelVisible" class="source-panel">
      <header>
        <div>
          <strong>{{ sourcePanelTitle }}</strong>
          <span>{{ sourcePanelCount }}</span>
        </div>
        <button type="button" @click="closeSourcePanel">×</button>
      </header>

      <div class="source-panel-toolbar">
        <div class="source-filter">
          <button :class="{ active: sourceViewMode === 'all' }" type="button" @click="setSourceViewMode('all')">
            {{ isSourcePanelDocumentOverview ? '全部文档' : '全部来源' }}
          </button>
          <button
            :class="{ active: sourceViewMode === 'related' }"
            type="button"
            :disabled="activeSourceSectionIndex === null"
            @click="setSourceViewMode('related')"
          >
            相关来源
          </button>
        </div>
        <div v-if="activeSourceSection?.title && sourceViewMode === 'related'" class="source-panel-note">
          正在查看“{{ activeSourceSection.title }}”的关联来源
        </div>
      </div>

      <section v-if="isSourcePanelDocumentOverview" class="document-overview-panel">
        <div class="document-overview-stats">
          <div class="document-overview-stat">
            <span>可读文档</span>
            <strong>{{ overviewDocumentTotal }}</strong>
          </div>
          <div class="document-overview-stat">
            <span>当前展示</span>
            <strong>{{ filteredSources.length }}</strong>
          </div>
          <div class="document-overview-stat">
            <span>展示方式</span>
            <strong>{{ sourceViewMode === 'related' ? '按回答段落筛选' : '全量清单' }}</strong>
          </div>
        </div>
        <p>
          这里展示的是你当前有权限访问的文档清单。摘要模式会默认把每份文档已解析出的全部片段交给模型；列表中仅展示摘要预览，点击“预览内容”可继续查看原始片段。
        </p>
      </section>

      <div ref="sourceScrollRef" class="source-scroll">
        <article
          v-for="(source, index) in filteredSources"
          :key="sourceKey(source, index)"
          :data-source-key="sourceKey(source, index)"
          :class="['source-card-modern', {
            related: sourceViewMode === 'related',
            highlighted: isHighlightedSource(source, index),
            overview: isSourcePanelDocumentOverview,
          }]"
        >
          <div class="source-index">{{ index + 1 }}</div>
          <div class="source-body">
            <div class="source-headline">
              <h3>{{ sourceTitle(source) }}</h3>
              <span v-if="source.summary_source" class="source-coverage-pill">已纳入 {{ source.chunks_used || 0 }}/{{ source.total_chunks || 0 }}</span>
            </div>
            <p>{{ sourceSnippet(source) || '该来源暂未返回片段内容。' }}</p>
            <div class="source-meta">{{ sourceType(source) }} · {{ sourceLocation(source) }}</div>
            <div class="source-actions">
              <button type="button" @click="previewSource(source)">预览内容</button>
              <button type="button" @click="openSource(source)">{{ openSourceLabel(source) }}</button>
            </div>
          </div>
        </article>

        <div v-if="!filteredSources.length" class="source-empty">
          当前回答段落还没有匹配到更明确的来源，可以切换到“全部来源”查看完整范围。
        </div>
      </div>

      <section v-if="previewSourceTitle" class="preview-box">
        <div class="preview-head">
          <strong>{{ previewSourceTitle }}</strong>
          <button type="button" @click="clearPreview">收起</button>
        </div>
        <pre>{{ previewText || '暂无可预览内容。' }}</pre>
      </section>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../../api'
import { useRouter } from 'vue-router'

type Role = 'assistant' | 'user'
type FeedbackRating = 'helpful' | 'unhelpful' | 'wrong' | 'unsafe' | 'other' | 'user_feedback'

type StructuredSectionKind = 'lead' | 'section' | 'highlight' | 'warning' | 'action'

interface SourceItem {
  document_id?: string
  document_title?: string
  title?: string
  filename?: string
  chunk_id?: string | null
  page_number?: number | string | null
  chunk_index?: number | string | null
  source_type?: string
  content?: string
  snippet?: string
  excerpt?: string
  view_url?: string
  url?: string
  content_url?: string
  summary_source?: boolean
  chunks_used?: number | string | null
  total_chunks?: number | string | null
  [key: string]: unknown
}

interface StructuredSection {
  title: string
  html: string
  plainText: string
  kind: StructuredSectionKind
  badge?: string
}

interface StructuredOutlineItem {
  index: number
  title: string
}

interface ChatMessageItem {
  id: string
  role: Role
  content: string
  created_at?: string
  sources: SourceItem[]
  pendingText?: string
  waitStartedAt?: number
  waitSeconds?: number
  streaming?: boolean
  mode?: string
  citation_mode?: string
  document_count?: number
  summary_mode?: boolean
  feedbackSubmitted?: boolean
}

interface SessionSummary {
  id: string
  title: string
  preview: string
  message_count: number
  created_at: string
}

type AttachmentKind = 'image' | 'file'
type AttachmentStatus = 'uploading' | 'ready' | 'failed'

interface PendingAttachment {
  localId: string
  id?: string
  filename: string
  title?: string
  kind: AttachmentKind
  extension?: string
  status: AttachmentStatus
  message?: string
  task_id?: string
}

const SPREADSHEET_EXTENSIONS = new Set(['csv', 'xlsx', 'xls', 'tsv'])
const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif'])

const router = useRouter()
const chatBodyRef = ref<HTMLElement | null>(null)
const imageInputRef = ref<HTMLInputElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const question = ref('')
const sessionId = ref('')
const sending = ref(false)
const uploadingAttachment = ref(false)
const attachmentMenuOpen = ref(false)
const pendingAttachments = ref<PendingAttachment[]>([])
const error = ref('')
const isAdmin = ref(false)
const sessions = ref<SessionSummary[]>([])
const messages = ref<ChatMessageItem[]>([welcomeMessage()])
const sourcePanelVisible = ref(false)
const activeSourceMessage = ref<ChatMessageItem | null>(null)
const activeSourceSectionIndex = ref<number | null>(null)
const sourceViewMode = ref<'all' | 'related'>('all')
const highlightedSourceKey = ref('')
const sourceScrollRef = ref<HTMLElement | null>(null)
const collapsedSectionState = ref<Record<string, Record<number, boolean>>>({})
const structuredSectionCache = new Map<string, { content: string; sections: StructuredSection[] }>()
const previewText = ref('')
const previewSourceTitle = ref('')
const feedbackDialogVisible = ref(false)
const feedbackSubmitting = ref(false)
const feedbackTargetMessage = ref<ChatMessageItem | null>(null)
const feedbackTargetRating = ref<FeedbackRating>('user_feedback')
const feedbackForm = ref({ content: '' })

const promptCards = [
  '总结我现在可读的文档',
  '列出回答的引用来源',
  '把内容整理成表格',
  '指出风险点和需要补充的资料',
]

const visibleMessages = computed(() => messages.value.filter((message) => message.id !== 'welcome'))
const showHero = computed(() => visibleMessages.value.length === 0)
const visibleSessions = computed(() => sessions.value.slice(0, 80))
const readyAttachmentCount = computed(() => pendingAttachments.value.filter((item) => item.status === 'ready').length)
const activeSources = computed(() => activeSourceMessage.value?.sources || [])
const activeSourceSection = computed(() => {
  const message = activeSourceMessage.value
  const sectionIndex = activeSourceSectionIndex.value
  if (!message || sectionIndex === null) return null
  return getStructuredSections(message)[sectionIndex] || null
})
const filteredSources = computed(() => {
  const message = activeSourceMessage.value
  if (!message) return []
  if (sourceViewMode.value === 'all' || activeSourceSectionIndex.value === null) return activeSources.value
  const section = activeSourceSection.value
  return section ? getRelatedSources(message, section) : []
})
const feedbackDialogTitle = computed(() => {
  if (feedbackTargetRating.value === 'helpful') return '提交正向反馈'
  if (feedbackTargetRating.value === 'unhelpful') return '提交问题反馈'
  return '补充详细反馈'
})
const isSourcePanelDocumentOverview = computed(() => isDocumentOverview(activeSourceMessage.value))
const overviewDocumentTotal = computed(() => {
  const message = activeSourceMessage.value
  if (!message) return 0
  return message.document_count || message.sources.length || 0
})
const sourcePanelTitle = computed(() => {
  if (sourceViewMode.value === 'related' && activeSourceSection.value?.title) return `关联来源 · ${activeSourceSection.value.title}`
  return isDocumentOverview(activeSourceMessage.value) ? '可读文档范围' : '引用来源'
})
const sourcePanelCount = computed(() => {
  const message = activeSourceMessage.value
  if (!message) return '0 条'
  const total = isDocumentOverview(message) ? (message.document_count || message.sources.length) : message.sources.length
  const visible = filteredSources.value.length
  if (sourceViewMode.value === 'related' && activeSourceSectionIndex.value !== null) {
    return `相关来源 ${visible} 条 · 全部 ${total} ${isDocumentOverview(message) ? '份文档' : '条片段'}`
  }
  return `${total} ${isDocumentOverview(message) ? '份文档' : '条片段'}`
})

function messageId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function welcomeMessage(): ChatMessageItem {
  return {
    id: 'welcome',
    role: 'assistant',
    content: '你好，我是内部 AI 助手。你可以直接提问、总结可读文档，或要求我按表格和风险点整理答案。',
    sources: [],
    created_at: new Date().toISOString(),
  }
}

function normalizeSources(...values: unknown[]): SourceItem[] {
  const arr = values.find((value) => Array.isArray(value)) as SourceItem[] | undefined
  return (arr || []).filter(Boolean).map((source) => ({
    ...source,
    document_title: source.document_title || source.title || source.filename || source.document_id || '未知来源',
    content: source.content || source.snippet || source.excerpt || '',
    view_url: source.view_url || source.url || '',
  }))
}

function stripInlineSourceMarkers(value: string) {
  return String(value || '')
    .replace(/\s*\[来源\s*\d+\]/g, '')
    .replace(/\s*（来源\s*\d+）/g, '')
    .replace(/\s*\(来源\s*\d+\)/g, '')
}

function fillAssistantMessage(message: ChatMessageItem, data: any, overwriteAnswer = false) {
  if (!data || typeof data !== 'object') return
  const sources = normalizeSources(data.sources, data.citations, data.references)
  sessionId.value = data.session_id || sessionId.value
  message.id = data.message_id || data.assistant_message_id || message.id
  if (overwriteAnswer || !message.content) message.content = stripInlineSourceMarkers(data.answer || message.content || '')
  message.sources = sources
  message.mode = data.mode || message.mode
  message.citation_mode = data.citation_mode || message.citation_mode
  message.document_count = Number(data.document_count || data.interaction_meta?.document_count || sources.length || 0)
  message.summary_mode = Boolean(data.summary_mode || message.summary_mode)
  if (typeof data.streaming === 'boolean') message.streaming = data.streaming
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

async function responseErrorMessage(response: Response) {
  try {
    const data = await response.json()
    return data?.detail || data?.message || response.statusText || '请求失败'
  } catch {
    return response.statusText || '请求失败'
  }
}

function pendingWithWait(message: ChatMessageItem, text: string) {
  const seconds = Math.max(0, Math.floor(message.waitSeconds || 0))
  return seconds > 0 ? `${text}（已等待 ${seconds} 秒）` : text
}

function sleep(ms: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, ms))
}

async function appendAssistantText(message: ChatMessageItem, piece: string, markDelta: () => void) {
  const text = String(piece || '')
  if (!text) return
  message.pendingText = pendingWithWait(message, '正在输出内容…')
  markDelta()
  let index = 0
  while (index < text.length) {
    const step = Math.min(18, text.length - index)
    message.content += text.slice(index, index + step)
    index += step
    await scrollToBottom()
    if (index < text.length) await sleep(10)
  }
}

async function applyStreamEvent(event: { event: string; data: any }, assistantMessage: ChatMessageItem, markDelta: () => void) {
  if (event.event === 'status') {
    assistantMessage.streaming = true
    const message = typeof event.data === 'string' ? event.data : String(event.data?.message || '')
    if (!assistantMessage.content && message) assistantMessage.pendingText = pendingWithWait(assistantMessage, message)
    await scrollToBottom()
    return false
  }
  if (event.event === 'meta') {
    assistantMessage.streaming = true
    fillAssistantMessage(assistantMessage, event.data)
    if (!assistantMessage.content) assistantMessage.pendingText = pendingWithWait(assistantMessage, '已找到可用资料，正在调用模型组织回答…')
    await scrollToBottom()
    return false
  }
  if (event.event === 'delta') {
    assistantMessage.streaming = true
    const piece = typeof event.data === 'string' ? event.data : String(event.data?.delta || '')
    await appendAssistantText(assistantMessage, piece, markDelta)
    return false
  }
  if (event.event === 'done') {
    if (event.data?.error) {
      const errorText = String(event.data?.answer || event.data?.message || '生成回答时发生错误，请稍后重试。')
      if (!assistantMessage.content) assistantMessage.content = errorText
      fillAssistantMessage(assistantMessage, { ...event.data, answer: '' }, false)
      assistantMessage.streaming = false
      assistantMessage.pendingText = ''
      await scrollToBottom()
      return true
    }
    const finalAnswer = typeof event.data?.answer === 'string' ? event.data.answer : ''
    if (!assistantMessage.content && finalAnswer) {
      fillAssistantMessage(assistantMessage, { ...event.data, answer: '' })
      await appendAssistantText(assistantMessage, finalAnswer, markDelta)
    } else {
      fillAssistantMessage(assistantMessage, event.data, false)
    }
    assistantMessage.streaming = false
    assistantMessage.pendingText = ''
    await scrollToBottom()
    return true
  }
  return false
}

async function sendWithStream(text: string, assistantMessage: ChatMessageItem, markDelta: () => void) {
  const token = localStorage.getItem('token')
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), 120000)
  let response: Response
  try {
    response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers,
      body: JSON.stringify({ question: text, session_id: sessionId.value || null }),
      signal: controller.signal,
    })
  } catch (err: any) {
    if (err?.name === 'AbortError') throw new Error('模型运行超过 120 秒仍未返回，请稍后重试或缩小问题范围')
    throw err
  } finally {
    window.clearTimeout(timeoutId)
  }
  if (response.status === 401) {
    router.push('/login')
    throw new Error('登录已过期，请重新登录')
  }
  if (!response.ok) throw new Error(await responseErrorMessage(response))
  if (!response.body) throw new Error('当前浏览器不支持流式响应')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completed = false
  while (true) {
    const { value, done } = await reader.read()
    if (value) buffer += decoder.decode(value, { stream: !done })
    buffer = buffer.replace(/\r\n/g, '\n')
    let index = buffer.indexOf('\n\n')
    while (index >= 0) {
      const block = buffer.slice(0, index)
      buffer = buffer.slice(index + 2)
      const parsed = parseSseBlock(block)
      if (parsed && (await applyStreamEvent(parsed, assistantMessage, markDelta))) completed = true
      index = buffer.indexOf('\n\n')
    }
    if (done) break
  }
  buffer += decoder.decode()
  if (buffer.trim()) {
    const parsed = parseSseBlock(buffer)
    if (parsed && (await applyStreamEvent(parsed, assistantMessage, markDelta))) completed = true
  }
  if (!completed) throw new Error('流式响应未完整结束，请稍后重试')
}

function toggleAttachmentMenu() {
  if (sending.value || uploadingAttachment.value) return
  attachmentMenuOpen.value = !attachmentMenuOpen.value
}

function openAttachmentPicker(kind: AttachmentKind) {
  attachmentMenuOpen.value = false
  if (kind === 'image') imageInputRef.value?.click()
  else fileInputRef.value?.click()
}

function fileExtension(filename: string) {
  const dot = filename.lastIndexOf('.')
  return dot >= 0 ? filename.slice(dot + 1).toLowerCase() : ''
}

function attachmentIcon(item: PendingAttachment) {
  if (item.kind === 'image' || IMAGE_EXTENSIONS.has(item.extension || '')) return '▧'
  if (['pdf'].includes(item.extension || '')) return 'PDF'
  if (['docx'].includes(item.extension || '')) return 'DOC'
  if (['pptx'].includes(item.extension || '')) return 'PPT'
  if (['xlsx', 'csv'].includes(item.extension || '')) return 'XLS'
  return 'FILE'
}

function attachmentStatusText(item: PendingAttachment) {
  if (item.status === 'uploading') return '上传中…'
  if (item.status === 'failed') return item.message || '上传失败'
  return item.message || '已上传，正在解析，稍后会参与检索'
}

function removeAttachment(localId: string) {
  pendingAttachments.value = pendingAttachments.value.filter((item) => item.localId !== localId)
}

async function handleAttachmentInput(event: Event, pickerKind: AttachmentKind) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length) return
  attachmentMenuOpen.value = false
  uploadingAttachment.value = true
  try {
    for (const file of files) {
      const extension = fileExtension(file.name)
      const kind: AttachmentKind = pickerKind === 'image' || IMAGE_EXTENSIONS.has(extension) ? 'image' : 'file'
      const localId = `att-${Date.now()}-${Math.random().toString(16).slice(2)}`
      const item: PendingAttachment = { localId, filename: file.name, kind, extension, status: 'uploading' }
      pendingAttachments.value.push(item)
      const formData = new FormData()
      formData.append('file', file)
      try {
        const { data } = await http.post('/chat/attachments', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
        item.id = data?.id || item.id
        item.title = data?.title || item.title
        item.filename = data?.filename || item.filename
        item.extension = data?.kind || item.extension
        item.task_id = data?.task_id || item.task_id
        item.status = 'ready'
        item.message = data?.message || '已上传，正在后台解析/OCR'
      } catch (err: any) {
        item.status = 'failed'
        item.message = err?.response?.data?.detail || err?.message || '上传失败'
        ElMessage.error(item.message)
      }
    }
  } finally {
    uploadingAttachment.value = false
  }
}

function readyAttachments() {
  return pendingAttachments.value.filter((item) => item.status === 'ready')
}

function buildAttachmentPrompt(text: string) {
  const ready = readyAttachments()
  if (!ready.length) return text
  const lines = ready.map((item, index) => `${index + 1}. ${item.filename}${item.id ? `（附件ID：${item.id}）` : ''}`)
  const base = text || '请先阅读并总结我刚刚上传的附件。'
  return `${base}\n\n[本轮已上传附件]\n${lines.join('\n')}\n请优先结合这些附件以及我有权限访问的资料回答；如果附件还在解析中，请明确提示我稍后重试。`
}

function buildUserMessageContent(text: string) {
  const ready = readyAttachments()
  if (!ready.length) return text
  const lines = ready.map((item) => `- ${item.filename}`)
  return `${text || '请阅读并总结附件'}\n\n已上传附件：\n${lines.join('\n')}`
}

async function send() {
  const rawText = question.value.trim()
  if ((!rawText && !readyAttachmentCount.value) || sending.value) return
  const text = buildAttachmentPrompt(rawText)
  const displayText = buildUserMessageContent(rawText)
  const sentAttachmentIds = new Set(readyAttachments().map((item) => item.localId))
  error.value = ''
  const userMessage: ChatMessageItem = { id: messageId('user'), role: 'user', content: displayText, sources: [], created_at: new Date().toISOString() }
  const assistantMessage: ChatMessageItem = {
    id: messageId('assistant'),
    role: 'assistant',
    content: '',
    sources: [],
    created_at: new Date().toISOString(),
    pendingText: '正在连接知识库…',
    waitStartedAt: Date.now(),
    waitSeconds: 0,
    streaming: true,
  }
  messages.value.push(userMessage, assistantMessage)
  question.value = ''
  sending.value = true
  await scrollToBottom()

  let receivedDelta = false
  const waitTimer = window.setInterval(() => {
    if (!assistantMessage.streaming) {
      window.clearInterval(waitTimer)
      return
    }
    assistantMessage.waitSeconds = Math.floor((Date.now() - (assistantMessage.waitStartedAt || Date.now())) / 1000)
    const current = assistantMessage.content ? '正在输出内容…' : (assistantMessage.pendingText || '模型正在运行，请稍候…')
    const base = current.replace(/（已等待 \d+ 秒）$/, '')
    assistantMessage.pendingText = pendingWithWait(assistantMessage, base)
  }, 1000)

  try {
    await sendWithStream(text, assistantMessage, () => { receivedDelta = true })
    if (!assistantMessage.content) {
      const recovered = await recoverAssistantMessageFromSession(assistantMessage)
      if (recovered) ElMessage.info('已从服务器同步最终回答。')
    }
    pendingAttachments.value = pendingAttachments.value.filter((item) => !sentAttachmentIds.has(item.localId))
    await loadSessions()
  } catch (err: any) {
    const detail = err?.response?.data?.detail || err?.message || '发送失败'
    error.value = detail
    assistantMessage.streaming = false
    assistantMessage.pendingText = ''
    if (!assistantMessage.content) assistantMessage.content = `发送失败：${detail}`
    else assistantMessage.content += `\n\n发送中断：${detail}`
    ElMessage.error(detail)
  } finally {
    window.clearInterval(waitTimer)
    sending.value = false
    await scrollToBottom()
  }
}

function askPrompt(text: string) {
  question.value = text
  send()
}

function onEnter(event: KeyboardEvent) {
  if (event.shiftKey || event.isComposing) return
  event.preventDefault()
  send()
}

async function loadCurrentUser() {
  try {
    const { data } = await http.get('/me')
    isAdmin.value = Boolean(data?.is_admin)
    localStorage.setItem('user', JSON.stringify(data || {}))
  } catch (err: any) {
    if (err?.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      isAdmin.value = false
      router.push('/login')
    }
    if (err?.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      isAdmin.value = false
      router.push('/login')
    }
  }
}

async function loadSessions() {
  const token = localStorage.getItem('token')
  if (!token) {
    sessions.value = []
    return
  }
  try {
    sessions.value = (await http.get('/chat/sessions')).data || []
  } catch (err: any) {
    if (err?.response?.status === 401) {
      sessions.value = []
      return
    }
    sessions.value = []
  }
}

async function openSession(id: string) {
  try {
    const { data } = await http.get(`/chat/sessions/${id}`)
    sessionId.value = id
    messages.value = (data.messages || []).map((item: any) => ({
      id: item.id || messageId(item.role || 'message'),
      role: item.role,
      content: item.content || '',
      created_at: item.created_at,
      sources: item.role === 'assistant' ? normalizeSources(item.sources, item.citations) : [],
      mode: item.mode,
      citation_mode: item.citation_mode,
      document_count: Number(item.document_count || 0),
      summary_mode: Boolean(item.summary_mode),
    }))
    if (!messages.value.length) messages.value = [welcomeMessage()]
    await scrollToBottom()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载历史会话失败')
  }
}

async function recoverAssistantMessageFromSession(assistantMessage: ChatMessageItem) {
  if (!sessionId.value || assistantMessage.content) return false
  try {
    const { data } = await http.get(`/chat/sessions/${sessionId.value}`)
    const saved = (data.messages || []).find((item: any) => item.id === assistantMessage.id)
    if (!saved?.content) return false
    assistantMessage.content = stripInlineSourceMarkers(saved.content || '')
    assistantMessage.sources = normalizeSources(saved.sources, saved.citations)
    assistantMessage.mode = saved.mode || assistantMessage.mode
    assistantMessage.citation_mode = saved.citation_mode || assistantMessage.citation_mode
    assistantMessage.document_count = Number(saved.document_count || assistantMessage.sources.length || 0)
    assistantMessage.summary_mode = Boolean(saved.summary_mode || assistantMessage.summary_mode)
    return true
  } catch {
    return false
  }
}

function newConversation() {
  sessionId.value = ''
  messages.value = [welcomeMessage()]
  error.value = ''
  closeSourcePanel()
  pendingAttachments.value = []
  question.value = ''
}

function logout() {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
  router.push('/login')
}

function openSourcePanel(message: ChatMessageItem, sectionIndex: number | null = null) {
  activeSourceMessage.value = message
  activeSourceSectionIndex.value = sectionIndex
  sourceViewMode.value = sectionIndex === null ? 'all' : 'related'
  sourcePanelVisible.value = true
  highlightedSourceKey.value = ''
  clearPreview()
  if (sectionIndex !== null) nextTick(() => focusFirstHighlightedSource(message, sectionIndex))
}

function openSources(message: ChatMessageItem, sectionIndex: number | null = null) {
  openSourcePanel(message, sectionIndex)
}

function closeSourcePanel() {
  sourcePanelVisible.value = false
  activeSourceMessage.value = null
  activeSourceSectionIndex.value = null
  sourceViewMode.value = 'all'
  highlightedSourceKey.value = ''
  clearPreview()
}

function setSourceViewMode(mode: 'all' | 'related') {
  sourceViewMode.value = mode
}

function clearPreview() {
  previewSourceTitle.value = ''
  previewText.value = ''
}

function previewSource(source: SourceItem) {
  previewSourceTitle.value = sourceTitle(source)
  previewText.value = sourceSnippet(source) || '暂无可预览内容。'
}

function sourceApiPath(url: string) {
  if (!url) return ''
  if (url.startsWith('/api/')) return url.slice(4)
  if (url.startsWith('/')) return url
  try {
    const parsed = new URL(url)
    return parsed.pathname.startsWith('/api/') ? parsed.pathname.slice(4) + parsed.search : parsed.pathname + parsed.search
  } catch {
    return url
  }
}

function filenameFromDisposition(disposition = '') {
  const match = /filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)\"?/i.exec(disposition)
  const raw = match?.[1] || match?.[2] || ''
  try {
    return decodeURIComponent(raw)
  } catch {
    return raw
  }
}

function sourceFileExtension(source: SourceItem) {
  const name = String(source.filename || source.document_title || source.title || source.view_url || source.url || '')
  const clean = name.split('?')[0].split('#')[0]
  const dot = clean.lastIndexOf('.')
  return dot >= 0 ? clean.slice(dot + 1).toLowerCase() : ''
}

function canPreviewSourceInBrowser(source: SourceItem, contentType = '') {
  const ext = sourceFileExtension(source)
  const type = String(contentType || '').toLowerCase()
  if (['pdf', 'txt', 'md', 'markdown', 'csv', 'png', 'jpg', 'jpeg', 'webp', 'gif'].includes(ext)) return true
  return type.startsWith('text/') || type.includes('pdf') || type.startsWith('image/')
}

function openSourceLabel(source: SourceItem) {
  return canPreviewSourceInBrowser(source) ? '打开文档' : '下载文档'
}

async function openSource(source: SourceItem) {
  const url = String(source.view_url || source.url || '')
  if (!url) {
    ElMessage.warning('该来源没有可打开的地址')
    return
  }
  try {
    const response = await http.get(sourceApiPath(url), { responseType: 'blob' })
    const contentType = response.headers['content-type'] || 'application/octet-stream'
    const blob = new Blob([response.data], { type: contentType })
    const objectUrl = URL.createObjectURL(blob)
    const name = filenameFromDisposition(response.headers['content-disposition']) || String(source.filename || source.document_title || 'document')
    if (canPreviewSourceInBrowser(source, contentType)) {
      const opened = window.open(objectUrl, '_blank', 'noopener,noreferrer')
      if (!opened) {
        const link = document.createElement('a')
        link.href = objectUrl
        link.download = name
        document.body.appendChild(link)
        link.click()
        link.remove()
      }
    } else {
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = name
      document.body.appendChild(link)
      link.click()
      link.remove()
      ElMessage.info('该格式通常不能直接在浏览器预览，已为你下载原文件。')
    }
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '文档打开失败，请确认你有权限访问该文档。')
  }
}

function isDocumentOverview(message?: ChatMessageItem | null) {
  return !!message && (message.citation_mode === 'accessible_documents' || message.summary_mode === true)
}

function showAnswerMeta(message: ChatMessageItem) {
  return Boolean(message.content || message.pendingText || message.sources.length || message.mode || message.summary_mode || message.streaming)
}

function answerModeLabel(message: ChatMessageItem) {
  if (message.streaming) return '流式生成'
  if (message.summary_mode) return '文档总览'
  if (message.mode === 'knowledge' || message.sources.length) return '知识回答'
  return '对话回答'
}

function sourceBlockTitle(message: ChatMessageItem) {
  return isDocumentOverview(message) ? '可读文档范围' : '引用来源'
}

function sourceBlockCount(message: ChatMessageItem) {
  const count = isDocumentOverview(message) ? (message.document_count || message.sources.length) : message.sources.length
  return `${count} ${isDocumentOverview(message) ? '份文档' : '条片段'}`
}

function sourceBlockSubtitle(message: ChatMessageItem) {
  const total = isDocumentOverview(message) ? (message.document_count || message.sources.length) : message.sources.length
  if (isDocumentOverview(message) && message.sources.length) {
    const first = message.sources[0]
    if (first?.summary_source) {
      const used = Number(first.chunks_used || 0)
      const all = Number(first.total_chunks || 0)
      if (all > 0 && used >= all) return `${sourceBlockCount(message)} · 已纳入全部已解析片段`
      if (all > used && used > 0) return `${sourceBlockCount(message)} · 当前纳入 ${used}/${all} 个片段`
    }
    if (total > message.sources.length) {
      return `${sourceBlockCount(message)} · 当前展示 ${message.sources.length} 项`
    }
  }
  return sourceBlockCount(message)
}

function sourceKey(source: SourceItem, index: number) {
  return String(
    source.chunk_id
    || source.document_id
    || source.view_url
    || source.content_url
    || source.filename
    || source.title
    || index
  )
}

function sourceTitle(source: SourceItem) {
  return String(source.document_title || source.title || source.filename || source.document_id || '未知来源')
}

function isSpreadsheetSource(source: SourceItem) {
  const name = String(source.filename || source.document_title || source.title || '').toLowerCase()
  const ext = name.includes('.') ? name.split('.').pop() || '' : ''
  const type = String(source.source_type || '').toLowerCase()
  return SPREADSHEET_EXTENSIONS.has(ext) || type.includes('xlsx') || type.includes('xls') || type.includes('csv')
}

function formatSpreadsheetSnippet(text: string) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim()
  if (!normalized) return ''
  const cells = normalized.split(/\s*\|\s*/).map((part) => part.trim()).filter(Boolean)
  if (cells.length >= 4) return cells.slice(0, 8).join(' · ')
  return normalized
    .replace(/([A-Z]{1,3}\d+:)/g, '\n$1')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 6)
    .join('\n')
}

function sourceSnippet(source: SourceItem) {
  const raw = String(source.content || source.snippet || source.excerpt || '')
  return isSpreadsheetSource(source) ? formatSpreadsheetSnippet(raw) : raw
}

function sourceType(source: SourceItem) {
  const type = String(source.source_type || '')
  if (type.startsWith('chat_')) return '个人附件'
  return type || '知识库文档'
}

function sourceLocation(source: SourceItem) {
  if (source.summary_source) return `已纳入片段 ${source.chunks_used || 0}/${source.total_chunks || 0}`
  if (source.page_number === 0 || source.page_number) return `第 ${source.page_number} 页`
  if (source.chunk_index === 0 || source.chunk_index) return `片段 ${source.chunk_index}`
  return '位置未知'
}

function sectionDomId(message: ChatMessageItem, index: number) {
  return `answer-section-${message.id}-${index}`
}

function sectionStateFor(message: ChatMessageItem) {
  if (!collapsedSectionState.value[message.id]) collapsedSectionState.value[message.id] = {}
  return collapsedSectionState.value[message.id]
}

function isSectionCollapsed(message: ChatMessageItem, index: number) {
  return Boolean(sectionStateFor(message)[index])
}

function setSectionCollapsed(message: ChatMessageItem, index: number, collapsed: boolean) {
  sectionStateFor(message)[index] = collapsed
}

function toggleSectionCollapse(message: ChatMessageItem, index: number) {
  setSectionCollapsed(message, index, !isSectionCollapsed(message, index))
}

function expandAllSections(message: ChatMessageItem) {
  getStructuredSections(message).forEach((_, index) => setSectionCollapsed(message, index, false))
}

function collapseSecondarySections(message: ChatMessageItem) {
  getStructuredSections(message).forEach((section, index) => {
    setSectionCollapsed(message, index, Boolean(section.title && index > 0))
  })
}

async function scrollToSection(message: ChatMessageItem, index: number) {
  setSectionCollapsed(message, index, false)
  await nextTick()
  document.getElementById(sectionDomId(message, index))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function normalizeSearchText(value: string) {
  return String(value || '').toLowerCase()
}

function extractSearchTokens(value: string) {
  const raw = String(value || '')
  const ascii = raw.toLowerCase().match(/[a-z0-9_]{2,}/g) || []
  const cjk = raw.match(/[\u4e00-\u9fff]{2,}/g) || []
  return Array.from(new Set([...ascii, ...cjk])).slice(0, 16)
}

function scoreSourceAgainstSection(source: SourceItem, section: StructuredSection) {
  const title = normalizeSearchText(sourceTitle(source))
  const body = normalizeSearchText(`${sourceSnippet(source)} ${String(source.location || '')}`)
  const sectionTitle = normalizeSearchText(section.title)
  const tokens = extractSearchTokens(`${section.title} ${section.plainText}`)
  let score = 0
  if (sectionTitle && title.includes(sectionTitle)) score += 5
  if (sectionTitle && body.includes(sectionTitle)) score += 3
  for (const token of tokens) {
    if (token.length < 2) continue
    if (title.includes(token)) score += 2
    else if (body.includes(token)) score += 1
  }
  if (source.summary_source && (section.kind === 'lead' || section.kind === 'highlight')) score += 2
  return score
}

function getRelatedSources(message: ChatMessageItem, section: StructuredSection) {
  const scored = message.sources
    .map((source) => ({ source, score: scoreSourceAgainstSection(source, section) }))
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score)
    .map((item) => item.source)
  if (scored.length) return scored
  if (section.kind === 'lead' || section.kind === 'highlight') return message.sources
  return []
}

function relatedSourceCount(message: ChatMessageItem, section: StructuredSection) {
  return getRelatedSources(message, section).length
}

function isHighlightedSource(source: SourceItem, index: number) {
  return highlightedSourceKey.value === sourceKey(source, index)
}

function scrollToHighlightedSource() {
  if (!highlightedSourceKey.value || !sourceScrollRef.value) return
  const target = sourceScrollRef.value.querySelector(`[data-source-key="${highlightedSourceKey.value}"]`) as HTMLElement | null
  target?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

function focusFirstHighlightedSource(message: ChatMessageItem, sectionIndex: number) {
  const section = getStructuredSections(message)[sectionIndex]
  if (!section) return
  const related = getRelatedSources(message, section)
  if (!related.length) {
    highlightedSourceKey.value = ''
    return
  }
  const first = related[0]
  highlightedSourceKey.value = sourceKey(first, 0)
  nextTick().then(scrollToHighlightedSource)
}

function sourceTriggerLabel(message: ChatMessageItem) {
  return isDocumentOverview(message) ? '查看文档清单' : '查看来源'
}

function formatTime(value?: string) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text || '')
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
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

function inlineMarkdown(value: string) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
}

function isTableSeparator(line: string) {
  const core = String(line || '').trim().replace(/^\|/, '').replace(/\|$/, '').trim()
  return /^:?-{3,}:?(?:\s*\|\s*:?-{3,}:?)+$/.test(core)
}

function splitTableRow(line: string) {
  return String(line || '')
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => inlineMarkdown(cell.trim()))
}

function renderMarkdown(content: string) {
  const lines = String(content || '').replace(/\r\n/g, '\n').split('\n')
  const html: string[] = []
  let listMode: '' | 'ul' | 'ol' = ''

  const closeList = () => {
    if (listMode) {
      html.push(`</${listMode}>`)
      listMode = ''
    }
  }

  const openList = (mode: 'ul' | 'ol') => {
    if (listMode !== mode) {
      closeList()
      html.push(`<${mode}>`)
      listMode = mode
    }
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    const trimmed = line.trim()
    const next = lines[index + 1]?.trim() || ''

    if (!trimmed) {
      closeList()
      continue
    }

    if (trimmed.includes('|') && next && isTableSeparator(next)) {
      closeList()
      const headers = splitTableRow(trimmed)
      const rows: string[][] = []
      index += 2
      while (index < lines.length) {
        const rowLine = lines[index]
        const rowTrimmed = rowLine.trim()
        if (!rowTrimmed || !rowTrimmed.includes('|')) {
          index -= 1
          break
        }
        rows.push(splitTableRow(rowLine))
        index += 1
      }
      html.push(
        `<table><thead><tr>${headers.map((cell) => `<th>${cell}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table>`,
      )
      continue
    }

    const heading = /^(#{1,4})\s+(.+)$/.exec(trimmed)
    if (heading) {
      closeList()
      const level = Math.min(heading[1].length + 1, 4)
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`)
      continue
    }

    const quote = /^>\s+(.+)$/.exec(trimmed)
    if (quote) {
      closeList()
      html.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`)
      continue
    }

    const bullet = /^[-*]\s+(.+)$/.exec(trimmed)
    if (bullet) {
      openList('ul')
      html.push(`<li>${inlineMarkdown(bullet[1])}</li>`)
      continue
    }

    const ordered = /^\d+\.\s+(.+)$/.exec(trimmed)
    if (ordered) {
      openList('ol')
      html.push(`<li>${inlineMarkdown(ordered[1])}</li>`)
      continue
    }

    closeList()
    html.push(`<p>${inlineMarkdown(trimmed)}</p>`)
  }

  closeList()
  return html.join('')
}

function classifyStructuredSection(title: string, body: string, index: number, total: number) {
  const titleText = String(title || '')
  if (/(总结|结论|摘要|概览|总览)/.test(titleText)) return { kind: 'highlight' as StructuredSectionKind, badge: '摘要' }
  if (/(风险|注意|提醒|限制|警告|问题)/.test(titleText)) return { kind: 'warning' as StructuredSectionKind, badge: '风险' }
  if (/(建议|下一步|行动|处理|方案)/.test(titleText)) return { kind: 'action' as StructuredSectionKind, badge: '建议' }
  if (!titleText && index === 0) return { kind: 'lead' as StructuredSectionKind, badge: total > 1 ? '概览' : '回答' }
  if (!titleText && /(^|\n)\s*(?:[-*]|\d+\.)\s+/.test(body)) return { kind: 'section' as StructuredSectionKind, badge: '要点' }
  return { kind: titleText ? ('section' as StructuredSectionKind) : ('lead' as StructuredSectionKind), badge: titleText ? '分节' : '回答' }
}

function buildStructuredSections(content: string): StructuredSection[] {
  const normalized = String(content || '').replace(/\r\n/g, '\n').trim()
  if (!normalized) return []

  const blocks: Array<{ title: string; lines: string[] }> = []
  let current = { title: '', lines: [] as string[] }

  const pushCurrent = () => {
    const body = current.lines.join('\n').trim()
    if (current.title || body) blocks.push({ title: current.title, lines: [...current.lines] })
  }

  for (const line of normalized.split('\n')) {
    const trimmed = line.trim()
    const headingMatch = /^(#{1,4})\s+(.+)$/.exec(trimmed)
    if (headingMatch) {
      pushCurrent()
      current = { title: headingMatch[2].trim(), lines: [] }
      continue
    }

    const labeledMatch = /^(结论|总结|摘要|概览|总览|风险|注意|提醒|建议|下一步|行动|说明|引用来源|可读文档范围)[：:]\s*(.*)$/.exec(trimmed)
    if (labeledMatch) {
      pushCurrent()
      current = { title: labeledMatch[1], lines: labeledMatch[2] ? [labeledMatch[2]] : [] }
      continue
    }

    current.lines.push(line)
  }

  pushCurrent()

  return blocks.map((block, index) => {
    const body = block.lines.join('\n').trim() || block.title
    const { kind, badge } = classifyStructuredSection(block.title, body, index, blocks.length)
    return {
      title: block.title,
      html: renderMarkdown(body),
      plainText: body,
      kind,
      badge,
    }
  })
}

function getStructuredSections(message: ChatMessageItem) {
  const content = stripInlineSourceMarkers(message.content || message.pendingText || '')
  const cached = structuredSectionCache.get(message.id)
  if (cached && cached.content === content) return cached.sections
  const sections = buildStructuredSections(content)
  structuredSectionCache.set(message.id, { content, sections })
  return sections
}

function getStructuredOutline(message: ChatMessageItem): StructuredOutlineItem[] {
  return getStructuredSections(message)
    .map((section, index) => ({ index, title: section.title }))
    .filter((section) => Boolean(section.title))
    .slice(0, 6)
}

async function scrollToBottom() {
  await nextTick()
  if (chatBodyRef.value) chatBodyRef.value.scrollTop = chatBodyRef.value.scrollHeight
}

onMounted(() => {
  loadCurrentUser()
  loadSessions()
})
</script>
