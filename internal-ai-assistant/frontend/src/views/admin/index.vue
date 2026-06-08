<template>
  <div class="admin-page">
    <h2>后台管理</h2>
    <p>这里不是平台，只保留员工、岗位组、文档和文档权限。</p>
    <el-tabs>
      <el-tab-pane label="岗位组">
        <el-input v-model="groupName" placeholder="岗位组名称" style="max-width: 240px" />
        <el-button type="primary" @click="createGroup">新增</el-button>
        <ul><li v-for="g in groups" :key="g.id">{{ g.name }}</li></ul>
      </el-tab-pane>

      <el-tab-pane label="员工">
        <el-input v-model="user.username" placeholder="用户名" style="max-width: 160px" />
        <el-input v-model="user.password" placeholder="密码" style="max-width: 160px" />
        <el-select v-model="user.group_ids" multiple placeholder="所属岗位组" style="width: 260px">
          <el-option v-for="g in groups" :key="g.id" :label="g.name" :value="g.id" />
        </el-select>
        <el-checkbox v-model="user.is_admin">管理员</el-checkbox>
        <el-button type="primary" @click="createUser">新增员工</el-button>
        <el-table :data="users" style="margin-top: 16px">
          <el-table-column prop="username" label="用户名" />
          <el-table-column label="岗位组">
            <template #default="scope">{{ scope.row.groups.map((g:any) => g.name).join('、') }}</template>
          </el-table-column>
          <el-table-column label="管理员">
            <template #default="scope">{{ scope.row.is_admin ? '是' : '否' }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="文档与权限">
        <div class="admin-toolbar">
          <el-upload :auto-upload="false" :show-file-list="false" :on-change="handleFile">
            <el-button type="primary">选择文件上传</el-button>
          </el-upload>
          <span class="tip">支持 PDF / Markdown / Word / Excel / PPT / CSV / TXT / 图片；上传后显示解析和 PageIndex 状态。</span>
        </div>
        <div class="tip">高级索引：{{ pageIndexEngineText }} · {{ pageIndexStatus?.status_detail || '正在读取 PageIndex 状态' }}</div>
        <el-table :data="docs" style="margin-top: 16px">
          <el-table-column prop="title" label="文档" min-width="160" />
          <el-table-column prop="filename" label="文件名" min-width="160" />
          <el-table-column label="解析状态" min-width="220">
            <template #default="scope">
              <div class="doc-status-cell">
                <strong>{{ statusText(scope.row.status) }} · {{ stageText(scope.row.stage) }}</strong>
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
                style="width: 100%"
                @change="saveDocPermission(scope.row.id)"
              >
                <el-option v-for="g in groups" :key="g.id" :label="g.name" :value="g.id" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180">
            <template #default="scope">
              <el-button link type="primary" @click="openDocumentPageIndex(scope.row)">结构树</el-button>
              <el-button link @click="rebuildDocumentPageIndex(scope.row)">重建高级索引</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="pageIndexDialogVisible" title="高级结构索引" width="min(760px, calc(100vw - 32px))">
      <div v-if="pageIndexLoading">正在加载高级索引…</div>
      <div v-else>
        <p>{{ pageIndexStatusText(pageIndexPayload?.page_index) }}</p>
        <el-card v-for="node in pageIndexFlatNodes" :key="node.key" class="source-card">
          <strong>{{ node.indent }}{{ node.title }}</strong>
          <p>{{ node.summary || '暂无摘要' }}</p>
        </el-card>
        <div v-if="!pageIndexFlatNodes.length">暂无结构树。可点击“重建高级索引”。</div>
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
const pageIndexDialogVisible = ref(false)
const pageIndexLoading = ref(false)
const pageIndexPayload = ref<any | null>(null)
const pageIndexDoc = ref<any | null>(null)

const pageIndexEngineText = computed(() => {
  if (!pageIndexStatus.value?.enabled) return '已关闭'
  if (pageIndexStatus.value?.official_available && !pageIndexStatus.value?.forced_lightweight) return '官方 PageIndex'
  return '轻量结构树兜底'
})
const pageIndexFlatNodes = computed(() => flattenPageIndexNodes(pageIndexPayload.value?.structure || []))

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
