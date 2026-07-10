<template>
  <div class="admin-page admin-chatgpt-page">
    <header class="admin-hero">
      <div>
        <span class="admin-eyebrow">Knowledge Admin</span>
        <h2>后台管理</h2>
        <p>管理岗位组、员工账号、文档权限、后台任务和模型配置。</p>
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

      <article class="admin-stat-card wide" :class="{ 'admin-stat-card-warning': vectorStatus?.degraded }">
        <span>向量库状态</span>
        <strong>{{ vectorStatusLabel }}</strong>
        <small>{{ vectorBackendLabel }} · {{ vectorRetrievalLabel }}</small>
        <small>{{ vectorStatusImpact }}</small>
      </article>
    </section>

    <section class="admin-quickbar" aria-label="后台快捷操作">
      <div class="admin-quickbar-group">
        <button type="button" class="admin-quickbar-btn" :disabled="refreshing" @click="refreshAllData">{{ refreshing ? '刷新中…' : '刷新数据' }}</button>
        <button type="button" :class="['admin-quickbar-btn', { active: adminTabIndex === 'groups' }]" @click="jumpToTab('groups')">岗位组</button>
        <button type="button" :class="['admin-quickbar-btn', { active: adminTabIndex === 'users' }]" @click="jumpToTab('users')">员工</button>
        <button type="button" :class="['admin-quickbar-btn', { active: adminTabIndex === 'docs' }]" @click="jumpToTab('docs')">文档与权限</button>

        <button type="button" :class="['admin-quickbar-btn', { active: adminTabIndex === 'model' }]" @click="jumpToTab('model')">模型配置</button>
        <button type="button" :class="['admin-quickbar-btn', { active: adminTabIndex === 'feedback' }]" @click="jumpToTab('feedback')">反馈管理</button>
        <button type="button" :class="['admin-quickbar-btn', { active: adminTabIndex === 'evaluation' }]" @click="jumpToTab('evaluation')">评测面板</button>
        <button type="button" :class="['admin-quickbar-btn', { active: adminTabIndex === 'operations' }]" @click="jumpToTab('operations')">运营中心</button>
        <button type="button" :class="['admin-quickbar-btn', { active: adminTabIndex === 'wiki' }]" @click="jumpToTab('wiki')">Wiki管理</button>
        <button type="button" :class="['admin-quickbar-btn', { active: adminTabIndex === 'wikiGraph' }]" @click="jumpToTab('wikiGraph')">Wiki图谱</button>
        <button type="button" :class="['admin-quickbar-btn', { active: adminTabIndex === 'graph' }]" @click="jumpToTab('graph')">图谱管理</button>
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
              <div class="admin-row-actions admin-group-card-actions">
                <el-button link type="danger" :loading="deletingGroupId === g.id" @click="deleteGroup(g)">删除岗位组</el-button>
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
              <h3>本地员工管理</h3>
              <p>创建本地员工账号并分配岗位组；员工来源、岗位组和权限均由本系统独立管理。</p>
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
              <button :class="{ active: userRoleFilter === 'pending' }" type="button" @click="userRoleFilter = 'pending'">
                待审批 {{ userPendingCount }}
              </button>
              <button :class="{ active: userRoleFilter === 'inactive' }" type="button" @click="userRoleFilter = 'inactive'">
                停用/拒绝 {{ userInactiveCount }}
              </button>
            </div>
            <div class="admin-list-summary admin-user-summary">当前显示 {{ filteredUsers.length }} / {{ users.length }} 名员工</div>
          </div>
          <div class="admin-form-row admin-form-row-wrap">
            <el-input v-model="user.username" placeholder="员工账号" class="admin-input-sm" />
            <el-input v-model="user.password" placeholder="密码" class="admin-input-sm" />
            <el-select v-model="user.group_ids" multiple placeholder="所属岗位组" class="admin-select-md">
              <el-option v-for="g in groups" :key="g.id" :label="g.name" :value="g.id" />
            </el-select>
            <el-checkbox v-model="user.is_admin">管理员</el-checkbox>
            <el-button type="primary" @click="createUser">新增员工</el-button>
            <span class="admin-model-helper">本地账号仅使用系统用户名登录；岗位组由本系统独立维护。</span>
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
            <el-table-column label="状态" width="120">
              <template #default="scope">
                <span :class="['admin-status-pill', scope.row.is_active ? 'ready' : 'waiting']">{{ scope.row.is_active ? '已启用' : '未启用' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="审批" width="150">
              <template #default="scope">
                <span :class="['admin-status-pill', userApprovalKind(scope.row)]">{{ userApprovalLabel(scope.row) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="岗位组" min-width="260">
              <template #default="scope">{{ userGroupsText(scope.row) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="180">
              <template #default="scope">
                <el-button v-if="isUserPending(scope.row)" link type="primary" @click="openApprovalDialog(scope.row)">审批</el-button>
                <el-button v-else link type="primary" @click="toggleUserStatus(scope.row)">{{ scope.row.is_active ? '停用' : '启用' }}</el-button>
              </template>
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
            <el-upload multiple :auto-upload="false" :show-file-list="false" :on-change="handleFile" :disabled="uploadingDoc">
              <el-button type="primary" :loading="uploadingDoc">{{ uploadingDoc ? '上传中…' : '选择文件上传（可多选）' }}</el-button>
            </el-upload>
          </header>

          <div class="admin-upload-note">
            <span>支持 PDF / Markdown / Word / Excel / PPT / CSV / TXT / 图片</span>
            <span>上传后自动解析、分类并写入 Wiki 与向量索引。</span>
          </div>
          <div class="admin-form-row admin-form-row-wrap">
            <label class="admin-search-box">
              <span>上传到</span>
              <el-select v-model="uploadKnowledgeScope" class="admin-select-md">
                <el-option label="正式库（默认问答使用）" value="production" />
                <el-option label="测试库（仅诊断/评测使用）" value="test" />
              </el-select>
            </label>
            <span class="admin-model-helper">文档类型由系统自动识别；只有低置信度文档需要人工复核。</span>
          </div>

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
            <div class="admin-filter-row" aria-label="文档体检筛选">
              <button :class="{ active: docQualityFilter === 'all' }" type="button" @click="docQualityFilter = 'all'">
                全部体检 {{ docs.length }}
              </button>
              <button :class="{ active: docQualityFilter === 'good' }" type="button" @click="docQualityFilter = 'good'">
                状态良好 {{ docQualityCounts.good }}
              </button>
              <button :class="{ active: docQualityFilter === 'needs_review' }" type="button" @click="docQualityFilter = 'needs_review'">
                需要复核 {{ docQualityCounts.needs_review }}
              </button>
              <button :class="{ active: docQualityFilter === 'poor' }" type="button" @click="docQualityFilter = 'poor'">
                质量较差 {{ docQualityCounts.poor }}
              </button>
              <button :class="{ active: docQualityFilter === 'blocked' }" type="button" @click="docQualityFilter = 'blocked'">
                严重异常 {{ docQualityCounts.blocked }}
              </button>
              <button :class="{ active: docQualityFilter === 'unknown' }" type="button" @click="docQualityFilter = 'unknown'">
                未体检 {{ docQualityCounts.unknown }}
              </button>
              <el-button
                size="small"
                type="warning"
                :loading="bulkReparsingQualityDocs"
                :disabled="!qualityReparseCandidateCount"
                @click="bulkReparseQualityDocs"
              >
                批量重新解析异常文件 {{ qualityReparseCandidateCount }}
              </el-button>
            </div>
            <div class="admin-doc-summary">当前显示 {{ filteredDocs.length }} / {{ docs.length }} 份文档</div>
          </div>

          <div v-if="docs.length && !filteredDocs.length" class="admin-dialog-empty admin-doc-empty">没有匹配的文档。可以清空搜索词、切换状态或体检筛选。</div>

          <div v-if="filteredDocs.length" class="admin-doc-list" aria-label="文档与权限列表">
            <article
              v-for="doc in filteredDocs"
              :key="doc.id"
              :id="`admin-doc-${doc.id}`"
              :class="['admin-doc-card-row', docQualityRowClass(doc), { 'admin-doc-card-row--focus': latestUploadDoc && String(latestUploadDoc.id) === String(doc.id) }]"
            >
              <div class="admin-doc-card-main">
                <div class="admin-doc-card-head">
                  <div>
                    <strong>{{ docTitle(doc) }}</strong>
                    <span>{{ docFilename(doc) }}</span>
                  </div>
                  <div class="admin-doc-status-stack">
                    <span :class="['admin-status-pill', docStatusKind(doc)]">{{ docStatusLabel(doc) }}</span>
                    <span :class="['admin-quality-pill', documentQualityKind(doc)]">{{ documentQualityLabel(doc) }}</span>
                  </div>
                </div>
                <p>{{ docDescription(doc) }}</p>
                <div class="admin-doc-card-meta">
                  <span>ID {{ doc.id }}</span>
                  <span>阶段：{{ docStageLabel(doc) }}</span>
                  <span>片段 {{ doc.chunks || 0 }} · {{ doc.searchable ? '可检索' : '未检索' }}</span>
                  <span>知识库：{{ knowledgeScopeLabel(doc.knowledge_scope) }}</span>
                  <span>文档类型：{{ documentKindLabel(doc.document_kind) }}</span>
                  <span v-if="String(doc.document_kind_status || '') === 'needs_review'" class="admin-doc-kind-review needs-review">分类待复核</span>
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
                <label v-if="String(doc.document_kind_status || '') === 'needs_review'" class="admin-doc-permission-box">
                  <span>确认文档类型</span>
                  <el-select :model-value="doc.document_kind || 'general'" class="admin-full-select" @change="(value) => updateDocumentClassification(doc, value)">
                    <el-option v-for="item in routingDocumentKindOptions" :key="item.value" :label="item.label" :value="item.value" />
                  </el-select>
                </label>
                <div class="admin-row-actions admin-doc-card-actions">
                  <el-button link type="primary" :disabled="openingDocId === doc.id" @click="openAdminDocument(doc)">
                    {{ openingDocId === doc.id ? '打开中…' : '打开原文' }}
                  </el-button>
                  <el-button link type="primary" @click="openDocumentQuality(doc)">文件体检</el-button>
                  <el-button link type="primary" @click="openDocumentDiagnostics(doc)">诊断详情</el-button>
                  <el-button link @click="openChunkEditor(doc)">修改索引片段</el-button>
                  <el-button link :disabled="deletingDocId === doc.id || reparsingDocId === doc.id" @click="reparseDocument(doc)">
                    {{ reparsingDocId === doc.id ? '解析中…' : '重新解析' }}
                  </el-button>
                  <el-button link class="admin-danger-link" :disabled="deletingDocId === doc.id || reparsingDocId === doc.id" @click="deleteDocument(doc)">
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
              <p>查看文档解析、图谱抽取和 OCR 等后台任务状态，并对失败任务进行重试。</p>
            </div>
            <div class="admin-row-actions admin-task-header-actions">
              <span v-if="taskPolling" class="admin-auto-refresh-hint">自动刷新中</span>
              <span v-else-if="taskLastRefreshLabel" class="admin-task-refresh-time">上次刷新 {{ taskLastRefreshLabel }}</span>
              <el-button :disabled="loadingTasks" @click="loadTasks(true)">
                {{ loadingTasks ? '刷新中…' : '刷新任务' }}
              </el-button>
            </div>
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

              <button :class="{ active: taskTypeFilter === 'graph_extract' }" type="button" @click="taskTypeFilter = 'graph_extract'">图谱抽取 {{ taskTypeCount('graph_extract') }}</button>
              <button :class="{ active: taskTypeFilter === 'graph_rebuild' }" type="button" @click="taskTypeFilter = 'graph_rebuild'">重建图谱 {{ taskTypeCount('graph_rebuild') }}</button>
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
                <div v-if="task.document_message" class="admin-task-error"><strong>解析详情：</strong>{{ task.document_message }}</div>
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
              <span>向量库</span>
              <strong>{{ vectorStatusLabel }}</strong>
              <p>{{ vectorBackendLabel }} · {{ vectorStatus?.collection || '本地 SQLite' }}</p>
              <div class="admin-model-test-result" :class="vectorStatus?.degraded ? 'failed' : (vectorStatus?.qdrant_ready ? 'ok' : 'idle')">
                {{ vectorRetrievalLabel }}
              </div>
              <p class="admin-model-helper" :class="vectorStatus?.degraded ? 'warning' : ''">{{ vectorStatusImpact }}</p>
              <p v-if="vectorStatus?.message" class="admin-model-helper">{{ vectorStatus.message }}</p>
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
              <p>用管理员权限测试一次问题的 Wiki、向量、图谱召回和 rerank 结果。</p>
            </div>
            <el-button :disabled="searchTesting" @click="runSearchTest">
              {{ searchTesting ? '测试中…' : '运行检索测试' }}
            </el-button>
          </header>

          <div class="admin-form-row admin-form-row-wrap">
            <el-input v-model="searchTestForm.question" clearable placeholder="输入一个要诊断的知识库问题" class="admin-input-search" @keyup.enter="runSearchTest" />
            <el-select v-model="searchTestForm.knowledge_scope" class="admin-select-md">
              <el-option label="正式库" value="production" />
              <el-option label="测试库" value="test" />
              <el-option label="全部" value="all" />
            </el-select>
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
            <p v-if="searchSourceQualityWarning" class="admin-model-helper warning">
              {{ searchSourceQualityWarning }} · 受影响 {{ searchSourceQualityNotice.affected_document_count || searchSourceQualityNotice.affected_source_count || 0 }} 个来源
            </p>

            <div class="admin-retrieval-debug-overview">
              <article>
                <span>进入回答的片段</span>
                <strong>{{ retrievalDebugSummary.answer_context_count ?? searchTestResult.source_count ?? 0 }}</strong>
                <p>覆盖文档 {{ retrievalDebugSummary.unique_document_count ?? '-' }} 份</p>
              </article>
              <article>
                <span>检索通道</span>
                <strong>{{ formatDiagnosticValue(retrievalDebugSummary.channel_counts || {}) }}</strong>
                <p>候选 {{ retrievalDebugSummary.candidate_count ?? searchTestResult.candidate_count ?? 0 }}</p>
              </article>
              <article :class="(retrievalDebugSummary.warnings || []).length ? 'is-warning' : ''">
                <span>人工判断提示</span>
                <strong>{{ (retrievalDebugSummary.warnings || []).length ? '需要核验' : '暂无明显风险' }}</strong>
                <p>{{ formatDiagnosticList(retrievalDebugSummary.warnings) || '前几条来源可直接用于判断检索是否命中正确资料。' }}</p>
              </article>
            </div>

            <section v-if="promptContextPreview.text" class="admin-search-context-preview">
              <header>
                <div>
                  <strong>实际喂给回答模型的检索上下文</strong>
                  <span>展示 {{ promptContextPreview.previewed_source_count || 0 }}/{{ promptContextPreview.source_count || 0 }} 条，单条最多 {{ promptContextPreview.max_chars_per_source || 0 }} 字</span>
                </div>
                <div>
                  <button type="button" @click="searchContextPreviewOpen = !searchContextPreviewOpen">{{ searchContextPreviewOpen ? '收起' : '展开查看' }}</button>
                  <button type="button" @click="copySearchPromptContext">复制上下文</button>
                </div>
              </header>
              <pre v-if="searchContextPreviewOpen">{{ promptContextPreview.text }}</pre>
            </section>

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
              <article class="admin-router-diagnostic-card" :class="promptTemplateDiagnostic.count ? '' : 'is-muted'">
                <span>Prompt Template</span>
                <strong>{{ promptTemplateDiagnostic.count ? '已匹配' : '未匹配' }}</strong>
                <p>模板：{{ formatDiagnosticList(promptTemplateDiagnostic.labels) || '-' }}</p>
                <p>已应用到回答：{{ promptTemplateDiagnostic.applied_to_answer === false ? '否' : '是' }}</p>
              </article>
              <article class="admin-router-diagnostic-card" :class="tableQueryDiagnostics.hasTableSignals ? '' : 'is-muted'">
                <span>Table Query</span>
                <strong>{{ tableQueryDiagnostics.summary }}</strong>
                <p>解释：{{ tableQueryDiagnostics.explanation?.summary || '无' }}</p>
                <p>操作：{{ tableQueryDiagnostics.query_op || '无' }}</p>
                <p>过滤：{{ formatTableFilters(tableQueryDiagnostics.value_filters, tableQueryDiagnostics.filter_logic, tableQueryDiagnostics.filter_groups) || '无' }}</p>
                <p>展示：{{ formatDiagnosticList(tableQueryDiagnostics.select_columns) || '默认字段' }}</p>
                <p>聚合：{{ tableQueryDiagnostics.aggregate_op || '无' }} · 指标：{{ tableQueryDiagnostics.measure_column || '无' }}</p>
                <p>多指标：{{ formatTableMetrics(tableQueryDiagnostics.metrics) || '无' }}</p>
                <p>排序：{{ tableQueryDiagnostics.sort_by || '默认' }} · 展开：{{ tableQueryDiagnostics.limit || '默认' }}</p>
                <p>时间：{{ tableQueryDiagnostics.time_value || '无' }}</p>
                <p>映射：{{ formatTableSchema(tableQueryDiagnostics.table_schema) || '无' }}</p>
                <p>建议：{{ formatTableSchemaSuggestions(tableQueryDiagnostics.table_schema_suggestions) || '无' }}</p>
                <div v-if="tableSchemaSuggestionItems.length" class="admin-schema-suggestion-list">
                  <div v-for="item in tableSchemaSuggestionItems" :key="item.suggestion_key || `${item.document_id}-${item.semantic_name}-${item.raw_name}`" class="admin-schema-suggestion-row">
                    <span>{{ schemaSuggestionLabel(item) }}</span>
                    <div>
                      <button type="button" :disabled="schemaAliasActionBusy === schemaSuggestionBusyKey(item)" @click="saveTableSchemaSuggestion(item, 'confirm')">确认</button>
                      <button type="button" :disabled="schemaAliasActionBusy === schemaSuggestionBusyKey(item)" @click="saveTableSchemaSuggestion(item, 'ignore')">忽略</button>
                    </div>
                  </div>
                </div>
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
              <article v-for="item in searchTestResult.source_diagnostics || []" :key="`${item.rank}-${item.document_id}-${item.chunk_id || item.chunk_index}`" :class="['admin-doc-card-row', sourceDiagnosticQualityClass(item)]">
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
                  <p class="admin-search-source-preview">{{ sourceDiagnosticText(item) || '暂无片段预览' }}</p>
                  <div v-if="sourceDiagnosticHasMore(item)" class="admin-inline-actions">
                    <button type="button" @click="toggleSearchSourceExpanded(item)">{{ expandedSearchSources[sourceDiagnosticKey(item)] ? '收起片段' : '展开完整片段' }}</button>
                    <button type="button" @click="copyText(item.full_content || item.preview || '')">复制片段</button>
                  </div>
                  <div class="admin-doc-card-meta">
                    <span>score {{ formatRetrievalScore(item.score) }}</span>
                    <span>rerank {{ formatRetrievalScore(item.rerank_score) }}</span>
                    <span v-if="item.llm_rerank_score !== undefined && item.llm_rerank_score !== null">llm {{ formatRetrievalScore(item.llm_rerank_score) }}</span>
                    <span>{{ item.location || `chunk ${item.chunk_index ?? '-'}` }}</span>
                    <span>知识库：{{ knowledgeScopeLabel(item.knowledge_scope) }}</span>
                    <span>类型：{{ documentKindLabel(item.document_kind) }}</span>
                    <span v-if="sourceDiagnosticQualityLabel(item)">{{ sourceDiagnosticQualityLabel(item) }}</span>
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
                  <div class="admin-doc-permission-box">
                    <span>片段信息</span>
                    <strong>{{ item.content_length || 0 }} 字 · {{ item.location || `chunk ${item.chunk_index ?? '-'}` }}</strong>
                  </div>
                  <div v-if="item.source_quality?.reasons?.length" class="admin-doc-permission-box">
                    <span>质量原因</span>
                    <strong>{{ formatDiagnosticList(item.source_quality.reasons) }}</strong>
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

      <el-tab-pane label="反馈管理" name="feedback">
        <section class="admin-panel-card admin-feedback-panel">
          <header class="admin-section-header">
            <div>
              <h3>反馈管理</h3>
              <p>查看用户对回答的反馈，判断是答案组织问题、检索问题还是资料问题。</p>
            </div>
            <el-button :disabled="loadingFeedback" @click="loadFeedback">
              {{ loadingFeedback ? '刷新中…' : '刷新反馈' }}
            </el-button>
          </header>

          <div class="admin-list-toolbar">
            <label class="admin-search-box">
              <span>搜索反馈</span>
              <el-input v-model="feedbackSearch" clearable placeholder="按用户、问题、回答、反馈内容搜索" class="admin-input-search" />
            </label>
            <div class="admin-filter-row" aria-label="反馈状态筛选">
              <button :class="{ active: feedbackStatusFilter === 'all' }" type="button" @click="feedbackStatusFilter = 'all'">全部 {{ feedbackItems.length }}</button>
              <button :class="{ active: feedbackStatusFilter === 'new' }" type="button" @click="feedbackStatusFilter = 'new'">待处理 {{ feedbackNewCount }}</button>
              <button :class="{ active: feedbackStatusFilter === 'reviewed' }" type="button" @click="feedbackStatusFilter = 'reviewed'">已查看 {{ feedbackReviewedCount }}</button>
              <button :class="{ active: feedbackStatusFilter === 'resolved' }" type="button" @click="feedbackStatusFilter = 'resolved'">已解决 {{ feedbackResolvedCount }}</button>
              <button :class="{ active: feedbackStatusFilter === 'ignored' }" type="button" @click="feedbackStatusFilter = 'ignored'">已忽略 {{ feedbackIgnoredCount }}</button>
            </div>
            <div class="admin-feedback-root-filter">
              <span>问题归因</span>
              <el-select v-model="feedbackRootCauseFilter" placeholder="全部归因" class="admin-select-md">
                <el-option label="全部归因" value="all" />
                <el-option v-for="item in feedbackRootCauseOptions" :key="item.value || 'empty'" :label="item.label" :value="item.value" />
              </el-select>
            </div>
            <div class="admin-list-summary">当前显示 {{ filteredFeedback.length }} / {{ feedbackItems.length }} 条反馈</div>
          </div>

          <div v-if="loadingFeedback" class="admin-dialog-empty">正在加载反馈…</div>
          <div v-else-if="feedbackItems.length && !filteredFeedback.length" class="admin-dialog-empty">没有匹配的反馈。可以切换状态或清空搜索词。</div>
          <div v-else-if="filteredFeedback.length" class="admin-feedback-list">
            <article v-for="item in filteredFeedback" :key="item.id" :class="['admin-feedback-card', feedbackStatusKind(item)]">
              <div class="admin-feedback-card-main">
                <div class="admin-feedback-head">
                  <strong>{{ feedbackRatingLabel(item.rating) }} · {{ feedbackCategoryLabel(item.category) }}</strong>
                  <div class="admin-feedback-head-tags">
                    <span :class="['admin-feedback-cause', feedbackRootCauseClass(item.root_cause)]">{{ feedbackRootCauseLabel(item.root_cause) }}</span>
                    <span :class="['admin-feedback-status', feedbackStatusKind(item)]">{{ feedbackStatusLabel(item.status) }}</span>
                  </div>
                </div>
                <p class="admin-feedback-content">{{ item.content || '无反馈内容' }}</p>
                <div class="admin-feedback-question">
                  <span>问题</span>
                  <p>{{ item.question || '未记录问题快照' }}</p>
                </div>
                <div class="admin-doc-card-meta">
                  <span>{{ item.username || item.user_id || '未知用户' }}</span>
                  <span>{{ feedbackCreatedTime(item) }}</span>
                  <span>来源 {{ feedbackSourceCount(item) }}</span>
                </div>
              </div>
              <aside class="admin-feedback-card-side">
                <button type="button" @click="openFeedbackDetail(item)">查看详情</button>
                <button v-if="item.question" type="button" @click="searchTestForm.question = item.question; jumpToTab('model'); runSearchTest()">运行检索诊断</button>
              </aside>
            </article>
          </div>
          <div v-else class="admin-dialog-empty">暂无用户反馈。</div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="评测面板" name="evaluation">
        <section class="admin-panel-card admin-evaluation-panel">
          <header class="admin-section-header">
            <div>
              <h3>评测运营面板</h3>
              <p>用人工维护的真实问题、用户反馈和文档状态持续观察检索效果；不会盲目相信自动生成问题。</p>
            </div>
            <div class="admin-row-actions">
              <el-button :disabled="loadingEvaluation" @click="loadEvaluationOverview">
                {{ loadingEvaluation ? '刷新中…' : '刷新面板' }}
              </el-button>
              <el-button type="primary" :loading="evaluationSuiteRunning" @click="runEvaluationSuite">
                {{ evaluationSuiteRunning ? '评测中…' : '运行真实评测' }}
              </el-button>
            </div>
          </header>

          <section class="admin-stat-grid" aria-label="评测运营概览">
            <article class="admin-stat-card">
              <span>真实用例</span>
              <strong>{{ evaluationOverview?.case_count || 0 }}</strong>
            </article>
            <article class="admin-stat-card">
              <span>可检索文档</span>
              <strong>{{ evaluationOverview?.documents?.searchable || 0 }}</strong>
            </article>
            <article class="admin-stat-card">
              <span>失败用例</span>
              <strong>{{ evaluationSuiteFailures.length }}</strong>
            </article>
            <article class="admin-stat-card wide" :class="{ 'admin-stat-card-warning': (evaluationOverview?.risk_signals || []).length }">
              <span>风险提示</span>
              <strong>{{ evaluationRiskSummary }}</strong>
              <small>{{ evaluationOverview?.automation_note || '评测数据加载后显示自动化说明。' }}</small>
            </article>
          </section>

          <div class="admin-form-row admin-form-row-wrap">
            <el-input v-model="evaluationForm.question" placeholder="输入一个真实问题，或点击下方用例填入" class="admin-input-lg" />
            <el-input-number v-model="evaluationForm.top_k" :min="1" :max="20" />
            <el-button type="primary" :loading="evaluationCaseRunning" @click="runEvaluationCase">运行单题评测</el-button>
          </div>

          <section class="admin-routing-editor-card">
            <header class="admin-routing-editor-head compact">
              <div>
                <h4>新增评测用例</h4>
                <p>把真实用户问题、无来源问题或反馈问题沉淀为回归用例，后续一键运行评测。</p>
              </div>
              <el-button type="primary" :loading="savingEvaluationCase" @click="createEvaluationCase">保存为用例</el-button>
            </header>
            <div class="admin-form-row admin-form-row-wrap">
              <el-input v-model="evaluationNewCase.id" clearable placeholder="用例 ID（可选，留空自动生成）" class="admin-input-sm" />
              <el-input v-model="evaluationNewCase.category" clearable placeholder="分类，如 财务/制度/反馈沉淀" class="admin-input-sm" />
              <el-input-number v-model="evaluationNewCase.top_k" :min="1" :max="20" />
            </div>
            <el-input v-model="evaluationNewCase.question" clearable placeholder="评测问题" class="admin-input-search" />
            <el-input v-model="evaluationNewCase.why" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" maxlength="1000" show-word-limit placeholder="为什么加入这个用例，例如：用户反馈命中错误 / 高频无答案 / 关键业务问题" />
          </section>

          <div v-if="evaluationSuiteResult" class="admin-upload-result-card">
            <div class="admin-upload-result-head">
              <div>
                <span>最近一次真实评测</span>
                <strong>{{ evaluationSuiteResult.passed || 0 }} / {{ evaluationSuiteResult.total || 0 }} 通过</strong>
                <p>通过率 {{ formatPercent(evaluationSuiteResult.pass_rate) }}</p>
              </div>
              <span :class="['admin-status-pill', evaluationSuiteResult.ok ? 'ready' : 'failed']">{{ evaluationSuiteResult.ok ? '通过' : '有失败' }}</span>
            </div>
            <div v-if="evaluationSuiteFailures.length" class="admin-feedback-list">
              <article v-for="item in evaluationSuiteFailures.slice(0, 5)" :key="item.id" class="admin-feedback-card new">
                <div class="admin-feedback-card-main">
                  <div class="admin-feedback-head">
                    <strong>{{ item.id || item.question }}</strong>
                    <span class="admin-feedback-status new">失败</span>
                  </div>
                  <p class="admin-feedback-content">{{ item.question }}</p>
                  <p class="admin-model-helper warning">{{ (item.errors || []).join('；') }}</p>
                </div>
                <aside class="admin-feedback-card-side">
                  <button type="button" @click="runEvaluationCaseFromResult(item)">重跑单题</button>
                </aside>
              </article>
            </div>
          </div>

          <div v-if="evaluationCaseResult" class="admin-search-result admin-evaluation-result">
            <div class="admin-search-result-head">
              <strong>单题检索结果</strong>
              <span>Backend: <strong>{{ evaluationCaseResult.retrieval_backend || '-' }}</strong></span>
              <span>Confidence: <strong>{{ formatRetrievalScore(evaluationCaseResult.confidence) }}</strong></span>
              <span>来源 {{ evaluationCaseResult.source_count || 0 }}</span>
            </div>
            <p v-if="evaluationCasePromptTemplate.labels?.length" class="admin-model-helper">Prompt 模板：{{ formatDiagnosticList(evaluationCasePromptTemplate.labels) }} · 应用到回答：{{ evaluationCasePromptTemplate.applied_to_answer === false ? '否' : '是' }}</p>
            <p v-if="evaluationCaseResult.retrieval_note" class="admin-model-helper">{{ evaluationCaseResult.retrieval_note }}</p>
            <div v-if="evaluationCaseSources.length" class="admin-search-source-list">
              <article v-for="item in evaluationCaseSources.slice(0, 8)" :key="`${item.rank}-${item.document_id}-${item.chunk_id || item.chunk_index}`" class="admin-search-source-card">
                <header>
                  <strong>#{{ item.rank }} {{ item.document_title || item.filename || '未知文档' }}</strong>
                  <span>{{ item.retrieval_channel || 'semantic' }}</span>
                </header>
                <div class="admin-doc-card-meta">
                  <span>score {{ formatRetrievalScore(item.score) }}</span>
                  <span>rerank {{ formatRetrievalScore(item.rerank_score) }}</span>
                  <span>{{ item.location || '无位置信息' }}</span>
                </div>
                <p>{{ item.preview }}</p>
              </article>
            </div>
            <div v-else class="admin-dialog-empty">没有命中可展示来源。</div>
          </div>

          <div v-if="evaluationCases.length" class="admin-feedback-list">
            <article v-for="item in evaluationCases" :key="item.id" class="admin-feedback-card reviewed">
              <div class="admin-feedback-card-main">
                <div class="admin-feedback-head">
                  <strong>{{ item.category || '未分类' }} · {{ item.id }}</strong>
                  <span class="admin-feedback-status reviewed">{{ item.source === 'custom' ? '后台用例' : '文件用例' }}</span>
                </div>
                <p class="admin-feedback-content">{{ item.question }}</p>
                <p class="admin-model-helper">{{ item.why }}</p>
              </div>
              <aside class="admin-feedback-card-side">
                <button type="button" @click="fillEvaluationQuestion(item)">填入问题</button>
                <button type="button" @click="runEvaluationCaseFromResult(item)">运行</button>
                <button v-if="item.source === 'custom'" type="button" @click="deleteEvaluationCase(item)">删除</button>
              </aside>
            </article>
          </div>
          <div v-else-if="!loadingEvaluation" class="admin-dialog-empty">暂无真实评测用例。请先维护评测用例，再运行评测。</div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="运营中心" name="operations">
        <section class="admin-panel-card admin-operations-panel">
          <header class="admin-section-header">
            <div>
              <h3>知识库运营中心</h3>
              <p>集中查看文档健康、分类待复核、无来源问题、用户反馈和 Prompt 模板，让知识库可以持续运营。</p>
            </div>
            <div class="admin-row-actions">
              <el-button :disabled="loadingOperations" @click="loadOperationsOverview">
                {{ loadingOperations ? '刷新中…' : '刷新运营数据' }}
              </el-button>
              <el-button :disabled="loadingOperations" @click="loadPromptTemplates">刷新模板</el-button>
            </div>
          </header>

          <section class="admin-stat-grid" aria-label="运营总览">
            <article class="admin-stat-card">
              <span>文档总数</span>
              <strong>{{ operationsOverview?.documents?.total || 0 }}</strong>
            </article>
            <article class="admin-stat-card">
              <span>可检索文档</span>
              <strong>{{ operationsOverview?.documents?.searchable || 0 }}</strong>
            </article>
            <article class="admin-stat-card" :class="{ 'admin-stat-card-warning': (operationsOverview?.documents?.failed || 0) > 0 }">
              <span>解析失败</span>
              <strong>{{ operationsOverview?.documents?.failed || 0 }}</strong>
            </article>
            <article class="admin-stat-card" :class="{ 'admin-stat-card-warning': (operationsOverview?.documents?.needs_review_classification || 0) > 0 }">
              <span>分类待复核</span>
              <strong>{{ operationsOverview?.documents?.needs_review_classification || 0 }}</strong>
            </article>
            <article class="admin-stat-card" :class="{ 'admin-stat-card-warning': (operationsOverview?.feedback?.unresolved || 0) > 0 }">
              <span>待处理反馈</span>
              <strong>{{ operationsOverview?.feedback?.unresolved || 0 }}</strong>
            </article>
            <article class="admin-stat-card wide" :class="{ 'admin-stat-card-warning': (operationsOverview?.risk_signals || []).length }">
              <span>运营风险</span>
              <strong>{{ (operationsOverview?.risk_signals || []).length ? `${(operationsOverview?.risk_signals || []).length} 条需关注` : '暂无明显风险' }}</strong>
              <small>{{ (operationsOverview?.recommendations || [])[0] || '建议定期运行评测并处理新增反馈。' }}</small>
            </article>
          </section>

          <div class="admin-model-grid admin-routing-bottom-grid">
            <section class="admin-model-form-card">
              <h4>风险信号与建议动作</h4>
              <div v-if="operationsOverview?.risk_signals?.length" class="admin-feedback-list compact">
                <article v-for="item in operationsOverview.risk_signals" :key="item" class="admin-feedback-card new">
                  <div class="admin-feedback-card-main"><p class="admin-feedback-content">{{ item }}</p></div>
                </article>
              </div>
              <div v-else class="admin-dialog-empty">暂无明显风险。可以继续运行评测套件观察效果。</div>
              <h4>建议动作</h4>
              <div class="admin-quality-tags semantic">
                <span v-for="item in operationsOverview?.recommendations || []" :key="item">{{ item }}</span>
              </div>
            </section>

            <aside class="admin-model-info-card">
              <strong>分类与质量分布</strong>
              <div class="admin-search-test-meta-grid">
                <div v-for="item in operationsOverview?.documents?.by_kind || []" :key="item.kind">
                  <span>{{ item.label || item.kind }}</span>
                  <strong>{{ item.count }}</strong>
                </div>
                <div v-for="(count, grade) in operationsOverview?.quality?.grade_counts || {}" :key="grade">
                  <span>质量 {{ qualityGradeLabel(String(grade)) }}</span>
                  <strong>{{ count }}</strong>
                </div>
              </div>
              <p class="admin-model-helper">启用分类 {{ operationsOverview?.routing?.enabled_kind_count || 0 }} 个，停用 {{ operationsOverview?.routing?.disabled_kind_count || 0 }} 个。</p>
            </aside>
          </div>

          <section class="admin-routing-editor-card">
            <header class="admin-routing-editor-head compact">
              <div>
                <h4>Prompt 优化采用统计</h4>
                <p>记录 A/B 对比后被管理员采用的模板，帮助判断哪些模板在真实问题中更稳定。</p>
              </div>
            </header>
            <div class="admin-model-grid admin-routing-bottom-grid">
              <section class="admin-model-form-card">
                <h4>模板胜出排行</h4>
                <div v-if="operationsOverview?.prompt_adoptions?.by_template?.length" class="admin-search-test-meta-grid">
                  <div v-for="item in operationsOverview.prompt_adoptions.by_template" :key="item.key">
                    <span>{{ promptTemplateLabel(item.key) }}</span>
                    <strong>{{ item.wins }}</strong>
                  </div>
                </div>
                <div v-else class="admin-dialog-empty">暂无采用记录。完成 A/B 对比后可点击“采用 A/B”。</div>
              </section>
              <section class="admin-model-form-card">
                <h4>按分类自动推荐</h4>
                <div v-if="operationsOverview?.prompt_adoptions?.recommended_by_document_kind?.length" class="admin-feedback-list compact">
                  <article v-for="item in operationsOverview.prompt_adoptions.recommended_by_document_kind" :key="`${item.kind}-${item.template}`" class="admin-feedback-card resolved">
                    <div class="admin-feedback-card-main">
                      <div class="admin-feedback-head">
                        <strong>{{ item.label || item.kind }}</strong>
                        <span class="admin-feedback-status resolved">推荐</span>
                      </div>
                      <p class="admin-feedback-content">{{ item.template_label || promptTemplateLabel(item.template) }}</p>
                      <p class="admin-model-helper">胜出 {{ item.wins || 0 }} 次<span v-if="item.latest_at"> · 最近 {{ formatDateTime(item.latest_at) }}</span></p>
                    </div>
                  </article>
                </div>
                <div v-else class="admin-dialog-empty">暂无分类推荐。积累采用记录后会自动生成。</div>
              </section>
              <aside class="admin-model-info-card">
                <strong>最近采用记录</strong>
                <div v-if="operationsOverview?.prompt_adoptions?.recent?.length" class="admin-feedback-list compact">
                  <article v-for="item in operationsOverview.prompt_adoptions.recent.slice(0, 5)" :key="item.id" class="admin-feedback-card reviewed">
                    <div class="admin-feedback-card-main">
                      <div class="admin-feedback-head">
                        <strong>{{ promptTemplateLabels(item.selected_template_keys) }}</strong>
                        <span class="admin-feedback-status reviewed">{{ String(item.selected_variant || '').toUpperCase() }}</span>
                      </div>
                      <p class="admin-feedback-content">{{ item.question }}</p>
                      <p class="admin-model-helper">{{ item.admin_note || '暂无备注' }}</p>
                    </div>
                  </article>
                </div>
                <div v-else class="admin-dialog-empty">暂无最近采用记录。</div>
              </aside>
            </div>
          </section>

          <section class="admin-routing-editor-card">
            <header class="admin-routing-editor-head compact">
              <div>
                <h4>无可靠来源/未命中问题样本</h4>
                <p>这些问题可转成评测用例，或用于补充文档与分类关键词。</p>
              </div>
            </header>
            <div v-if="operationsOverview?.chat?.recent_unanswered?.length" class="admin-feedback-list">
              <article v-for="item in operationsOverview.chat.recent_unanswered" :key="item.message_id" class="admin-feedback-card reviewed">
                <div class="admin-feedback-card-main">
                  <div class="admin-feedback-head">
                    <strong>{{ item.question || '未记录问题' }}</strong>
                    <span class="admin-feedback-status reviewed">来源 {{ item.source_count || 0 }}</span>
                  </div>
                  <p class="admin-feedback-content">{{ item.answer_preview || '暂无回答快照' }}</p>
                </div>
                <aside class="admin-feedback-card-side">
                  <button type="button" @click="evaluationNewCase.question = item.question || ''; evaluationNewCase.why = '来自运营中心无来源问题'; jumpToTab('evaluation')">转评测用例</button>
                  <button type="button" @click="searchTestForm.question = item.question || ''; jumpToTab('model'); runSearchTest()">检索诊断</button>
                </aside>
              </article>
            </div>
            <div v-else class="admin-dialog-empty">最近没有无可靠来源样本。</div>
          </section>

          <section class="admin-routing-editor-card">
            <header class="admin-routing-editor-head compact">
              <div>
                <h4>Prompt 模板测试预览</h4>
                <p>输入一个真实问题，预览会命中的文档类型、Prompt 模板、附加规则和来源片段；不会调用大模型。</p>
              </div>
              <el-button type="primary" :loading="promptPreviewLoading" @click="previewPromptTemplate">运行预览</el-button>
            </header>
            <div class="admin-form-row admin-form-row-wrap">
              <el-input v-model="promptPreviewForm.question" clearable placeholder="例如：报销需要提交哪些材料？" class="admin-input-lg" @keyup.enter="previewPromptTemplate" />
              <el-select v-model="promptPreviewForm.knowledge_scope" class="admin-select-md">
                <el-option label="正式库" value="production" />
                <el-option label="测试库" value="test" />
                <el-option label="全部" value="all" />
              </el-select>
              <el-input-number v-model="promptPreviewForm.top_k" :min="1" :max="20" />
            </div>
            <div v-if="promptPreviewResult" class="admin-search-test-result">
              <div class="admin-search-test-meta">
                <span>Backend: <strong>{{ promptPreviewResult.retrieval_backend || '-' }}</strong></span>
                <span>Candidates: <strong>{{ promptPreviewResult.candidate_count ?? 0 }}</strong></span>
                <span>Answer Contexts: <strong>{{ promptPreviewResult.answer_context_count ?? 0 }}</strong></span>
                <span>Templates: <strong>{{ promptPreviewResult.prompt_template?.count || 0 }}</strong></span>
              </div>
              <div class="admin-router-diagnostics">
                <article class="admin-router-diagnostic-card">
                  <span>命中文档类型</span>
                  <strong>{{ formatPromptPreviewKinds(promptPreviewResult.matched_document_kinds) || '-' }}</strong>
                  <p>路由：{{ promptPreviewResult.retrieval_route?.name || '-' }}</p>
                </article>
                <article class="admin-router-diagnostic-card" :class="promptPreviewResult.prompt_template?.count ? '' : 'is-warning'">
                  <span>Prompt 模板</span>
                  <strong>{{ formatDiagnosticList(promptPreviewResult.prompt_template?.labels) || '未匹配' }}</strong>
                  <p>应用到回答：{{ promptPreviewResult.prompt_template?.applied_to_answer === false ? '否' : '是' }}</p>
                  <p v-if="promptPreviewResult.prompt_template?.recommended?.length">推荐来源：{{ formatPromptTemplateRecommendations(promptPreviewResult.prompt_template.recommended) }}</p>
                </article>
                <article class="admin-router-diagnostic-card">
                  <span>基础规则</span>
                  <strong>{{ (promptPreviewResult.rules_preview?.base_rules || []).length }} 条</strong>
                  <p>{{ formatDiagnosticList(promptPreviewResult.rules_preview?.base_rules) }}</p>
                </article>
              </div>
              <section class="admin-search-context-preview">
                <header>
                  <div>
                    <strong>最终追加到模型的模板规则</strong>
                    <span>仅展示模板附加规则，不展示完整系统提示词。</span>
                  </div>
                  <div><button type="button" @click="copyText(promptPreviewResult.rules_preview?.template_instructions || '')">复制规则</button></div>
                </header>
                <pre>{{ promptPreviewResult.rules_preview?.template_instructions || '暂无模板规则' }}</pre>
              </section>
              <div v-if="promptPreviewResult.source_diagnostics?.length" class="admin-search-source-list">
                <article v-for="item in promptPreviewResult.source_diagnostics" :key="`${item.rank}-${item.document_id}-${item.location}`" class="admin-search-source-card">
                  <header>
                    <strong>#{{ item.rank }} {{ item.document_title }}</strong>
                    <span>{{ item.document_kind_label || item.document_kind }}</span>
                  </header>
                  <div class="admin-doc-card-meta">
                    <span>{{ item.retrieval_channel || '-' }}</span>
                    <span>score {{ formatRetrievalScore(item.score) }}</span>
                    <span>rerank {{ formatRetrievalScore(item.rerank_score) }}</span>
                    <span>{{ item.location || '-' }}</span>
                  </div>
                  <p>{{ item.preview || '暂无片段预览' }}</p>
                </article>
              </div>
              <div v-else class="admin-dialog-empty">没有命中可用于回答的来源片段。</div>
            </div>
          </section>

          <section class="admin-routing-editor-card">
            <header class="admin-routing-editor-head compact">
              <div>
                <h4>Prompt 模板回答 A/B 对比</h4>
                <p>同一个问题分别应用两组模板，比较回答结构、来源利用和无依据风险。dry-run 不调用模型，只做抽取式预览。</p>
              </div>
              <el-button type="primary" :loading="promptCompareLoading" @click="comparePromptTemplates">运行 A/B 对比</el-button>
            </header>
            <div class="admin-form-row admin-form-row-wrap">
              <el-input v-model="promptCompareForm.question" clearable placeholder="输入要对比的问题" class="admin-input-lg" @keyup.enter="comparePromptTemplates" />
              <el-select v-model="promptCompareForm.knowledge_scope" class="admin-select-md">
                <el-option label="正式库" value="production" />
                <el-option label="测试库" value="test" />
                <el-option label="全部" value="all" />
              </el-select>
              <el-input-number v-model="promptCompareForm.top_k" :min="1" :max="20" />
              <el-checkbox v-model="promptCompareForm.dry_run">dry-run</el-checkbox>
            </div>
            <div class="admin-model-grid admin-routing-bottom-grid">
              <label class="admin-model-field">
                <span>A 组模板</span>
                <el-select v-model="promptCompareForm.template_a_keys" multiple filterable class="admin-full-select">
                  <el-option v-for="item in enabledPromptTemplateOptions" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
              </label>
              <label class="admin-model-field">
                <span>B 组模板</span>
                <el-select v-model="promptCompareForm.template_b_keys" multiple filterable class="admin-full-select">
                  <el-option v-for="item in enabledPromptTemplateOptions" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
              </label>
            </div>
            <div v-if="promptCompareResult" class="admin-search-test-result">
              <div class="admin-search-test-meta">
                <span>Backend: <strong>{{ promptCompareResult.retrieval_backend || '-' }}</strong></span>
                <span>Contexts: <strong>{{ promptCompareResult.answer_context_count || 0 }}</strong></span>
                <span>Mode: <strong>{{ promptCompareResult.dry_run ? 'dry-run' : 'model' }}</strong></span>
              </div>
              <div class="admin-model-grid admin-routing-bottom-grid">
                <article class="admin-model-form-card">
                  <h4>A：{{ formatDiagnosticList(promptCompareResult.variant_a?.prompt_template?.labels) || '模板 A' }}</h4>
                  <div class="admin-doc-card-meta">
                    <span>长度 {{ promptCompareResult.variant_a?.quality_signals?.length || 0 }}</span>
                    <span>结构化 {{ promptCompareResult.variant_a?.quality_signals?.has_structure ? '是' : '否' }}</span>
                    <span>提到无依据 {{ promptCompareResult.variant_a?.quality_signals?.mentions_no_evidence ? '是' : '否' }}</span>
                  </div>
                  <pre class="admin-answer-compare-box">{{ promptCompareResult.variant_a?.answer || '暂无回答' }}</pre>
                </article>
                <article class="admin-model-form-card">
                  <h4>B：{{ formatDiagnosticList(promptCompareResult.variant_b?.prompt_template?.labels) || '模板 B' }}</h4>
                  <div class="admin-doc-card-meta">
                    <span>长度 {{ promptCompareResult.variant_b?.quality_signals?.length || 0 }}</span>
                    <span>结构化 {{ promptCompareResult.variant_b?.quality_signals?.has_structure ? '是' : '否' }}</span>
                    <span>提到无依据 {{ promptCompareResult.variant_b?.quality_signals?.mentions_no_evidence ? '是' : '否' }}</span>
                  </div>
                  <pre class="admin-answer-compare-box">{{ promptCompareResult.variant_b?.answer || '暂无回答' }}</pre>
                </article>
              </div>
              <div class="admin-quality-tags semantic">
                <span v-for="item in promptCompareResult.comparison_tips || []" :key="item">{{ item }}</span>
              </div>
              <div class="admin-form-row admin-form-row-wrap">
                <el-input v-model="promptAdoptionNote" clearable placeholder="采用备注，例如：A 结构更清晰，B 有无依据扩写" class="admin-input-lg" />
                <el-button :loading="promptAdoptionSaving === 'a'" @click="adoptPromptVariant('a')">采用 A</el-button>
                <el-button :loading="promptAdoptionSaving === 'b'" @click="adoptPromptVariant('b')">采用 B</el-button>
              </div>
              <div v-if="promptCompareResult.source_diagnostics?.length" class="admin-search-source-list">
                <article v-for="item in promptCompareResult.source_diagnostics" :key="`${item.rank}-${item.document_id}-${item.location}`" class="admin-search-source-card">
                  <header>
                    <strong>#{{ item.rank }} {{ item.document_title }}</strong>
                    <span>{{ item.document_kind }}</span>
                  </header>
                  <p>{{ item.preview || '暂无片段预览' }}</p>
                </article>
              </div>
            </div>
          </section>

          <section class="admin-routing-editor-card">
            <header class="admin-routing-editor-head compact">
              <div>
                <h4>Prompt 模板管理</h4>
                <p>先作为后台配置沉淀不同文档类型的回答规范；后续可以接入回答生成链路。</p>
              </div>
              <div class="admin-row-actions">
                <el-button :loading="savingPromptTemplates" @click="savePromptTemplates">保存模板</el-button>
                <el-button :disabled="savingPromptTemplates" @click="resetPromptTemplates">恢复默认</el-button>
              </div>
            </header>
            <el-table :data="promptTemplates" class="admin-table admin-routing-table">
              <el-table-column label="模板" min-width="180">
                <template #default="scope">
                  <el-input v-model="scope.row.label" placeholder="模板名称" @change="markPromptTemplatesDirty" />
                  <p class="admin-model-helper">Key：{{ scope.row.key }}</p>
                </template>
              </el-table-column>
              <el-table-column label="文档类型" width="180">
                <template #default="scope">
                  <el-select v-model="scope.row.document_kind" class="admin-full-select" @change="markPromptTemplatesDirty">
                    <el-option v-for="item in routingDocumentKindOptions" :key="item.value" :label="item.label" :value="item.value" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="启用" width="90">
                <template #default="scope"><el-switch v-model="scope.row.enabled" @change="markPromptTemplatesDirty" /></template>
              </el-table-column>
              <el-table-column label="模板内容" min-width="420">
                <template #default="scope">
                  <el-input v-model="scope.row.content" type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" maxlength="4000" show-word-limit @change="markPromptTemplatesDirty" />
                </template>
              </el-table-column>
            </el-table>
          </section>
        </section>
      </el-tab-pane>

      <el-tab-pane label="Wiki管理" name="wiki">
        <section class="admin-panel-card admin-graph-panel">
          <header class="admin-section-header">
            <div>
              <h3>Wiki-first 管理</h3>
              <p>统一查看生产 Wiki 编译结果、健康检查、引用来源和 Wiki 检索命中，用于判断真实提问能否被可靠回答。</p>
            </div>
            <div class="admin-row-actions">
              <el-button :disabled="loadingWikiAdmin" @click="loadWikiAdminData(true)">
                {{ loadingWikiAdmin ? '刷新中...' : '刷新Wiki' }}
              </el-button>
              <el-button :loading="wikiLintLoading" @click="runWikiLint">运行Lint并记录</el-button>
              <el-button type="primary" :loading="compilingWiki" @click="compileAllWiki">编译生产Wiki</el-button>
            </div>
          </header>

          <div class="admin-stat-grid admin-graph-stat-grid">
            <article class="admin-stat-card">
              <span>Wiki页面</span>
              <strong>{{ wikiStatus?.page_count || 0 }}</strong>
              <small>已发布 {{ wikiStatus?.published_count || 0 }} · 草稿 {{ wikiStatus?.draft_count || 0 }}</small>
            </article>
            <article class="admin-stat-card">
              <span>已编译文档</span>
              <strong>{{ wikiStatus?.compiled_document_count || 0 }}</strong>
              <small>生产范围：{{ wikiStatus?.knowledge_scope || 'production' }}</small>
            </article>
            <article class="admin-stat-card" :class="{ 'admin-stat-card-warning': (wikiStatus?.failed_document_count || 0) > 0 }">
              <span>编译失败</span>
              <strong>{{ wikiStatus?.failed_document_count || 0 }}</strong>
              <small>失败文档会影响可回答范围</small>
            </article>
            <article class="admin-stat-card" :class="{ 'admin-stat-card-warning': (wikiStatus?.health_finding_count || 0) > 0 }">
              <span>健康评分</span>
              <strong>{{ wikiStatus?.health_score ?? '-' }}</strong>
              <small>发现 {{ wikiStatus?.health_finding_count || 0 }} 个问题</small>
            </article>
            <article class="admin-stat-card">
              <span>页面网络</span>
              <strong>{{ wikiIndex?.count || 0 }}</strong>
              <small>社区 {{ wikiIndexSummary.community_count || 0 }} · 关系 {{ wikiIndexSummary.edge_count || 0 }}</small>
            </article>
            <article class="admin-stat-card" :class="{ 'admin-stat-card-warning': (wikiIndexSummary.orphan_page_count || 0) > 0 }">
              <span>孤页</span>
              <strong>{{ wikiIndexSummary.orphan_page_count || 0 }}</strong>
              <small>无反链 {{ wikiIndexSummary.no_backlink_page_count || 0 }} · 断链 {{ wikiIndexSummary.broken_link_count || 0 }}</small>
            </article>
          </div>

          <div class="admin-list-toolbar">
            <label class="admin-search-box">
              <span>搜索Wiki页面</span>
              <el-input v-model="wikiPageSearch" clearable placeholder="按标题、摘要、slug 搜索" class="admin-input-lg" />
            </label>
            <label class="admin-search-box">
              <span>页面状态</span>
              <el-select v-model="wikiPageStatusFilter" class="admin-select-md">
                <el-option label="全部" value="all" />
                <el-option label="已发布" value="published" />
                <el-option label="草稿" value="draft" />
                <el-option label="已归档" value="archived" />
              </el-select>
            </label>
            <div class="admin-list-summary">当前显示 {{ filteredWikiPages.length }} / {{ wikiPages.length }} 个 Wiki 页面</div>
          </div>

          <div class="admin-graph-columns">
            <section>
              <h4>Wiki页面列表</h4>
              <div v-if="loadingWikiAdmin && !wikiPages.length" class="admin-dialog-empty">正在加载 Wiki 页面...</div>
              <div v-else-if="filteredWikiPages.length" class="admin-feedback-list">
                <article v-for="page in filteredWikiPages" :key="page.id" :class="['admin-feedback-card', wikiPageStatusClass(page.status)]">
                  <div class="admin-feedback-card-main">
                    <div class="admin-feedback-head">
                      <strong>{{ page.title || page.slug }}</strong>
                      <div class="admin-feedback-head-tags">
                        <span :class="['admin-feedback-status', wikiPageStatusClass(page.status)]">{{ wikiPageStatusLabel(page.status) }}</span>
                        <span class="admin-feedback-cause has-cause">{{ wikiPageTypeLabel(page.page_type) }}</span>
                        <span v-if="wikiIndexForPage(page)?.health?.finding_count" class="admin-feedback-status reviewed">体检 {{ wikiIndexForPage(page)?.health?.finding_count }}</span>
                      </div>
                    </div>
                    <p class="admin-feedback-content">{{ page.summary || '暂无摘要' }}</p>
                    <p class="admin-model-helper">{{ page.slug }} · 来源 {{ page.source_count || 0 }} · 连接 {{ wikiIndexForPage(page)?.graph?.link_count ?? 0 }} · 入链 {{ wikiIndexForPage(page)?.graph?.incoming_link_count ?? 0 }} · 出链 {{ wikiIndexForPage(page)?.graph?.outgoing_link_count ?? 0 }} · 置信度 {{ formatRetrievalScore(page.confidence) }} · 更新 {{ formatDateTime(page.updated_at) }}</p>
                    <p v-if="wikiIndexForPage(page)?.recommendations?.length" class="admin-model-helper">建议：{{ wikiIndexForPage(page)?.recommendations?.join('；') }}</p>
                  </div>
                  <aside class="admin-feedback-card-side">
                    <button type="button" @click="loadWikiPageDetail(page, true)">查看详情</button>
                  </aside>
                </article>
              </div>
              <div v-else class="admin-dialog-empty">暂无匹配的 Wiki 页面。可以先点击“编译生产Wiki”。</div>
            </section>

            <section>
              <h4>页面详情与来源</h4>
              <div v-if="wikiPageDetailLoading" class="admin-dialog-empty">正在加载 Wiki 页面详情...</div>
              <div v-else-if="wikiSelectedPage" class="admin-quality-stack">
                <section class="admin-search-context-preview">
                  <header>
                    <div>
                      <span>{{ wikiPageTypeLabel(wikiSelectedPage.page_type) }} · {{ wikiPageStatusLabel(wikiSelectedPage.status) }}</span>
                      <strong>{{ wikiSelectedPage.title || wikiSelectedPage.slug }}</strong>
                    </div>
                    <div>
                      <button type="button" @click="jumpToTab('wikiGraph')">查看图谱</button>
                    </div>
                  </header>
                  <pre>{{ wikiSelectedPage.content_md || '暂无正文' }}</pre>
                </section>
                <section class="admin-quality-section">
                  <h4>引用来源</h4>
                  <div v-if="wikiSelectedPage.sources?.length" class="admin-search-source-list">
                    <article v-for="source in wikiSelectedPage.sources" :key="`${source.document_id}-${source.chunk_id}-${source.source_order}`" class="admin-search-source-card">
                      <header>
                        <strong>{{ source.document_title || source.document_id || '未知文档' }}</strong>
                        <span>S{{ source.source_order || '-' }} · 页码 {{ source.page_number || '未知' }}</span>
                      </header>
                      <p class="admin-search-source-preview">{{ source.quote || '暂无摘录' }}</p>
                    </article>
                  </div>
                  <div v-else class="admin-dialog-empty">该 Wiki 页面暂无来源映射，回答时可信度会下降。</div>
                </section>
              </div>
              <div v-else class="admin-dialog-empty">请选择一个 Wiki 页面查看详情。</div>
            </section>
          </div>

          <div class="admin-graph-columns">
            <section class="admin-quality-section">
              <header class="admin-routing-editor-head compact">
                <div>
                  <h4>Wiki健康检查</h4>
                  <p>Lint 会记录到 Wiki 操作日志，用于观察知识库健康趋势。</p>
                </div>
                <el-button size="small" :loading="wikiLintLoading" @click="runWikiLint">运行Lint</el-button>
              </header>
              <div v-if="wikiHealth" class="admin-search-test-result">
                <div class="admin-search-test-meta-grid">
                  <div><span>来源覆盖</span><strong>{{ formatPercent(wikiHealth.source_coverage) }}</strong></div>
                  <div><span>引用覆盖</span><strong>{{ formatPercent(wikiHealth.citation_coverage) }}</strong></div>
                  <div><span>WikiLink</span><strong>{{ wikiHealth.wikilink_count || 0 }}</strong></div>
                  <div><span>断链</span><strong>{{ wikiHealth.broken_link_count ?? wikiHealth.broken_wikilink_count ?? 0 }}</strong></div>
                  <div><span>孤页</span><strong>{{ wikiHealth.orphan_page_count || 0 }}</strong></div>
                  <div><span>无反链</span><strong>{{ wikiHealth.no_backlink_page_count || 0 }}</strong></div>
                </div>
                <div v-if="wikiHealthFindings.length" class="admin-feedback-list">
                  <article v-for="item in wikiHealthFindings.slice(0, 10)" :key="`${item.rule}-${item.page_id || item.document_id || item.message}`" :class="['admin-feedback-card', wikiHealthSeverityClass(item.severity)]">
                    <div class="admin-feedback-card-main">
                      <div class="admin-feedback-head">
                        <strong>{{ item.title || item.slug || item.document_id || wikiHealthRuleLabel(item.rule) }}</strong>
                        <span :class="['admin-feedback-status', wikiHealthSeverityClass(item.severity)]">{{ wikiHealthSeverityLabel(item.severity) }}</span>
                      </div>
                      <p class="admin-feedback-content">{{ wikiHealthRuleLabel(item.rule) }}：{{ item.message }}</p>
                      <p class="admin-model-helper" v-if="item.target">目标：{{ item.target }}</p>
                    </div>
                  </article>
                </div>
                <div v-else class="admin-dialog-empty">Wiki 健康检查暂未发现问题。</div>
              </div>
              <div v-else class="admin-dialog-empty">暂无 Wiki 健康检查数据。</div>
            </section>

            <section class="admin-quality-section">
              <h4>Wiki检索测试</h4>
              <div class="admin-list-toolbar">
                <label class="admin-search-box">
                  <span>真实问题</span>
                  <el-input v-model="wikiSearchForm.question" clearable placeholder="例如：电子劳动合同怎么操作？" class="admin-input-lg" @keyup.enter="runWikiSearchTest" />
                </label>
                <el-select v-model="wikiSearchForm.knowledge_scope" class="admin-select-md">
                  <el-option label="生产" value="production" />
                  <el-option label="测试" value="test" />
                </el-select>
                <el-input-number v-model="wikiSearchForm.top_k" :min="1" :max="20" />
                <el-button type="primary" :loading="wikiSearchLoading" @click="runWikiSearchTest">测试Wiki命中</el-button>
              </div>
              <div v-if="wikiSearchResult" class="admin-search-result">
                <div class="admin-search-result-head">
                  <span>候选 <strong>{{ wikiSearchResult.meta?.candidate_count ?? 0 }}</strong></span>
                  <span>上下文 <strong>{{ wikiSearchResult.meta?.context_count ?? 0 }}</strong></span>
                  <span>强命中 <strong>{{ wikiSearchResult.meta?.strong_count ?? 0 }}</strong></span>
                  <span>最佳分 <strong>{{ formatRetrievalScore(wikiSearchResult.meta?.best_score) }}</strong></span>
                </div>
                <p class="admin-model-helper">{{ wikiSearchResult.meta?.reason || 'wiki_search' }} · {{ wikiSearchResult.meta?.context_pack || '-' }}</p>
                <div v-if="wikiSearchContexts.length" class="admin-search-source-list">
                  <article v-for="item in wikiSearchContexts" :key="item.wiki_page_id || item.chunk_id || item.document_id" class="admin-search-source-card">
                    <header>
                      <strong>{{ item.wiki_title || item.document_title || 'Wiki页面' }}</strong>
                      <span>分数 {{ formatRetrievalScore(item.score) }} · 来源 {{ item.wiki_source_count || 0 }}</span>
                    </header>
                    <p class="admin-search-source-preview">{{ item.content || '暂无上下文' }}</p>
                    <small>{{ (item.match_terms || []).join('、') }}</small>
                  </article>
                </div>
                <div v-else class="admin-dialog-empty">Wiki 暂未命中。可检查页面标题、摘要、来源引用或重新编译 Wiki。</div>
              </div>
            </section>
          </div>

          <section class="admin-quality-section">
            <header class="admin-routing-editor-head compact">
              <div>
                <h4>Wiki操作日志</h4>
                <p>记录编译、Lint 和检索测试操作，便于追踪 Wiki 自生长闭环。</p>
              </div>
              <el-button size="small" :disabled="loadingWikiAdmin" @click="loadWikiAdminData(false)">刷新日志</el-button>
            </header>
            <div v-if="wikiLogItems.length" class="admin-feedback-list">
              <article v-for="item in wikiLogItems.slice(0, 8)" :key="item.id" class="admin-feedback-card reviewed">
                <div class="admin-feedback-card-main">
                  <div class="admin-feedback-head">
                    <strong>{{ wikiLogActionLabel(item.action) }}</strong>
                    <span class="admin-feedback-status reviewed">{{ item.actor_username || 'system' }}</span>
                  </div>
                  <p class="admin-feedback-content">{{ wikiLogDetailSummary(item) }}</p>
                  <p class="admin-model-helper">{{ item.knowledge_scope || 'production' }} · {{ formatDateTime(item.created_at) }}</p>
                </div>
              </article>
            </div>
            <div v-else class="admin-dialog-empty">暂无 Wiki 操作日志。运行 Lint、编译或检索测试后会出现在这里。</div>
          </section>
        </section>
      </el-tab-pane>

      <el-tab-pane label="Wiki图谱" name="wikiGraph">
        <section class="admin-panel-card admin-graph-panel">
          <header class="admin-section-header">
            <div>
              <h3>Wiki 页面关系图谱</h3>
              <p>参考 llm_wiki 的最新版 Wiki graph 思路：Wiki 页面是节点，<code>[[wikilink]]</code> 是关系边，并叠加直接链接、共同来源、共同邻居和类型亲和四类信号来发现主题社区、意外连接与知识缺口。</p>
            </div>
            <el-button :disabled="loadingWikiGraph" @click="loadWikiGraphData(true)">
              {{ loadingWikiGraph ? '刷新中…' : '刷新Wiki图谱' }}
            </el-button>
          </header>

          <div class="admin-stat-grid admin-graph-stat-grid">
            <article class="admin-stat-card">
              <span>Wiki页面</span>
              <strong>{{ wikiGraph?.node_count || 0 }}</strong>
            </article>
            <article class="admin-stat-card">
              <span>Wiki关系</span>
              <strong>{{ wikiGraph?.edge_count || 0 }}</strong>
            </article>
            <article class="admin-stat-card">
              <span>主题社区</span>
              <strong>{{ wikiGraph?.community_count || 0 }}</strong>
            </article>
            <article class="admin-stat-card" :class="{ 'admin-stat-card-warning': wikiGraphInsightCount > 0 }">
              <span>图谱洞察</span>
              <strong>{{ wikiGraphInsightCount }}</strong>
            </article>
            <article class="admin-stat-card" :class="{ 'admin-stat-card-warning': (wikiGraph?.broken_link_count || 0) > 0 }">
              <span>断链</span>
              <strong>{{ wikiGraph?.broken_link_count || 0 }}</strong>
            </article>
            <article class="admin-stat-card" :class="{ 'admin-stat-card-warning': (wikiGraph?.orphan_count || 0) > 0 }">
              <span>孤立页</span>
              <strong>{{ wikiGraph?.orphan_count || 0 }}</strong>
            </article>
          </div>

          <section class="admin-graph-visual-card">
            <div class="admin-graph-visual-head">
              <div>
                <h4>Wiki 页面网络</h4>
                <p>节点代表 Wiki 页面，颜色代表主题社区，连线代表页面之间的 <code>[[wikilink]]</code>；线越粗说明多信号权重越高。</p>
              </div>
              <span>{{ wikiGraphNodes.length }} 个页面 · {{ wikiGraphEdges.length }} 条关系 · {{ wikiGraphCommunities.length }} 个社区</span>
            </div>
            <div v-if="wikiGraphNodes.length" class="admin-graph-network-layout">
              <div class="admin-graph-network-wrap">
                <div ref="wikiGraphChartRef" class="admin-graph-network" aria-label="Wiki页面关系网络"></div>
                <div class="admin-graph-network-help">可滚轮缩放、拖拽画布和节点；悬浮节点/连线可查看 Wiki 页面与 wikilink 关系。</div>
              </div>
              <aside class="admin-graph-inspector">
                <div class="admin-graph-inspector-head">
                  <span>{{ wikiGraphSelectedNodeName ? 'Wiki相邻关系' : '高连接Wiki关系' }}</span>
                  <button v-if="wikiGraphSelectedNodeName" type="button" @click="wikiGraphSelectedNode = ''">清除选择</button>
                </div>
                <strong>{{ wikiGraphSelectedNodeName || '未选择页面' }}</strong>
                <p>{{ wikiGraphSelectedNodeName ? '以下是该 Wiki 页面直接关联的页面。' : '点击左侧 Wiki 页面节点后，这里会聚焦展示直接关系。' }}</p>
                <div class="admin-graph-inspector-list">
                  <article v-for="edge in wikiGraphSelectedEdges" :key="edge.id" class="admin-graph-inspector-item">
                    <div>
                      <span>{{ edge.source_title }}</span>
                      <em>wikilink</em>
                      <span>{{ edge.target_title }}</span>
                    </div>
                    <p>{{ wikiGraphStrengthLabel(edge.strength) }} · 权重 {{ formatWikiGraphWeight(edge.weight) }} · 显式链接 {{ edge.mentions || 0 }} 次 · 标题提及 {{ edge.title_mentions || 0 }} 次</p>
                    <small>{{ wikiGraphSignalsText(edge) }}</small>
                    <small>{{ edge.source }} ↔ {{ edge.target }} · 共同来源 {{ edge.shared_source_count || 0 }}<template v-if="edge.title_mention_terms?.length"> · 匹配：{{ edge.title_mention_terms.slice(0, 4).join('、') }}</template></small>
                  </article>
                </div>
              </aside>
            </div>
            <div v-else-if="!loadingWikiGraph" class="admin-dialog-empty">还没有可展示的 Wiki 页面关系。请先编译 Wiki，并在页面正文中加入 <code>[[页面标题]]</code> 链接。</div>
          </section>

          <div class="admin-graph-columns">
            <section>
              <h4>Wiki页面节点</h4>
              <div v-if="wikiGraphNodes.length" class="admin-feedback-list">
                <article v-for="node in wikiGraphNodes.slice(0, 12)" :key="node.slug" class="admin-feedback-card reviewed">
                  <div class="admin-feedback-head">
                    <strong>{{ node.title || node.slug }}</strong>
                    <span class="admin-feedback-status reviewed">{{ wikiPageTypeLabel(node.page_type) }}</span>
                  </div>
                  <p>{{ node.summary || '暂无摘要' }}</p>
                  <small>{{ node.community_label || '社区 1' }} · 连接 {{ node.link_count || 0 }} · 入链 {{ node.incoming_link_count || 0 }} · 出链 {{ node.outgoing_link_count || 0 }} · 来源 {{ node.source_count || 0 }}</small>
                </article>
              </div>
              <div v-else class="admin-dialog-empty">暂无 Wiki 页面。</div>
            </section>

            <section>
              <h4>主题社区</h4>
              <div v-if="wikiGraphCommunities.length" class="admin-feedback-list">
                <article v-for="community in wikiGraphCommunities.slice(0, 8)" :key="community.id" class="admin-feedback-card reviewed">
                  <div class="admin-feedback-head">
                    <strong>{{ community.label || `社区 ${Number(community.id || 0) + 1}` }}</strong>
                    <span class="admin-feedback-status reviewed">{{ community.node_count || 0 }} 页</span>
                  </div>
                  <p>核心页面：{{ (community.top_nodes || []).join('、') || '暂无' }}</p>
                  <small>内部关系 {{ community.edge_count || 0 }} · 密度 {{ formatWikiGraphWeight(community.cohesion || 0) }}</small>
                </article>
              </div>
              <div v-else class="admin-dialog-empty">暂无可识别的 Wiki 主题社区。</div>
            </section>

            <section>
              <h4>Graph Insights</h4>
              <div v-if="wikiGraphSurprisingConnections.length || wikiGraphKnowledgeGaps.length" class="admin-feedback-list">
                <article v-for="item in wikiGraphSurprisingConnections.slice(0, 4)" :key="`surprise-${item.key}`" class="admin-feedback-card reviewed">
                  <div class="admin-feedback-head">
                    <strong>{{ item.source_title }} ↔ {{ item.target_title }}</strong>
                    <span class="admin-feedback-status reviewed">意外连接</span>
                  </div>
                  <p>{{ (item.reasons || []).join('、') || '跨主题关系' }}</p>
                  <small>权重 {{ formatWikiGraphWeight(item.weight) }} · 分数 {{ item.score || 0 }}</small>
                </article>
                <article v-for="gap in wikiGraphKnowledgeGaps.slice(0, 6)" :key="`gap-${gap.type}-${gap.title}`" class="admin-feedback-card pending">
                  <div class="admin-feedback-head">
                    <strong>{{ gap.title }}</strong>
                    <span class="admin-feedback-status pending">{{ wikiGraphInsightTypeLabel(gap.type) }}</span>
                  </div>
                  <p>{{ gap.description }}</p>
                  <small>{{ gap.suggestion }}</small>
                </article>
              </div>
              <div v-else class="admin-dialog-empty">当前没有需要处理的 Wiki 图谱洞察。</div>
            </section>

            <section>
              <h4>断链 Wikilink</h4>
              <div v-if="wikiGraphBrokenLinks.length" class="admin-feedback-list">
                <article v-for="item in wikiGraphBrokenLinks.slice(0, 12)" :key="`${item.source}-${item.target}`" class="admin-feedback-card pending">
                  <div class="admin-feedback-head">
                    <strong>{{ item.source_title }}</strong>
                    <span class="admin-feedback-status pending">断链</span>
                  </div>
                  <p>找不到目标页面：<code>{{ item.target }}</code></p>
                  <small>{{ item.source }}</small>
                </article>
              </div>
              <div v-else class="admin-dialog-empty">当前没有 WikiLink 断链。</div>
            </section>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="图谱管理" name="graph">
        <section class="admin-panel-card admin-graph-panel">
          <header class="admin-section-header">
            <div>
              <h3>知识图谱 MVP</h3>
              <p>作为现有 RAG 的旁路增强层：自动从文档切片抽取实体关系，先在后台审核和测试，不直接替换聊天检索。</p>
            </div>
            <el-button :disabled="loadingGraph" @click="loadGraphData(true)">
              {{ loadingGraph ? '刷新中…' : '刷新图谱' }}
            </el-button>
          </header>

          <div class="admin-stat-grid admin-graph-stat-grid">
            <article class="admin-stat-card">
              <span>实体</span>
              <strong>{{ graphOverview?.entity_count || 0 }}</strong>
            </article>
            <article class="admin-stat-card">
              <span>关系</span>
              <strong>{{ graphOverview?.relation_count || 0 }}</strong>
            </article>
            <article class="admin-stat-card" :class="{ 'admin-stat-card-warning': (graphOverview?.pending_count || 0) > 0 }">
              <span>待审核关系</span>
              <strong>{{ graphOverview?.pending_count || 0 }}</strong>
            </article>
            <article class="admin-stat-card">
              <span>已完成文档</span>
              <strong>{{ graphOverview?.ready_document_count || 0 }}</strong>
            </article>
          </div>

          <div class="admin-list-toolbar">
            <label class="admin-search-box">
              <span>图谱搜索测试</span>
              <el-input v-model="graphSearchForm.question" clearable placeholder="例如：入职会触发哪些工单？" class="admin-input-lg" />
            </label>
            <el-button type="primary" :loading="graphSearchLoading" @click="runGraphSearchTest">测试图谱命中</el-button>
          </div>

          <div v-if="graphSearchResult" class="admin-search-result">
            <div class="admin-search-summary">
              <span>命中 <strong>{{ graphSearchResult.count || 0 }}</strong> 条图谱证据</span>
            </div>
            <div v-if="graphSearchContexts.length" class="admin-search-source-list">
              <article v-for="item in graphSearchContexts" :key="item.graph?.id || item.chunk_id || item.document_id" class="admin-search-source-card">
                <strong>{{ item.document_title || item.filename || '未知文档' }}</strong>
                <p>{{ item.content }}</p>
                <small>页码 {{ item.page_number || '未知' }} · 置信度 {{ formatRetrievalScore(item.score) }}</small>
              </article>
            </div>
            <div v-else class="admin-dialog-empty">图谱暂未命中。可先确认文档图谱状态，或等待抽取任务完成。</div>
          </div>

          <section class="admin-graph-visual-card">
            <div class="admin-graph-visual-head">
              <div>
                <h4>图谱关系鸟瞰</h4>
                <p>借鉴力导向图展示方式：节点大小表示连接数，颜色表示实体类型；点击节点可查看关联证据。</p>
              </div>
              <span>{{ graphNetworkData.nodes.length }} 个实体 · {{ graphNetworkData.links.length }} 条关系</span>
            </div>
            <div v-if="graphVisibleRelations.length" class="admin-graph-network-layout">
              <div class="admin-graph-network-wrap">
                <div ref="graphChartRef" class="admin-graph-network" aria-label="知识图谱关系网络"></div>
                <div class="admin-graph-network-help">可滚轮缩放、拖拽画布和节点；悬浮关系线查看来源文档与置信度。</div>
              </div>
              <aside class="admin-graph-inspector">
                <div class="admin-graph-inspector-head">
                  <span>{{ graphSelectedNodeName ? '节点证据' : '近期关系证据' }}</span>
                  <button v-if="graphSelectedNodeName" type="button" @click="graphSelectedNode = ''">清除选择</button>
                </div>
                <strong>{{ graphSelectedNodeName || '未选择节点' }}</strong>
                <p>{{ graphSelectedNodeName ? '以下是该实体直接关联的来源证据。' : '点击左侧节点后，这里会聚焦展示该实体的来源证据。' }}</p>
                <div class="admin-graph-inspector-list">
                  <article v-for="relation in graphSelectedRelations" :key="relation.id" class="admin-graph-inspector-item">
                    <div>
                      <span>{{ relation.source_entity_name }}</span>
                      <em>{{ relation.relation_type }}</em>
                      <span>{{ relation.target_entity_name }}</span>
                    </div>
                    <p>{{ relation.evidence_text || relation.description || '暂无证据文本' }}</p>
                    <small>{{ relation.source_document_title || relation.source_document_filename || '未知文档' }} · {{ graphRelationStatusLabel(relation.status) }} · 置信度 {{ formatRetrievalScore(relation.confidence) }}</small>
                  </article>
                </div>
              </aside>
            </div>
            <div v-else-if="!loadingGraph" class="admin-dialog-empty">还没有可展示的图谱关系。请先选择文档重建图谱，完成后这里会显示实体关系。</div>
          </section>

          <div class="admin-graph-columns">
            <section>
              <h4>文档图谱状态</h4>
              <div v-if="graphDocuments.length" class="admin-task-list">
                <article v-for="doc in graphDocuments.slice(0, 12)" :key="doc.id" class="admin-task-card">
                  <div class="admin-task-main">
                    <div class="admin-task-head">
                      <div>
                        <strong>{{ doc.title || doc.filename }}</strong>
                        <span>{{ doc.filename }}</span>
                      </div>
                      <span :class="['admin-task-status-pill', graphStatusKind(doc.graph?.status)]">{{ graphStatusLabel(doc.graph?.status) }}</span>
                    </div>
                    <p>{{ graphDocumentSummary(doc) }}</p>
                    <div class="admin-task-meta">
                      <span>实体 {{ doc.graph?.entity_count || 0 }}</span>
                      <span>关系 {{ doc.graph?.relation_count || 0 }}</span>
                      <span>待审 {{ doc.graph?.pending_count || 0 }}</span>
                    </div>
                    <div class="admin-task-meta admin-graph-detail">
                      <span>{{ graphDocumentDetail(doc) || '暂无更新时间' }}</span>
                    </div>
                    <p class="admin-model-helper">{{ graphStatusHint(doc.graph?.status) }}</p>
                    <div v-if="graphDocumentFailure(doc)" class="admin-task-error"><strong>失败原因：</strong>{{ graphDocumentFailure(doc) }}</div>
                  </div>
                  <div class="admin-row-actions admin-task-actions">
                    <el-button size="small" :disabled="rebuildingGraphDocId === doc.id" @click="rebuildDocumentGraph(doc)">
                      {{ rebuildingGraphDocId === doc.id ? '已入队…' : '重建图谱' }}
                    </el-button>
                    <el-button size="small" plain @click="jumpToTab('tasks')">去任务中心</el-button>
                  </div>
                </article>
              </div>
              <div v-else-if="!loadingGraph" class="admin-dialog-empty">暂无文档图谱状态。</div>
            </section>

            <section>
              <h4>待审核关系</h4>
              <div v-if="graphRelations.length" class="admin-feedback-list">
                <article v-for="relation in graphRelations.slice(0, 12)" :key="relation.id" class="admin-feedback-card reviewed">
                  <div class="admin-feedback-card-main">
                    <div class="admin-feedback-head">
                      <strong>{{ relation.source_entity_name }} → {{ relation.target_entity_name }}</strong>
                      <span class="admin-feedback-status reviewed">{{ graphRelationStatusLabel(relation.status) }}</span>
                    </div>
                    <p class="admin-feedback-content">{{ relation.relation_type }}：{{ relation.evidence_text || relation.description }}</p>
                    <p class="admin-model-helper">{{ relation.source_document_title || relation.source_document_filename }} · 置信度 {{ formatRetrievalScore(relation.confidence) }}</p>
                  </div>
                  <aside class="admin-feedback-card-side">
                    <button type="button" @click="reviewGraphRelation(relation, 'confirmed')">确认</button>
                    <button type="button" @click="reviewGraphRelation(relation, 'ignored')">忽略</button>
                  </aside>
                </article>
              </div>
              <div v-else-if="!loadingGraph" class="admin-dialog-empty">暂无待审核关系。</div>
            </section>
          </div>
        </section>
      </el-tab-pane>
    </el-tabs>

    <el-drawer
      v-model="feedbackDetailVisible"
      title="反馈详情"
      direction="rtl"
      size="min(820px, calc(100vw - 32px))"
      class="admin-pageindex-drawer admin-feedback-drawer"
    >
      <div v-if="feedbackDetailLoading" class="admin-dialog-empty">正在加载反馈详情…</div>
      <div v-else-if="feedbackDetail" class="admin-pageindex-drawer-body admin-feedback-detail">
        <div class="admin-pageindex-drawer-meta">
          <span>{{ feedbackRatingLabel(feedbackDetail.rating) }} · {{ feedbackCategoryLabel(feedbackDetail.category) }}</span>
          <strong>{{ feedbackDetail.username || feedbackDetail.user_id || '未知用户' }}</strong>
          <p>{{ feedbackCreatedTime(feedbackDetail) }} · {{ feedbackStatusLabel(feedbackDetail.status) }} · {{ feedbackRootCauseLabel(feedbackDetail.root_cause) }}</p>
        </div>

        <section class="admin-feedback-detail-section">
          <h4>用户反馈</h4>
          <p>{{ feedbackDetail.content || '无反馈内容' }}</p>
        </section>

        <section class="admin-feedback-detail-section">
          <h4>用户问题</h4>
          <p>{{ feedbackDetail.question || '未记录问题快照' }}</p>
          <div class="admin-feedback-actions">
            <button v-if="feedbackDetail.question" type="button" class="admin-feedback-action" :disabled="feedbackCompareLoading" @click="runFeedbackCompareSearch">
              {{ feedbackCompareLoading ? '正在重跑检索…' : '重跑检索做对照' }}
            </button>
            <button v-if="feedbackDetail.question" type="button" class="admin-feedback-action" @click="runFeedbackQuestionSearch">打开完整检索诊断</button>
          </div>
        </section>

        <section class="admin-feedback-detail-section">
          <h4>AI 回答</h4>
          <pre>{{ feedbackDetail.answer || '未记录回答快照' }}</pre>
        </section>

        <section class="admin-feedback-detail-section">
          <h4>引用来源</h4>
          <div v-if="feedbackDetail.sources?.length" class="admin-feedback-source-list">
            <article v-for="(source, index) in feedbackDetail.sources" :key="`${source.document_id || source.filename || index}-${source.chunk_id || source.chunk_index || index}`">
              <strong>#{{ index + 1 }} {{ feedbackSourceTitle(source) }}</strong>
              <span>{{ source.location || source.filename || source.document_id }}</span>
              <p>{{ source.content || source.snippet || source.excerpt || '暂无来源摘要' }}</p>
            </article>
          </div>
          <div v-else class="admin-dialog-empty">这条反馈没有记录引用来源。</div>
        </section>

        <section class="admin-feedback-detail-section admin-feedback-compare-section">
          <h4>检索对照</h4>
          <div class="admin-feedback-compare-summary" :class="feedbackCompareResult && feedbackCompareOverlap.matched_count === 0 && feedbackCompareOriginalSources.length && feedbackCompareCurrentSources.length ? 'is-warning' : ''">
            <strong>{{ feedbackCompareSummary }}</strong>
            <span v-if="feedbackCompareResult">当前命中 {{ feedbackCompareCurrentSources.length }} 条 · 原引用 {{ feedbackCompareOriginalSources.length }} 条 · 置信度 {{ formatRetrievalScore(feedbackCompareResult.confidence) }}</span>
            <span v-else>点击“重跑检索做对照”，即可比较这条反馈当时的引用来源和当前检索命中。</span>
          </div>
          <div v-if="feedbackCompareResult?.source_warning" class="admin-model-helper warning">{{ feedbackCompareResult.source_warning }}</div>
          <div v-if="feedbackCompareCurrentSources.length" class="admin-feedback-compare-grid">
            <article v-for="item in feedbackCompareCurrentSources.slice(0, 6)" :key="`${item.rank}-${item.document_id}-${item.chunk_id || item.chunk_index}`" :class="['admin-feedback-compare-card', feedbackCurrentSourceMatched(item) ? 'matched' : '']">
              <div>
                <strong>#{{ item.rank }} {{ item.document_title }}</strong>
                <span>{{ feedbackCurrentSourceMatched(item) ? '与原引用重合' : '当前新命中' }}</span>
              </div>
              <p>{{ item.preview || '暂无片段预览' }}</p>
              <div class="admin-doc-card-meta">
                <span>score {{ formatRetrievalScore(item.score) }}</span>
                <span>rerank {{ formatRetrievalScore(item.rerank_score) }}</span>
                <span>{{ item.location || `chunk ${item.chunk_index ?? '-'}` }}</span>
              </div>
            </article>
          </div>
        </section>

        <section class="admin-feedback-detail-section">
          <h4>处理备注</h4>
          <label class="admin-feedback-root-select">
            <span>问题归因</span>
            <el-select v-model="feedbackRootCause" placeholder="选择问题归因">
              <el-option v-for="item in feedbackRootCauseOptions" :key="item.value || 'empty'" :label="item.label" :value="item.value" />
            </el-select>
          </label>
          <el-input v-model="feedbackReviewNote" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" maxlength="1000" show-word-limit placeholder="记录排查结论，例如：检索命中文档不对 / 来源不足 / 回答组织问题" />
          <div class="admin-feedback-actions">
            <button type="button" :disabled="feedbackReviewBusy" @click="reviewFeedback('reviewed')">标记已查看</button>
            <button type="button" :disabled="feedbackReviewBusy" @click="reviewFeedback('resolved')">标记已解决</button>
            <button type="button" :disabled="feedbackReviewBusy" @click="reviewFeedback('ignored')">忽略</button>
          </div>
        </section>
      </div>
      <div v-else class="admin-dialog-empty">请选择一条反馈。</div>
    </el-drawer>

    <el-dialog v-model="approvalDialogVisible" title="账号审批" width="560px">
      <div v-if="approvalUser" class="admin-approval-dialog">
        <p><strong>{{ approvalUser.username }}</strong> 正在等待管理员审批。通过后账号会立即启用，拒绝后账号保持不可登录。</p>
        <label class="admin-feedback-root-select">
          <span>通过后分配岗位组</span>
          <el-select v-model="approvalForm.group_ids" multiple placeholder="选择岗位组" class="admin-full-select">
            <el-option v-for="g in groups" :key="g.id" :label="g.name" :value="g.id" />
          </el-select>
        </label>
        <el-checkbox v-model="approvalForm.is_admin">设为管理员</el-checkbox>
        <el-input v-model="approvalForm.note" type="textarea" :autosize="{ minRows: 3, maxRows: 5 }" maxlength="1000" show-word-limit placeholder="审批说明，例如：已核验部门和岗位，批准访问对应知识库" />
      </div>
      <template #footer>
        <el-button @click="approvalDialogVisible = false">取消</el-button>
        <el-button type="danger" :loading="approvalBusy" @click="reviewUserApproval('reject')">拒绝</el-button>
        <el-button type="primary" :loading="approvalBusy" @click="reviewUserApproval('approve')">通过并启用</el-button>
      </template>
    </el-dialog>


    <el-drawer
      v-model="documentDiagnosticsVisible"
      title="文档诊断详情"
      direction="rtl"
      size="min(860px, calc(100vw - 32px))"
      class="admin-pageindex-drawer admin-quality-drawer"
    >
      <div v-if="documentDiagnosticsLoading" class="admin-dialog-empty">正在加载文档诊断…</div>
      <div v-else-if="documentDiagnosticsReport" class="admin-pageindex-drawer-body">
        <div class="admin-pageindex-drawer-meta">
          <span>当前文档</span>
          <strong>{{ documentDiagnosticsReport.document?.title || docTitle(documentDiagnosticsDoc) }}</strong>
          <p>{{ documentDiagnosticsReport.document?.filename || docFilename(documentDiagnosticsDoc) }}</p>
        </div>
        <section class="admin-quality-stack">
          <div class="admin-quality-score-card">
            <span>分类解释</span>
            <strong>{{ documentDiagnosticsReport.classification?.label || documentKindLabel(documentDiagnosticsReport.classification?.kind) }}</strong>
            <p>状态：{{ documentDiagnosticsReport.classification?.status || '-' }} · 置信度 {{ formatPercent(documentDiagnosticsReport.classification?.confidence ?? 0) }}</p>
            <div v-if="documentDiagnosticsReport.classification?.reasons?.length" class="admin-quality-tags">
              <span v-for="item in documentDiagnosticsReport.classification.reasons" :key="item">{{ item }}</span>
            </div>
            <p v-else class="admin-model-helper">暂无分类原因，可能来自人工确认或历史数据。</p>
          </div>
          <div class="admin-quality-score-card">
            <span>处理状态</span>
            <strong>{{ statusText(documentDiagnosticsReport.processing?.status) }}</strong>
            <p>{{ stageText(documentDiagnosticsReport.processing?.stage) }} · 切片 {{ documentDiagnosticsReport.processing?.chunks || 0 }} · {{ documentDiagnosticsReport.processing?.searchable ? '可检索' : '不可检索' }}</p>
            <p class="admin-model-helper">{{ documentDiagnosticsReport.processing?.message || '-' }}</p>
          </div>
          <div class="admin-quality-score-card">
            <span>质量与建议</span>
            <strong>{{ qualityGradeLabel(documentDiagnosticsReport.quality?.quality?.grade) }}</strong>
            <div v-if="documentDiagnosticsReport.suggestions?.length" class="admin-quality-tags semantic">
              <span v-for="item in documentDiagnosticsReport.suggestions" :key="item">{{ item }}</span>
            </div>
            <p v-else class="admin-model-helper">暂无必须处理的诊断建议。</p>
          </div>
        </section>
        <section class="admin-feedback-detail-section">
          <h4>切片预览</h4>
          <div v-if="documentDiagnosticsReport.chunk_preview?.length" class="admin-search-source-list">
            <article v-for="chunk in documentDiagnosticsReport.chunk_preview" :key="chunk.id" class="admin-search-source-card">
              <header>
                <strong>Chunk {{ chunk.chunk_index }}</strong>
                <span>页码 {{ chunk.page_number || '未知' }}</span>
              </header>
              <p>{{ chunk.content || '暂无内容' }}</p>
            </article>
          </div>
          <div v-else class="admin-dialog-empty">暂无切片，可能文档尚未解析完成。</div>
        </section>
      </div>
      <div v-else class="admin-dialog-empty">暂无诊断数据。</div>
    </el-drawer>

    <el-drawer
      v-model="documentQualityVisible"
      title="文件处理质量体检"
      direction="rtl"
      size="min(860px, calc(100vw - 32px))"
      class="admin-pageindex-drawer admin-quality-drawer"
    >
      <div v-if="documentQualityLoading" class="admin-dialog-empty">正在生成质量报告…</div>
      <div v-else class="admin-pageindex-drawer-body">
        <div class="admin-pageindex-drawer-meta">
          <span>当前文档</span>
          <strong>{{ docTitle(documentQualityDoc) }}</strong>
          <p>{{ docFilename(documentQualityDoc) }}</p>
        </div>

        <section v-if="documentQualityReport" class="admin-quality-stack">
          <div class="admin-quality-score-card">
            <div>
              <span>综合评分</span>
              <strong>{{ documentQualityReport.quality?.score ?? 0 }}</strong>
              <p>{{ qualityGradeLabel(documentQualityReport.quality?.grade) }}</p>
            </div>
            <div>
              <span>问题数量</span>
              <strong>{{ documentQualityReport.quality?.issue_count ?? 0 }}</strong>
              <p>严重 {{ documentQualityReport.quality?.critical_count ?? 0 }} · 警告 {{ documentQualityReport.quality?.warning_count ?? 0 }}</p>
            </div>
          </div>

          <div class="admin-quality-grid">
            <div>
              <span>原文件</span>
              <strong>{{ documentQualityReport.document?.storage_exists ? '存在' : '缺失' }}</strong>
              <p>{{ formatFileSize(documentQualityReport.document?.file_size || 0) }}</p>
            </div>
            <div>
              <span>文本切片</span>
              <strong>{{ documentQualityReport.chunks?.count || 0 }}</strong>
              <p>{{ documentQualityReport.chunks?.total_chars || 0 }} 字 · 平均 {{ documentQualityReport.chunks?.avg_chars || 0 }} 字</p>
            </div>
            <div>
              <span>表格数据</span>
              <strong>{{ documentQualityReport.table?.data_rows || 0 }}</strong>
              <p>{{ documentQualityReport.table?.sheet_count || 0 }} 个 Sheet · {{ documentQualityReport.table?.column_count || 0 }} 列</p>
            </div>

            <div>
              <span>处理诊断</span>
              <strong>{{ documentQualityReport.processing?.ocr_triggered ? '已触发 OCR' : '普通解析' }}</strong>
              <p>抽取 {{ documentQualityReport.processing?.extracted_chars ?? '-' }} 字 · OCR {{ documentQualityReport.processing?.ocr_chars ?? '-' }} 字</p>
            </div>
          </div>

          <section class="admin-quality-section">
            <h4>发现的问题</h4>
            <div v-if="documentQualityReport.recommended_actions?.length" class="admin-quality-tags semantic">
              <span v-for="action in documentQualityReport.recommended_actions" :key="action.code">
                {{ action.label }}
              </span>
            </div>
            <div v-if="documentQualityReport.issues?.length" class="admin-quality-issue-list">
              <article v-for="issue in documentQualityReport.issues" :key="`${issue.code}-${issue.message}`" :class="['admin-quality-issue', issue.severity]">
                <strong>{{ qualitySeverityLabel(issue.severity) }} · {{ issue.code }}</strong>
                <p>{{ issue.message }}</p>
                <span v-if="issue.suggestion">建议：{{ issue.suggestion }}</span>
              </article>
            </div>
            <div v-else class="admin-dialog-empty">未发现明显文件处理问题。</div>
          </section>

          <section v-if="documentQualityReport.table?.sheets?.length" class="admin-quality-section">
            <h4>表格结构</h4>
            <article v-for="sheet in documentQualityReport.table.sheets" :key="sheet.sheet_name" class="admin-quality-sheet-card">
              <strong>{{ sheet.sheet_name }}</strong>
              <p>数据行 {{ sheet.data_rows }} · 表头行 {{ sheet.header_rows }} · 字段 {{ sheet.column_count }}</p>
              <div v-if="sheet.columns?.length" class="admin-quality-tags">
                <span v-for="column in sheet.columns.slice(0, 12)" :key="column">{{ column }}</span>
              </div>
              <div v-if="sheet.semantic_columns?.length" class="admin-quality-tags semantic">
                <span v-for="field in sheet.semantic_columns" :key="field.semantic_name">{{ field.label }} → {{ field.raw_name }}</span>
              </div>
            </article>
          </section>
        </section>

        <div v-else class="admin-dialog-empty">暂无质量报告。</div>
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
        <p class="admin-index-note dialog-note">修改索引片段后，系统会同步更新向量。</p>
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
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TitleComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ECharts, EChartsOption } from 'echarts/core'
import http from '../../api'

echarts.use([GraphChart, GridComponent, LegendComponent, TitleComponent, TooltipComponent, CanvasRenderer])


const groups = ref<any[]>([])
const users = ref<any[]>([])
const docs = ref<any[]>([])
const vectorStatus = ref<any | null>(null)
const modelConfig = ref<any>({
  base_url: 'https://api.deepseek.com',
  model: 'deepseek-chat',
  api_key_set: false,
  embedding: { provider: 'local', model: 'local-hash', base_url: '', api_key_set: false, ready: false, using_local_hash: true, warning: '' },
  reranker: { enabled: false, model: 'deepseek-chat', max_candidates: 24, ready: false, warning: '' },
})
const tasks = ref<any[]>([])
const feedbackItems = ref<any[]>([])
const evaluationOverview = ref<any | null>(null)
const evaluationSuiteResult = ref<any | null>(null)
const evaluationCaseResult = ref<any | null>(null)
const operationsOverview = ref<any | null>(null)
const promptTemplates = ref<any[]>([])
const promptTemplatesDirty = ref(false)
const promptPreviewForm = reactive({ question: '', top_k: 8, knowledge_scope: 'production' })
const promptPreviewResult = ref<any | null>(null)
const promptPreviewLoading = ref(false)
const promptCompareForm = reactive({ question: '', template_a_keys: ['general'] as string[], template_b_keys: ['policy'] as string[], top_k: 8, knowledge_scope: 'production', dry_run: true })
const promptCompareResult = ref<any | null>(null)
const promptCompareLoading = ref(false)
const promptAdoptionNote = ref('')
const promptAdoptionSaving = ref('')
const graphOverview = ref<any | null>(null)
const graphDocuments = ref<any[]>([])
const graphRelations = ref<any[]>([])
const graphPreviewRelations = ref<any[]>([])
const graphChartRef = ref<HTMLDivElement | null>(null)
const graphSelectedNode = ref<string>('')
const graphSearchResult = ref<any | null>(null)
const wikiGraph = ref<any | null>(null)
const wikiGraphChartRef = ref<HTMLDivElement | null>(null)
const wikiGraphSelectedNode = ref<string>('')
const wikiStatus = ref<any | null>(null)
const wikiPages = ref<any[]>([])
const wikiSelectedPage = ref<any | null>(null)
const wikiHealth = ref<any | null>(null)
const wikiIndex = ref<any | null>(null)
const wikiLogsPayload = ref<any | null>(null)
const wikiSearchResult = ref<any | null>(null)
const documentQualityMap = ref<Record<string, any>>({})
const docGroupMap = reactive<Record<string, string[]>>({})
const groupName = ref('')
const user = reactive({ username: '', password: '', is_admin: false, group_ids: [] as string[] })
const approvalDialogVisible = ref(false)
const approvalBusy = ref(false)
const approvalUser = ref<any | null>(null)
const approvalForm = reactive({ group_ids: [] as string[], is_admin: false, note: '' })
const evaluationForm = reactive({ question: '', top_k: 8 })
const evaluationNewCase = reactive({ id: '', category: '后台维护', question: '', why: '', top_k: 8 })
const graphSearchForm = reactive({ question: '', top_k: 8 })
const wikiSearchForm = reactive({ question: '', top_k: 5, knowledge_scope: 'production' })

type DocStatusFilter = 'all' | 'ready' | 'processing' | 'waiting' | 'failed'
type DocQualityFilter = 'all' | 'good' | 'needs_review' | 'poor' | 'blocked' | 'unknown'
type UserRoleFilter = 'all' | 'admin' | 'member' | 'unassigned' | 'pending' | 'inactive'
type TaskStatusFilter = 'all' | 'pending' | 'running' | 'done' | 'failed'
type TaskTypeFilter = 'all' | 'document_parse' | 'document_reparse' | 'chat_attachment_parse' | 'graph_extract' | 'graph_rebuild' | 'ocr' | 'other'
type FeedbackStatusFilter = 'all' | 'new' | 'reviewed' | 'resolved' | 'ignored'
type FeedbackRootCause = '' | 'answer_quality' | 'retrieval_miss' | 'insufficient_source' | 'document_quality' | 'permission_scope' | 'unclear_question' | 'other'
type FeedbackRootCauseFilter = 'all' | FeedbackRootCause
type WikiPageStatusFilter = 'all' | 'published' | 'draft' | 'archived'
type EditableChunk = { id: string; page_number?: number | null; chunk_index?: number | string | null; content: string }
type UploadSummary = { docId: string; taskId?: string | null; title?: string; filename?: string; status?: string; message?: string; error?: string; searchable?: boolean }

const adminTabIndex = ref('groups')
const documentQualityVisible = ref(false)
const documentQualityLoading = ref(false)
const documentQualityDoc = ref<any | null>(null)
const documentQualityReport = ref<any | null>(null)
const documentDiagnosticsVisible = ref(false)
const documentDiagnosticsLoading = ref(false)
const documentDiagnosticsDoc = ref<any | null>(null)
const documentDiagnosticsReport = ref<any | null>(null)
const chunkEditorVisible = ref(false)
const chunkEditorLoading = ref(false)
const feedbackDetailVisible = ref(false)
const feedbackDetailLoading = ref(false)
const feedbackDetail = ref<any | null>(null)
const feedbackReviewBusy = ref(false)
const feedbackReviewNote = ref('')
const feedbackRootCause = ref<FeedbackRootCause>('')
const feedbackCompareLoading = ref(false)
const feedbackCompareResult = ref<any | null>(null)
const chunkEditorDoc = ref<any | null>(null)
const chunkEditorChunks = ref<EditableChunk[]>([])
const savingChunkId = ref<string | null>(null)
const openingDocId = ref<string | null>(null)
const reparsingDocId = ref<string | null>(null)
const bulkReparsingQualityDocs = ref(false)
const deletingDocId = ref<string | null>(null)
const deletingGroupId = ref<string | null>(null)
const uploadingDoc = ref(false)
const uploadQueue = ref<any[]>([])
const uploadKnowledgeScope = ref<'production' | 'test'>('production')
const lastUploadSummary = ref<UploadSummary | null>(null)
const groupSearch = ref('')
const userSearch = ref('')
const userRoleFilter = ref<UserRoleFilter>('all')
const docSearch = ref('')
const docStatusFilter = ref<DocStatusFilter>('all')
const docQualityFilter = ref<DocQualityFilter>('all')
const taskStatusFilter = ref<TaskStatusFilter>('all')
const taskTypeFilter = ref<TaskTypeFilter>('all')
const taskSearch = ref('')
const feedbackStatusFilter = ref<FeedbackStatusFilter>('all')
const feedbackRootCauseFilter = ref<FeedbackRootCauseFilter>('all')
const feedbackSearch = ref('')
const wikiPageSearch = ref('')
const wikiPageStatusFilter = ref<WikiPageStatusFilter>('all')
const loadingFeedback = ref(false)
const loadingEvaluation = ref(false)
const loadingOperations = ref(false)
const loadingGraph = ref(false)
const loadingWikiGraph = ref(false)
const loadingWikiAdmin = ref(false)
const wikiPageDetailLoading = ref(false)
const wikiSearchLoading = ref(false)
const wikiLintLoading = ref(false)
const compilingWiki = ref(false)
const graphSearchLoading = ref(false)
const evaluationSuiteRunning = ref(false)
const evaluationCaseRunning = ref(false)
const savingEvaluationCase = ref(false)
const savingPromptTemplates = ref(false)
const loadingTasks = ref(false)
const rebuildingGraphDocId = ref<string | null>(null)
const retryingTaskId = ref<string | null>(null)
const refreshing = ref(false)
const lastRefreshAt = ref<Date | null>(null)
const statusPolling = ref(false)
const taskPolling = ref(false)
const taskLastRefreshAt = ref<Date | null>(null)
let statusPollTimer: number | null = null
let taskPollTimer: number | null = null
let graphChart: ECharts | null = null
let graphResizeObserver: ResizeObserver | null = null
let wikiGraphChart: ECharts | null = null
let wikiGraphResizeObserver: ResizeObserver | null = null
let statusPollDeadline = 0
const STATUS_POLL_INTERVAL_MS = 3000
const STATUS_POLL_TIMEOUT_MS = 5 * 60 * 1000
const TASK_POLL_INTERVAL_MS = 5000

const feedbackRootCauseOptions: Array<{ value: FeedbackRootCause; label: string }> = [
  { value: '', label: '未归因' },
  { value: 'answer_quality', label: '回答组织问题' },
  { value: 'retrieval_miss', label: '检索命中错误' },
  { value: 'insufficient_source', label: '来源不足' },
  { value: 'document_quality', label: '文档解析/切片问题' },
  { value: 'permission_scope', label: '权限/可见范围问题' },
  { value: 'unclear_question', label: '用户问题不清楚' },
  { value: 'other', label: '其他' },
]
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
const searchTestForm = reactive({ question: '', top_k: 8, knowledge_scope: 'production' })
const routingDocumentKindOptions = ref<Array<{ value: string; label: string }>>([])
const searchTesting = ref(false)
const searchContextPreviewOpen = ref(false)
const expandedSearchSources = ref<Record<string, boolean>>({})
const schemaAliasActionBusy = ref('')
const searchTestResult = ref<any | null>(null)
const enabledPromptTemplateOptions = computed(() => promptTemplates.value.filter((item: any) => item?.enabled).map((item: any) => ({ value: String(item.key || ''), label: item.label || item.key })).filter((item: any) => item.value))
const routerAnalysis = computed(() => searchTestResult.value?.query_analysis || searchTestResult.value?.retrieval_meta?.query_analysis || {})
const routerRoute = computed(() => searchTestResult.value?.retrieval_route || searchTestResult.value?.retrieval_meta?.retrieval_route || {})
const routerEvidence = computed(() => searchTestResult.value?.evidence_check || searchTestResult.value?.retrieval_meta?.evidence_check || {})
const promptTemplateDiagnostic = computed(() => searchTestResult.value?.prompt_template || searchTestResult.value?.retrieval_meta?.prompt_template || {})
const searchSourceQualityNotice = computed(() => searchTestResult.value?.source_quality_notice || {})
const searchSourceQualityWarning = computed(() => searchTestResult.value?.source_warning || searchSourceQualityNotice.value?.warning || '')
const retrievalDebugSummary = computed(() => searchTestResult.value?.retrieval_debug_summary || {})
const promptContextPreview = computed(() => searchTestResult.value?.prompt_context_preview || {})
const feedbackCompareOriginalSources = computed(() => Array.isArray(feedbackDetail.value?.sources) ? feedbackDetail.value.sources : [])
const feedbackCompareCurrentSources = computed(() => Array.isArray(feedbackCompareResult.value?.source_diagnostics) ? feedbackCompareResult.value.source_diagnostics : [])
const feedbackCompareOverlap = computed(() => {
  const original = new Set(feedbackCompareOriginalSources.value.map((source: any) => String(source?.document_id || source?.filename || source?.document_title || source?.title || '')).filter(Boolean))
  const current = new Set(feedbackCompareCurrentSources.value.map((source: any) => String(source?.document_id || source?.filename || source?.document_title || source?.title || '')).filter(Boolean))
  const matched = [...original].filter((key) => current.has(key))
  return { original_count: original.size, current_count: current.size, matched_count: matched.length, matched }
})
const feedbackCompareSummary = computed(() => {
  if (!feedbackCompareResult.value) return '尚未重跑检索'
  if (!feedbackCompareCurrentSources.value.length) return '当前检索没有命中来源'
  if (!feedbackCompareOriginalSources.value.length) return '原回答没有记录引用来源，可直接查看当前检索命中'
  if (feedbackCompareOverlap.value.matched_count > 0) return `原引用中有 ${feedbackCompareOverlap.value.matched_count}/${feedbackCompareOverlap.value.original_count} 份文档仍能命中`
  return '当前检索与原回答引用没有文档重合，请重点排查检索或文档状态变化'
})
const evaluationCases = computed(() => Array.isArray(evaluationOverview.value?.cases) ? evaluationOverview.value.cases : [])
const evaluationCaseSources = computed(() => Array.isArray(evaluationCaseResult.value?.source_diagnostics) ? evaluationCaseResult.value.source_diagnostics : [])
const evaluationCasePromptTemplate = computed(() => evaluationCaseResult.value?.prompt_template || evaluationCaseResult.value?.retrieval_meta?.prompt_template || {})
const wikiHealthFindings = computed(() => Array.isArray(wikiHealth.value?.findings) ? wikiHealth.value.findings : [])
const wikiIndexItems = computed(() => Array.isArray(wikiIndex.value?.items) ? wikiIndex.value.items : [])
const wikiIndexSummary = computed(() => wikiIndex.value?.summary || {})
const wikiLogItems = computed(() => Array.isArray(wikiLogsPayload.value?.items) ? wikiLogsPayload.value.items : [])
const wikiIndexBySlug = computed(() => {
  const result: Record<string, any> = {}
  wikiIndexItems.value.forEach((item: any) => {
    const slug = String(item?.slug || '')
    if (slug) result[slug] = item
  })
  return result
})
const wikiSearchContexts = computed(() => Array.isArray(wikiSearchResult.value?.contexts) ? wikiSearchResult.value.contexts : [])
const filteredWikiPages = computed(() => {
  const query = normalizeText(wikiPageSearch.value)
  return wikiPages.value.filter((page: any) => {
    const status = normalizeText(page?.status || '')
    if (wikiPageStatusFilter.value !== 'all' && status !== wikiPageStatusFilter.value) return false
    if (!query) return true
    const haystack = normalizeText([page?.title, page?.slug, page?.summary, page?.page_type].filter(Boolean).join(' '))
    return haystack.includes(query)
  })
})
const graphSearchContexts = computed(() => Array.isArray(graphSearchResult.value?.contexts) ? graphSearchResult.value.contexts : [])
const graphVisibleRelations = computed(() => graphPreviewRelations.value.filter((item: any) => item?.status !== 'ignored'))
const graphTypePalette = ['#2563eb', '#059669', '#d97706', '#7c3aed', '#dc2626', '#0891b2', '#4f46e5', '#65a30d']
const graphEntityTypeCategories = computed(() => {
  const seen: Record<string, boolean> = {}
  const categories: Array<{ name: string; itemStyle: { color: string } }> = []
  graphVisibleRelations.value.forEach((relation: any) => {
    ;[relation?.source_entity_type, relation?.target_entity_type].forEach((rawType: any) => {
      const name = graphEntityTypeLabel(rawType)
      if (seen[name]) return
      seen[name] = true
      categories.push({ name, itemStyle: { color: graphTypePalette[(categories.length) % graphTypePalette.length] } })
    })
  })
  return categories.length ? categories : [{ name: '实体', itemStyle: { color: graphTypePalette[0] } }]
})
const graphNetworkData = computed(() => {
  const degree: Record<string, number> = {}
  graphVisibleRelations.value.forEach((relation: any) => {
    const source = graphEntityKey(relation, 'source')
    const target = graphEntityKey(relation, 'target')
    if (!source || !target) return
    degree[source] = (degree[source] || 0) + 1
    degree[target] = (degree[target] || 0) + 1
  })

  const nodeMap: Record<string, any> = {}
  const links: any[] = []
  graphVisibleRelations.value.forEach((relation: any) => {
    const source = graphEntityKey(relation, 'source')
    const target = graphEntityKey(relation, 'target')
    if (!source || !target) return
    const sourceName = String(relation?.source_entity_name || '未命名实体')
    const targetName = String(relation?.target_entity_name || '未命名实体')
    const sourceType = graphEntityTypeLabel(relation?.source_entity_type)
    const targetType = graphEntityTypeLabel(relation?.target_entity_type)
    nodeMap[source] = nodeMap[source] || {
      id: source,
      name: sourceName,
      category: sourceType,
      value: degree[source] || 1,
      symbolSize: graphNodeSize(degree[source] || 1),
      draggable: true,
    }
    nodeMap[target] = nodeMap[target] || {
      id: target,
      name: targetName,
      category: targetType,
      value: degree[target] || 1,
      symbolSize: graphNodeSize(degree[target] || 1),
      draggable: true,
    }
    links.push({
      id: String(relation?.id || `${source}-${target}-${links.length}`),
      source,
      target,
      name: relation?.relation_type || '关联',
      value: relation?.confidence || 0,
      relation,
      lineStyle: { width: graphRelationWidth(relation?.confidence), opacity: relation?.status === 'pending' ? 0.48 : 0.72 },
    })
  })
  return { nodes: Object.values(nodeMap), links }
})
const graphSelectedRelations = computed(() => {
  const selected = graphSelectedNode.value
  if (!selected) return graphVisibleRelations.value.slice(0, 6)
  return graphVisibleRelations.value.filter((relation: any) => graphEntityKey(relation, 'source') === selected || graphEntityKey(relation, 'target') === selected).slice(0, 8)
})
const graphSelectedNodeName = computed(() => {
  const selected = graphSelectedNode.value
  if (!selected) return ''
  const node = graphNetworkData.value.nodes.find((item: any) => item.id === selected)
  return node?.name || ''
})
const wikiGraphNodes = computed(() => Array.isArray(wikiGraph.value?.nodes) ? wikiGraph.value.nodes : [])
const wikiGraphEdges = computed(() => Array.isArray(wikiGraph.value?.edges) ? wikiGraph.value.edges : [])
const wikiGraphBrokenLinks = computed(() => Array.isArray(wikiGraph.value?.broken_links) ? wikiGraph.value.broken_links : [])
const wikiGraphCommunities = computed(() => Array.isArray(wikiGraph.value?.communities) ? wikiGraph.value.communities : [])
const wikiGraphInsights = computed(() => wikiGraph.value?.insights || {})
const wikiGraphSurprisingConnections = computed(() => Array.isArray(wikiGraphInsights.value?.surprising_connections) ? wikiGraphInsights.value.surprising_connections : [])
const wikiGraphKnowledgeGaps = computed(() => Array.isArray(wikiGraphInsights.value?.knowledge_gaps) ? wikiGraphInsights.value.knowledge_gaps : [])
const wikiGraphInsightCount = computed(() => wikiGraphSurprisingConnections.value.length + wikiGraphKnowledgeGaps.value.length)
const wikiGraphPageTypeCategories = computed(() => {
  const seen: Record<string, boolean> = {}
  const categories: Array<{ name: string; itemStyle: { color: string } }> = []
  wikiGraphNodes.value.forEach((node: any) => {
    const name = wikiPageTypeLabel(node?.page_type)
    if (seen[name]) return
    seen[name] = true
    categories.push({ name, itemStyle: { color: graphTypePalette[(categories.length) % graphTypePalette.length] } })
  })
  return categories.length ? categories : [{ name: 'Wiki页面', itemStyle: { color: graphTypePalette[0] } }]
})
const wikiGraphNetworkData = computed(() => ({
  nodes: wikiGraphNodes.value.map((node: any) => ({
    id: String(node?.slug || node?.id || ''),
    name: String(node?.title || node?.slug || '未命名页面'),
    category: wikiPageTypeLabel(node?.page_type),
    value: Number(node?.link_count || 0),
    symbolSize: graphNodeSize(Number(node?.link_count || 1)),
    draggable: true,
    itemStyle: { color: wikiGraphCommunityColor(Number(node?.community || 0)) },
    page: node,
  })).filter((node: any) => node.id),
  links: wikiGraphEdges.value.map((edge: any) => ({
    id: String(edge?.id || `${edge?.source}-${edge?.target}`),
    source: String(edge?.source || ''),
    target: String(edge?.target || ''),
    name: formatWikiGraphWeight(edge?.weight || edge?.mentions || 1),
    value: Number(edge?.weight || edge?.mentions || 1),
    edge,
    lineStyle: {
      width: graphRelationWidth(Number(edge?.weight || edge?.mentions || 1) / 10),
      opacity: edge?.strength === 'weak' ? 0.42 : 0.78,
      color: edge?.strength === 'strong' ? '#2563eb' : edge?.strength === 'medium' ? '#0891b2' : '#94a3b8',
    },
  })).filter((edge: any) => edge.source && edge.target),
}))
const wikiGraphSelectedEdges = computed(() => {
  const selected = wikiGraphSelectedNode.value
  if (!selected) return wikiGraphEdges.value.slice(0, 8)
  return wikiGraphEdges.value.filter((edge: any) => edge?.source === selected || edge?.target === selected).slice(0, 12)
})
const wikiGraphSelectedNodeName = computed(() => {
  const selected = wikiGraphSelectedNode.value
  if (!selected) return ''
  const node = wikiGraphNetworkData.value.nodes.find((item: any) => item.id === selected)
  return node?.name || ''
})
const graphRecentTaskByDoc = computed(() => {
  const result: Record<string, any> = {}
  tasks.value.forEach((task: any) => {
    if (!['graph_extract', 'graph_rebuild'].includes(String(task?.task_type || ''))) return
    const docId = String(task?.document_id || '')
    if (!docId || result[docId]) return
    result[docId] = task
  })
  return result
})
const evaluationSuiteFailures = computed(() => Array.isArray(evaluationSuiteResult.value?.results) ? evaluationSuiteResult.value.results.filter((item: any) => !item?.ok) : [])
const evaluationRiskSummary = computed(() => {
  const risks = evaluationOverview.value?.risk_signals || []
  if (!Array.isArray(risks) || !risks.length) return '暂无明显风险'
  return risks.slice(0, 3).join('；')
})
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
  const metrics = Array.isArray(plan.metrics) ? plan.metrics : (Array.isArray(meta.metrics) ? meta.metrics : [])
  const selectColumns = Array.isArray(plan.select_columns) ? plan.select_columns : (Array.isArray(meta.select_columns) ? meta.select_columns : [])
  const sortBy = plan.sort_by || meta.sort_by || ''
  const limit = plan.limit || meta.limit || ''
  const timeGrain = plan.time_grain || meta.time_grain || ''
  const timeValue = plan.time_value || meta.time_value || ''
  const timeTokens = Array.isArray(plan.time_tokens) ? plan.time_tokens : (Array.isArray(meta.time_tokens) ? meta.time_tokens : [])
  const explanation = meta.table_query_explanation || {}
  const tableSchema = meta.table_schema || {}
  const tableSchemaSuggestions = meta.table_schema_suggestions || {}
  const schemaSuggestionEntries = Object.values(tableSchemaSuggestions)
    .flatMap((items: any) => Array.isArray(items) ? items : [])
  return {
    value_filters: valueFilters,
    filter_logic: filterLogic,
    filter_groups: filterGroups,
    group_by: groupBy,
    distinct_by: distinctBy,
    select_columns: selectColumns,
    table_schema: tableSchema,
    table_schema_suggestions: tableSchemaSuggestions,
    schema_suggestion_count: schemaSuggestionEntries.length,
    explanation,
    query_op: queryOp,
    aggregate_op: aggregateOp,
    measure_column: measureColumn,
    metrics,
    sort_by: sortBy,
    limit,
    time_grain: timeGrain,
    time_value: timeValue,
    time_tokens: timeTokens,
    matched_rows: meta.value_filter_matched_rows,
    hasTableSignals: valueFilters.length > 0 || Boolean(groupBy) || Boolean(distinctBy) || Boolean(aggregateOp) || metrics.length > 0 || selectColumns.length > 0 || Boolean(sortBy) || Boolean(limit) || Boolean(timeValue) || Boolean(queryOp) || schemaSuggestionEntries.length > 0,
    summary: explanation.summary || (valueFilters.length > 0 || groupBy || distinctBy || aggregateOp || metrics.length > 0 || selectColumns.length > 0 || sortBy || limit || timeValue || queryOp
      ? `${valueFilters.length} filters · ${meta.value_filter_matched_rows ?? '-'} rows`
      : (schemaSuggestionEntries.length > 0 ? `${schemaSuggestionEntries.length} schema suggestions` : '未识别结构化条件')),
  }
})
const tableSchemaSuggestionItems = computed(() => {
  const suggestions = tableQueryDiagnostics.value.table_schema_suggestions || {}
  return Object.values(suggestions)
    .flatMap((items: any) => Array.isArray(items) ? items : [])
    .slice(0, 12)
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
  delete meta.metrics
  delete meta.select_columns
  delete meta.sort_by
  delete meta.limit
  delete meta.time_grain
  delete meta.time_value
  delete meta.time_tokens
  delete meta.table_schema
  delete meta.table_schema_suggestions
  delete meta.table_query_plan
  delete meta.table_query_explanation
  delete meta.query_op
  return meta
})


const vectorStatusLabel = computed(() => {
  if (!vectorStatus.value) return '读取中'
  if (vectorStatus.value.degraded) return 'SQLite 回退中'
  if (vectorStatus.value.qdrant_ready) return 'Qdrant 正常'
  return 'SQLite 本地向量'
})
const vectorBackendLabel = computed(() => {
  if (!vectorStatus.value) return '未知'
  return ({ qdrant: 'Qdrant', sqlite: 'SQLite', sqlite_fallback: 'SQLite 回退', local: 'SQLite 本地', unknown: '未知' } as Record<string, string>)[String(vectorStatus.value.backend || 'unknown')] || String(vectorStatus.value.backend || '未知')
})
const vectorRetrievalLabel = computed(() => {
  if (!vectorStatus.value) return '未知'
  if (vectorStatus.value.degraded) return '当前检索：SQLite 本地向量检索'
  if (vectorStatus.value.qdrant_ready) return '当前检索：Qdrant 向量检索'
  return '当前检索：SQLite 本地向量检索'
})
const vectorStatusImpact = computed(() => {
  if (!vectorStatus.value) return '正在读取向量库状态'
  if (vectorStatus.value.degraded) return 'Qdrant 暂不可用时，检索会回退到 SQLite，本地结果可能更慢、召回更弱。'
  if (vectorStatus.value.qdrant_ready) return `Qdrant 正常，集合 ${vectorStatus.value.collection || '默认集合'} 可用。`
  return '当前使用 SQLite 本地向量检索。'
})

const lastRefreshLabel = computed(() => {
  if (!lastRefreshAt.value) return '未刷新'
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(lastRefreshAt.value)
})
const taskLastRefreshLabel = computed(() => {
  if (!taskLastRefreshAt.value) return ''
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(taskLastRefreshAt.value)
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
    if (userRoleFilter.value === 'pending' && !isUserPending(item)) return false
    if (userRoleFilter.value === 'inactive' && (item?.is_active || isUserPending(item))) return false
    if (!['all', 'pending', 'inactive'].includes(userRoleFilter.value) && userRoleKind(item) !== userRoleFilter.value) return false
    if (!keyword) return true
    const haystack = normalizeText([
      item?.username,
      item?.id,
      item?.groups?.map((g: any) => g?.name).join('、'),
      item?.is_admin ? '管理员' : '成员',
      userApprovalLabel(item),
      item?.approval_note,
    ].join(' '))
    return haystack.includes(keyword)
  })
})
const filteredDocs = computed(() => {
  const keyword = normalizeText(docSearch.value).trim()
  return docs.value.filter((doc: any) => {
    if (docStatusFilter.value !== 'all' && docStatusKind(doc) !== docStatusFilter.value) return false
    if (docQualityFilter.value !== 'all' && documentQualityKind(doc) !== docQualityFilter.value) return false
    if (!keyword) return true
    const haystack = normalizeText([
      docTitle(doc),
      docFilename(doc),
      docDescription(doc),
      docGroupsText(doc),
      statusText(doc.status),
      stageText(doc.stage),

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
const filteredFeedback = computed(() => {
  const keyword = normalizeText(feedbackSearch.value).trim()
  return feedbackItems.value.filter((item: any) => {
    if (feedbackStatusFilter.value !== 'all' && feedbackStatusKind(item) !== feedbackStatusFilter.value) return false
    if (feedbackRootCauseFilter.value !== 'all' && String(item?.root_cause || '') !== feedbackRootCauseFilter.value) return false
    if (!keyword) return true
    const haystack = normalizeText([
      item?.username,
      item?.rating,
      item?.category,
      item?.content,
      item?.question,
      item?.answer,
      item?.admin_note,
      item?.root_cause,
      feedbackRootCauseLabel(item?.root_cause),
    ].join(' '))
    return haystack.includes(keyword)
  })
})
const docReadyCount = computed(() => docs.value.filter((doc: any) => docStatusKind(doc) === 'ready').length)
const docProcessingCount = computed(() => docs.value.filter((doc: any) => docStatusKind(doc) === 'processing').length)
const docWaitingCount = computed(() => docs.value.filter((doc: any) => docStatusKind(doc) === 'waiting').length)
const docFailedCount = computed(() => docs.value.filter((doc: any) => docStatusKind(doc) === 'failed').length)
const docQualityCounts = computed(() => docs.value.reduce((acc: Record<string, number>, doc: any) => {
  const kind = documentQualityKind(doc)
  acc[kind] = (acc[kind] || 0) + 1
  return acc
}, { good: 0, needs_review: 0, poor: 0, blocked: 0, unknown: 0 }))
const qualityReparseCandidateCount = computed(() => docs.value.filter((doc: any) => qualityReportHasAction(documentQualityMap.value[String(doc?.id || '')], 'reparse')).length)
const userAdminCount = computed(() => users.value.filter((item: any) => item?.is_admin).length)
const userMemberCount = computed(() => users.value.filter((item: any) => !item?.is_admin && (item?.groups || []).length > 0).length)
const userUnassignedCount = computed(() => users.value.filter((item: any) => !isUserPending(item) && !(item?.groups || []).length).length)
const userPendingCount = computed(() => users.value.filter((item: any) => isUserPending(item)).length)
const userInactiveCount = computed(() => users.value.filter((item: any) => !item?.is_active && !isUserPending(item)).length)
const taskPendingCount = computed(() => tasks.value.filter((task: any) => taskStatusKind(task) === 'pending').length)
const taskRunningCount = computed(() => tasks.value.filter((task: any) => taskStatusKind(task) === 'running').length)
const taskDoneCount = computed(() => tasks.value.filter((task: any) => taskStatusKind(task) === 'done').length)
const taskFailedCount = computed(() => tasks.value.filter((task: any) => taskStatusKind(task) === 'failed').length)
const feedbackNewCount = computed(() => feedbackItems.value.filter((item: any) => feedbackStatusKind(item) === 'new').length)
const feedbackReviewedCount = computed(() => feedbackItems.value.filter((item: any) => feedbackStatusKind(item) === 'reviewed').length)
const feedbackResolvedCount = computed(() => feedbackItems.value.filter((item: any) => feedbackStatusKind(item) === 'resolved').length)
const feedbackIgnoredCount = computed(() => feedbackItems.value.filter((item: any) => feedbackStatusKind(item) === 'ignored').length)
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
  return ({ admin: '管理员', member: '成员', unassigned: '未分配', pending: '待审批', inactive: '停用' } as Record<string, string>)[userRoleKind(item)]
}

function knowledgeScopeLabel(value: any) {
  return ({ production: '正式库', test: '测试库', all: '全部' } as Record<string, string>)[String(value || 'production')] || '正式库'
}

function documentKindLabel(value: any) {
  const key = String(value || 'general')
  const matched = routingDocumentKindOptions.value.find((item) => String(item.value) === key)
  if (matched?.label) return matched.label
  return ({
    table: '表格数据',
    employee_guide: '员工指南',
    workorder: '工单/内部流程',
    form: '表单/信息表',
    policy: '制度/政策',
    general: '通用文档',
  } as Record<string, string>)[key] || key || '通用文档'
}

function documentKindStatusLabel(doc: any) {
  const status = String(doc?.document_kind_status || 'confirmed')
  const confidence = Number(doc?.document_kind_confidence ?? 1)
  const percent = Number.isFinite(confidence) ? ` · ${(confidence * 100).toFixed(0)}%` : ''
  if (status === 'needs_review') return `待复核${percent}`
  if (status === 'auto') return `自动识别${percent}`
  return `已确认${percent}`
}

function documentKindReviewClass(doc: any) {
  const status = String(doc?.document_kind_status || 'confirmed')
  if (status === 'needs_review') return 'needs-review'
  if (status === 'auto') return 'auto'
  return 'confirmed'
}

function isUserPending(item: any) {
  return String(item?.approval_status || '').toLowerCase() === 'pending'
}

function userApprovalKind(item: any) {
  const status = String(item?.approval_status || 'approved').toLowerCase()
  if (status === 'pending') return 'waiting'
  if (status === 'rejected') return 'failed'
  return 'ready'
}

function userApprovalLabel(item: any) {
  const status = String(item?.approval_status || 'approved').toLowerCase()
  if (status === 'pending') return '待审批'
  if (status === 'rejected') return '已拒绝'
  return '已通过'
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

function documentQualityKind(doc: any) {
  const report = documentQualityMap.value[String(doc?.id || '')]
  return report?.quality?.grade || 'unknown'
}

function documentQualityLabel(doc: any) {
  const report = documentQualityMap.value[String(doc?.id || '')]
  if (!report) return '未体检'
  return qualityGradeLabel(report?.quality?.grade)
}

function qualityReportHasAction(report: any, code: string) {
  return Boolean((report?.recommended_actions || []).some((action: any) => action?.code === code && action?.available !== false))
}

function docQualityRowClass(doc: any) {
  const kind = documentQualityKind(doc)
  return kind === 'blocked' || kind === 'poor' ? 'admin-doc-card-row--quality-issue' : ''
}

function sourceDiagnosticQualityGrade(item: any) {
  return String(item?.source_quality?.grade || '').toLowerCase()
}

function sourceDiagnosticQualityClass(item: any) {
  const grade = sourceDiagnosticQualityGrade(item)
  return grade === 'blocked' || grade === 'poor' ? 'admin-doc-card-row--quality-issue' : ''
}

function sourceDiagnosticQualityLabel(item: any) {
  const grade = sourceDiagnosticQualityGrade(item)
  if (grade === 'blocked') return '来源质量：阻断/需修复'
  if (grade === 'poor') return '来源质量：偏低'
  return ''
}

function sourceDiagnosticKey(item: any) {
  return `${item?.rank || ''}-${item?.document_id || ''}-${item?.chunk_id || item?.chunk_index || ''}`
}

function sourceDiagnosticText(item: any) {
  const key = sourceDiagnosticKey(item)
  const expanded = expandedSearchSources.value[key]
  const text = String(item?.full_content || item?.preview || '')
  return expanded ? text : text.slice(0, 420)
}

function sourceDiagnosticHasMore(item: any) {
  return String(item?.full_content || item?.preview || '').length > 420
}

function toggleSearchSourceExpanded(item: any) {
  const key = sourceDiagnosticKey(item)
  expandedSearchSources.value = { ...expandedSearchSources.value, [key]: !expandedSearchSources.value[key] }
}

async function copyText(text: string) {
  const content = String(text || '')
  if (!content.trim()) {
    ElMessage.warning('没有可复制的内容')
    return
  }
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(content)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = content
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      textarea.remove()
    }
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败，请手动选择内容复制')
  }
}

async function copySearchPromptContext() {
  await copyText(String(promptContextPreview.value?.text || ''))
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
  if (type === 'graph_extract') return 'graph_extract'
  if (type === 'graph_rebuild') return 'graph_rebuild'
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
    task?.document_status,
    task?.document_stage,
    task?.document_message,
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
  return ({ document_parse: '文档解析', document_reparse: '重新解析', chat_attachment_parse: '聊天附件解析', page_index: '历史结构索引', page_index_rebuild: '历史结构索引重建', graph_extract: '图谱抽取', graph_rebuild: '重建图谱', ocr: 'OCR 识别' } as Record<string, string>)[String(type || '')] || type || '后台任务'
}

function graphEntityKey(relation: any, role: 'source' | 'target') {
  const id = relation?.[`${role}_entity_id`]
  const name = relation?.[`${role}_entity_name`]
  return String(id || name || '').trim()
}

function graphEntityTypeLabel(type?: string) {
  const value = normalizeText(type || 'entity')
  return ({
    person: '人员',
    user: '人员',
    employee: '员工',
    department: '部门',
    group: '岗位组',
    role: '角色',
    document: '文档',
    policy: '制度',
    process: '流程',
    task: '任务',
    system: '系统',
    entity: '实体',
  } as Record<string, string>)[value] || type || '实体'
}

function graphNodeSize(degree: number) {
  return Math.max(24, Math.min(62, 22 + Math.sqrt(Math.max(degree, 1)) * 9))
}

function graphRelationWidth(confidence?: number) {
  const value = Number(confidence || 0)
  return Math.max(1, Math.min(4, 1 + value * 3))
}

function wikiGraphCommunityColor(community: number) {
  return graphTypePalette[Math.abs(Number(community || 0)) % graphTypePalette.length]
}

function formatWikiGraphWeight(value: any) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '-'
  return num.toFixed(num >= 10 ? 1 : 2)
}

function wikiGraphStrengthLabel(value?: string) {
  return ({ strong: '强关系', medium: '中关系', weak: '弱关系' } as Record<string, string>)[String(value || '')] || '关系'
}

function wikiGraphInsightTypeLabel(value?: string) {
  return ({
    'isolated-node': '低连接页面',
    'broken-link': 'WikiLink断链',
    'sparse-community': '稀疏社区',
    'bridge-node': '桥接页面',
  } as Record<string, string>)[String(value || '')] || value || '洞察'
}

function wikiGraphSignalsText(edge: any) {
  const signals = edge?.signals || {}
  const parts = [
    `直接链接 ${formatWikiGraphWeight(signals.direct_link || 0)}`,
    `共同来源 ${formatWikiGraphWeight(signals.source_overlap || 0)}`,
    `标题提及 ${formatWikiGraphWeight(signals.title_mention || 0)}`,
    `共同邻居 ${formatWikiGraphWeight(signals.common_neighbor || 0)}`,
    `类型亲和 ${formatWikiGraphWeight(signals.type_affinity || 0)}`,
  ]
  return parts.join(' · ')
}

function escapeHtml(value: any) {
  return String(value || '').replace(/[&<>"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' } as Record<string, string>)[char] || char)
}

function graphStatusKind(status?: string): TaskStatusFilter {
  const value = normalizeText(status || 'not_started')
  if (value === 'processing') return 'running'
  if (value === 'ready') return 'done'
  if (value === 'failed') return 'failed'
  return 'pending'
}

function graphStatusLabel(status?: string) {
  return ({ not_started: '未构建', pending: '等待中', processing: '抽取中', ready: '已完成', failed: '失败' } as Record<string, string>)[normalizeText(status || 'not_started')] || status || '未构建'
}

function graphStatusHint(status?: string) {
  return ({ not_started: '尚未开始抽取', pending: '已入队，等待后台处理', processing: '正在抽取实体和关系', ready: '图谱已可用于检索测试', failed: '请查看失败原因并重建' } as Record<string, string>)[normalizeText(status || 'not_started')] || ''
}

function graphRelationStatusLabel(status?: string) {
  return ({ pending: '待审核', confirmed: '已确认', ignored: '已忽略', auto: '自动确认' } as Record<string, string>)[normalizeText(status || 'pending')] || status || '待审核'
}

function graphDocumentSummary(doc: any) {
  const status = normalizeText(doc?.graph?.status || 'not_started')
  if (status === 'ready') {
    return `已抽取完成 · 实体 ${doc?.graph?.entity_count || 0} · 关系 ${doc?.graph?.relation_count || 0}`
  }
  if (status === 'processing') {
    return `抽取中 · 实体 ${doc?.graph?.entity_count || 0} · 关系 ${doc?.graph?.relation_count || 0}`
  }
  if (status === 'failed') {
    return doc?.graph?.error_message || doc?.graph?.message || '图谱构建失败'
  }
  if (status === 'pending') {
    return doc?.graph?.message || '已进入抽取队列'
  }
  return doc?.graph?.message || '尚未构建图谱'
}

function graphDocumentDetail(doc: any) {
  const parts: string[] = []
  const graph = doc?.graph || {}
  if (graph?.updated_at) parts.push(`更新时间 ${formatDateTime(graph.updated_at)}`)
  if (graph?.pending_count !== undefined) parts.push(`待审 ${graph.pending_count || 0}`)
  const task = graphRecentTaskByDoc.value[String(doc?.id || '')]
  if (task?.task_type) parts.push(`最近任务 ${taskTypeLabel(task.task_type)}`)
  if (task?.status) parts.push(`任务状态 ${taskStatusLabel(task.status)}`)
  return parts.join(' · ')
}

function graphDocumentFailure(doc: any) {
  if (normalizeText(doc?.graph?.status || '') !== 'failed') return ''
  return doc?.graph?.error_message || doc?.graph?.message || '图谱构建失败'
}

function formatDateTime(value?: string | null) {
  if (!value) return '未知时间'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}

function wikiPageTypeLabel(type?: string) {
  return ({ source: '来源页', concept: '概念页', rule: '规则页', entity: '实体页', workflow: '流程页', faq: '问答页', document: '文档页' } as Record<string, string>)[normalizeText(type || '')] || type || 'Wiki页面'
}

function wikiPageStatusLabel(status?: string) {
  return ({ published: '已发布', draft: '草稿', archived: '已归档' } as Record<string, string>)[normalizeText(status || '')] || status || '未知'
}

function wikiPageStatusClass(status?: string) {
  const value = normalizeText(status || '')
  if (value === 'published') return 'resolved'
  if (value === 'draft') return 'reviewed'
  if (value === 'archived') return 'ignored'
  return 'new'
}

function wikiHealthSeverityLabel(severity?: string) {
  return ({ error: '错误', warning: '警告', info: '提示' } as Record<string, string>)[normalizeText(severity || '')] || severity || '提示'
}

function wikiHealthSeverityClass(severity?: string) {
  const value = normalizeText(severity || '')
  if (value === 'error') return 'new'
  if (value === 'warning') return 'reviewed'
  return 'resolved'
}

function wikiHealthRuleLabel(rule?: string) {
  return ({
    'missing-source': '缺少来源',
    'missing-summary': '缺少摘要',
    'empty-page': '页面过短',
    'low-confidence': '低置信度',
    'stale-page': '页面过期',
    'source-marker-out-of-range': '来源编号越界',
    'low-citation-coverage': '引用覆盖不足',
    'broken-wikilink': 'WikiLink断链',
    'broken-page-link': '持久化链接断链',
    'orphan-page': '孤页',
    'no-backlink': '无反链',
    'duplicate-title': '标题重复',
    'compile-failed': '编译失败',
  } as Record<string, string>)[String(rule || '')] || rule || '健康检查'
}

function wikiIndexForPage(page: any) {
  return wikiIndexBySlug.value[String(page?.slug || '')] || null
}

function wikiLogActionLabel(action?: string) {
  return ({
    'wiki.compile.document': '编译单文档',
    'wiki.compile.all': '批量编译',
    'wiki.lint': '运行 Lint',
    'wiki.search_test': '检索测试',
  } as Record<string, string>)[String(action || '')] || action || 'Wiki操作'
}

function wikiLogDetailSummary(item: any) {
  const detail = item?.detail || {}
  if (item?.action === 'wiki.lint') return `评分 ${detail.score ?? '-'} · 问题 ${detail.finding_count ?? 0} · 孤页 ${detail.orphan_page_count ?? 0}`
  if (item?.action === 'wiki.search_test') return `问题：${detail.query || '-'} · 命中 ${detail.context_count ?? 0}/${detail.candidate_count ?? 0} · ${detail.reason || '-'}`
  if (item?.action === 'wiki.compile.all') return `文档 ${detail.document_count ?? detail.compiled_count ?? '-'} · 编译 ${detail.compiled_count ?? '-'} 页/批次`
  if (item?.action === 'wiki.compile.document') return `文档 ${item?.resource_id || '-'} · 页面 ${detail.page_count ?? '-'} · derived ${detail.derived_page_count ?? '-'}`
  return item?.resource_id || '-'
}

function wikiCompileMessage(result: any) {
  const compiled = result?.compiled_count ?? result?.success_count ?? result?.ready_count ?? result?.page_count
  const skipped = result?.skipped_count ?? result?.unchanged_count
  const failed = result?.failed_count ?? result?.error_count
  const parts = [
    compiled !== undefined ? `编译 ${compiled}` : '',
    skipped !== undefined ? `跳过 ${skipped}` : '',
    failed !== undefined ? `失败 ${failed}` : '',
  ].filter(Boolean)
  return parts.length ? `Wiki编译完成：${parts.join('，')}` : 'Wiki编译任务已完成'
}

function feedbackStatusKind(item: any): FeedbackStatusFilter {
  const status = normalizeText(item?.status || 'new')
  if (status === 'reviewed' || status === 'resolved' || status === 'ignored') return status as FeedbackStatusFilter
  return 'new'
}

function feedbackStatusLabel(status?: string) {
  return ({ new: '待处理', reviewed: '已查看', resolved: '已解决', ignored: '已忽略' } as Record<string, string>)[normalizeText(status || 'new')] || status || '待处理'
}

function feedbackRatingLabel(rating?: string) {
  return ({ helpful: '有帮助', unhelpful: '不够好', wrong: '错误', unsafe: '安全问题', other: '其他', user_feedback: '用户补充' } as Record<string, string>)[normalizeText(rating || '')] || rating || '反馈'
}

function feedbackCategoryLabel(category?: string) {
  return ({ incorrect: '答案错误', missing_source: '缺少来源', not_helpful: '不够好', other: '其他' } as Record<string, string>)[normalizeText(category || '')] || category || '其他'
}

function feedbackRootCauseLabel(value?: string) {
  const cause = String(value || '') as FeedbackRootCause
  return feedbackRootCauseOptions.find((item) => item.value === cause)?.label || '未归因'
}

function feedbackRootCauseClass(value?: string) {
  return value ? 'has-cause' : 'empty'
}

function feedbackSourceCount(item: any) {
  return Array.isArray(item?.sources) ? item.sources.length : 0
}

function feedbackStatusCount(status: FeedbackStatusFilter) {
  if (status === 'all') return feedbackItems.value.length
  return feedbackItems.value.filter((item: any) => feedbackStatusKind(item) === status).length
}

function feedbackCreatedTime(item: any) {
  return item?.created_at ? formatDateTime(item.created_at) : '-'
}

function feedbackSourceTitle(source: any) {
  return source?.document_title || source?.title || source?.filename || source?.document_id || '未知来源'
}

function docStageLabel(doc: any) {
  return stageText(doc?.stage)
}

function requestErrorDetail(err: any, fallback: string) {
  const detail = err?.response?.data?.detail || err?.response?.data?.message || err?.message || fallback
  const status = err?.response?.status
  return status ? `${detail}（HTTP ${status}）` : detail
}

async function loadDocumentQualityMap() {
  try {
    const { data } = await http.get('/admin/document-quality', { params: { limit: 200 } })
    const map: Record<string, any> = {}
    for (const report of data?.reports || []) {
      const id = String(report?.document?.id || '')
      if (id) map[id] = report
    }
    documentQualityMap.value = map
  } catch {
    // 质量报告失败不影响主列表渲染
  }
}

async function load() {
  try {
    groups.value = (await http.get('/admin/groups')).data || []
    users.value = (await http.get('/admin/users')).data || []
    await loadRoutingConfig()
    docs.value = (await http.get('/admin/documents')).data || []
    docs.value.forEach((d: any) => {
      docGroupMap[d.id] = (d.groups || []).map((g: any) => g.id)
    })
    await loadModelConfig()
    await loadTasks(false)
    await loadFeedback(false)
    await loadEvaluationOverview(false)
    await loadOperationsOverview(false)
    await loadPromptTemplates(false)
    await loadWikiAdminData(false)
    await loadWikiGraphData(false)
    await loadGraphData(false)
    await loadVectorStatus()
    await loadDocumentQualityMap()
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
  await loadGraphData(false)
  await loadVectorStatus()
  await loadDocumentQualityMap()
  await loadOperationsOverview(false)
  lastRefreshAt.value = new Date()
}

function removeDocumentFromLocalState(documentId: string) {
  const id = String(documentId || '')
  if (!id) return
  docs.value = docs.value.filter((item: any) => String(item?.id) !== id)
  tasks.value = tasks.value.filter((item: any) => String(item?.document_id) !== id)
  graphDocuments.value = graphDocuments.value.filter((item: any) => String(item?.id) !== id)
  graphRelations.value = graphRelations.value.filter((item: any) => String(item?.source_document_id) !== id)
  graphPreviewRelations.value = graphPreviewRelations.value.filter((item: any) => String(item?.source_document_id) !== id)
  delete documentQualityMap.value[id]
  delete docGroupMap[id]
  if (lastUploadSummary.value?.docId && String(lastUploadSummary.value.docId) === id) lastUploadSummary.value = null

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

function hasActiveTasks() {
  return tasks.value.some((task: any) => ['pending', 'running'].includes(taskStatusKind(task)))
}

function stopTaskPolling() {
  if (taskPollTimer) window.clearInterval(taskPollTimer)
  taskPollTimer = null
  taskPolling.value = false
}

function ensureTaskPolling() {
  if (!hasActiveTasks()) {
    stopTaskPolling()
    return
  }
  taskPolling.value = true
  if (!taskPollTimer) {
    taskPollTimer = window.setInterval(() => pollTasks(), TASK_POLL_INTERVAL_MS)
  }
}

async function pollTasks() {
  try {
    await loadTasks(false, true)
  } catch {
    // loadTasks 已负责用户可见错误提示；轮询失败时下次继续尝试
  }
}

function jumpToTab(name: string) {
  adminTabIndex.value = name
  if (name === 'wiki' && !wikiPages.value.length) void loadWikiAdminData(false)
  if (name === 'graph') renderGraphChart()
  if (name === 'wikiGraph') renderWikiGraphChart()
}

watch(adminTabIndex, (name) => {
  if (name === 'wiki' && !wikiPages.value.length) void loadWikiAdminData(false)
  if (name === 'graph') renderGraphChart()
  if (name === 'wikiGraph') renderWikiGraphChart()
})

watch(graphVisibleRelations, () => {
  if (adminTabIndex.value === 'graph') renderGraphChart()
})

watch(wikiGraphNetworkData, () => {
  if (adminTabIndex.value === 'wikiGraph') renderWikiGraphChart()
})


async function loadVectorStatus() {
  try {
    vectorStatus.value = (await http.get('/admin/vector/status')).data || null
  } catch (err: any) {
    vectorStatus.value = { backend: 'unknown', qdrant_enabled: false, qdrant_ready: false, degraded: true, status: 'unknown', message: requestErrorDetail(err, '向量库状态读取失败') }
  }
}

async function loadRoutingConfig() {
  try {
    const data = (await http.get('/admin/document-routing/config')).data || {}
    const options = Array.isArray(data.document_kind_options) ? data.document_kind_options : []
    const configuredKinds = Array.isArray(data.config?.document_kinds) ? data.config.document_kinds : []
    routingDocumentKindOptions.value = options.length
      ? options
      : configuredKinds.filter((item: any) => !item?.disabled).map((item: any) => ({ value: String(item?.value || ''), label: String(item?.label || item?.value || '') })).filter((item: any) => item.value)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载文档类型失败')
  }
}

async function updateDocumentClassification(doc: any, value: string) {
  if (!doc?.id || !value || String(doc.document_kind || '') === String(value)) return
  try {
    const data = (await http.put(`/admin/documents/${doc.id}/classification`, { document_kind: value })).data || {}
    doc.document_kind = data.document_kind || value
    doc.document_kind_confidence = data.document_kind_confidence ?? 1
    doc.document_kind_status = data.document_kind_status || 'confirmed'
    doc.document_kind_reason = 'manual'
    ElMessage.success('文档类型已确认')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '更新文档类型失败')
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

function formatPercent(value: any) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '-'
  return `${Math.round(num * 100)}%`
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

function formatTableMetrics(value: any) {
  if (!Array.isArray(value) || !value.length) return ''
  return value
    .map((item: any) => item?.label || [item?.op, item?.column].filter(Boolean).join(':'))
    .filter(Boolean)
    .slice(0, 8)
    .join('、')
}

function formatTableSchema(value: any) {
  if (!value || typeof value !== 'object') return ''
  const entries = Object.values(value)
    .flatMap((items: any) => Array.isArray(items) ? items : [])
    .map((item: any) => `${item?.semantic_name || item?.label || 'field'}=${item?.raw_name || '-'}`)
    .filter(Boolean)
  return [...new Set(entries)].slice(0, 8).join('；')
}

function formatTableSchemaSuggestions(value: any) {
  if (!value || typeof value !== 'object') return ''
  const entries = Object.values(value)
    .flatMap((items: any) => Array.isArray(items) ? items : [])
    .map((item: any) => schemaSuggestionLabel(item))
    .filter(Boolean)
  return [...new Set(entries)].slice(0, 8).join('；')
}

function schemaSuggestionLabel(item: any) {
  const label = item?.label || item?.semantic_name || 'field'
  const rawName = item?.raw_name || '-'
  const confidence = formatRetrievalScore(item?.confidence)
  const status = item?.status && item.status !== 'suggested' ? ` · ${item.status}` : ''
  return `${label}←${rawName} (${confidence})${status}`
}

function schemaSuggestionBusyKey(item: any) {
  return String(item?.suggestion_key || `${item?.document_id || ''}:${item?.semantic_name || ''}:${item?.raw_name || ''}`)
}

async function saveTableSchemaSuggestion(item: any, action: 'confirm' | 'ignore') {
  const busyKey = schemaSuggestionBusyKey(item)
  schemaAliasActionBusy.value = busyKey
  try {
    await http.post(`/admin/table-schema-aliases/${action}`, {
      document_id: item?.document_id || '',
      sheet_name: item?.sheet_name || '',
      raw_name: item?.raw_name || '',
      semantic_name: item?.semantic_name || '',
      suggestion_key: item?.suggestion_key || '',
      confidence: Number(item?.confidence || 0),
      reasons: Array.isArray(item?.reasons) ? item.reasons : [],
      samples: Array.isArray(item?.samples) ? item.samples : [],
    })
    ElMessage.success(action === 'confirm' ? 'schema 映射已确认' : 'schema 建议已忽略')
    if (searchTestForm.question.trim()) await runSearchTest()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || 'schema 建议处理失败')
  } finally {
    schemaAliasActionBusy.value = ''
  }
}

async function runSearchTest() {
  const question = searchTestForm.question.trim()
  if (!question) {
    ElMessage.warning('请输入要测试的检索问题')
    return
  }
  searchTesting.value = true
  searchTestResult.value = null
  searchContextPreviewOpen.value = false
  expandedSearchSources.value = {}
  try {
    const { data } = await http.post('/admin/search-test', {
      question,
      top_k: Number(searchTestForm.top_k) || 8,
      knowledge_scope: searchTestForm.knowledge_scope || 'production',
    })
    searchTestResult.value = data || null
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '检索测试失败')
  } finally {
    searchTesting.value = false
  }
}
async function loadTasks(showMessage = true, fromPolling = false) {
  if (loadingTasks.value && fromPolling) return
  loadingTasks.value = true
  try {
    tasks.value = (await http.get('/admin/tasks', { params: { limit: 500 } })).data || []
    taskLastRefreshAt.value = new Date()
    if (showMessage) ElMessage.success('后台任务已刷新')
    if (!fromPolling || taskPolling.value) ensureTaskPolling()
  } catch (err: any) {
    if (!fromPolling) ElMessage.error(err?.response?.data?.detail || '加载后台任务失败')
  } finally {
    loadingTasks.value = false
  }
}

async function loadOperationsOverview(showMessage = true) {
  loadingOperations.value = true
  try {
    operationsOverview.value = (await http.get('/admin/operations/overview', { params: { days: 30 } })).data || null
    if (showMessage) ElMessage.success('运营数据已刷新')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载运营数据失败')
  } finally {
    loadingOperations.value = false
  }
}

async function loadPromptTemplates(showMessage = false) {
  try {
    const data = (await http.get('/admin/prompt-templates')).data || {}
    promptTemplates.value = Array.isArray(data.templates) ? data.templates : []
    promptTemplatesDirty.value = false
    if (showMessage) ElMessage.success('Prompt 模板已刷新')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载 Prompt 模板失败')
  }
}

function markPromptTemplatesDirty() {
  promptTemplatesDirty.value = true
}

async function savePromptTemplates() {
  savingPromptTemplates.value = true
  try {
    const data = (await http.put('/admin/prompt-templates', { templates: promptTemplates.value })).data || {}
    promptTemplates.value = Array.isArray(data.templates) ? data.templates : promptTemplates.value
    promptTemplatesDirty.value = false
    ElMessage.success('Prompt 模板已保存')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '保存 Prompt 模板失败')
  } finally {
    savingPromptTemplates.value = false
  }
}

async function previewPromptTemplate() {
  const question = String(promptPreviewForm.question || '').trim()
  if (!question) {
    ElMessage.error('请输入要预览的问题')
    return
  }
  promptPreviewLoading.value = true
  promptPreviewResult.value = null
  try {
    promptPreviewResult.value = (await http.post('/admin/prompt-templates/preview', {
      question,
      top_k: Number(promptPreviewForm.top_k) || 8,
      knowledge_scope: promptPreviewForm.knowledge_scope,
    })).data || null
    ElMessage.success('Prompt 模板预览完成')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || 'Prompt 模板预览失败')
  } finally {
    promptPreviewLoading.value = false
  }
}

function formatPromptPreviewKinds(items: any[]) {
  if (!Array.isArray(items) || !items.length) return ''
  return items.map((item: any) => `${item.label || item.kind} ${item.count || 0}`).join('、')
}

function promptTemplateLabel(key: string) {
  const item = promptTemplates.value.find((template: any) => String(template?.key || '') === String(key || ''))
  return item?.label || key || '-'
}

function promptTemplateLabels(keys: any[]) {
  if (!Array.isArray(keys) || !keys.length) return '-'
  return keys.map((key) => promptTemplateLabel(String(key))).join('、')
}

function formatPromptTemplateRecommendations(items: any[]) {
  if (!Array.isArray(items) || !items.length) return '-'
  return items
    .map((item: any) => `${item.kind || 'general'} → ${promptTemplateLabel(String(item.key || ''))}（胜出 ${item.wins || 0} 次）`)
    .join('、')
}

async function comparePromptTemplates() {
  const question = String(promptCompareForm.question || '').trim()
  if (!question) {
    ElMessage.error('请输入要对比的问题')
    return
  }
  if (!promptCompareForm.template_a_keys.length || !promptCompareForm.template_b_keys.length) {
    ElMessage.error('请选择 A/B 两组模板')
    return
  }
  promptCompareLoading.value = true
  promptCompareResult.value = null
  try {
    promptCompareResult.value = (await http.post('/admin/prompt-templates/compare', {
      question,
      template_a_keys: promptCompareForm.template_a_keys,
      template_b_keys: promptCompareForm.template_b_keys,
      top_k: Number(promptCompareForm.top_k) || 8,
      knowledge_scope: promptCompareForm.knowledge_scope,
      dry_run: Boolean(promptCompareForm.dry_run),
    })).data || null
    ElMessage.success('Prompt 模板 A/B 对比完成')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || 'Prompt 模板 A/B 对比失败')
  } finally {
    promptCompareLoading.value = false
  }
}

async function adoptPromptVariant(variant: 'a' | 'b') {
  if (!promptCompareResult.value) {
    ElMessage.error('请先运行 A/B 对比')
    return
  }
  const selectedKeys = variant === 'a' ? promptCompareForm.template_a_keys : promptCompareForm.template_b_keys
  const rejectedKeys = variant === 'a' ? promptCompareForm.template_b_keys : promptCompareForm.template_a_keys
  promptAdoptionSaving.value = variant
  try {
    const data = (await http.post('/admin/prompt-templates/adoptions', {
      question: promptCompareResult.value.question || promptCompareForm.question,
      selected_variant: variant,
      selected_template_keys: selectedKeys,
      rejected_template_keys: rejectedKeys,
      document_kinds: (promptCompareResult.value.source_diagnostics || []).map((item: any) => item.document_kind).filter(Boolean),
      source_document_ids: (promptCompareResult.value.source_diagnostics || []).map((item: any) => item.document_id).filter(Boolean),
      admin_note: promptAdoptionNote.value,
      dry_run: Boolean(promptCompareResult.value.dry_run),
    })).data || {}
    if (operationsOverview.value) operationsOverview.value.prompt_adoptions = data.stats || operationsOverview.value.prompt_adoptions
    promptAdoptionNote.value = ''
    ElMessage.success(`已采用 ${variant.toUpperCase()} 组模板`)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '记录采用结果失败')
  } finally {
    promptAdoptionSaving.value = ''
  }
}

async function resetPromptTemplates() {
  try {
    await ElMessageBox.confirm('将恢复默认 Prompt 模板，并覆盖当前模板内容。确定继续？', '恢复默认模板', { type: 'warning' })
  } catch {
    return
  }
  savingPromptTemplates.value = true
  try {
    const data = (await http.post('/admin/prompt-templates/reset')).data || {}
    promptTemplates.value = Array.isArray(data.templates) ? data.templates : []
    promptTemplatesDirty.value = false
    ElMessage.success('已恢复默认 Prompt 模板')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '恢复默认模板失败')
  } finally {
    savingPromptTemplates.value = false
  }
}

async function createEvaluationCase() {
  const question = String(evaluationNewCase.question || '').trim()
  if (!question) {
    ElMessage.error('请输入评测问题')
    return
  }
  savingEvaluationCase.value = true
  try {
    await http.post('/admin/evaluation/cases', {
      id: evaluationNewCase.id,
      category: evaluationNewCase.category,
      question,
      why: evaluationNewCase.why,
      top_k: Number(evaluationNewCase.top_k) || 8,
    })
    evaluationNewCase.id = ''
    evaluationNewCase.category = '后台维护'
    evaluationNewCase.question = ''
    evaluationNewCase.why = ''
    evaluationNewCase.top_k = 8
    await loadEvaluationOverview(false)
    ElMessage.success('评测用例已新增')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '新增评测用例失败')
  } finally {
    savingEvaluationCase.value = false
  }
}

async function deleteEvaluationCase(item: any) {
  if (item?.source !== 'custom') {
    ElMessage.warning('内置文件用例不能在后台删除')
    return
  }
  try {
    await ElMessageBox.confirm(`确定删除评测用例「${item.id || item.question}」？`, '删除评测用例', { type: 'warning' })
  } catch {
    return
  }
  try {
    await http.delete(`/admin/evaluation/cases/${item.id}`)
    await loadEvaluationOverview(false)
    ElMessage.success('评测用例已删除')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '删除评测用例失败')
  }
}

async function loadEvaluationOverview(showMessage = true) {
  loadingEvaluation.value = true
  try {
    evaluationOverview.value = (await http.get('/admin/evaluation/overview', { params: { days: 30 } })).data || null
    if (showMessage) ElMessage.success('评测面板已刷新')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载评测面板失败')
  } finally {
    loadingEvaluation.value = false
  }
}

function initGraphChart() {
  if (!graphChartRef.value) return null
  if (!graphChart) {
    graphChart = echarts.init(graphChartRef.value)
    graphChart.on('click', (params: any) => {
      if (params?.dataType === 'node' && params?.data?.id) {
        graphSelectedNode.value = graphSelectedNode.value === params.data.id ? '' : params.data.id
      }
    })
    graphResizeObserver = new ResizeObserver(() => graphChart?.resize())
    graphResizeObserver.observe(graphChartRef.value)
  }
  return graphChart
}

function renderGraphChart() {
  nextTick(() => {
    if (adminTabIndex.value !== 'graph' || !graphVisibleRelations.value.length) return
    const chart = initGraphChart()
    if (!chart) return
    const data = graphNetworkData.value
    const option: EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        confine: true,
        formatter: (params: any) => {
          if (params.dataType === 'edge') {
            const relation = params.data?.relation || {}
            return `<div class="admin-graph-tooltip"><strong>${escapeHtml(relation.relation_type || '关联')}</strong><br/>${escapeHtml(relation.source_entity_name)} → ${escapeHtml(relation.target_entity_name)}<br/><small>${escapeHtml(relation.source_document_title || relation.source_document_filename || '未知文档')} · ${escapeHtml(graphRelationStatusLabel(relation.status))} · 置信度 ${escapeHtml(formatRetrievalScore(relation.confidence))}</small></div>`
          }
          return `<div class="admin-graph-tooltip"><strong>${escapeHtml(params.data?.name || '实体')}</strong><br/><small>${escapeHtml(params.data?.category || '实体')} · 连接 ${escapeHtml(params.data?.value || 0)}</small></div>`
        },
      },
      legend: [{
        top: 0,
        left: 0,
        itemWidth: 10,
        itemHeight: 10,
        textStyle: { color: '#475569', fontSize: 11 },
        data: graphEntityTypeCategories.value.map((item) => item.name),
      }],
      series: [{
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        top: 34,
        bottom: 12,
        left: 8,
        right: 8,
        data: data.nodes,
        links: data.links,
        categories: graphEntityTypeCategories.value,
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: 7,
        label: {
          show: true,
          position: 'right',
          formatter: '{b}',
          color: '#1f2937',
          fontSize: 11,
        },
        edgeLabel: {
          show: true,
          formatter: '{b}',
          color: '#64748b',
          fontSize: 10,
        },
        force: {
          repulsion: 180,
          edgeLength: [70, 150],
          gravity: 0.08,
          friction: 0.35,
        },
        emphasis: {
          focus: 'adjacency',
          lineStyle: { width: 4 },
        },
        lineStyle: {
          color: '#94a3b8',
          curveness: 0.18,
        },
      }],
    }
    chart.setOption(option, true)
    graphChart?.resize()
  })
}

function disposeGraphChart() {
  graphResizeObserver?.disconnect()
  graphResizeObserver = null
  graphChart?.dispose()
  graphChart = null
}

function initWikiGraphChart() {
  if (!wikiGraphChartRef.value) return null
  if (!wikiGraphChart) {
    wikiGraphChart = echarts.init(wikiGraphChartRef.value)
    wikiGraphChart.on('click', (params: any) => {
      if (params?.dataType === 'node' && params?.data?.id) {
        wikiGraphSelectedNode.value = wikiGraphSelectedNode.value === params.data.id ? '' : params.data.id
      }
    })
    wikiGraphResizeObserver = new ResizeObserver(() => wikiGraphChart?.resize())
    wikiGraphResizeObserver.observe(wikiGraphChartRef.value)
  }
  return wikiGraphChart
}

function renderWikiGraphChart() {
  nextTick(() => {
    if (adminTabIndex.value !== 'wikiGraph' || !wikiGraphNodes.value.length) return
    const chart = initWikiGraphChart()
    if (!chart) return
    const data = wikiGraphNetworkData.value
    const option: EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        confine: true,
        formatter: (params: any) => {
          if (params.dataType === 'edge') {
            const edge = params.data?.edge || {}
            const rawTargets = Array.isArray(edge.raw_targets) ? edge.raw_targets.join('、') : ''
            const mentionTerms = Array.isArray(edge.title_mention_terms) ? edge.title_mention_terms.slice(0, 6).join('、') : ''
            return `<div class="admin-graph-tooltip"><strong>${escapeHtml(wikiGraphStrengthLabel(edge.strength))} · 权重 ${escapeHtml(formatWikiGraphWeight(edge.weight))}</strong><br/>${escapeHtml(edge.source_title || edge.source)} ↔ ${escapeHtml(edge.target_title || edge.target)}<br/><small>显式链接 ${escapeHtml(edge.mentions || 0)} 次 · 标题提及 ${escapeHtml(edge.title_mentions || 0)} 次 · 共同来源 ${escapeHtml(edge.shared_source_count || 0)}${rawTargets ? ' · ' + escapeHtml(rawTargets) : ''}${mentionTerms ? ' · 匹配：' + escapeHtml(mentionTerms) : ''}<br/>${escapeHtml(wikiGraphSignalsText(edge))}</small></div>`
          }
          const page = params.data?.page || {}
          return `<div class="admin-graph-tooltip"><strong>${escapeHtml(params.data?.name || 'Wiki页面')}</strong><br/><small>${escapeHtml(params.data?.category || 'Wiki页面')} · ${escapeHtml(page.community_label || '社区 1')} · 连接 ${escapeHtml(params.data?.value || 0)} · 来源 ${escapeHtml(page.source_count || 0)}</small></div>`
        },
      },
      legend: [{
        top: 0,
        left: 0,
        itemWidth: 10,
        itemHeight: 10,
        textStyle: { color: '#475569', fontSize: 11 },
        data: wikiGraphPageTypeCategories.value.map((item) => item.name),
      }],
      series: [{
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        top: 34,
        bottom: 12,
        left: 8,
        right: 8,
        data: data.nodes,
        links: data.links,
        categories: wikiGraphPageTypeCategories.value,
        edgeSymbol: ['none', 'none'],
        label: {
          show: true,
          position: 'right',
          formatter: '{b}',
          color: '#1f2937',
          fontSize: 11,
        },
        edgeLabel: {
          show: true,
          formatter: '{b}',
          color: '#64748b',
          fontSize: 10,
        },
        force: {
          repulsion: 170,
          edgeLength: [80, 170],
          gravity: 0.08,
          friction: 0.35,
        },
        emphasis: {
          focus: 'adjacency',
          lineStyle: { width: 4 },
        },
        lineStyle: {
          color: '#94a3b8',
          curveness: 0.12,
        },
      }],
    }
    chart.setOption(option, true)
    wikiGraphChart?.resize()
  })
}

function disposeWikiGraphChart() {
  wikiGraphResizeObserver?.disconnect()
  wikiGraphResizeObserver = null
  wikiGraphChart?.dispose()
  wikiGraphChart = null
}

async function loadWikiPageDetail(page: any, showMessage = false) {
  const id = String(page?.id || page || '')
  if (!id) return
  wikiPageDetailLoading.value = true
  try {
    wikiSelectedPage.value = (await http.get(`/admin/wiki/pages/${id}`)).data || null
    if (showMessage) ElMessage.success('Wiki页面详情已加载')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载Wiki页面详情失败')
  } finally {
    wikiPageDetailLoading.value = false
  }
}

async function loadWikiAdminData(showMessage = true) {
  loadingWikiAdmin.value = true
  try {
    const [statusResp, pagesResp, healthResp, indexResp, logsResp] = await Promise.all([
      http.get('/admin/wiki/status', { params: { knowledge_scope: 'production' } }),
      http.get('/admin/wiki/pages', { params: { knowledge_scope: 'production', limit: 300 } }),
      http.get('/admin/wiki/health', { params: { knowledge_scope: 'production' } }),
      http.get('/admin/wiki/index', { params: { knowledge_scope: 'production', status: 'published', limit: 500 } }),
      http.get('/admin/wiki/logs', { params: { knowledge_scope: 'production', limit: 50 } }),
    ])
    wikiStatus.value = statusResp.data || null
    wikiPages.value = Array.isArray(pagesResp.data?.items) ? pagesResp.data.items : []
    wikiHealth.value = healthResp.data || null
    wikiIndex.value = indexResp.data || null
    wikiLogsPayload.value = logsResp.data || null
    const currentId = String(wikiSelectedPage.value?.id || '')
    const nextPage = (currentId && wikiPages.value.find((item: any) => String(item?.id) === currentId)) || wikiPages.value[0]
    if (nextPage) await loadWikiPageDetail(nextPage, false)
    else wikiSelectedPage.value = null
    if (showMessage) ElMessage.success('Wiki管理数据已刷新')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载Wiki管理数据失败')
  } finally {
    loadingWikiAdmin.value = false
  }
}

async function runWikiLint() {
  wikiLintLoading.value = true
  try {
    wikiHealth.value = (await http.get('/admin/wiki/lint', { params: { knowledge_scope: 'production' } })).data || null
    const [indexResp, logsResp] = await Promise.all([
      http.get('/admin/wiki/index', { params: { knowledge_scope: 'production', status: 'published', limit: 500 } }),
      http.get('/admin/wiki/logs', { params: { knowledge_scope: 'production', limit: 50 } }),
    ])
    wikiIndex.value = indexResp.data || null
    wikiLogsPayload.value = logsResp.data || null
    ElMessage.success('Wiki Lint 已完成并记录到操作日志')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '运行 Wiki Lint 失败')
  } finally {
    wikiLintLoading.value = false
  }
}

async function compileAllWiki() {
  try {
    await ElMessageBox.confirm('将把生产范围内可编译文档重新生成 Wiki 页面，并刷新健康检查与图谱。确定继续？', '编译生产Wiki', {
      confirmButtonText: '开始编译',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  compilingWiki.value = true
  try {
    const { data } = await http.post('/admin/wiki/compile-all', null, { params: { knowledge_scope: 'production', limit: 100 } })
    ElMessage.success(wikiCompileMessage(data || {}))
    await loadWikiAdminData(false)
    await loadWikiGraphData(false)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || 'Wiki编译失败')
  } finally {
    compilingWiki.value = false
  }
}

async function runWikiSearchTest() {
  const question = wikiSearchForm.question.trim()
  if (!question) {
    ElMessage.warning('请输入要测试的 Wiki 问题')
    return
  }
  wikiSearchLoading.value = true
  wikiSearchResult.value = null
  try {
    wikiSearchResult.value = (await http.get('/admin/wiki/search-test', {
      params: {
        q: question,
        top_k: Number(wikiSearchForm.top_k) || 5,
        knowledge_scope: wikiSearchForm.knowledge_scope || 'production',
      },
    })).data || null
    wikiLogsPayload.value = (await http.get('/admin/wiki/logs', { params: { knowledge_scope: wikiSearchForm.knowledge_scope || 'production', limit: 50 } })).data || null
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || 'Wiki检索测试失败')
  } finally {
    wikiSearchLoading.value = false
  }
}

async function loadWikiGraphData(showMessage = true) {
  loadingWikiGraph.value = true
  try {
    wikiGraph.value = (await http.get('/admin/wiki/graph', { params: { knowledge_scope: 'production', status: 'published', limit: 500 } })).data || null
    if (!wikiGraphEdges.value.some((edge: any) => edge?.source === wikiGraphSelectedNode.value || edge?.target === wikiGraphSelectedNode.value)) wikiGraphSelectedNode.value = ''
    renderWikiGraphChart()
    if (showMessage) ElMessage.success('Wiki图谱数据已刷新')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载Wiki图谱失败')
  } finally {
    loadingWikiGraph.value = false
  }
}

async function loadGraphData(showMessage = true) {
  loadingGraph.value = true
  try {
    const [overviewResp, docsResp, pendingRelationsResp, previewRelationsResp] = await Promise.all([
      http.get('/admin/graph/overview'),
      http.get('/admin/graph/documents', { params: { limit: 200 } }),
      http.get('/admin/graph/relations', { params: { status: 'pending', limit: 100 } }),
      http.get('/admin/graph/relations', { params: { limit: 120 } }),
    ])
    graphOverview.value = overviewResp.data || null
    graphDocuments.value = docsResp.data || []
    graphRelations.value = pendingRelationsResp.data || []
    graphPreviewRelations.value = (previewRelationsResp.data || []).filter((item: any) => item?.status !== 'ignored')
    if (!graphVisibleRelations.value.length) graphSelectedNode.value = ''
    renderGraphChart()
    if (showMessage) ElMessage.success('图谱数据已刷新')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载图谱数据失败')
  } finally {
    loadingGraph.value = false
  }
}

async function runGraphSearchTest() {
  const question = graphSearchForm.question.trim()
  if (!question) {
    ElMessage.warning('请输入要测试的图谱问题')
    return
  }
  graphSearchLoading.value = true
  graphSearchResult.value = null
  try {
    graphSearchResult.value = (await http.post('/admin/graph/search-test', { question, top_k: Number(graphSearchForm.top_k) || 8 })).data || null
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '图谱搜索测试失败')
  } finally {
    graphSearchLoading.value = false
  }
}

async function rebuildDocumentGraph(doc: any) {
  if (!doc?.id) return
  rebuildingGraphDocId.value = doc.id
  try {
    await http.post(`/admin/documents/${doc.id}/graph/rebuild`)
    ElMessage.success('图谱重建任务已入队')
    await loadGraphData(false)
    await loadTasks(false)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '图谱重建入队失败')
  } finally {
    rebuildingGraphDocId.value = null
  }
}

async function reviewGraphRelation(relation: any, status: 'confirmed' | 'ignored') {
  if (!relation?.id) return
  try {
    await http.put(`/admin/graph/relations/${relation.id}`, { status })
    ElMessage.success(status === 'confirmed' ? '已确认关系' : '已忽略关系')
    await loadGraphData(false)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '更新图谱关系失败')
  }
}

function fillEvaluationQuestion(item: any) {
  evaluationForm.question = String(item?.question || '')
  evaluationForm.top_k = Number(item?.top_k || evaluationForm.top_k || 8)
}

async function runEvaluationCase() {
  const question = String(evaluationForm.question || '').trim()
  if (!question) {
    ElMessage.error('请输入评测问题')
    return
  }
  evaluationCaseRunning.value = true
  evaluationCaseResult.value = null
  try {
    evaluationCaseResult.value = (await http.post('/admin/evaluation/run-case', { question, top_k: Number(evaluationForm.top_k) || 8 })).data || null
    ElMessage.success('单题评测完成')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '单题评测失败')
  } finally {
    evaluationCaseRunning.value = false
  }
}

async function runEvaluationCaseFromResult(item: any) {
  fillEvaluationQuestion(item)
  await runEvaluationCase()
}

async function runEvaluationSuite() {
  evaluationSuiteRunning.value = true
  evaluationSuiteResult.value = null
  try {
    evaluationSuiteResult.value = (await http.post('/admin/evaluation/run-suite', null, { params: { limit: 50 } })).data || null
    const result = evaluationSuiteResult.value || {}
    if (result.ok) ElMessage.success(`真实评测通过：${result.passed || 0}/${result.total || 0}`)
    else ElMessage.warning(`真实评测存在失败：${result.failed || 0} 个失败用例`)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '运行真实评测失败')
  } finally {
    evaluationSuiteRunning.value = false
  }
}

async function loadFeedback(showMessage = true) {
  loadingFeedback.value = true
  try {
    feedbackItems.value = (await http.get('/admin/feedback', { params: { summary: true, limit: 300 } })).data || []
    if (showMessage) ElMessage.success('反馈列表已刷新')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载反馈列表失败')
  } finally {
    loadingFeedback.value = false
  }
}

async function openFeedbackDetail(item: any) {
  if (!item?.id) return
  feedbackDetailVisible.value = true
  feedbackDetailLoading.value = true
  feedbackDetail.value = null
  feedbackReviewNote.value = ''
  feedbackRootCause.value = ''
  feedbackCompareResult.value = null
  try {
    feedbackDetail.value = (await http.get(`/admin/feedback/${item.id}`)).data || null
    feedbackReviewNote.value = feedbackDetail.value?.admin_note || feedbackDetail.value?.review_note || ''
    feedbackRootCause.value = (feedbackDetail.value?.root_cause || '') as FeedbackRootCause
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '加载反馈详情失败')
  } finally {
    feedbackDetailLoading.value = false
  }
}

async function reviewFeedback(status: FeedbackStatusFilter) {
  if (!feedbackDetail.value?.id || status === 'all') return
  feedbackReviewBusy.value = true
  try {
    await http.put(`/admin/feedback/${feedbackDetail.value.id}`, {
      status,
      admin_note: feedbackReviewNote.value,
      review_note: feedbackReviewNote.value,
      root_cause: feedbackRootCause.value,
    })
    ElMessage.success('反馈状态已更新')
    await openFeedbackDetail(feedbackDetail.value)
    await loadFeedback(false)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '处理反馈失败')
  } finally {
    feedbackReviewBusy.value = false
  }
}

async function runFeedbackCompareSearch() {
  const question = String(feedbackDetail.value?.question || '').trim()
  if (!question) return
  feedbackCompareLoading.value = true
  feedbackCompareResult.value = null
  try {
    const { data } = await http.post('/admin/search-test', { question, top_k: 8, knowledge_scope: 'all' })
    feedbackCompareResult.value = data || null
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '反馈检索对照失败')
  } finally {
    feedbackCompareLoading.value = false
  }
}

function runFeedbackQuestionSearch() {
  const question = String(feedbackDetail.value?.question || '').trim()
  if (!question) return
  searchTestForm.question = question
  adminTabIndex.value = 'model'
  runSearchTest()
}

function feedbackSourceKey(source: any) {
  return String(source?.document_id || source?.filename || source?.document_title || source?.title || '')
}

function feedbackCurrentSourceMatched(source: any) {
  const key = feedbackSourceKey(source)
  return Boolean(key && feedbackCompareOverlap.value.matched.includes(key))
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

async function deleteGroup(group: any) {
  if (!group?.id) return
  const memberCount = groupMemberCount(group.id)
  const documentCount = groupDocumentCount(group.id)
  if (memberCount || documentCount) {
    ElMessage.warning(`该岗位组仍关联 ${memberCount} 名员工、${documentCount} 份文档，请先移除关联后再删除。`)
    return
  }
  await ElMessageBox.confirm(`确定删除岗位组「${group.name}」吗？`, '删除岗位组', {
    confirmButtonText: '删除',
    cancelButtonText: '取消',
    type: 'warning',
    confirmButtonClass: 'el-button--danger',
  })
  deletingGroupId.value = group.id
  try {
    await http.delete(`/admin/groups/${group.id}`)
    ElMessage.success('岗位组已删除')
    await load()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '删除岗位组失败')
  } finally {
    deletingGroupId.value = null
  }
}

async function createUser() {
  await http.post('/admin/users', user)
  user.username = ''
  user.password = ''
  user.is_admin = false
  user.group_ids = []
  await load()
}
function openApprovalDialog(item: any) {
  approvalUser.value = item
  approvalForm.group_ids = (item?.groups || []).map((g: any) => String(g.id))
  approvalForm.is_admin = Boolean(item?.is_admin)
  approvalForm.note = item?.approval_note || ''
  approvalDialogVisible.value = true
}
async function reviewUserApproval(action: 'approve' | 'reject') {
  if (!approvalUser.value?.id) return
  approvalBusy.value = true
  try {
    await http.post(`/admin/users/${approvalUser.value.id}/approval`, {
      action,
      note: approvalForm.note,
      group_ids: approvalForm.group_ids,
      is_admin: approvalForm.is_admin,
    })
    ElMessage.success(action === 'approve' ? '账号已审批通过并启用' : '账号已拒绝')
    approvalDialogVisible.value = false
    approvalUser.value = null
    await load()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '处理账号审批失败')
  } finally {
    approvalBusy.value = false
  }
}
async function toggleUserStatus(item: any) {
  if (!item?.id) return
  const nextActive = !item.is_active
  await http.put(`/admin/users/${item.id}/status`, { is_active: nextActive })
  ElMessage.success(nextActive ? '账号已启用' : '账号已停用')
  await load()
}
async function handleFile(file: any) {
  const rawFile = file?.raw
  if (!rawFile) return
  uploadQueue.value.push(rawFile)
  if (!uploadingDoc.value) await processUploadQueue()
}

async function processUploadQueue() {
  uploadingDoc.value = true
  let successCount = 0
  try {
    while (uploadQueue.value.length) {
      const rawFile = uploadQueue.value.shift()
      if (!rawFile) continue
      const ok = await uploadSingleDocument(rawFile)
      if (ok) successCount += 1
    }
    if (successCount > 1) ElMessage.success(`已提交 ${successCount} 个文档进入解析队列`)
  } finally {
    uploadingDoc.value = false
  }
}

async function uploadSingleDocument(rawFile: any) {
  const fd = new FormData()
  fd.append('file', rawFile)
  fd.append('knowledge_scope', uploadKnowledgeScope.value)
  fd.append('document_kind', 'auto')
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
        knowledge_scope: data.knowledge_scope || uploadKnowledgeScope.value,
        document_kind: data.document_kind || 'general',
        document_kind_confidence: data.document_kind_confidence ?? 1,
        document_kind_reason: data.document_kind_reason || '',
        document_kind_status: data.document_kind_status || 'auto',
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
    if (uploadQueue.value.length === 0) ElMessage.success('文档上传并已进入解析队列')
    if (lastUploadSummary.value?.docId) startStatusPolling(lastUploadSummary.value.docId)
    await load()
    await nextTick()
    if (lastUploadSummary.value?.docId) {
      document.getElementById(`admin-doc-${lastUploadSummary.value.docId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
    return true
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
    ElMessage.error(`${rawFile.name}：${detail}`)
    return false
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

async function bulkReparseQualityDocs() {
  if (!qualityReparseCandidateCount.value) return
  try {
    await ElMessageBox.confirm(`将按体检结果重新解析 ${qualityReparseCandidateCount.value} 份异常文件，并重新生成切片与索引任务。确定继续？`, '批量修复文件处理问题', {
      confirmButtonText: '批量重新解析',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  bulkReparsingQualityDocs.value = true
  try {
    const { data } = await http.post('/admin/document-quality/reparse', { grades: ['blocked', 'poor'], limit: 200 })
    ElMessage.success(`已加入重新解析队列 ${data?.queued_count || 0} 份，跳过 ${data?.skipped_count || 0} 份`)
    await load()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '批量重新解析失败')
  } finally {
    bulkReparsingQualityDocs.value = false
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


async function openDocumentQuality(doc: any) {
  if (!doc?.id) return
  documentQualityDoc.value = doc
  documentQualityVisible.value = true
  documentQualityLoading.value = true
  documentQualityReport.value = null
  try {
    documentQualityReport.value = (await http.get(`/admin/documents/${doc.id}/quality`)).data || null
  } catch (err: any) {
    ElMessage.error(requestErrorDetail(err, '加载文件质量报告失败'))
  } finally {
    documentQualityLoading.value = false
  }
}

async function openDocumentDiagnostics(doc: any) {
  if (!doc?.id) return
  documentDiagnosticsDoc.value = doc
  documentDiagnosticsVisible.value = true
  documentDiagnosticsLoading.value = true
  documentDiagnosticsReport.value = null
  try {
    documentDiagnosticsReport.value = (await http.get(`/admin/documents/${doc.id}/diagnostics`)).data || null
  } catch (err: any) {
    ElMessage.error(requestErrorDetail(err, '加载文档诊断失败'))
  } finally {
    documentDiagnosticsLoading.value = false
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
function qualityGradeLabel(grade?: string) {
  return ({ good: '状态良好', needs_review: '需要复核', poor: '质量较差', blocked: '严重异常' } as Record<string, string>)[grade || ''] || grade || '未知'
}
function qualitySeverityLabel(severity?: string) {
  return ({ critical: '严重', warning: '警告', info: '提示', ok: '正常' } as Record<string, string>)[severity || ''] || severity || '未知'
}
function formatFileSize(size: number) {
  const value = Number(size || 0)
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
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
  ensureTaskPolling()
})
onUnmounted(() => {
  stopStatusPolling()
  stopTaskPolling()
  disposeGraphChart()
  disposeWikiGraphChart()
  document.documentElement.classList.remove('admin-scroll-page')
  document.body.classList.remove('admin-scroll-page')
})
</script>
