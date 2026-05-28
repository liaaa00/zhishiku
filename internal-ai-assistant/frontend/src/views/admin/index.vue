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
        <el-upload :auto-upload="false" :show-file-list="false" :on-change="handleFile">
          <el-button type="primary">选择 PDF 上传</el-button>
        </el-upload>
        <el-table :data="docs" style="margin-top: 16px">
          <el-table-column prop="title" label="文档" />
          <el-table-column prop="filename" label="文件名" />
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
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../../api'

const groups = ref<any[]>([])
const users = ref<any[]>([])
const docs = ref<any[]>([])
const docGroupMap = reactive<Record<string, string[]>>({})
const groupName = ref('')
const user = reactive({ username: '', password: '', is_admin: false, group_ids: [] as string[] })

async function load() {
  groups.value = (await http.get('/admin/groups')).data
  users.value = (await http.get('/admin/users')).data
  docs.value = (await http.get('/admin/documents')).data
  docs.value.forEach((d: any) => {
    docGroupMap[d.id] = d.groups.map((g: any) => g.id)
  })
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
  ElMessage.success('文档上传并向量化完成')
  await load()
}
async function saveDocPermission(documentId: string) {
  await http.put(`/admin/documents/${documentId}/permissions`, { group_ids: docGroupMap[documentId] || [] })
  ElMessage.success('文档权限已保存')
}
onMounted(load)
</script>
