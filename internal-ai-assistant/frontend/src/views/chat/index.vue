<template>
  <div class="ai-workbench" @paste="handleWorkbenchPaste" @drop.prevent="handleWorkbenchDrop" @dragover.prevent>
    <aside class="ai-sidebar">
      <div class="brand-card">
        <div class="brand-logo">AI</div>
        <div>
          <div class="brand-title">内部 AI 助手</div>
          <div class="brand-subtitle">Knowledge Copilot</div>
        </div>
      </div>

      <button class="new-chat" type="button" aria-label="新建对话" @click="newConversation">
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
          <button class="session-delete" type="button" title="删除会话" :aria-label="`删除会话：${item.title || '新的对话'}`" @click.stop="deleteSession(item.id)">×</button>
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
          <div class="chat-search-box">
            <input v-model="chatSearchQuery" type="search" aria-label="搜索当前会话" placeholder="搜索当前会话" @keydown.enter.prevent="jumpToNextSearchMatch" />
            <span>{{ chatSearchSummary }}</span>
            <button type="button" :disabled="!chatSearchMatches.length" @click="jumpToPrevSearchMatch">上一个</button>
            <button type="button" :disabled="!chatSearchMatches.length" @click="jumpToNextSearchMatch">下一个</button>
          </div>
          <span class="status-pill">{{ conversationStatusLabel }}</span>
          <span class="status-pill dark">{{ currentSessionLabel }}</span>
        </div>
      </header>

      <div class="workbench-layout">
        <section class="chat-column">

          <section ref="chatBodyRef" class="conversation-panel" @scroll.passive="handleChatScroll">
        <div v-if="showHero" class="hero-panel">
          <h2>有什么可以帮忙的？</h2>
          <p>可以直接提问，也可以上传文件后让我总结、整理表格或核对引用来源。</p>
          <div class="hero-trust-row" aria-label="知识库能力提示">
            <span>基于权限知识库</span>
            <span>来源可核验</span>
            <span>支持文档与表格</span>
          </div>
          <div class="prompt-grid">
            <button v-for="item in promptCards" :key="item" type="button" @click="askPrompt(item)">{{ item }}</button>
          </div>
        </div>

        <article
          v-for="message in visibleMessages"
          :id="messageDomId(message)"
          :key="message.id"
          :class="['message-row', message.role, { 'search-hit': isSearchMatchedMessage(message), 'search-current': isCurrentSearchMessage(message) }]"
        >
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
                <span v-if="sourceQualityWarningText(message)" class="answer-meta-pill warning">{{ sourceQualityWarningText(message) }}</span>
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
                    :class="['answer-section', block.kind, { 'has-title': !!block.title, 'plain-answer': !block.title, collapsed: isSectionCollapsed(message, blockIndex) }]"
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
                <span v-if="sourceQualityWarningText(message)" class="source-quality-warning">{{ sourceQualityWarningText(message) }}</span>
              </div>
              <button type="button" @click="openSources(message)">{{ sourceTriggerLabel(message) }}</button>
            </div>

            <div v-if="message.role === 'assistant' && message.id !== 'welcome'" class="message-actions">
              <button type="button" @click="copyText(stripInlineSourceMarkers(message.content))">复制</button>
              <button type="button" @click="copyText(message.content)">复制 Markdown</button>
              <button type="button" @click="copyText(answerWithSourceSummary(message))">复制含来源</button>
              <button type="button" :disabled="sending" @click="regenerateAnswer(message)">重新生成</button>
              <button type="button" :disabled="message.feedbackSubmitted || feedbackSubmitting" @click="submitQuickFeedback(message, 'helpful')">有帮助</button>
              <button type="button" :disabled="message.feedbackSubmitted || feedbackSubmitting" @click="openFeedbackDialog(message, 'unhelpful')">不够好</button>
              <span v-if="message.feedbackSubmitted">已反馈</span>
            </div>
            <div v-else-if="message.role === 'user'" class="message-actions user-message-actions">
              <button type="button" :disabled="sending" @click="editUserMessage(message)">编辑并重发</button>
              <button type="button" @click="copyText(message.content)">复制问题</button>
            </div>
          </div>
        </article>
          <button v-if="showScrollToBottom" class="chat-scroll-bottom" type="button" @click="scrollToBottom">
            回到最新消息
            <span>↓</span>
          </button>
      </section>
        </section>

      </div>

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
            <span>请尽量写清楚这条回答哪里不对、不完整，或你期望看到什么结果。</span>
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
            <button
              type="button"
              :class="['attachment-progress-ring', item.status]"
              :style="attachmentProgressStyle(item)"
              :title="item.status === 'uploading' ? '取消上传' : attachmentStatusText(item)"
              :aria-label="item.status === 'uploading' ? `取消上传 ${item.filename}` : attachmentStatusText(item)"
              :disabled="item.status !== 'uploading'"
              @click="cancelAttachmentUpload(item)"
            >
              <span>{{ attachmentProgressLabel(item) }}</span>
            </button>
            <span class="attachment-main">
              <strong>{{ item.filename }}</strong>
              <small>{{ attachmentStatusText(item) }}</small>
            </span>
            <button v-if="item.status === 'failed'" type="button" class="attachment-retry" :disabled="sending || uploadingAttachment" @click="retryAttachment(item)">重试</button>
            <button type="button" class="attachment-remove" :disabled="sending" aria-label="移除附件" @click="removeAttachment(item.localId)">×</button>
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
              aria-label="上传图片或文件"
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
            class="composer-input"
            type="textarea"
            :autosize="composerAutosize"
            :input-style="composerInputStyle"
            resize="none"
            maxlength="4000"
            :placeholder="pendingAttachments.length ? '描述你想基于附件了解什么…' : '输入问题，Shift + Enter 换行'"
            @keydown.enter.exact="onEnter"
          />
          <button
            :class="['send-button', { stopping: sending }]"
            type="button"
            :disabled="stoppingGeneration || (!sending && !question.trim() && !readyAttachmentCount)"
            :aria-label="sending ? '停止生成回答' : '发送问题'"
            @click="sending ? stopGeneration() : send()"
          >
            <span v-if="sending">{{ stoppingGeneration ? '停止中…' : '停止' }}</span>
            <span v-else>发送</span>
          </button>
        </div>
        <div class="composer-scope-row">
          <span>知识库范围</span>
          <button type="button" :class="{ active: chatKnowledgeScope === 'production' }" :disabled="sending" @click="chatKnowledgeScope = 'production'">正式库</button>
          <button type="button" :class="{ active: chatKnowledgeScope === 'test' }" :disabled="sending" @click="chatKnowledgeScope = 'test'">测试库</button>
          <button v-if="isAdmin" type="button" :class="{ active: chatKnowledgeScope === 'all' }" :disabled="sending" @click="chatKnowledgeScope = 'all'">全部</button>
        </div>
        <div class="composer-note">可点击上传、拖拽文件，或直接粘贴截图后提问；回答会尽量基于可访问资料生成，请结合引用来源核验重要结论。</div>
      </footer>
    </main>

    <aside v-if="sourcePanelVisible" class="source-panel">
      <header>
        <div>
          <strong>{{ sourcePanelTitle }}</strong>
          <span>{{ sourcePanelCount }}</span>
        </div>
        <button type="button" aria-label="关闭来源面板" @click="closeSourcePanel">×</button>
      </header>

      <div class="source-panel-toolbar">
        <div v-if="isSourcePanelDocumentOverview" class="document-list-controls">
          <label class="document-search-box">
            <span>搜索文档</span>
            <input v-model="documentSearch" type="search" placeholder="输入文件名、类型或片段内容" />
          </label>
          <div class="document-filter-row" aria-label="文档状态筛选">
            <button :class="{ active: documentStatusFilter === 'all' }" type="button" @click="documentStatusFilter = 'all'">
              全部 {{ activeSources.length }}
            </button>
            <button :class="{ active: documentStatusFilter === 'ready' }" type="button" @click="documentStatusFilter = 'ready'">
              已解析 {{ documentReadyCount }}
            </button>
            <button :class="{ active: documentStatusFilter === 'partial' }" type="button" @click="documentStatusFilter = 'partial'">
              部分内容 {{ documentPartialCount }}
            </button>
            <button :class="{ active: documentStatusFilter === 'empty' }" type="button" @click="documentStatusFilter = 'empty'">
              暂无预览 {{ documentEmptyCount }}
            </button>
          </div>
        </div>
        <template v-else>
          <div class="source-filter">
            <button :class="{ active: sourceViewMode === 'top' }" type="button" @click="setSourceViewMode('top')">
              重点证据
            </button>
            <button :class="{ active: sourceViewMode === 'all' }" type="button" @click="setSourceViewMode('all')">
              全部记录
            </button>
            <button
              v-if="activeSourceSectionIndex !== null"
              :class="{ active: sourceViewMode === 'related' }"
              type="button"
              @click="setSourceViewMode('related')"
            >
              当前段落来源
            </button>
          </div>
          <div v-if="activeSourceSection?.title && sourceViewMode === 'related'" class="source-panel-note">
            正在查看“{{ activeSourceSection.title }}”的关联来源
          </div>
        </template>
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
            <strong>文档清单</strong>
          </div>
        </div>
        <p>
          这里是当前账号可访问的文档范围。可以按文件名搜索，也可以用状态快速查看哪些文档已经解析、哪些只有部分内容或暂无预览。
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
            'quality-warning': isLowQualitySource(source),
            overview: isSourcePanelDocumentOverview,
          }]"
        >
          <div class="source-index">{{ isSourcePanelDocumentOverview ? sourceExtension(source) : index + 1 }}</div>
          <div class="source-body">
            <div class="source-headline">
              <div>
                <h3>{{ sourceTitle(source) }}</h3>
                <span v-if="isSourcePanelDocumentOverview" class="document-file-name">{{ sourceFilename(source) }}</span>
              </div>
              <span v-if="isLowQualitySource(source)" class="source-quality-pill">{{ sourceQualityLabel(source) }}</span>
              <span v-else-if="isSourcePanelDocumentOverview" :class="['document-status-pill', documentStatusKind(source)]">
                {{ documentStatusLabel(source) }}
              </span>
              <span v-else-if="source.summary_source" class="source-coverage-pill">已纳入 {{ source.chunks_used || 0 }}/{{ source.total_chunks || 0 }}</span>
            </div>
            <p>{{ sourceEvidenceSummary(source) || (isSourcePanelDocumentOverview ? '这个文档暂时没有可展示的预览内容。' : '该来源暂未返回可读证据摘要。') }}</p>
            <div class="source-meta">
              <template v-if="isSourcePanelDocumentOverview">
                {{ sourceType(source) }} · {{ documentStatusDetail(source) }}
              </template>
              <template v-else>
                {{ sourceType(source) }} · {{ sourceLocation(source) }}
              </template>
            </div>
            <div class="source-actions">
              <button type="button" @click="previewSource(source)">查看证据</button>
              <button type="button" @click="copyText(sourceEvidenceSummary(source) || sourceTitle(source))">复制证据</button>
              <button type="button" @click="openSource(source)">{{ openSourceLabel(source) }}</button>
            </div>
          </div>
        </article>

        <div v-if="!filteredSources.length" class="source-empty">
          {{ isSourcePanelDocumentOverview ? '没有匹配的文档。可以清空搜索词或切换状态筛选。' : '当前回答段落还没有匹配到更明确的来源，可以切换到“全部来源”查看完整范围。' }}
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
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../../api'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'

type Role = 'assistant' | 'user'
type FeedbackRating = 'helpful' | 'unhelpful'

type StructuredSectionKind = 'lead' | 'section' | 'highlight' | 'warning' | 'action' | 'data'
type DocumentStatusFilter = 'all' | 'ready' | 'partial' | 'empty'

interface SourceQualityNotice {
  has_low_quality_sources?: boolean
  warning?: string
  affected_source_count?: number
  affected_document_count?: number
  grades?: Record<string, number>
  reasons?: string[]
  documents?: string[]
  [key: string]: unknown
}

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
  retrieval_channel?: string
  source_quality?: SourceQualityNotice
  quality_penalty?: number | string | null
  table_row?: Record<string, unknown> | null
  sheet_name?: string
  row_number?: number | string | null
  location?: string
  section_title?: string
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
  source_quality_notice?: SourceQualityNotice
  source_warning?: string
  source_warnings?: string[]
  feedbackSubmitted?: boolean
  requestText?: string
  displayText?: string
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
  file?: File
  progress?: number
  abortController?: AbortController
}

const SPREADSHEET_EXTENSIONS = new Set(['csv', 'xlsx', 'xls', 'tsv'])
const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif'])

const router = useRouter()
const auth = useAuthStore()
const chatBodyRef = ref<HTMLElement | null>(null)
const imageInputRef = ref<HTMLInputElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const question = ref('')
const sessionId = ref('')
const chatKnowledgeScope = ref<'production' | 'test' | 'all'>('production')
const sending = ref(false)
const activeStreamController = ref<AbortController | null>(null)
const stoppingGeneration = ref(false)
const uploadingAttachment = ref(false)
const attachmentMenuOpen = ref(false)
const pendingAttachments = ref<PendingAttachment[]>([])
const error = ref('')
const isAdmin = computed(() => auth.isAdmin)
const sessions = ref<SessionSummary[]>([])
const messages = ref<ChatMessageItem[]>([welcomeMessage()])
const sourcePanelVisible = ref(false)
const activeSourceMessage = ref<ChatMessageItem | null>(null)
const activeSourceSectionIndex = ref<number | null>(null)
const sourceViewMode = ref<'all' | 'related' | 'top'>('top')
const documentSearch = ref('')
const documentStatusFilter = ref<DocumentStatusFilter>('all')
const highlightedSourceKey = ref('')
const sourceScrollRef = ref<HTMLElement | null>(null)
const collapsedSectionState = ref<Record<string, Record<number, boolean>>>({})
const structuredSectionCache = new Map<string, { content: string; sections: StructuredSection[] }>()
const previewText = ref('')
const previewSourceTitle = ref('')
const feedbackDialogVisible = ref(false)
const feedbackSubmitting = ref(false)
const feedbackTargetMessage = ref<ChatMessageItem | null>(null)
const feedbackTargetRating = ref<FeedbackRating>('unhelpful')
const feedbackForm = ref({ content: '' })
const CHAT_SCROLL_THRESHOLD = 72
const composerAutosize = { minRows: 1, maxRows: 10 }
const composerInputStyle = { maxHeight: '240px', overflowY: 'auto' }
const isChatAtBottom = ref(true)
const chatSearchQuery = ref('')
const currentSearchMatchIndex = ref(0)

const promptCards = [
  '总结我现在可读的文档',
  '列出回答的引用来源',
  '把内容整理成表格',
  '指出风险点和需要补充的资料',
]

const visibleMessages = computed(() => messages.value.filter((message) => message.id !== 'welcome'))
const showHero = computed(() => visibleMessages.value.length === 0)
const chatSearchMatches = computed(() => {
  const keyword = normalizeSearchText(chatSearchQuery.value).trim()
  if (!keyword) return []
  return visibleMessages.value.filter((message) => normalizeSearchText(message.content).includes(keyword))
})
const chatSearchSummary = computed(() => {
  if (!chatSearchQuery.value.trim()) return '未搜索'
  const total = chatSearchMatches.value.length
  if (!total) return '0 条'
  return `${Math.min(currentSearchMatchIndex.value + 1, total)} / ${total}`
})
const visibleSessions = computed(() => sessions.value.slice(0, 80))
const readyAttachmentCount = computed(() => pendingAttachments.value.filter((item) => item.status === 'ready').length)
const latestAssistantMessage = computed(() => [...visibleMessages.value].reverse().find((message) => message.role === 'assistant') || null)
const latestAssistantSourceCount = computed(() => {
  const message = latestAssistantMessage.value
  if (!message) return 0
  return isDocumentOverview(message) ? (message.document_count || message.sources.length || 0) : message.sources.length
})
const latestAssistantSources = computed(() => latestAssistantMessage.value?.sources || [])
const latestAssistantSourcesPreview = computed(() => latestAssistantSources.value.slice(0, 4))
const railAttachmentsPreview = computed(() => pendingAttachments.value.slice(0, 5))
const conversationStatusLabel = computed(() => {
  if (sending.value) return 'AI 正在回答'
  if (readyAttachmentCount.value > 0) return `附件已就绪 · ${readyAttachmentCount.value}`
  if (visibleMessages.value.length > 0) return '可继续追问'
  return '准备提问'
})
const currentSessionLabel = computed(() => {
  const current = sessions.value.find((item) => item.id === sessionId.value)
  if (current?.title) return current.title
  if (sessionId.value) return '已保存会话'
  return '新会话'
})
const showScrollToBottom = computed(() => !showHero.value && !isChatAtBottom.value && !sourcePanelVisible.value)
const activeSources = computed(() => sortSourcesForDisplay(activeSourceMessage.value?.sources || [], activeSourceMessage.value))
const activeSourceSection = computed(() => {
  const message = activeSourceMessage.value
  const sectionIndex = activeSourceSectionIndex.value
  if (!message || sectionIndex === null) return null
  return getStructuredSections(message)[sectionIndex] || null
})
const filteredSources = computed(() => {
  const message = activeSourceMessage.value
  if (!message) return []
  if (isDocumentOverview(message)) return filterDocumentSources(activeSources.value)
  if (sourceViewMode.value === 'top') return activeSources.value.slice(0, 6)
  if (sourceViewMode.value === 'all' || activeSourceSectionIndex.value === null) return activeSources.value
  const section = activeSourceSection.value
  return section ? getRelatedSources(message, section) : []
})
const feedbackDialogTitle = computed(() => feedbackTargetRating.value === 'helpful' ? '提交正向反馈' : '提交问题反馈')
const isSourcePanelDocumentOverview = computed(() => isDocumentOverview(activeSourceMessage.value))
const overviewDocumentTotal = computed(() => {
  const message = activeSourceMessage.value
  if (!message) return 0
  return message.document_count || message.sources.length || 0
})
const documentReadyCount = computed(() => activeSources.value.filter((source) => documentStatusKind(source) === 'ready').length)
const documentPartialCount = computed(() => activeSources.value.filter((source) => documentStatusKind(source) === 'partial').length)
const documentEmptyCount = computed(() => activeSources.value.filter((source) => documentStatusKind(source) === 'empty').length)
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
    return `相关证据 ${visible} 条 · 全部 ${total} ${isDocumentOverview(message) ? '份文档' : '条证据'}`
  }
  return `${total} ${isDocumentOverview(message) ? '份文档' : '条证据'}`
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

const LOW_SOURCE_QUALITY_GRADES = new Set(['poor', 'blocked'])
const SOURCE_QUALITY_WARNING_TEXT = '部分来源质量较低，请结合原文或后台体检结果核验答案。'

function sourceQualityGrade(source: SourceItem) {
  const quality = source.source_quality && typeof source.source_quality === 'object' ? source.source_quality : null
  return String(quality?.grade || '').toLowerCase()
}

function isLowQualitySource(source: SourceItem) {
  return LOW_SOURCE_QUALITY_GRADES.has(sourceQualityGrade(source))
}

function buildSourceQualityNotice(sources: SourceItem[]): SourceQualityNotice {
  const affected = sources.filter(isLowQualitySource)
  const grades: Record<string, number> = {}
  const reasons = new Set<string>()
  const documents = new Map<string, string>()
  for (const source of affected) {
    const quality = source.source_quality && typeof source.source_quality === 'object' ? source.source_quality : {}
    const grade = sourceQualityGrade(source)
    if (grade) grades[grade] = (grades[grade] || 0) + 1
    for (const reason of (quality.reasons || []) as string[]) if (reason) reasons.add(String(reason))
    const key = String(source.document_id || source.filename || sourceTitle(source))
    documents.set(key, sourceTitle(source))
  }
  const hasLowQuality = affected.length > 0
  return {
    has_low_quality_sources: hasLowQuality,
    warning: hasLowQuality ? SOURCE_QUALITY_WARNING_TEXT : '',
    affected_source_count: affected.length,
    affected_document_count: documents.size,
    grades,
    reasons: Array.from(reasons).sort(),
    documents: Array.from(documents.values()).slice(0, 6),
  }
}

function sourceQualityNotice(message: ChatMessageItem): SourceQualityNotice {
  const notice = message.source_quality_notice || buildSourceQualityNotice(message.sources)
  if (notice.has_low_quality_sources !== undefined) return notice
  return buildSourceQualityNotice(message.sources)
}

function sourceQualityWarningText(message: ChatMessageItem) {
  const notice = sourceQualityNotice(message)
  if (!notice.has_low_quality_sources) return ''
  const affected = Number(notice.affected_document_count || notice.affected_source_count || 0)
  return affected > 0 ? `${notice.warning || SOURCE_QUALITY_WARNING_TEXT}（${affected} 个来源受影响）` : (notice.warning || SOURCE_QUALITY_WARNING_TEXT)
}

function sourceQualityLabel(source: SourceItem) {
  const grade = sourceQualityGrade(source)
  if (grade === 'blocked') return '低质来源 · 需核验'
  if (grade === 'poor') return '来源质量偏低'
  return ''
}

function sourceDisplayScore(source: SourceItem, message?: ChatMessageItem | null) {
  const channel = String(source.retrieval_channel || '')
  const name = String(source.filename || source.document_title || source.title || '').toLowerCase()
  const text = normalizeSearchText([sourceTitle(source), sourceLocation(source), sourceSnippet(source), message?.content || ''].join(' '))
  let score = 0
  if (channel === 'table' || String(source.chunk_index ?? '').startsWith('table:')) score += 120
  if (isSpreadsheetSource(source)) score += 60
  if (name.includes('北仑')) score += 45
  if (name.includes('进度表') || name.includes('派单') || name.includes('截止时间')) score += 18
  if (text.includes('城市') || text.includes('公司名称') || text.includes('开设公司名称') || text.includes('分公司')) score += 24
  if (source.table_row) score += 40
  if (channel === 'pageindex') score += 6
  if (!isSpreadsheetSource(source) && channel === 'pageindex') score -= 25
  return score
}

function sortSourcesForDisplay(sources: SourceItem[], message?: ChatMessageItem | null) {
  return [...sources]
    .map((source, index) => ({ source, index, score: sourceDisplayScore(source, message) }))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map((item) => item.source)
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
  message.source_quality_notice = data.source_quality_notice || message.source_quality_notice || buildSourceQualityNotice(sources)
  message.source_warning = data.source_warning || message.source_quality_notice?.warning || ''
  message.source_warnings = Array.isArray(data.source_warnings) ? data.source_warnings : (message.source_warning ? [message.source_warning] : [])
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
  const fallback = response.status >= 500
    ? '后端服务暂时不可用，请确认 8000 后端服务已启动后再重试'
    : (response.statusText || '请求失败')
  try {
    const contentType = response.headers.get('content-type') || ''
    if (contentType.includes('application/json')) {
      const data = await response.json()
      return data?.detail || data?.message || fallback
    }
    const text = (await response.text()).trim()
    if (/internal server error/i.test(text)) return fallback
    return text || fallback
  } catch {
    return fallback
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
  const token = auth.token
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  const controller = new AbortController()
  activeStreamController.value = controller
  let timedOut = false
  const timeoutId = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, 120000)
  let response: Response
  try {
    response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers,
      body: JSON.stringify({ question: text, session_id: sessionId.value || null, knowledge_scope: chatKnowledgeScope.value }),
      signal: controller.signal,
    })
  } catch (err: any) {
    if (err?.name === 'AbortError') {
      if (timedOut) throw new Error('模型运行超过 120 秒仍未返回，请稍后重试或缩小问题范围')
      throw new Error('已停止生成')
    }
    throw err
  } finally {
    window.clearTimeout(timeoutId)
    if (activeStreamController.value === controller) activeStreamController.value = null
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

function stopGeneration() {
  if (!sending.value || !activeStreamController.value) return
  stoppingGeneration.value = true
  activeStreamController.value.abort()
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

async function uploadAttachmentItem(item: PendingAttachment) {
  if (!item.file) return
  item.status = 'uploading'
  item.progress = 0
  item.message = '上传中…'
  const controller = new AbortController()
  item.abortController = controller
  const formData = new FormData()
  formData.append('file', item.file)
  try {
    const { data } = await http.post('/chat/attachments', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      signal: controller.signal,
      onUploadProgress: (event) => {
        if (!event.total) return
        item.progress = Math.min(99, Math.round((event.loaded / event.total) * 100))
      },
    })
    item.id = data?.id || item.id
    item.title = data?.title || item.title
    item.filename = data?.filename || item.filename
    item.extension = data?.kind || item.extension
    item.task_id = data?.task_id || item.task_id
    item.status = 'ready'
    item.progress = 100
    item.message = data?.message || '已上传，正在后台解析/OCR'
  } catch (err: any) {
    item.status = 'failed'
    item.message = err?.code === 'ERR_CANCELED' ? '已取消上传' : (err?.response?.data?.detail || err?.message || '上传失败')
    if (err?.code !== 'ERR_CANCELED') ElMessage.error(item.message)
  } finally {
    item.abortController = undefined
  }
}

async function retryAttachment(item: PendingAttachment) {
  if (sending.value || uploadingAttachment.value || !item.file) return
  uploadingAttachment.value = true
  try {
    await uploadAttachmentItem(item)
  } finally {
    uploadingAttachment.value = false
  }
}

function cancelAttachmentUpload(item: PendingAttachment) {
  if (item.status !== 'uploading') return
  item.abortController?.abort()
}

function attachmentProgressStyle(item: PendingAttachment) {
  const progress = Math.max(0, Math.min(100, Math.round(item.progress || 0)))
  return { '--attachment-progress': `${progress * 3.6}deg` }
}

function attachmentProgressLabel(item: PendingAttachment) {
  if (item.status === 'uploading') return `${Math.max(0, Math.min(99, Math.round(item.progress || 0)))}%`
  if (item.status === 'ready') return '✓'
  if (item.status === 'failed') return '!'
  return attachmentIcon(item)
}

async function addAttachmentFiles(files: File[], pickerKind: AttachmentKind = 'file') {
  if (!files.length || sending.value) return
  attachmentMenuOpen.value = false
  uploadingAttachment.value = true
  try {
    for (const file of files) {
      const extension = fileExtension(file.name)
      const kind: AttachmentKind = pickerKind === 'image' || IMAGE_EXTENSIONS.has(extension) || file.type.startsWith('image/') ? 'image' : 'file'
      const localId = `att-${Date.now()}-${Math.random().toString(16).slice(2)}`
      const item: PendingAttachment = { localId, filename: file.name, kind, extension, status: 'uploading', file }
      pendingAttachments.value.push(item)
      await uploadAttachmentItem(item)
    }
  } finally {
    uploadingAttachment.value = false
  }
}

async function handleAttachmentInput(event: Event, pickerKind: AttachmentKind) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  await addAttachmentFiles(files, pickerKind)
}

function filesFromClipboard(event: ClipboardEvent) {
  return Array.from(event.clipboardData?.items || [])
    .filter((item) => item.kind === 'file')
    .map((item) => item.getAsFile())
    .filter((file): file is File => Boolean(file))
}

function handleWorkbenchPaste(event: ClipboardEvent) {
  const files = filesFromClipboard(event)
  if (!files.length) return
  event.preventDefault()
  addAttachmentFiles(files, 'image')
}

function handleWorkbenchDrop(event: DragEvent) {
  const files = Array.from(event.dataTransfer?.files || [])
  if (!files.length) return
  addAttachmentFiles(files, 'file')
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

function createAssistantMessage(): ChatMessageItem {
  return {
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
}

async function runAssistantRequest(text: string, assistantMessage: ChatMessageItem, sentAttachmentIds = new Set<string>()) {
  error.value = ''
  sending.value = true
  assistantMessage.content = ''
  assistantMessage.sources = []
  assistantMessage.pendingText = '正在连接知识库…'
  assistantMessage.waitStartedAt = Date.now()
  assistantMessage.waitSeconds = 0
  assistantMessage.streaming = true
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
    if (sentAttachmentIds.size) pendingAttachments.value = pendingAttachments.value.filter((item) => !sentAttachmentIds.has(item.localId))
    await loadSessions()
  } catch (err: any) {
    const detail = err?.response?.data?.detail || err?.message || '发送失败'
    const stoppedByUser = detail === '已停止生成'
    error.value = stoppedByUser ? '' : detail
    assistantMessage.streaming = false
    assistantMessage.pendingText = ''
    if (stoppedByUser) {
      assistantMessage.content = assistantMessage.content
        ? `${assistantMessage.content}\n\n（已停止生成）`
        : '已停止生成。'
      ElMessage.info('已停止生成')
    } else {
      if (!assistantMessage.content) assistantMessage.content = `发送失败：${detail}`
      else assistantMessage.content += `\n\n发送中断：${detail}`
      ElMessage.error(detail)
    }
  } finally {
    window.clearInterval(waitTimer)
    sending.value = false
    stoppingGeneration.value = false
    activeStreamController.value = null
    await scrollToBottom()
  }
}

async function send() {
  const rawText = question.value.trim()
  if ((!rawText && !readyAttachmentCount.value) || sending.value) return
  const text = buildAttachmentPrompt(rawText)
  const displayText = buildUserMessageContent(rawText)
  const sentAttachmentIds = new Set(readyAttachments().map((item) => item.localId))
  const userMessage: ChatMessageItem = {
    id: messageId('user'),
    role: 'user',
    content: displayText,
    sources: [],
    created_at: new Date().toISOString(),
    requestText: text,
    displayText,
  }
  const assistantMessage = createAssistantMessage()
  assistantMessage.requestText = text
  messages.value.push(userMessage, assistantMessage)
  question.value = ''
  await runAssistantRequest(text, assistantMessage, sentAttachmentIds)
}

function findPreviousUserMessage(message: ChatMessageItem) {
  const index = messages.value.findIndex((item) => item.id === message.id)
  if (index <= 0) return null
  for (let i = index - 1; i >= 0; i -= 1) {
    if (messages.value[i]?.role === 'user') return messages.value[i]
  }
  return null
}

async function regenerateAnswer(message: ChatMessageItem) {
  if (sending.value) return
  const userMessage = findPreviousUserMessage(message)
  const text = message.requestText || userMessage?.requestText || userMessage?.content || ''
  if (!text.trim()) {
    ElMessage.warning('没有找到可重新生成的问题')
    return
  }
  message.requestText = text
  await runAssistantRequest(text, message)
}

function editUserMessage(message: ChatMessageItem) {
  if (sending.value) return
  question.value = message.requestText || message.content
  const index = messages.value.findIndex((item) => item.id === message.id)
  if (index >= 0) messages.value = messages.value.slice(0, index)
  closeSourcePanel()
  nextTick().then(scrollToBottom)
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
    await auth.loadCurrentUser()
  } catch (err: any) {
    if (err?.response?.status === 401) {
      auth.clearAuth()
      router.push('/login')
    }
  }
}

async function loadSessions() {
  if (!auth.isAuthenticated) {
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
    messages.value = (data.messages || []).map((item: any) => {
      const sources = item.role === 'assistant' ? normalizeSources(item.sources, item.citations) : []
      const sourceNotice = item.source_quality_notice || buildSourceQualityNotice(sources)
      return {
        id: item.id || messageId(item.role || 'message'),
        role: item.role,
        content: item.content || '',
        created_at: item.created_at,
        sources,
        mode: item.mode,
        citation_mode: item.citation_mode,
        document_count: Number(item.document_count || 0),
        summary_mode: Boolean(item.summary_mode),
        source_quality_notice: sourceNotice,
        source_warning: item.source_warning || sourceNotice.warning || '',
        source_warnings: Array.isArray(item.source_warnings) ? item.source_warnings : (sourceNotice.warning ? [sourceNotice.warning] : []),
        requestText: item.content || '',
        displayText: item.content || '',
      }
    })
    if (!messages.value.length) messages.value = [welcomeMessage()]
    await scrollToBottom()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载历史会话失败')
  }
}

async function deleteSession(id: string) {
  if (!id) return
  if (!window.confirm('确定删除这条会话历史吗？')) return
  try {
    await http.delete(`/chat/sessions/${id}`)
    sessions.value = sessions.value.filter((item) => item.id !== id)
    if (sessionId.value === id) newConversation()
    ElMessage.success('会话已删除')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '删除会话失败')
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
    assistantMessage.source_quality_notice = saved.source_quality_notice || buildSourceQualityNotice(assistantMessage.sources)
    assistantMessage.source_warning = saved.source_warning || assistantMessage.source_quality_notice.warning || ''
    assistantMessage.source_warnings = Array.isArray(saved.source_warnings) ? saved.source_warnings : (assistantMessage.source_warning ? [assistantMessage.source_warning] : [])
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
  auth.logout()
  router.push('/login')
}

function updateChatScrollState() {
  const el = chatBodyRef.value
  if (!el) return
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight
  isChatAtBottom.value = distance <= CHAT_SCROLL_THRESHOLD
}

function handleChatScroll() {
  updateChatScrollState()
}

function openSourcePanel(message: ChatMessageItem, sectionIndex: number | null = null) {
  activeSourceMessage.value = message
  activeSourceSectionIndex.value = sectionIndex
  sourceViewMode.value = sectionIndex === null ? 'top' : 'related'
  documentSearch.value = ''
  documentStatusFilter.value = 'all'
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
  documentSearch.value = ''
  documentStatusFilter.value = 'all'
  highlightedSourceKey.value = ''
  clearPreview()
}

function setSourceViewMode(mode: 'all' | 'related' | 'top') {
  sourceViewMode.value = mode
}

function clearPreview() {
  previewSourceTitle.value = ''
  previewText.value = ''
}

function previewSource(source: SourceItem) {
  previewSourceTitle.value = `${sourceTitle(source)} · ${sourceLocation(source)}`
  const summary = sourceEvidenceSummary(source)
  const raw = sourceSnippet(source)
  previewText.value = summary
    ? `证据摘要：\n${summary}${raw && raw !== summary ? `\n\n原始命中：\n${raw}` : ''}`
    : '暂无可预览内容。'
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
  const title = String(source.document_title || source.title || '')
  const filename = String(source.filename || '')
  const id = String(source.document_id || '')
  const titleLooksLikeId = Boolean(title && /^\d{6,}$/.test(title.trim()))
  const filenameBase = filename.includes('.') ? filename.split('.').slice(0, -1).join('.') : filename
  if (filename && (!title || titleLooksLikeId || title === filenameBase)) return filename
  return title || filename || id || '未知来源'
}

function sourceFilename(source: SourceItem) {
  return String(source.filename || source.document_title || source.title || source.document_id || '未知文档')
}

function sourceExtension(source: SourceItem) {
  const name = sourceFilename(source).toLowerCase()
  const ext = name.includes('.') ? name.split('.').pop() || '' : ''
  return ext ? ext.toUpperCase() : 'DOC'
}

function documentStatusKind(source: SourceItem): DocumentStatusFilter {
  const used = Number(source.chunks_used || 0)
  const total = Number(source.total_chunks || 0)
  if (source.summary_source && total > 0 && used >= total) return 'ready'
  if (source.summary_source && used > 0) return 'partial'
  if (sourceSnippet(source)) return 'partial'
  return 'empty'
}

function documentStatusLabel(source: SourceItem) {
  const kind = documentStatusKind(source)
  if (kind === 'ready') return '已解析'
  if (kind === 'partial') return '部分内容'
  return '暂无预览'
}

function documentStatusDetail(source: SourceItem) {
  const used = Number(source.chunks_used || 0)
  const total = Number(source.total_chunks || 0)
  if (source.summary_source && total > 0) return `${used}/${total} 个片段`
  return sourceLocation(source)
}

function filterDocumentSources(sources: SourceItem[]) {
  const keyword = normalizeSearchText(documentSearch.value).trim()
  return sources.filter((source) => {
    if (documentStatusFilter.value !== 'all' && documentStatusKind(source) !== documentStatusFilter.value) return false
    if (!keyword) return true
    const haystack = normalizeSearchText([
      sourceTitle(source),
      sourceFilename(source),
      sourceType(source),
      sourceLocation(source),
      sourceSnippet(source),
    ].join(' '))
    return haystack.includes(keyword)
  })
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

function tableRowFromSource(source: SourceItem) {
  const row = source.table_row
  if (row && typeof row === 'object' && !Array.isArray(row)) return row as Record<string, unknown>
  return null
}

function sourceEvidenceSummary(source: SourceItem) {
  const row = tableRowFromSource(source)
  if (row) {
    const priority = [
      '省份',
      '城市',
      '单位名称',
      '开设公司名称',
      '当前进度-1.银行账户是否开具完成',
      '当前进度-2.社保公积金账户是否开具完成',
      '当前进度-3.公积金比例',
      '当前进度-4.开设公司名称',
      '操作规则-社保',
      '操作规则-医保',
      '操作规则-公积金',
      '截止时间-社保',
      '截止时间-医保',
      '截止时间-公积金',
      '预计缴款时间-社保',
      '预计缴款时间-公积金',
      '备注',
    ]
    const parts = priority
      .map((key) => {
        const value = String(row[key] || '').trim()
        return value ? `${key}：${value}` : ''
      })
      .filter(Boolean)
    if (parts.length) return parts.slice(0, 8).join(' · ')
  }
  return sourceSnippet(source)
}

function sourceSnippet(source: SourceItem) {
  const raw = String(source.content || source.snippet || source.excerpt || '')
  return isSpreadsheetSource(source) ? formatSpreadsheetSnippet(raw) : raw
}

function sourceType(source: SourceItem) {
  const channel = String(source.retrieval_channel || '')
  if (channel === 'table' || String(source.chunk_index ?? '').startsWith('table:')) return '表格行证据'
  const type = String(source.source_type || '')
  if (type.startsWith('chat_')) return '个人附件'
  if (isSpreadsheetSource(source)) return '表格文档'
  return type || '知识库文档'
}

function sourceLocation(source: SourceItem) {
  if (source.summary_source) return `已纳入 ${source.chunks_used || 0}/${source.total_chunks || 0}`
  const channel = String(source.retrieval_channel || '')
  const chunkIndex = String(source.chunk_index ?? '')
  const sheet = String(source.sheet_name || source.section_title || '').trim()
  const rowNumber = source.row_number || source.page_number
  if (channel === 'table' || chunkIndex.startsWith('table:')) {
    const parts = []
    if (sheet) parts.push(sheet)
    if (rowNumber === 0 || rowNumber) parts.push(`第 ${rowNumber} 行`)
    return parts.length ? parts.join(' · ') : '表格行'
  }
  if (source.location) {
    const readable = String(source.location)
      .replace(/\bchunk\s*[:#]?\s*[^|]+/gi, '')
      .replace(/\s*\|\s*/g, ' · ')
      .replace(/\s+/g, ' ')
      .replace(/^·\s*|\s*·$/g, '')
      .trim()
    if (readable) return readable
  }
  if (source.page_number === 0 || source.page_number) return `第 ${source.page_number} 页`
  if (isSpreadsheetSource(source)) return '表格命中'
  return '文档命中'
}

function messageDomId(message: ChatMessageItem) {
  return `chat-message-${message.id}`
}

function isSearchMatchedMessage(message: ChatMessageItem) {
  return chatSearchMatches.value.some((item) => item.id === message.id)
}

function isCurrentSearchMessage(message: ChatMessageItem) {
  const current = chatSearchMatches.value[currentSearchMatchIndex.value]
  return Boolean(current && current.id === message.id)
}

async function scrollToSearchMatch() {
  const match = chatSearchMatches.value[currentSearchMatchIndex.value]
  if (!match) return
  await nextTick()
  document.getElementById(messageDomId(match))?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function jumpToNextSearchMatch() {
  const total = chatSearchMatches.value.length
  if (!total) return
  currentSearchMatchIndex.value = (currentSearchMatchIndex.value + 1) % total
  scrollToSearchMatch()
}

function jumpToPrevSearchMatch() {
  const total = chatSearchMatches.value.length
  if (!total) return
  currentSearchMatchIndex.value = (currentSearchMatchIndex.value - 1 + total) % total
  scrollToSearchMatch()
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

function answerWithSourceSummary(message: ChatMessageItem) {
  const answer = stripInlineSourceMarkers(message.content || '')
  if (!message.sources.length) return answer
  const sourceLines = message.sources.slice(0, 8).map((source, index) => {
    return `${index + 1}. ${sourceTitle(source)}（${sourceLocation(source)}）`
  })
  return `${answer}\n\n引用来源：\n${sourceLines.join('\n')}`
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

function feedbackCategoryOf(rating: FeedbackRating) {
  return rating === 'helpful' ? 'other' : 'not_helpful'
}

async function submitFeedback(message: ChatMessageItem, rating: FeedbackRating, content: string) {
  if (!message || message.feedbackSubmitted) return
  feedbackSubmitting.value = true
  try {
    const payload = {
      session_id: sessionId.value || undefined,
      message_id: message.id,
      rating,
      category: feedbackCategoryOf(rating),
      feedback_category: feedbackCategoryOf(rating),
      content: content.trim(),
    }
    await http.post('/chat/feedback', payload)
    message.feedbackSubmitted = true
    ElMessage.success(rating === 'helpful' ? '感谢反馈' : '反馈已提交')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '反馈提交失败')
  } finally {
    feedbackSubmitting.value = false
  }
}

async function submitQuickFeedback(message: ChatMessageItem, rating: FeedbackRating) {
  const content = rating === 'helpful' ? '这条回答有帮助' : '这条回答不够好'
  await submitFeedback(message, rating, content)
}

function openFeedbackDialog(message: ChatMessageItem, rating: FeedbackRating) {
  if (!message || message.feedbackSubmitted) return
  feedbackTargetMessage.value = message
  feedbackTargetRating.value = rating
  feedbackForm.value = { content: '' }
  feedbackDialogVisible.value = true
}

function closeFeedbackDialog() {
  feedbackDialogVisible.value = false
  feedbackTargetMessage.value = null
  feedbackForm.value = { content: '' }
  feedbackTargetRating.value = 'unhelpful'
}

async function confirmFeedbackSubmit() {
  const message = feedbackTargetMessage.value
  const content = feedbackForm.value.content.trim()
  if (!message || !content) return
  await submitFeedback(message, feedbackTargetRating.value, content)
  if (message.feedbackSubmitted) closeFeedbackDialog()
}

function feedbackPlaceholderOf(rating: FeedbackRating) {
  return rating === 'helpful'
    ? '可以简单写：这条回答有帮助。'
    : '请描述哪里不对、不完整，或者你期望的回答是什么。'
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

function previewRowMatch(line: string) {
  return /^行\s*(\d+)\s*[：:]\s*(.+)$/.exec(String(line || '').trim())
}

function parsePreviewRow(line: string) {
  const raw = String(line || '').trim()
  const rowMatch = previewRowMatch(raw)
  const bulletMatch = /^(?:[-*]|•)\s+(.+)$/.exec(raw)
  let payload = ''

  if (rowMatch) {
    payload = rowMatch[2]
  } else if (bulletMatch && bulletMatch[1].includes('=') && bulletMatch[1].includes('|')) {
    payload = bulletMatch[1]
  } else {
    return null
  }

  const values: Record<string, string> = {}
  for (const part of payload.split(/\s*\|\s*/)) {
    const index = part.indexOf('=')
    if (index <= 0) continue
    const key = part.slice(0, index).trim()
    const value = part.slice(index + 1).trim()
    if (key) values[key] = value
  }
  return Object.keys(values).length ? { rowNumber: rowMatch?.[1] || '', values } : null
}

function renderPreviewRowsTable(rows: Array<{ rowNumber: string; values: Record<string, string> }>) {
  const headers: string[] = []
  for (const row of rows) {
    for (const key of Object.keys(row.values)) {
      if (!headers.includes(key)) headers.push(key)
    }
  }
  const body = rows.map((row) => {
    const cells = headers.map((header) => inlineMarkdown(row.values[header] || ''))
    return `<tr>${cells.map((cell) => `<td>${cell}</td>`).join('')}</tr>`
  }).join('')
  return `<div class="answer-data-table"><div class="answer-data-table-head"><strong>明细列表</strong><span>${rows.length} 条</span></div><div class="answer-data-table-scroll"><table><thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table></div></div>`
}

function renderConclusionCard(text: string) {
  const metric = /共有\s*([\d,]+)\s*([^，。,.\s]*)/.exec(text)
  const metricHtml = metric
    ? `<div class="answer-stat-metric"><strong>${escapeHtml(metric[1])}</strong><span>${escapeHtml(metric[2] || '条')}</span></div>`
    : ''
  return `<div class="answer-stat-card"><div><span>统计结论</span><p>${inlineMarkdown(text)}</p></div>${metricHtml}</div>`
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

    const conclusion = /^结论[：:]\s*(.+)$/.exec(trimmed)
    if (conclusion) {
      closeList()
      html.push(renderConclusionCard(conclusion[1]))
      continue
    }

    const previewRow = parsePreviewRow(trimmed)
    if (previewRow) {
      closeList()
      const rows = [previewRow]
      while (index + 1 < lines.length) {
        const nextRow = parsePreviewRow(lines[index + 1])
        if (!nextRow) break
        rows.push(nextRow)
        index += 1
      }
      html.push(renderPreviewRowsTable(rows))
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
        `<div class="answer-data-table"><div class="answer-data-table-scroll"><table><thead><tr>${headers.map((cell) => `<th>${cell}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div></div>`,
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
  if (/(表格|统计|口径|来源明细|命中行|预览|Sheet|数据)/.test(titleText)) return { kind: 'data' as StructuredSectionKind, badge: '数据' }
  if (/(总结|结论|摘要|概览|总览)/.test(titleText)) return { kind: 'highlight' as StructuredSectionKind, badge: '摘要' }
  if (/(风险|注意|提醒|限制|警告|问题)/.test(titleText)) return { kind: 'warning' as StructuredSectionKind, badge: '风险' }
  if (/(建议|下一步|行动|处理|方案)/.test(titleText)) return { kind: 'action' as StructuredSectionKind, badge: '建议' }
  if (!titleText && index === 0) return { kind: 'lead' as StructuredSectionKind, badge: total > 1 ? '概览' : '回答' }
  if (!titleText && /(^|\n)\s*(?:[-*]|\d+\.)\s+/.test(body)) return { kind: 'section' as StructuredSectionKind, badge: '要点' }
  return { kind: titleText ? ('section' as StructuredSectionKind) : ('lead' as StructuredSectionKind), badge: titleText ? '分节' : '回答' }
}

function shouldUseCompactAnswer(content: string) {
  const normalized = String(content || '').replace(/\r\n/g, '\n').trim()
  if (!normalized) return true
  const lines = normalized.split('\n').filter((line) => line.trim())
  const headingCount = lines.filter((line) => /^(#{1,4})\s+/.test(line.trim())).length
  const labeledCount = lines.filter((line) => /^(结论|总结|摘要|概览|总览|风险|注意|提醒|建议|下一步|行动)[：:]\s+/.test(line.trim())).length
  const listCount = lines.filter((line) => /^\s*(?:[-*]|\d+\.)\s+/.test(line)).length

  if (headingCount >= 2) return false
  if (headingCount >= 1 && normalized.length >= 260) return false
  if (labeledCount >= 2 && normalized.length >= 360) return false
  if (normalized.length >= 520 && listCount >= 3) return false
  return normalized.length < 520
}

function buildStructuredSections(content: string): StructuredSection[] {
  const normalized = String(content || '').replace(/\r\n/g, '\n').trim()
  if (!normalized) return []
  if (shouldUseCompactAnswer(normalized)) {
    return [{
      title: '',
      html: renderMarkdown(normalized),
      plainText: normalized,
      kind: 'lead' as StructuredSectionKind,
      badge: '回答',
    }]
  }

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

    const labeledMatch = /^(结论|总结|摘要|概览|总览|风险|注意|提醒|建议|下一步|行动)[：:]\s*(.*)$/.exec(trimmed)
    if (labeledMatch) {
      pushCurrent()
      current = { title: labeledMatch[1], lines: labeledMatch[2] ? [labeledMatch[2]] : [] }
      continue
    }

    current.lines.push(line)
  }

  pushCurrent()

  if (blocks.length <= 1) {
    return [{
      title: '',
      html: renderMarkdown(normalized),
      plainText: normalized,
      kind: 'lead' as StructuredSectionKind,
      badge: '回答',
    }]
  }

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
  if (chatBodyRef.value) {
    chatBodyRef.value.scrollTop = chatBodyRef.value.scrollHeight
    updateChatScrollState()
  }
}

watch(chatSearchQuery, () => {
  currentSearchMatchIndex.value = 0
  if (chatSearchMatches.value.length) scrollToSearchMatch()
})

onMounted(() => {
  loadCurrentUser()
  loadSessions()
})
</script>
