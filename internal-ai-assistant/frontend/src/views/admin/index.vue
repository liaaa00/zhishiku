<template>
  <div class="admin-page admin-chatgpt-page">
    <header class="admin-hero">
      <div>
        <span class="admin-eyebrow">Knowledge Admin</span>
        <h2>后台管理</h2>
        <p>管理岗位组、员工账号、文档权限、后台任务、模型配置和高级索引状态。</p>
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
      <article class="admin-stat-card">
        <span>模型配置</span>
        <strong>{{ modelConfig.api_key_set ? '已配置' : '未配置' }}</strong>
      </article>
      <article class="admin-stat-card">
        <span>后台任务</span>
        <strong>{{ tasks.length }}</strong>
      </article>
      <article class="admin-stat-card wide">
        <span>高级索引状态</span>
        <strong>{{ pageIndexStatus?.status_detail || '正在读取 PageIndex 状态' }}</strong>
      </article>
    </section>

    <section class="admin-quickbar" aria-label="后台快捷操作">
      <div class="admin-quickbar-group">
        <button type="button" class="admin-quickbar-btn" :disabled="refreshing" @click="refreshAllData">{{ refreshing ? '刷新中…' : '刷新数据' }}</button>
        <button type="button" :class="['admin-quickbar-btn', { active: adminTabIndex === 'groups' }]" @click="jumpToTab('groups')">岗位组</button>
        <button type="button" :class="['admin-quickbar-btn', { active: adminTabIndex === 'users' }]" @click="jumpToTab('users')">员工</button>
        <button type="button" :class="['admin-quickbar-btn', { active: adminTabIndex === 'docs' }]" @click="jumpToTab('docs')">文档与权限</button>
        <button type="button" :class="['admin-quickbar-btn', { active: adminTabIndex === 'model' }]" @click="jumpToTab('model')">模型配置</button>
        <button type="button" :class="['admin-quickbar-btn', { active: adminTabIndex === 'tasks' }]" @click="jumpToTab('tasks')">任务中心</button>
      </div>
      <div class="admin-quickbar-hint">轻量快捷入口，方便切换后台主要管理区域。· 最后刷新：{{ lastRefreshLabel }}</div>
    </section>

    <el-tabs v-model="adminTabIndex" class="admin-tabs">
      <el-tab-pane label="岗位组" name="groups">
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

      <el-tab-pane label="员工" name="users">
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

      <el-tab-pane label="文档与权限" name="docs">
        <section class="admin-panel-card">
          <header class="admin-section-header">
            <div>
              <h3>文档与权限</h3>
              <p>上传知识文档，查看解析进度，并配置岗位组可见范围。</p>
            </div>
            <el-upload :auto-upload="false" :show-file-list="false" :on-change="handleFile" :disabled="uploadingDoc">
              <el-button type="primary" :loading="uploadingDoc">选择文件上传</el-button>
            </el-upload>
          </header>

          <div class="admin-upload-note">
            <span>支持 PDF / Markdown / Word / Excel / PPT / CSV / TXT / 图片</span>
            <span>上传后显示解析和 PageIndex 状态。</span>
          </div>
          <div class="admin-index-note">高级索引：{{ pageIndexEngineText }} · {{ pageIndexStatus?.status_detail || '正在读取 PageIndex 状态' }}</div>

          <section v-if="lastUploadSummary" class="admin-upload-result-card">
            <div class="admin-upload-result-head">
              <div>
                <span>最近上传</span>
                <strong>{{ latestUploadDoc ? docTitle(latestUploadDoc) : (lastUploadSummary.filename || lastUploadSummary.title || '上传文件') }}</strong>
                <p>{{ latestUploadDoc ? docFilename(latestUploadDoc) : (lastUploadSummary.filename || '等待后端返回文档信息') }}</p>
              </div>
              <span :class="['admin-status-pill', uploadSummaryStatusKind]">{{ uploadSummaryStatusLabel }}</span>
            </div>
            <p class="admin-upload-result-message">{{ uploadSummaryDetail }}</p>
            <div class="admin-upload-result-meta">
              <span v-if="lastUploadSummary.taskId">任务 {{ lastUploadSummary.taskId }}</span>
              <span>{{ uploadSummaryProgressText }}</span>
              <span v-if="statusPolling" class="admin-auto-refresh-hint">自动更新中</span>
              <span v-if="lastUploadSummary.error" class="admin-upload-result-error">{{ lastUploadSummary.error }}</span>
            </div>
            <div class="admin-row-actions admin-upload-result-actions">
              <el-button link type="primary" @click="jumpToTab('tasks')">去任务中心查看</el-button>
              <el-button link @click="load()">刷新状态</el-button>
            </div>
          </section>

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

          <div v-if="filteredDocs.length" class="admin-doc-list" aria-label="文档与权限列表">
            <article
              v-for="doc in filteredDocs"
              :key="doc.id"
              :id="`admin-doc-${doc.id}`"
              :class="['admin-doc-card-row', { 'admin-doc-card-row--focus': latestUploadDoc && String(latestUploadDoc.id) === String(doc.id) }]"
            >
              <div class="admin-doc-card-main">
                <div class="admin-doc-card-head">
                  <div>
                    <strong>{{ docTitle(doc) }}</strong>
                    <span>{{ docFilename(doc) }}</span>
                  </div>
                  <span :class="['admin-status-pill', docStatusKind(doc)]">{{ docStatusLabel(doc) }}</span>
                </div>
                <p>{{ docDescription(doc) }}</p>
                <div class="admin-doc-card-meta">
                  <span>ID {{ doc.id }}</span>
                  <span>阶段：{{ docStageLabel(doc) }}</span>
                  <span>片段 {{ doc.chunks || 0 }} · {{ doc.searchable ? '可检索' : '未检索' }}</span>
                  <span>高级索引：{{ pageIndexStatusText(doc.page_index) }}</span>
                </div>
              </div>
              <aside class="admin-doc-card-side">
                <label class="admin-doc-permission-box">
                  <span>可访问岗位组</span>
                  <el-select
                    v-model="docGroupMap[doc.id]"
                    multiple
                    placeholder="选择岗位组"
                    class="admin-full-select"
                    @change="saveDocPermission(doc.id)"
                  >
                    <el-option v-for="g in groups" :key="g.id" :label="g.name" :value="g.id" />
                  </el-select>
                </label>
                <div class="admin-row-actions admin-doc-card-actions">
                  <el-button link type="primary" :disabled="openingDocId === doc.id" @click="openAdminDocument(doc)">
                    {{ openingDocId === doc.id ? '打开中…' : '打开原文' }}
                  </el-button>
                  <el-button link type="primary" @click="openDocumentPageIndex(doc)">查看结构树</el-button>
                  <el-button link @click="openChunkEditor(doc)">修改索引片段</el-button>
                  <el-button link :disabled="deletingDocId === doc.id || rebuildingPageIndexDocId === doc.id || reparsingDocId === doc.id" @click="reparseDocument(doc)">
                    {{ reparsingDocId === doc.id ? '解析中…' : '重新解析' }}
                  </el-button>
                  <el-button link :disabled="deletingDocId === doc.id || rebuildingPageIndexDocId === doc.id || reparsingDocId === doc.id" @click="rebuildDocumentPageIndex(doc)">
                    {{ rebuildingPageIndexDocId === doc.id ? '重建中…' : '重建高级索引' }}
                  </el-button>
                  <el-button link class="admin-danger-link" :disabled="deletingDocId === doc.id || rebuildingPageIndexDocId === doc.id || reparsingDocId === doc.id" @click="deleteDocument(doc)">
                    {{ deletingDocId === doc.id ? '删除中…' : '删除文档' }}
                  </el-button>
                </div>
              </aside>
            </article>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="任务中心" name="tasks">
        <section class="admin-panel-card admin-task-panel">
          <header class="admin-section-header">
            <div>
              <h3>任务中心</h3>
              <p>查看文档解析、重新解析、PageIndex 构建等后台任务状态，并对失败任务进行重试。</p>
            </div>
            <el-button :disabled="loadingTasks" @click="loadTasks">
              {{ loadingTasks ? '刷新中…' : '刷新任务' }}
            </el-button>
          </header>

          <div v-if="tasks.length" class="admin-list-toolbar admin-task-toolbar">
            <label class="admin-search-box admin-task-search-box">
              <span>搜索任务</span>
              <el-input
                v-model="taskSearch"
                clearable
                placeholder="按文档名、文件名、任务 ID、错误信息搜索"
                class="admin-input-search"
              />
            </label>
            <div class="admin-filter-row admin-task-type-row" aria-label="任务类型筛选">
              <button :class="{ active: taskTypeFilter === 'all' }" type="button" @click="taskTypeFilter = 'all'">全部 {{ tasks.length }}</button>
              <button :class="{ active: taskTypeFilter === 'document_parse' }" type="button" @click="taskTypeFilter = 'document_parse'">文档解析 {{ taskTypeCount('document_parse') }}</button>
              <button :class="{ active: taskTypeFilter === 'document_reparse' }" type="button" @click="taskTypeFilter = 'document_reparse'">重新解析 {{ taskTypeCount('document_reparse') }}</button>
              <button :class="{ active: taskTypeFilter === 'chat_attachment_parse' }" type="button" @click="taskTypeFilter = 'chat_attachment_parse'">聊天附件 {{ taskTypeCount('chat_attachment_parse') }}</button>
              <button :class="{ active: taskTypeFilter === 'page_index' }" type="button" @click="taskTypeFilter = 'page_index'">高级索引 {{ taskTypeCount('page_index') }}</button>
              <button :class="{ active: taskTypeFilter === 'page_index_rebuild' }" type="button" @click="taskTypeFilter = 'page_index_rebuild'">重建索引 {{ taskTypeCount('page_index_rebuild') }}</button>
              <button :class="{ active: taskTypeFilter === 'ocr' }" type="button" @click="taskTypeFilter = 'ocr'">OCR {{ taskTypeCount('ocr') }}</button>
              <button :class="{ active: taskTypeFilter === 'other' }" type="button" @click="taskTypeFilter = 'other'">其他 {{ taskTypeCount('other') }}</button>
            </div>
            <div class="admin-filter-row" aria-label="任务状态筛选">
              <button :class="{ active: taskStatusFilter === 'all' }" type="button" @click="taskStatusFilter = 'all'">全部状态</button>
              <button :class="{ active: taskStatusFilter === 'pending' }" type="button" @click="taskStatusFilter = 'pending'">等待中 {{ taskPendingCount }}</button>
              <button :class="{ active: taskStatusFilter === 'running' }" type="button" @click="taskStatusFilter = 'running'">执行中 {{ taskRunningCount }}</button>
              <button :class="{ active: taskStatusFilter === 'done' }" type="button" @click="taskStatusFilter = 'done'">已完成 {{ taskDoneCount }}</button>
              <button :class="{ active: taskStatusFilter === 'failed' }" type="button" @click="taskStatusFilter = 'failed'">失败 {{ taskFailedCount }}</button>
            </div>
            <div class="admin-list-summary admin-task-summary">当前显示 {{ filteredTasks.length }} / {{ tasks.length }} 个任务</div>
          </div>

          <div v-if="tasks.length && !filteredTasks.length" class="admin-dialog-empty admin-task-empty">没有匹配的后台任务。可以切换状态、类型筛选或清空搜索词。</div>
          <div v-if="filteredTasks.length" class="admin-task-list" aria-label="后台任务列表">
            <article v-for="task in filteredTasks" :key="task.id" :class="['admin-task-card', { 'admin-task-card--failed': taskStatusKind(task) === 'failed' }]">
              <div class="admin-task-main">
                <div class="admin-task-head">
                  <div>
                    <strong>{{ taskTypeLabel(task.task_type) }}</strong>
                    <span>{{ task.document_title || task.document_filename || task.document_id || '未关联文档' }}</span>
                  </div>
                  <span :class="['admin-task-status-pill', taskStatusKind(task)]">{{ taskStatusLabel(task.status) }}</span>
                </div>
                <p>任务 ID {{ task.id }}</p>
                <div class="admin-task-meta">
                  <span v-if="task.document_filename">文件 {{ task.document_filename }}</span>
                  <span>尝试 {{ task.attempts || 0 }} 次</span>
                  <span>创建 {{ formatDateTime(task.created_at) }}</span>
                  <span v-if="task.started_at">开始 {{ formatDateTime(task.started_at) }}</span>
                  <span v-if="task.finished_at">结束 {{ formatDateTime(task.finished_at) }}</span>
                </div>
                <div v-if="task.last_error" class="admin-task-error"><strong>失败原因：</strong>{{ task.last_error }}</div>
              </div>
              <div class="admin-row-actions admin-task-actions">
                <div v-if="taskStatusKind(task) === 'failed'" class="admin-task-action-hint">失败任务可直接重试</div>
                <el-button
                  v-if="taskStatusKind(task) === 'failed' || taskStatusKind(task) === 'done'"
                  :type="taskStatusKind(task) === 'failed' ? 'danger' : 'primary'"
                  :plain="taskStatusKind(task) === 'done'"
                  :disabled="retryingTaskId === task.id"
                  @click="retryTask(task)"
                >
                  {{ retryingTaskId === task.id ? '重试中…' : taskStatusKind(task) === 'failed' ? '重试失败任务' : '重新执行任务' }}
                </el-button>
              </div>
            </article>
          </div>
          <div v-if="!tasks.length && !loadingTasks" class="admin-dialog-empty admin-task-empty">暂无后台任务。</div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="模型配置" name="model">
        <section class="admin-panel-card admin-model-panel">
          <header class="admin-section-header">
            <div>
              <h3>模型配置</h3>
              <p>配置 OpenAI-compatible 模型服务，用于普通对话、文档问答和图片/OCR 识别。</p>
            </div>
            <span :class="['admin-model-status-pill', modelConfig.api_key_set ? 'ready' : 'waiting']">
              {{ modelConfig.api_key_set ? 'API Key 已保存' : 'API Key 未配置' }}
            </span>
          </header>

          <div class="admin-model-grid">
            <section class="admin-model-form-card">
              <label class="admin-model-field">
                <span>Base URL</span>
                <el-input v-model="modelForm.base_url" placeholder="https://api.deepseek.com" />
              </label>
              <label class="admin-model-field">
                <span>模型名称</span>
                <el-input v-model="modelForm.model" placeholder="deepseek-chat" />
              </label>
              <label class="admin-model-field">
                <span>API Key</span>
                <el-input v-model="modelForm.api_key" type="password" show-password placeholder="留空则保留已保存的密钥" />
              </label>
              <label class="admin-model-field">
                <span>Embedding Provider</span>
                <el-input v-model="modelForm.embedding_provider" placeholder="local / openai / openai-compatible" />
              </label>
              <label class="admin-model-field">
                <span>Embedding Base URL</span>
                <el-input v-model="modelForm.embedding_base_url" placeholder="OpenAI-compatible embeddings base URL" />
              </label>
              <label class="admin-model-field">
                <span>Embedding Model</span>
                <el-input v-model="modelForm.embedding_model" placeholder="text-embedding-3-small / bge-m3 / ..." />
              </label>
              <label class="admin-model-field">
                <span>Embedding API Key</span>
                <el-input v-model="modelForm.embedding_api_key" type="password" show-password placeholder="留空则保留已保存的 embedding key" />
              </label>
              <label class="admin-model-field admin-model-switch-field">
                <span>启用 LLM Reranker</span>
                <el-switch v-model="modelForm.reranker_enabled" active-text="开启" inactive-text="关闭" />
              </label>
              <label class="admin-model-field">
                <span>Reranker 模型</span>
                <el-input v-model="modelForm.reranker_model" placeholder="留空则使用聊天模型" />
              </label>
              <label class="admin-model-field">
                <span>Reranker 候选数</span>
                <el-input-number v-model="modelForm.reranker_max_candidates" :min="4" :max="60" />
              </label>
              <div class="admin-model-actions">
                <el-button type="primary" :disabled="savingModel" @click="saveModelConfig">
                  {{ savingModel ? '保存中…' : '保存配置' }}
                </el-button>
                <el-button :disabled="testingModel" @click="testModelConnection">
                  {{ testingModel ? '测试中…' : '测试聊天模型' }}
                </el-button>
                <el-button :disabled="testingModel" @click="testEmbeddingConnection">
                  {{ testingModel ? '测试中…' : '测试 Embedding' }}
                </el-button>
              </div>
            </section>

            <aside class="admin-model-info-card">
              <span>当前配置</span>
              <strong>{{ modelConfig.model || 'deepseek-chat' }}</strong>
              <p>{{ modelConfig.base_url || 'https://api.deepseek.com' }}</p>
              <span>Embedding</span>
              <strong>{{ modelConfig.embedding?.model || 'local-hash' }}</strong>
              <p>{{ modelConfig.embedding?.provider || 'local' }} · {{ modelConfig.embedding?.ready ? 'remote ready' : 'local fallback' }}</p>
              <div class="admin-model-test-result" :class="modelConfig.embedding?.ready ? 'ok' : 'failed'">
                {{ modelConfig.embedding?.warning || 'Embedding 状态未知' }}
              </div>
              <span>Reranker</span>
              <strong>{{ modelConfig.reranker?.enabled ? (modelConfig.reranker?.model || modelConfig.model || 'deepseek-chat') : '未启用' }}</strong>
              <p>{{ modelConfig.reranker?.enabled ? `候选 ${modelConfig.reranker?.max_candidates || 24} · ${modelConfig.reranker?.ready ? 'ready' : '等待 API Key'}` : '当前使用规则精排' }}</p>
              <div class="admin-model-test-result" :class="modelConfig.reranker?.enabled ? (modelConfig.reranker?.ready ? 'ok' : 'failed') : 'idle'">
                {{ modelConfig.reranker?.warning || 'Reranker 状态未知' }}
              </div>
              <div class="admin-model-test-result" :class="modelTestStatus">
                {{ modelTestMessage || '保存后可分别测试聊天模型和 Embedding。' }}
              </div>
              <p class="admin-model-helper">API Key 不会明文回显；更换 embedding 后请重建向量库。</p>
            </aside>
          </div>
        </section>

        <section class="admin-panel-card admin-search-test-panel">
          <header class="admin-section-header">
            <div>
              <h3>检索诊断</h3>
              <p>用管理员权限测试一次问题的召回、过滤、PageIndex 补充和 rerank 结果。</p>
            </div>
            <el-button :disabled="searchTesting" @click="runSearchTest">
              {{ searchTesting ? '测试中…' : '运行检索测试' }}
            </el-button>
          </header>

          <div class="admin-form-row admin-form-row-wrap">
            <el-input v-model="searchTestForm.question" clearable placeholder="输入一个要诊断的知识库问题" class="admin-input-search" @keyup.enter="runSearchTest" />
            <el-input-number v-model="searchTestForm.top_k" :min="1" :max="20" />
          </div>

          <div v-if="searchTestResult" class="admin-search-test-result">
            <div class="admin-search-test-meta">
              <span>Backend: <strong>{{ searchTestResult.retrieval_backend || '-' }}</strong></span>
              <span>Candidates: <strong>{{ searchTestResult.candidate_count ?? 0 }}</strong></span>
              <span>Sources: <strong>{{ searchTestResult.source_count ?? 0 }}</strong></span>
              <span>Confidence: <strong>{{ formatRetrievalScore(searchTestResult.confidence) }}</strong></span>
            </div>
            <p v-if="searchTestResult.retrieval_note" class="admin-model-helper">{{ searchTestResult.retrieval_note }}</p>

            <div class="admin-router-diagnostics">
              <article class="admin-router-diagnostic-card">
                <span>Query Analysis</span>
                <strong>{{ routerAnalysis.intent || '-' }} · {{ formatRetrievalScore(routerAnalysis.confidence) }}</strong>
                <p>实体：{{ formatDiagnosticList(routerAnalysis.entities) || '无' }}</p>
                <p>原因：{{ formatDiagnosticList(routerAnalysis.reasons) || '无' }}</p>
              </article>
              <article class="admin-router-diagnostic-card">
                <span>Retrieval Route</span>
                <strong>{{ routerRoute.name || '-' }}</strong>
                <p>意图：{{ routerRoute.intent || '-' }}</p>
                <p>说明：{{ routerRoute.reason || '-' }}</p>
              </article>
              <article class="admin-router-diagnostic-card" :class="routerEvidence.sufficient === false ? 'is-warning' : ''">
                <span>Evidence Check</span>
                <strong>{{ routerEvidence.sufficient === false ? '不足' : '通过' }}</strong>
                <p>{{ routerEvidence.reason || '-' }}</p>
                <p>来源 {{ routerEvidence.source_count ?? 0 }} · 文档 {{ routerEvidence.document_count ?? 0 }}</p>
              </article>
              <article class="admin-router-diagnostic-card" :class="tableQueryDiagnostics.hasTableSignals ? '' : 'is-muted'">
                <span>Table Query</span>
                <strong>{{ tableQueryDiagnostics.summary }}</strong>
                <p>解释：{{ tableQueryDiagnostics.explanation?.summary || '无' }}</p>
                <p>操作：{{ tableQueryDiagnostics.query_op || '无' }}</p>
                <p>过滤：{{ formatTableFilters(tableQueryDiagnostics.value_filters, tableQueryDiagnostics.filter_logic, tableQueryDiagnostics.filter_groups) || '无' }}</p>
                <p>展示：{{ formatDiagnosticList(tableQueryDiagnostics.select_columns) || '默认字段' }}</p>
                <p>聚合：{{ tableQueryDiagnostics.aggregate_op || '无' }} · 指标：{{ tableQueryDiagnostics.measure_column || '无' }}</p>
                <p>排序：{{ tableQueryDiagnostics.sort_by || '默认' }} · 展开：{{ tableQueryDiagnostics.limit || '默认' }}</p>
                <p>映射：{{ formatTableSchema(tableQueryDiagnostics.table_schema) || '无' }}</p>
                <p>分组：{{ tableQueryDiagnostics.group_by || '无' }} · 去重：{{ tableQueryDiagnostics.distinct_by || '无' }}</p>
              </article>
            </div>

            <div class="admin-search-test-meta-grid">
              <div v-for="(value, key) in flattenedRetrievalMeta" :key="String(key)">
                <span>{{ key }}</span>
                <strong>{{ formatDiagnosticValue(value) }}</strong>
              </div>
            </div>

            <div class="admin-doc-list">
              <article v-for="item in searchTestResult.source_diagnostics || []" :key="`${item.rank}-${item.document_id}-${item.chunk_id || item.chunk_index}`" class="admin-doc-card-row">
                <div class="admin-doc-card-main">
                  <div class="admin-doc-card-head">
                    <div>
                      <strong>#{{ item.rank }} {{ item.document_title }}</strong>
                      <span>{{ item.filename || item.document_id }}</span>
                    </div>
                    <span :class="['admin-status-pill', item.pageindex_source ? 'processing' : 'ready']">
                      {{ item.retrieval_channel || (item.pageindex_source ? 'pageindex' : 'semantic') }}
                    </span>
                  </div>
                  <p>{{ item.preview || '暂无片段预览' }}</p>
                  <div class="admin-doc-card-meta">
                    <span>score {{ formatRetrievalScore(item.score) }}</span>
                    <span>rerank {{ formatRetrievalScore(item.rerank_score) }}</span>
                    <span v-if="item.llm_rerank_score !== undefined && item.llm_rerank_score !== null">llm {{ formatRetrievalScore(item.llm_rerank_score) }}</span>
                    <span>{{ item.location || `chunk ${item.chunk_index ?? '-'}` }}</span>
                  </div>
                </div>
                <aside class="admin-doc-card-side">
                  <div class="admin-doc-permission-box">
                    <span>命中说明</span>
                    <strong>{{ item.match_reason || '未返回命中说明' }}</strong>
                  </div>
                  <div v-if="item.llm_rerank_reason" class="admin-doc-permission-box">
                    <span>LLM 精排</span>
                    <strong>{{ item.llm_rerank_reason }}</strong>
                  </div>
                  <div v-if="item.match_terms?.length" class="admin-chip-list">
                    <li v-for="term in item.match_terms.slice(0, 8)" :key="term">{{ term }}</li>
                  </div>
                </aside>
              </article>
            </div>
            <div v-if="!(searchTestResult.source_diagnostics || []).length" class="admin-dialog-empty">没有命中可展示片段。</div>
          </div>
        </section>
      </el-tab-pane>
    </el-tabs>

    <el-drawer
      v-model="pageIndexDialogVisible"
      title="高级结构索引"
      direction="rtl"
      size="min(760px, calc(100vw - 32px))"
      class="admin-pageindex-drawer"
    >
      <div v-if="pageIndexLoading" class="admin-dialog-empty">正在加载高级索引…</div>
      <div v-else class="admin-pageindex-drawer-body">
        <div class="admin-pageindex-drawer-meta">
          <span>当前文档</span>
          <strong>{{ docTitle(pageIndexDoc) }}</strong>
          <p>{{ docFilename(pageIndexDoc) }}</p>
        </div>
        <p class="admin-index-note dialog-note">{{ pageIndexStatusText(pageIndexPayload?.page_index) }}</p>
        <div class="admin-tree-stack">
          <el-card v-for="node in pageIndexFlatNodes" :key="node.key" class="source-card admin-tree-card">
            <strong>{{ node.indent }}{{ node.title }}</strong>
            <p>{{ node.summary || '暂无摘要' }}</p>
          </el-card>
        </div>
        <div v-if="!pageIndexFlatNodes.length" class="admin-dialog-empty">暂无结构树。可点击“重建高级索引”。</div>
      </div>
    </el-drawer>

    <el-drawer
      v-model="chunkEditorVisible"
      title="修改索引片段"
      direction="rtl"
      size="min(860px, calc(100vw - 32px))"
      class="admin-pageindex-drawer admin-chunk-editor-drawer"
    >
      <div v-if="chunkEditorLoading" class="admin-dialog-empty">正在加载文档片段…</div>
      <div v-else class="admin-pageindex-drawer-body">
        <div class="admin-pageindex-drawer-meta">
          <span>当前文档</span>
          <strong>{{ docTitle(chunkEditorDoc) }}</strong>
          <p>{{ docFilename(chunkEditorDoc) }}</p>
        </div>
        <p class="admin-index-note dialog-note">修改普通索引片段后，系统会同步更新向量；如果 PageIndex 已构建，会提示你重建高级索引。</p>
        <div v-if="chunkEditorChunks.length" class="admin-chunk-editor-list">
          <article v-for="chunk in chunkEditorChunks" :key="chunk.id" class="admin-chunk-editor-card">
            <div class="admin-chunk-editor-head">
              <strong>片段 {{ chunk.chunk_index }}</strong>
              <span>页码 {{ chunk.page_number || '未知' }}</span>
            </div>
            <el-input
              v-model="chunk.content"
              type="textarea"
              :autosize="{ minRows: 5, maxRows: 12 }"
              placeholder="编辑这个索引片段的文本内容"
            />
            <div class="admin-chunk-editor-actions">
              <span>{{ chunk.content.length }} 字</span>
              <el-button size="small" type="primary" :disabled="savingChunkId === chunk.id" @click="saveChunk(chunk)">
                {{ savingChunkId === chunk.id ? '保存中…' : '保存片段' }}
              </el-button>
            </div>
          </article>
        </div>
        <div v-else class="admin-dialog-empty">暂无可编辑片段。可以重新解析文档或检查解析状态。</div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../../api'

const groups = ref<any[]>([])
const users = ref<any[]>([])
const docs = ref<any[]>([])
const pageIndexStatus = ref<any | null>(null)
const modelConfig = ref<any>({
  base_url: 'https://api.deepseek.com',
  model: 'deepseek-chat',
  api_key_set: false,
  embedding: { provider: 'local', model: 'local-hash', base_url: '', api_key_set: false, ready: false, using_local_hash: true, warning: '' },
  reranker: { enabled: false, model: 'deepseek-chat', max_candidates: 24, ready: false, warning: '' },
})
const tasks = ref<any[]>([])
const docGroupMap = reactive<Record<string, string[]>>({})
const groupName = ref('')
const user = reactive({ username: '', password: '', is_admin: false, group_ids: [] as string[] })
type DocStatusFilter = 'all' | 'ready' | 'processing' | 'waiting' | 'failed'
type UserRoleFilter = 'all' | 'admin' | 'member' | 'unassigned'
type TaskStatusFilter = 'all' | 'pending' | 'running' | 'done' | 'failed'
type TaskTypeFilter = 'all' | 'document_parse' | 'document_reparse' | 'chat_attachment_parse' | 'page_index' | 'page_index_rebuild' | 'ocr' | 'other'
type EditableChunk = { id: string; page_number?: number | null; chunk_index?: number | string | null; content: string }
type UploadSummary = { docId: string; taskId?: string | null; title?: string; filename?: string; status?: string; message?: string; error?: string; searchable?: boolean }

const adminTabIndex = ref('groups')
const pageIndexDialogVisible = ref(false)
const pageIndexLoading = ref(false)
const pageIndexPayload = ref<any | null>(null)
const pageIndexDoc = ref<any | null>(null)
const chunkEditorVisible = ref(false)
const chunkEditorLoading = ref(false)
const chunkEditorDoc = ref<any | null>(null)
const chunkEditorChunks = ref<EditableChunk[]>([])
const savingChunkId = ref<string | null>(null)
const openingDocId = ref<string | null>(null)
const reparsingDocId = ref<string | null>(null)
const deletingDocId = ref<string | null>(null)
const rebuildingPageIndexDocId = ref<string | null>(null)
const uploadingDoc = ref(false)
const lastUploadSummary = ref<UploadSummary | null>(null)
const groupSearch = ref('')
const userSearch = ref('')
const userRoleFilter = ref<UserRoleFilter>('all')
const docSearch = ref('')
const docStatusFilter = ref<DocStatusFilter>('all')
const taskStatusFilter = ref<TaskStatusFilter>('all')
const taskTypeFilter = ref<TaskTypeFilter>('all')
const taskSearch = ref('')
const loadingTasks = ref(false)
const retryingTaskId = ref<string | null>(null)
const refreshing = ref(false)
const lastRefreshAt = ref<Date | null>(null)
const statusPolling = ref(false)
let statusPollTimer: number | null = null
let statusPollDeadline = 0
const STATUS_POLL_INTERVAL_MS = 3000
const STATUS_POLL_TIMEOUT_MS = 5 * 60 * 1000
const modelForm = reactive({
  base_url: 'https://api.deepseek.com',
  model: 'deepseek-chat',
  api_key: '',
  embedding_provider: 'local',
  embedding_base_url: '',
  embedding_model: 'local-hash',
  embedding_api_key: '',
  reranker_enabled: false,
  reranker_model: '',
  reranker_max_candidates: 24,
})
const savingModel = ref(false)
const testingModel = ref(false)
const modelTestMessage = ref('')
const modelTestStatus = ref<'idle' | 'ok' | 'failed'>('idle')
const searchTestForm = reactive({ question: '', top_k: 8 })
const searchTesting = ref(false)
const searchTestResult = ref<any | null>(null)
const routerAnalysis = computed(() => searchTestResult.value?.query_analysis || searchTestResult.value?.retrieval_meta?.query_analysis || {})
const routerRoute = computed(() => searchTestResult.value?.retrieval_route || searchTestResult.value?.retrieval_meta?.retrieval_route || {})
const routerEvidence = computed(() => searchTestResult.value?.evidence_check || searchTestResult.value?.retrieval_meta?.evidence_check || {})
const tableQueryDiagnostics = computed(() => {
  const meta = searchTestResult.value?.retrieval_meta || {}
  const plan = meta.table_query_plan || {}
  const valueFilters = Array.isArray(plan.filters) ? plan.filters : (Array.isArray(meta.value_filters) ? meta.value_filters : [])
  const filterLogic = plan.filter_logic || meta.filter_logic || 'and'
  const filterGroups = Array.isArray(plan.filter_groups) ? plan.filter_groups : (Array.isArray(meta.filter_groups) ? meta.filter_groups : [])
  const groupBy = plan.group_by || meta.group_by || ''
  const distinctBy = plan.distinct_by || meta.distinct_by || ''
  const queryOp = plan.query_op || meta.query_op || ''
  const aggregateOp = plan.aggregate_op || meta.aggregate_op || ''
  const measureColumn = plan.measure_column || meta.measure_column || ''
  const selectColumns = Array.isArray(plan.select_columns) ? plan.select_columns : (Array.isArray(meta.select_columns) ? meta.select_columns : [])
  const sortBy = plan.sort_by || meta.sort_by || ''
  const limit = plan.limit || meta.limit || ''
  const explanation = meta.table_query_explanation || {}
  const tableSchema = meta.table_schema || {}
  return {
    value_filters: valueFilters,
    filter_logic: filterLogic,
    filter_groups: filterGroups,
    group_by: groupBy,
    distinct_by: distinctBy,
    select_columns: selectColumns,
    table_schema: tableSchema,
    explanation,
    query_op: queryOp,
    aggregate_op: aggregateOp,
    measure_column: measureColumn,
    sort_by: sortBy,
    limit,
    matched_rows: meta.value_filter_matched_rows,
    hasTableSignals: valueFilters.length > 0 || Boolean(groupBy) || Boolean(distinctBy) || Boolean(aggregateOp) || selectColumns.length > 0 || Boolean(sortBy) || Boolean(limit) || Boolean(queryOp),
    summary: explanation.summary || (valueFilters.length > 0 || groupBy || distinctBy || aggregateOp || selectColumns.length > 0 || sortBy || limit || queryOp
      ? `${valueFilters.length} filters · ${meta.value_filter_matched_rows ?? '-'} rows`
      : '未识别结构化条件'),
  }
})
const flattenedRetrievalMeta = computed(() => {
  const meta = { ...(searchTestResult.value?.retrieval_meta || {}) }
  delete meta.query_analysis
  delete meta.retrieval_route
  delete meta.evidence_check
  delete meta.value_filters
  delete meta.filter_logic
  delete meta.filter_groups
  delete meta.group_by
  delete meta.distinct_by
  delete meta.aggregate_op
  delete meta.measure_column
  delete meta.select_columns
  delete meta.sort_by
  delete meta.limit
  delete meta.table_schema
  delete meta.table_query_plan
  delete meta.table_query_explanation
  delete meta.query_op
  return meta
})

const pageIndexEngineText = computed(() => {
  if (!pageIndexStatus.value?.enabled) return '已关闭'
  if (pageIndexStatus.value?.official_available && !pageIndexStatus.value?.forced_lightweight) return '官方 PageIndex'
  return '轻量结构树兜底'
})
const pageIndexFlatNodes = computed(() => flattenPageIndexNodes(pageIndexPayload.value?.structure || []))
const lastRefreshLabel = computed(() => {
  if (!lastRefreshAt.value) return '未刷新'
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(lastRefreshAt.value)
})
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
const filteredTasks = computed(() => {
  const keyword = normalizeText(taskSearch.value).trim()
  return tasks.value.filter((task: any) => {
    if (taskStatusFilter.value !== 'all' && taskStatusKind(task) !== taskStatusFilter.value) return false
    if (taskTypeFilter.value !== 'all' && taskTypeKind(task) !== taskTypeFilter.value) return false
    if (!keyword) return true
    return taskMatchesSearch(task, keyword)
  })
})
const docReadyCount = computed(() => docs.value.filter((doc: any) => docStatusKind(doc) === 'ready').length)
const docProcessingCount = computed(() => docs.value.filter((doc: any) => docStatusKind(doc) === 'processing').length)
const docWaitingCount = computed(() => docs.value.filter((doc: any) => docStatusKind(doc) === 'waiting').length)
const docFailedCount = computed(() => docs.value.filter((doc: any) => docStatusKind(doc) === 'failed').length)
const userAdminCount = computed(() => users.value.filter((item: any) => item?.is_admin).length)
const userMemberCount = computed(() => users.value.filter((item: any) => !item?.is_admin && (item?.groups || []).length > 0).length)
const userUnassignedCount = computed(() => users.value.filter((item: any) => !(item?.groups || []).length).length)
const taskPendingCount = computed(() => tasks.value.filter((task: any) => taskStatusKind(task) === 'pending').length)
const taskRunningCount = computed(() => tasks.value.filter((task: any) => taskStatusKind(task) === 'running').length)
const taskDoneCount = computed(() => tasks.value.filter((task: any) => taskStatusKind(task) === 'done').length)
const taskFailedCount = computed(() => tasks.value.filter((task: any) => taskStatusKind(task) === 'failed').length)
const latestUploadDoc = computed(() => {
  const summary = lastUploadSummary.value
  if (!summary?.docId) return null
  return docs.value.find((doc: any) => String(doc.id) === String(summary.docId)) || null
})
const uploadSummaryStatusKind = computed<DocStatusFilter>(() => {
  const doc = latestUploadDoc.value as any
  if (doc) return docStatusKind(doc)
  const status = normalizeText(lastUploadSummary.value?.status || '')
  if (['ready'].includes(status)) return 'ready'
  if (['processing', 'running'].includes(status)) return 'processing'
  if (['failed', 'error'].includes(status) || lastUploadSummary.value?.error) return 'failed'
  return 'waiting'
})
const uploadSummaryStatusLabel = computed(() => {
  const doc = latestUploadDoc.value as any
  if (doc) {
    const kind = docStatusKind(doc)
    if (kind === 'ready') return '可检索'
    if (kind === 'processing') return '解析中'
    if (kind === 'failed') return '失败'
    if (normalizeText(doc?.stage || '') === 'queued' || normalizeText(doc?.status || '') === 'pending') return '已入队'
    return '等待中'
  }
  const status = normalizeText(lastUploadSummary.value?.status || '')
  return ({ queued: '已入队', pending: '等待中', processing: '解析中', running: '解析中', ready: '可检索', failed: '失败', error: '失败' } as Record<string, string>)[status] || '上传结果'
})
const uploadSummaryDetail = computed(() => {
  const doc = latestUploadDoc.value as any
  if (doc) {
    if (docStatusKind(doc) === 'failed') return doc.message || docDescription(doc) || '文档解析失败。'
    if (docStatusKind(doc) === 'processing') return doc.message || docDescription(doc) || '文档正在解析。'
    if (docStatusKind(doc) === 'ready') return doc.message || '文档已完成解析，可检索。'
    return doc.message || docDescription(doc) || '文档已进入后台处理。'
  }
  return lastUploadSummary.value?.error || lastUploadSummary.value?.message || '文档已上传，正在进入后台解析流程。'
})
const uploadSummaryProgressText = computed(() => {
  const doc = latestUploadDoc.value as any
  if (doc) {
    const kind = docStatusKind(doc)
    if (kind === 'ready') return '可检索'
    if (kind === 'processing') return '解析中'
    if (kind === 'failed') return '失败'
    return '已入队'
  }
  const status = normalizeText(lastUploadSummary.value?.status || '')
  if (status === 'ready') return '可检索'
  if (status === 'processing' || status === 'running') return '解析中'
  if (status === 'failed' || status === 'error') return '失败'
  return '已入队'
})

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

function taskStatusKind(task: any): TaskStatusFilter {
  const status = normalizeText(task?.status || '')
  if (status === 'running' || status === 'processing') return 'running'
  if (status === 'done' || status === 'ready' || status === 'success' || status === 'completed') return 'done'
  if (status === 'failed' || status === 'error') return 'failed'
  return 'pending'
}

function taskStatusLabel(status?: string) {
  return ({ pending: '等待中', queued: '等待中', running: '执行中', processing: '执行中', done: '已完成', ready: '已完成', success: '已完成', completed: '已完成', failed: '失败', error: '失败' } as Record<string, string>)[normalizeText(status || '')] || status || '未知'
}

function taskTypeKind(task: any): TaskTypeFilter {
  const type = normalizeText(task?.task_type || '')
  if (type === 'document_parse') return 'document_parse'
  if (type === 'document_reparse') return 'document_reparse'
  if (type === 'chat_attachment_parse') return 'chat_attachment_parse'
  if (type === 'page_index') return 'page_index'
  if (type === 'page_index_rebuild') return 'page_index_rebuild'
  if (type === 'ocr') return 'ocr'
  return 'other'
}

function taskMatchesSearch(task: any, keyword: string) {
  const haystack = normalizeText([
    task?.id,
    task?.task_type,
    taskTypeLabel(task?.task_type),
    task?.document_title,
    task?.document_filename,
    task?.document_id,
    task?.status,
    taskStatusLabel(task?.status),
    task?.attempts,
    task?.last_error,
    task?.created_at,
    task?.started_at,
    task?.finished_at,
  ].join(' '))
  return haystack.includes(keyword)
}

function taskTypeCount(type: TaskTypeFilter) {
  if (type === 'all') return tasks.value.length
  return tasks.value.filter((task: any) => taskTypeKind(task) === type).length
}

function taskTypeLabel(type?: string) {
  return ({ document_parse: '文档解析', document_reparse: '重新解析', chat_attachment_parse: '聊天附件解析', page_index: '高级索引', page_index_rebuild: '重建高级索引', ocr: 'OCR 识别' } as Record<string, string>)[String(type || '')] || type || '后台任务'
}

function formatDateTime(value?: string | null) {
  if (!value) return '未知时间'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}

function docStageLabel(doc: any) {
  return stageText(doc?.stage)
}

function requestErrorDetail(err: any, fallback: string) {
  const detail = err?.response?.data?.detail || err?.response?.data?.message || err?.message || fallback
  const status = err?.response?.status
  return status ? `${detail}（HTTP ${status}）` : detail
}

async function load() {
  try {
    groups.value = (await http.get('/admin/groups')).data || []
    users.value = (await http.get('/admin/users')).data || []
    docs.value = (await http.get('/admin/documents')).data || []
    docs.value.forEach((d: any) => {
      docGroupMap[d.id] = (d.groups || []).map((g: any) => g.id)
    })
    await loadModelConfig()
    await loadTasks(false)
    await loadPageIndexStatus()
    lastRefreshAt.value = new Date()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载后台数据失败')
  }
}

async function refreshAllData() {
  refreshing.value = true
  try {
    await load()
    ElMessage.success('已刷新后台数据')
  } finally {
    refreshing.value = false
  }
}

async function loadDocumentStatus() {
  docs.value = (await http.get('/admin/documents')).data || []
  docs.value.forEach((d: any) => {
    docGroupMap[d.id] = (d.groups || []).map((g: any) => g.id)
  })
  await loadTasks(false)
  await loadPageIndexStatus()
  lastRefreshAt.value = new Date()
}

function removeDocumentFromLocalState(documentId: string) {
  const id = String(documentId || '')
  if (!id) return
  docs.value = docs.value.filter((item: any) => String(item?.id) !== id)
  tasks.value = tasks.value.filter((item: any) => String(item?.document_id) !== id)
  delete docGroupMap[id]
  if (lastUploadSummary.value?.docId && String(lastUploadSummary.value.docId) === id) lastUploadSummary.value = null
  if (pageIndexDoc.value?.id && String(pageIndexDoc.value.id) === id) {
    pageIndexDialogVisible.value = false
    pageIndexDoc.value = null
    pageIndexPayload.value = null
  }
  if (chunkEditorDoc.value?.id && String(chunkEditorDoc.value.id) === id) {
    chunkEditorVisible.value = false
    chunkEditorDoc.value = null
    chunkEditorChunks.value = []
  }
}

function hasActiveDocumentProcessing(documentId?: string) {
  const targetId = documentId ? String(documentId) : ''
  return docs.value.some((doc: any) => {
    if (targetId && String(doc?.id) !== targetId) return false
    return ['processing', 'waiting'].includes(docStatusKind(doc))
  })
}

function stopStatusPolling() {
  if (statusPollTimer) window.clearInterval(statusPollTimer)
  statusPollTimer = null
  statusPolling.value = false
  statusPollDeadline = 0
}

async function pollDocumentStatus(documentId?: string) {
  try {
    await loadDocumentStatus()
    if (!hasActiveDocumentProcessing(documentId) || Date.now() > statusPollDeadline) stopStatusPolling()
  } catch {
    if (Date.now() > statusPollDeadline) stopStatusPolling()
  }
}

function startStatusPolling(documentId?: string) {
  statusPollDeadline = Date.now() + STATUS_POLL_TIMEOUT_MS
  statusPolling.value = true
  if (statusPollTimer) window.clearInterval(statusPollTimer)
  statusPollTimer = window.setInterval(() => pollDocumentStatus(documentId), STATUS_POLL_INTERVAL_MS)
}

function startStatusPollingIfNeeded() {
  if (hasActiveDocumentProcessing()) startStatusPolling()
}

function jumpToTab(name: string) {
  adminTabIndex.value = name
}

async function loadPageIndexStatus() {
  try {
    pageIndexStatus.value = (await http.get('/admin/page-index/status')).data || null
  } catch {
    pageIndexStatus.value = { enabled: false, status_detail: 'PageIndex 状态读取失败' }
  }
}
async function loadModelConfig() {
  try {
    const data = (await http.get('/admin/model')).data || {}
    modelConfig.value = data
    modelForm.base_url = data.base_url || 'https://api.deepseek.com'
    modelForm.model = data.model || 'deepseek-chat'
    modelForm.api_key = ''
    modelForm.embedding_provider = data.embedding?.provider || 'local'
    modelForm.embedding_base_url = data.embedding?.base_url || ''
    modelForm.embedding_model = data.embedding?.model || 'local-hash'
    modelForm.embedding_api_key = ''
    modelForm.reranker_enabled = Boolean(data.reranker?.enabled)
    modelForm.reranker_model = data.reranker?.model || ''
    modelForm.reranker_max_candidates = Number(data.reranker?.max_candidates) || 24
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载模型配置失败')
  }
}
async function saveModelConfig() {
  savingModel.value = true
  modelTestStatus.value = 'idle'
  modelTestMessage.value = ''
  try {
    await http.put('/admin/model', { ...modelForm })
    ElMessage.success('模型配置已保存')
    await loadModelConfig()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '保存模型配置失败')
  } finally {
    savingModel.value = false
  }
}
async function testModelConnection() {
  testingModel.value = true
  modelTestStatus.value = 'idle'
  modelTestMessage.value = '正在测试模型连接…'
  try {
    const data = (await http.post('/admin/model/test')).data || {}
    modelTestStatus.value = data.ok ? 'ok' : 'failed'
    modelTestMessage.value = data.message || (data.ok ? '连接成功' : '连接失败')
  } catch (err: any) {
    modelTestStatus.value = 'failed'
    modelTestMessage.value = err?.response?.data?.detail || '测试连接失败'
  } finally {
    testingModel.value = false
  }
}

async function testEmbeddingConnection() {
  testingModel.value = true
  modelTestStatus.value = 'idle'
  modelTestMessage.value = '正在测试 Embedding 连接…'
  try {
    const data = (await http.post('/admin/model/embedding-test')).data || {}
    modelTestStatus.value = data.ok ? 'ok' : 'failed'
    modelTestMessage.value = data.message || (data.ok ? 'Embedding 连接成功' : 'Embedding 连接失败')
  } catch (err: any) {
    modelTestStatus.value = 'failed'
    modelTestMessage.value = err?.response?.data?.detail || 'Embedding 测试失败'
  } finally {
    testingModel.value = false
  }
}

function formatRetrievalScore(value: any) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '-'
  return num.toFixed(4)
}

function formatDiagnosticList(value: any) {
  if (!Array.isArray(value)) return ''
  return value.filter(Boolean).slice(0, 8).join('、')
}

function formatDiagnosticValue(value: any) {
  if (Array.isArray(value)) return value.join('、') || '-'
  if (value && typeof value === 'object') return JSON.stringify(value)
  if (value === true) return 'true'
  if (value === false) return 'false'
  return value ?? '-'
}

function formatTableFilters(value: any, logic = 'and', groups: any = []) {
  if (!Array.isArray(value) || !value.length) return ''
  const opLabels: Record<string, string> = {
    eq: '=',
    ne: '!=',
    contains: '包含',
    not_contains: '不包含',
    is_empty: '为空',
    is_not_empty: '非空',
    gt: '>',
    gte: '>=',
    lt: '<',
    lte: '<=',
  }
  const formatOne = (item: any) => {
    const op = item?.operator || 'contains'
    const label = opLabels[op] || op
    if (op === 'is_empty' || op === 'is_not_empty') return `${item?.column || 'field'} ${label}`
    return `${item?.column || 'field'} ${label} ${item?.value ?? ''}`
  }
  if (logic === 'or' && Array.isArray(groups) && groups.length) {
    return groups
      .map((group: any) => Array.isArray(group) ? group.map(formatOne).filter(Boolean).join(' 且 ') : '')
      .filter(Boolean)
      .slice(0, 4)
      .join('；或 ')
  }
  return value
    .map(formatOne)
    .filter(Boolean)
    .slice(0, 6)
    .join('；')
}

function formatTableSchema(value: any) {
  if (!value || typeof value !== 'object') return ''
  const entries = Object.values(value)
    .flatMap((items: any) => Array.isArray(items) ? items : [])
    .map((item: any) => `${item?.semantic_name || item?.label || 'field'}=${item?.raw_name || '-'}`)
    .filter(Boolean)
  return [...new Set(entries)].slice(0, 8).join('；')
}

async function runSearchTest() {
  const question = searchTestForm.question.trim()
  if (!question) {
    ElMessage.warning('请输入要测试的检索问题')
    return
  }
  searchTesting.value = true
  searchTestResult.value = null
  try {
    const { data } = await http.post('/admin/search-test', {
      question,
      top_k: Number(searchTestForm.top_k) || 8,
    })
    searchTestResult.value = data || null
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '检索测试失败')
  } finally {
    searchTesting.value = false
  }
}
async function loadTasks(showMessage = true) {
  loadingTasks.value = true
  try {
    tasks.value = (await http.get('/admin/tasks', { params: { limit: 500 } })).data || []
    if (showMessage) ElMessage.success('后台任务已刷新')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载后台任务失败')
  } finally {
    loadingTasks.value = false
  }
}
async function retryTask(task: any) {
  if (!task?.id) return
  retryingTaskId.value = task.id
  try {
    await http.post(`/admin/tasks/${task.id}/retry`)
    ElMessage.success('任务已重新入队')
    await loadTasks(false)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '重试任务失败')
  } finally {
    retryingTaskId.value = null
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
  const rawFile = file?.raw
  if (!rawFile) return
  uploadingDoc.value = true
  const fd = new FormData()
  fd.append('file', rawFile)
  try {
    const data = (await http.post('/admin/documents', fd, { headers: { 'Content-Type': 'multipart/form-data' } })).data || {}
    lastUploadSummary.value = {
      docId: String(data.id || ''),
      taskId: data.task_id || null,
      title: data.title || rawFile.name,
      filename: rawFile.name,
      status: data.status || 'queued',
      message: data.message || '文档已上传，正在进入后台解析流程。',
      searchable: Boolean(data.searchable),
    }
    if (data.id && !docs.value.some((doc: any) => String(doc.id) === String(data.id))) {
      docs.value = [{
        id: data.id,
        title: data.title || rawFile.name,
        filename: rawFile.name,
        source_type: rawFile.name.split('.').pop() || 'file',
        groups: [],
        status: data.status || 'pending',
        stage: 'queued',
        message: data.message || '文档已上传，正在后台解析。',
        chunks: 0,
        searchable: Boolean(data.searchable),
        created_at: new Date().toISOString(),
      }, ...docs.value]
      docGroupMap[data.id] = []
    }
    ElMessage.success('文档上传并已进入解析队列')
    if (lastUploadSummary.value?.docId) startStatusPolling(lastUploadSummary.value.docId)
    await load()
    await nextTick()
    if (lastUploadSummary.value?.docId) {
      document.getElementById(`admin-doc-${lastUploadSummary.value.docId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  } catch (err: any) {
    const rawDetail = err?.response?.data?.detail || err?.message || '文档上传失败'
    const detail = /服务器内部错误|timeout|locked|busy/i.test(rawDetail)
      ? '上传失败：后台正在处理其他文档或数据库繁忙，请稍后重试；如果刚才已上传成功，可点“刷新状态”查看。'
      : rawDetail
    lastUploadSummary.value = {
      docId: '',
      title: rawFile.name,
      filename: rawFile.name,
      status: 'failed',
      message: detail,
      error: detail,
      searchable: false,
    }
    ElMessage.error(detail)
  } finally {
    uploadingDoc.value = false
  }
}
async function saveDocPermission(documentId: string) {
  await http.put(`/admin/documents/${documentId}/permissions`, { group_ids: docGroupMap[documentId] || [] })
  ElMessage.success('文档权限已保存')
}

function docFileExtension(doc: any) {
  const name = docFilename(doc).split('?')[0].split('#')[0]
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : ''
}

function canPreviewDocumentInBrowser(doc: any, contentType = '') {
  const ext = docFileExtension(doc)
  const type = String(contentType || '').toLowerCase()
  if (['pdf', 'txt', 'md', 'markdown', 'csv', 'png', 'jpg', 'jpeg', 'webp', 'gif'].includes(ext)) return true
  return type.startsWith('text/') || type.includes('pdf') || type.startsWith('image/')
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

async function openAdminDocument(doc: any) {
  if (!doc?.id) return
  openingDocId.value = doc.id
  try {
    const response = await http.get(`/documents/${doc.id}/view`, { responseType: 'blob' })
    const contentType = response.headers['content-type'] || 'application/octet-stream'
    const blob = new Blob([response.data], { type: contentType })
    const objectUrl = URL.createObjectURL(blob)
    const name = filenameFromDisposition(response.headers['content-disposition']) || docFilename(doc)
    if (canPreviewDocumentInBrowser(doc, contentType)) {
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
    ElMessage.error(err?.response?.data?.detail || '打开原文失败，请确认文档仍存在且你有权限访问。')
  } finally {
    openingDocId.value = null
  }
}

async function reparseDocument(doc: any) {
  if (!doc?.id) return
  try {
    await ElMessageBox.confirm(`重新解析「${docTitle(doc)}」会重新生成片段和索引任务，确定继续？`, '重新解析文档', {
      confirmButtonText: '重新解析',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  reparsingDocId.value = doc.id
  try {
    await http.post(`/admin/documents/${doc.id}/reparse`)
    ElMessage.success('文档已进入重新解析队列')
    await load()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '重新解析失败')
  } finally {
    reparsingDocId.value = null
  }
}

async function deleteDocument(doc: any) {
  if (!doc?.id) return
  try {
    await ElMessageBox.confirm(`删除「${docTitle(doc)}」会同时移除片段、索引、权限配置和后台任务关联，确定删除？`, '删除文档', {
      confirmButtonText: '删除文档',
      cancelButtonText: '取消',
      type: 'error',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }
  deletingDocId.value = doc.id
  try {
    const { data } = await http.delete(`/admin/documents/${doc.id}`)
    removeDocumentFromLocalState(String(doc.id))
    ElMessage.success(data?.warning || '文档已删除')
    try {
      await load()
    } catch {
      // 本地状态已同步移除；静默刷新失败时不把已删除文档重新展示出来。
    }
  } catch (err: any) {
    if (err?.response?.status === 404) removeDocumentFromLocalState(String(doc.id))
    ElMessage.error(requestErrorDetail(err, '删除文档失败'))
  } finally {
    deletingDocId.value = null
  }
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
  pageIndexPayload.value = null
  try {
    pageIndexPayload.value = (await http.get(`/admin/documents/${doc.id}/page-index`)).data || null
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载高级索引失败')
  } finally {
    pageIndexLoading.value = false
  }
}
async function rebuildDocumentPageIndex(doc: any) {
  if (!doc?.id) return
  rebuildingPageIndexDocId.value = doc.id
  try {
    await http.post(`/admin/documents/${doc.id}/page-index/rebuild`)
    ElMessage.success('高级索引已重建')
    if (pageIndexDialogVisible.value && pageIndexDoc.value?.id === doc.id) await openDocumentPageIndex(doc)
    await load()
  } catch (err: any) {
    if (err?.response?.status === 404) removeDocumentFromLocalState(String(doc.id))
    ElMessage.error(requestErrorDetail(err, '重建高级索引失败'))
  } finally {
    rebuildingPageIndexDocId.value = null
  }
}
async function openChunkEditor(doc: any) {
  chunkEditorDoc.value = doc
  chunkEditorVisible.value = true
  chunkEditorLoading.value = true
  chunkEditorChunks.value = []
  try {
    const data = (await http.get(`/admin/documents/${doc.id}/chunks`)).data || {}
    chunkEditorChunks.value = (data.chunks || []).map((chunk: any) => ({
      id: String(chunk.id),
      page_number: chunk.page_number,
      chunk_index: chunk.chunk_index,
      content: String(chunk.content || ''),
    }))
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载索引片段失败')
  } finally {
    chunkEditorLoading.value = false
  }
}
async function saveChunk(chunk: EditableChunk) {
  if (!chunkEditorDoc.value?.id || !chunk.id) return
  const content = String(chunk.content || '').trim()
  if (!content) {
    ElMessage.error('片段内容不能为空')
    return
  }
  savingChunkId.value = chunk.id
  try {
    const data = (await http.put(`/admin/documents/${chunkEditorDoc.value.id}/chunks/${chunk.id}`, { content })).data || {}
    chunk.content = content
    ElMessage.success(data.message || '片段已保存')
    await load()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '保存片段失败')
  } finally {
    savingChunkId.value = null
  }
}
function statusText(status?: string) {
  return ({ ready: '可检索', processing: '处理中', failed: '失败', pending: '等待', queued: '已排队' } as Record<string, string>)[status || ''] || status || '未知'
}
function stageText(stage?: string) {
  return ({ uploaded: '已上传', queued: '等待队列', worker: '任务执行中', vision_ocr: '图片 OCR', pdf_text_extract: 'PDF 解析', pdf_vision_ocr: 'PDF 视觉 OCR', word_text_extract: 'Word 解析', pptx_text_extract: 'PPTX 解析', spreadsheet_extract: '表格解析', csv_extract: 'CSV 解析', text_extract: '文本解析', markdown_extract: 'Markdown 解析', indexed: '已索引', need_ocr: '需要 OCR', parse_error: '解析失败', file_missing: '文件缺失' } as Record<string, string>)[stage || ''] || stage || '未知阶段'
}

onMounted(async () => {
  document.documentElement.classList.add('admin-scroll-page')
  document.body.classList.add('admin-scroll-page')
  await load()
  startStatusPollingIfNeeded()
})
onUnmounted(() => {
  stopStatusPolling()
  document.documentElement.classList.remove('admin-scroll-page')
  document.body.classList.remove('admin-scroll-page')
})
</script>
