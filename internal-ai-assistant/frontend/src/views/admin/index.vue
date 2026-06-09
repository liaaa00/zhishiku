<template>
  <div class="admin-page admin-chatgpt-page">
    <header class="admin-hero">
      <div>
        <span class="admin-eyebrow">Knowledge Admin</span>
        <h2>后台管理</h2>
        <p>管理岗位组、员工账号、文档权限和高级索引状态。</p>
      </div>
      <div class="admin-hero-status">
        <span>PageIndex</span>
        <strong>{{ pageIndexEngineText }}</strong>
      </div>
    </header>

    <section class="admin-stat-grid" aria-label="后台数据概览">
      <article class="admin-stat-card">
        <span>岗位组</span>
        <strong>{{ groups.length }}</strong>
      </article>
      <article class="admin-stat-card">
        <span>员工</span>
        <strong>{{ users.length }}</strong>
      </article>
      <article class="admin-stat-card">
        <span>文档</span>
        <strong>{{ docs.length }}</strong>
      </article>
      <article class="admin-stat-card wide">
        <span>高级索引状态</span>
        <strong>{{ pageIndexStatus?.status_detail || '正在读取 PageIndex 状态' }}</strong>
      </article>
    </section>

    <el-tabs class="admin-tabs">
      <el-tab-pane label="岗位组">
        <section class="admin-panel-card">
          <header class="admin-section-header">
            <div>
              <h3>岗位组</h3>
              <p>用岗位组控制员工可以访问哪些知识文档。</p>
            </div>
          </header>
          <div v-if="groups.length" class="admin-list-toolbar">
            <label class="admin-search-box admin-group-search-box">
              <span>搜索岗位组</span>
              <el-input v-model="groupSearch" clearable placeholder="按岗位组名称、ID 或成员数搜索" class="admin-input-search" />
            </label>
            <div class="admin-list-summary admin-group-summary">当前显示 {{ filteredGroups.length }} / {{ groups.length }} 个岗位组</div>
          </div>
          <div class="admin-form-row">
            <el-input v-model="groupName" placeholder="岗位组名称" class="admin-input-sm" />
            <el-button type="primary" @click="createGroup">新增</el-button>
          </div>
          <div v-if="groups.length && !filteredGroups.length" class="admin-dialog-empty admin-group-empty">没有匹配的岗位组。可以清空搜索词重新查看。</div>
          <ul v-if="groups.length" class="admin-group-grid">
            <li v-for="g in filteredGroups" :key="g.id" class="admin-group-card">
              <div class="admin-group-card-head">
                <strong>{{ g.name }}</strong>
                <span class="admin-group-pill">{{ groupMemberCount(g.id) }} 名员工</span>
              </div>
              <div class="admin-group-card-meta">
                <span>{{ groupDocumentCount(g.id) }} 份文档</span>
                <span>ID {{ g.id }}</span>
              </div>
            </li>
          </ul>
          <div v-else class="admin-dialog-empty admin-group-empty">暂无岗位组</div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="员工">
        <section class="admin-panel-card">
          <header class="admin-section-header">
            <div>
              <h3>员工</h3>
              <p>创建员工账号，并分配可访问的岗位组。</p>
            </div>
          </header>
          <div v-if="users.length" class="admin-list-toolbar">
            <label class="admin-search-box admin-user-search-box">
              <span>搜索员工</span>
              <el-input v-model="userSearch" clearable placeholder="按用户名、岗位组或角色搜索" class="admin-input-search" />
            </label>
            <div class="admin-filter-row" aria-label="员工角色筛选">
              <button :class="{ active: userRoleFilter === 'all' }" type="button" @click="userRoleFilter = 'all'">
                全部 {{ users.length }}
              </button>
              <button :class="{ active: userRoleFilter === 'admin' }" type="button" @click="userRoleFilter = 'admin'">
                管理员 {{ userAdminCount }}
              </button>
              <button :class="{ active: userRoleFilter === 'member' }" type="button" @click="userRoleFilter = 'member'">
                成员 {{ userMemberCount }}
              </button>
              <button :class="{ active: userRoleFilter === 'unassigned' }" type="button" @click="userRoleFilter = 'unassigned'">
                未分配 {{ userUnassignedCount }}
              </button>
            </div>
            <div class="admin-list-summary admin-user-summary">当前显示 {{ filteredUsers.length }} / {{ users.length }} 名员工</div>
          </div>
          <div class="admin-form-row admin-form-row-wrap">
            <el-input v-model="user.username" placeholder="用户名" class="admin-input-sm" />
            <el-input v-model="user.password" placeholder="密码" class="admin-input-sm" />
            <el-select v-model="user.group_ids" multiple placeholder="所属岗位组" class="admin-select-md">
              <el-option v-for="g in groups" :key="g.id" :label="g.name" :value="g.id" />
            </el-select>
            <el-checkbox v-model="user.is_admin">管理员</el-checkbox>
            <el-button type="primary" @click="createUser">新增员工</el-button>
          </div>
          <div v-if="users.length && !filteredUsers.length" class="admin-dialog-empty admin-user-empty">没有匹配的员工。可以清空搜索词或切换角色筛选。</div>
          <el-table :data="filteredUsers" class="admin-table admin-user-table">
            <el-table-column label="员工" min-width="180">
              <template #default="scope">
                <div class="admin-user-cell">
                  <strong>{{ scope.row.username }}</strong>
                  <span>ID {{ scope.row.id }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="角色" width="120">
              <template #default="scope">
                <span :class="['admin-role-pill', userRoleKind(scope.row)]">{{ userRoleLabel(scope.row) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="岗位组" min-width="260">
              <template #default="scope">{{ userGroupsText(scope.row) }}</template>
            </el-table-column>
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="文档与权限">
        <section class="admin-panel-card">
          <header class="admin-section-header">
            <div>
              <h3>文档与权限</h3>
              <p>上传知识文档，查看解析进度，并配置岗位组可见范围。</p>
            </div>
            <el-upload :auto-upload="false" :show-file-list="false" :on-change="handleFile">
              <el-button type="primary">选择文件上传</el-button>
            </el-upload>
          </header>

          <div class="admin-upload-note">
            <span>支持 PDF / Markdown / Word / Excel / PPT / CSV / TXT / 图片</span>
            <span>上传后显示解析和 PageIndex 状态。</span>
          </div>
          <div class="admin-index-note">高级索引：{{ pageIndexEngineText }} · {{ pageIndexStatus?.status_detail || '正在读取 PageIndex 状态' }}</div>

          <div v-if="docs.length" class="admin-doc-toolbar">
            <label class="admin-search-box admin-doc-search-box">
              <span>搜索文档</span>
              <el-input
                v-model="docSearch"
                clearable
                placeholder="按文档名、文件名、说明或岗位组搜索"
                class="admin-input-search"
              />
            </label>
            <div class="admin-filter-row" aria-label="文档状态筛选">
              <button :class="{ active: docStatusFilter === 'all' }" type="button" @click="docStatusFilter = 'all'">
                全部 {{ docs.length }}
              </button>
              <button :class="{ active: docStatusFilter === 'ready' }" type="button" @click="docStatusFilter = 'ready'">
                已完成 {{ docReadyCount }}
              </button>
              <button :class="{ active: docStatusFilter === 'processing' }" type="button" @click="docStatusFilter = 'processing'">
                处理中 {{ docProcessingCount }}
              </button>
              <button :class="{ active: docStatusFilter === 'waiting' }" type="button" @click="docStatusFilter = 'waiting'">
                等待中 {{ docWaitingCount }}
              </button>
              <button :class="{ active: docStatusFilter === 'failed' }" type="button" @click="docStatusFilter = 'failed'">
                失败 {{ docFailedCount }}
              </button>
            </div>
            <div class="admin-doc-summary">当前显示 {{ filteredDocs.length }} / {{ docs.length }} 份文档</div>
          </div>

          <div v-if="docs.length && !filteredDocs.length" class="admin-dialog-empty admin-doc-empty">没有匹配的文档。可以清空搜索词或切换状态筛选。</div>

          <el-table :data="filteredDocs" class="admin-table admin-doc-table">
            <el-table-column label="文档" min-width="240">
              <template #default="scope">
                <div class="admin-doc-cell">
                  <div class="admin-doc-cell-head">
                    <strong>{{ docTitle(scope.row) }}</strong>
                    <span class="admin-doc-file">{{ docFilename(scope.row) }}</span>
                  </div>
                  <p>{{ docDescription(scope.row) }}</p>
                  <div class="admin-doc-cell-meta">
                    <span>{{ docGroupsText(scope.row) }}</span>
                    <span>ID {{ scope.row.id }}</span>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="解析状态" min-width="280">
              <template #default="scope">
                <div class="admin-doc-status">
                  <span :class="['admin-status-pill', docStatusKind(scope.row)]">{{ docStatusLabel(scope.row) }}</span>
                  <strong>{{ docStageLabel(scope.row) }}</strong>
                  <span>{{ scope.row.message || '暂无说明' }}</span>
                  <span>片段 {{ scope.row.chunks || 0 }} · {{ scope.row.searchable ? '可检索' : '未检索' }}</span>
                  <span>高级索引：{{ pageIndexStatusText(scope.row.page_index) }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="可访问岗位组" min-width="300">
              <template #default="scope">
                <el-select
                  v-model="docGroupMap[scope.row.id]"
                  multiple
                  placeholder="选择岗位组"
                  class="admin-full-select"
                  @change="saveDocPermission(scope.row.id)"
                >
                  <el-option v-for="g in groups" :key="g.id" :label="g.name" :value="g.id" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="190">
              <template #default="scope">
                <div class="admin-row-actions">
                  <el-button link type="primary" @click="openDocumentPageIndex(scope.row)">结构树</el-button>
                  <el-button link @click="rebuildDocumentPageIndex(scope.row)">重建高级索引</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="pageIndexDialogVisible" title="高级结构索引" width="min(760px, calc(100vw - 32px))" class="admin-pageindex-dialog">
      <div v-if="pageIndexLoading" class="admin-dialog-empty">正在加载高级索引…</div>
      <div v-else>
        <p class="admin-index-note dialog-note">{{ pageIndexStatusText(pageIndexPayload?.page_index) }}</p>
        <el-card v-for="node in pageIndexFlatNodes" :key="node.key" class="source-card admin-tree-card">
          <strong>{{ node.indent }}{{ node.title }}</strong>
          <p>{{ node.summary || '暂无摘要' }}</p>
        </el-card>
        <div v-if="!pageIndexFlatNodes.length" class="admin-dialog-empty">暂无结构树。可点击“重建高级索引”。</div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../../api'

const groups = ref<any[]>([])
const users = ref<any[]>([])
const docs = ref<any[]>([])
const pageIndexStatus = ref<any | null>(null)
const docGroupMap = reactive<Record<string, string[]>>({})
const groupName = ref('')
const user = reactive({ username: '', password: '', is_admin: false, group_ids: [] as string[] })
type DocStatusFilter = 'all' | 'ready' | 'processing' | 'waiting' | 'failed'
type UserRoleFilter = 'all' | 'admin' | 'member' | 'unassigned'

const pageIndexDialogVisible = ref(false)
const pageIndexLoading = ref(false)
const pageIndexPayload = ref<any | null>(null)
const pageIndexDoc = ref<any | null>(null)
const groupSearch = ref('')
const userSearch = ref('')
const userRoleFilter = ref<UserRoleFilter>('all')
const docSearch = ref('')
const docStatusFilter = ref<DocStatusFilter>('all')

const pageIndexEngineText = computed(() => {
  if (!pageIndexStatus.value?.enabled) return '已关闭'
  if (pageIndexStatus.value?.official_available && !pageIndexStatus.value?.forced_lightweight) return '官方 PageIndex'
  return '轻量结构树兜底'
})
const pageIndexFlatNodes = computed(() => flattenPageIndexNodes(pageIndexPayload.value?.structure || []))
const filteredGroups = computed(() => {
  const keyword = normalizeText(groupSearch.value).trim()
  return groups.value.filter((group: any) => {
    if (!keyword) return true
    const haystack = normalizeText([
      group?.name,
      group?.id,
      groupMemberCount(group?.id),
      groupDocumentCount(group?.id),
    ].join(' '))
    return haystack.includes(keyword)
  })
})
const filteredUsers = computed(() => {
  const keyword = normalizeText(userSearch.value).trim()
  return users.value.filter((item: any) => {
    if (userRoleFilter.value !== 'all' && userRoleKind(item) !== userRoleFilter.value) return false
    if (!keyword) return true
    const haystack = normalizeText([
      item?.username,
      item?.id,
      item?.groups?.map((g: any) => g?.name).join('、'),
      item?.is_admin ? '管理员' : '成员',
    ].join(' '))
    return haystack.includes(keyword)
  })
})
const filteredDocs = computed(() => {
  const keyword = normalizeText(docSearch.value).trim()
  return docs.value.filter((doc: any) => {
    if (docStatusFilter.value !== 'all' && docStatusKind(doc) !== docStatusFilter.value) return false
    if (!keyword) return true
    const haystack = normalizeText([
      docTitle(doc),
      docFilename(doc),
      docDescription(doc),
      docGroupsText(doc),
      statusText(doc.status),
      stageText(doc.stage),
      pageIndexStatusText(doc.page_index),
    ].join(' '))
    return haystack.includes(keyword)
  })
})
const docReadyCount = computed(() => docs.value.filter((doc: any) => docStatusKind(doc) === 'ready').length)
const docProcessingCount = computed(() => docs.value.filter((doc: any) => docStatusKind(doc) === 'processing').length)
const docWaitingCount = computed(() => docs.value.filter((doc: any) => docStatusKind(doc) === 'waiting').length)
const docFailedCount = computed(() => docs.value.filter((doc: any) => docStatusKind(doc) === 'failed').length)
const userAdminCount = computed(() => users.value.filter((item: any) => item?.is_admin).length)
const userMemberCount = computed(() => users.value.filter((item: any) => !item?.is_admin && (item?.groups || []).length > 0).length)
const userUnassignedCount = computed(() => users.value.filter((item: any) => !(item?.groups || []).length).length)

function groupMemberCount(groupId?: string) {
  if (!groupId) return 0
  return users.value.filter((userItem: any) => (userItem?.groups || []).some((group: any) => String(group?.id) === String(groupId))).length
}

function groupDocumentCount(groupId?: string) {
  if (!groupId) return 0
  return docs.value.filter((doc: any) => (doc?.groups || []).some((group: any) => String(group?.id) === String(groupId))).length
}

function userRoleKind(item: any): UserRoleFilter {
  if (item?.is_admin) return 'admin'
  if ((item?.groups || []).length) return 'member'
  return 'unassigned'
}

function userRoleLabel(item: any) {
  return ({ admin: '管理员', member: '成员', unassigned: '未分配' } as Record<string, string>)[userRoleKind(item)]
}

function userGroupsText(item: any) {
  return String((item?.groups || []).map((g: any) => g?.name).filter(Boolean).join('、') || '未分配')
}

function normalizeText(value: string) {
  return String(value || '').toLowerCase()
}

function docTitle(doc: any) {
  const title = String(doc?.title || '')
  const filename = String(doc?.filename || '')
  const id = String(doc?.id || '')
  const titleLooksLikeId = Boolean(title && /^\d{6,}$/.test(title.trim()))
  const filenameBase = filename.includes('.') ? filename.split('.').slice(0, -1).join('.') : filename
  if (filename && (!title || titleLooksLikeId || title === filenameBase)) return filename
  return title || filename || id || '未命名文档'
}

function docFilename(doc: any) {
  return String(doc?.filename || doc?.title || doc?.id || '未知文件')
}

function docDescription(doc: any) {
  if (doc?.message) return String(doc.message)
  if (doc?.stage) return stageText(doc.stage)
  if (doc?.status) return statusText(doc.status)
  return '暂无说明'
}

function docGroupsText(doc: any) {
  return String((doc?.groups || []).map((g: any) => g?.name).filter(Boolean).join('、') || '未分配')
}

function docStatusKind(doc: any): DocStatusFilter {
  const status = normalizeText(doc?.status || '')
  const stage = normalizeText(doc?.stage || '')
  if (status === 'failed' || stage === 'parse_error' || stage === 'file_missing') return 'failed'
  if (status === 'processing' || ['worker', 'vision_ocr', 'pdf_text_extract', 'pdf_vision_ocr', 'word_text_extract', 'pptx_text_extract', 'spreadsheet_extract', 'csv_extract', 'text_extract', 'markdown_extract'].includes(stage)) return 'processing'
  if (status === 'ready' || stage === 'indexed' || doc?.searchable) return 'ready'
  if (status === 'pending' || status === 'queued' || ['uploaded', 'queued', 'need_ocr'].includes(stage)) return 'waiting'
  return 'waiting'
}

function docStatusLabel(doc: any) {
  return statusText(doc?.status)
}

function docStageLabel(doc: any) {
  return stageText(doc?.stage)
}

async function load() {
  try {
    groups.value = (await http.get('/admin/groups')).data || []
    users.value = (await http.get('/admin/users')).data || []
    docs.value = (await http.get('/admin/documents')).data || []
    docs.value.forEach((d: any) => {
      docGroupMap[d.id] = (d.groups || []).map((g: any) => g.id)
    })
    await loadPageIndexStatus()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载后台数据失败')
  }
}
async function loadPageIndexStatus() {
  try {
    pageIndexStatus.value = (await http.get('/admin/page-index/status')).data || null
  } catch {
    pageIndexStatus.value = { enabled: false, status_detail: 'PageIndex 状态读取失败' }
  }
}
async function createGroup() {
  await http.post('/admin/groups', { name: groupName.value })
  groupName.value = ''
  await load()
}
async function createUser() {
  await http.post('/admin/users', user)
  user.username = ''
  user.password = ''
  user.is_admin = false
  user.group_ids = []
  await load()
}
async function handleFile(file: any) {
  const fd = new FormData()
  fd.append('file', file.raw)
  await http.post('/admin/documents', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  ElMessage.success('文档上传并已进入解析队列')
  await load()
}
async function saveDocPermission(documentId: string) {
  await http.put(`/admin/documents/${documentId}/permissions`, { group_ids: docGroupMap[documentId] || [] })
  ElMessage.success('文档权限已保存')
}
function pageIndexStatusText(pageIndex?: any) {
  const status = pageIndex?.status || 'not_built'
  const label = ({ ready: '已构建', processing: '构建中', pending: '等待构建', failed: '构建失败', not_built: '未构建' } as Record<string, string>)[status] || status
  const stats = [pageIndex?.node_count ? `${pageIndex.node_count} 个节点` : '', pageIndex?.page_count ? `${pageIndex.page_count} 页/行` : ''].filter(Boolean).join(' · ')
  return stats ? `${label} · ${stats}` : label
}
function flattenPageIndexNodes(nodes: any[], depth = 0, prefix = ''): any[] {
  const result: any[] = []
  ;(nodes || []).forEach((node: any, index: number) => {
    const key = String(node.node_id || `${prefix}${index}`)
    result.push({ key: `${prefix}${key}`, title: node.title || '未命名节点', indent: '　'.repeat(depth), summary: node.summary || node.prefix_summary || '' })
    if (Array.isArray(node.nodes) && node.nodes.length) result.push(...flattenPageIndexNodes(node.nodes, depth + 1, `${prefix}${key}-`))
  })
  return result
}
async function openDocumentPageIndex(doc: any) {
  pageIndexDoc.value = doc
  pageIndexDialogVisible.value = true
  pageIndexLoading.value = true
  try {
    pageIndexPayload.value = (await http.get(`/admin/documents/${doc.id}/page-index`)).data || null
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载高级索引失败')
  } finally {
    pageIndexLoading.value = false
  }
}
async function rebuildDocumentPageIndex(doc: any) {
  try {
    await http.post(`/admin/documents/${doc.id}/page-index/rebuild`)
    ElMessage.success('高级索引已重建')
    if (pageIndexDialogVisible.value && pageIndexDoc.value?.id === doc.id) await openDocumentPageIndex(doc)
    await load()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '重建高级索引失败')
  }
}
function statusText(status?: string) {
  return ({ ready: '可检索', processing: '处理中', failed: '失败', pending: '等待', queued: '已排队' } as Record<string, string>)[status || ''] || status || '未知'
}
function stageText(stage?: string) {
  return ({ uploaded: '已上传', queued: '等待队列', worker: '任务执行中', vision_ocr: '图片 OCR', pdf_text_extract: 'PDF 解析', pdf_vision_ocr: 'PDF 视觉 OCR', word_text_extract: 'Word 解析', pptx_text_extract: 'PPTX 解析', spreadsheet_extract: '表格解析', csv_extract: 'CSV 解析', text_extract: '文本解析', markdown_extract: 'Markdown 解析', indexed: '已索引', need_ocr: '需要 OCR', parse_error: '解析失败', file_missing: '文件缺失' } as Record<string, string>)[stage || ''] || stage || '未知阶段'
}

onMounted(() => {
  document.documentElement.classList.add('admin-scroll-page')
  document.body.classList.add('admin-scroll-page')
  load()
})
onUnmounted(() => {
  document.documentElement.classList.remove('admin-scroll-page')
  document.body.classList.remove('admin-scroll-page')
})
</script>
