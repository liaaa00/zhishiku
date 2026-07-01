<template>
  <div class="page-center">
    <el-card class="card auth-card">
      <template #header>
        <div class="auth-header">
          <span>{{ mode === 'login' ? '员工登录' : '员工自助注册' }}</span>
          <button type="button" class="auth-switch" @click="toggleMode">
            {{ mode === 'login' ? '申请账号' : '返回登录' }}
          </button>
        </div>
      </template>
      <el-form :model="form" @submit.prevent>
        <el-form-item label="账号"><el-input v-model="form.username" autocomplete="username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" /></el-form-item>
        <el-form-item v-if="mode === 'register'" label="确认密码">
          <el-input v-model="form.confirmPassword" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-button type="primary" :loading="submitting" @click="mode === 'login' ? login() : register()">
          {{ mode === 'login' ? '登录' : '提交注册申请' }}
        </el-button>
      </el-form>
      <div class="tip">
        <template v-if="mode === 'login'">请使用管理员分配或已启用的公司账号登录。</template>
        <template v-else>注册后账号默认待启用，需要管理员审核、启用并分配岗位组后才能访问知识库。</template>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../../api'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const mode = ref<'login' | 'register'>('login')
const submitting = ref(false)
const form = reactive({ username: '', password: '', confirmPassword: '' })

function readableAuthError(err: any, fallback: string) {
  const detail = err?.response?.data?.detail || err?.message || fallback
  if (/failed to fetch|network error/i.test(String(detail))) {
    return `${fallback}：无法连接到服务，请确认前端和后端正常运行后重试。`
  }
  return String(detail || fallback)
}

function toggleMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  form.password = ''
  form.confirmPassword = ''
}

async function login() {
  if (submitting.value) return
  submitting.value = true
  try {
    const res = await http.post('/auth/login', { username: form.username, password: form.password })
    auth.setAuthPayload(res.data || {})
    try {
      await auth.loadCurrentUser()
    } catch {
      auth.setUser(res.data?.user || null)
    }
    ElMessage.success('登录成功')
    router.push('/chat')
  } catch (err: any) {
    ElMessage.error(readableAuthError(err, '登录失败'))
  } finally {
    submitting.value = false
  }
}

async function register() {
  if (submitting.value) return
  const username = form.username.trim()
  if (!username || !form.password) {
    ElMessage.warning('请输入账号和密码')
    return
  }
  if (form.password !== form.confirmPassword) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  submitting.value = true
  try {
    const res = await http.post('/auth/register', { username, password: form.password })
    ElMessage.success(res.data?.message || '注册已提交，请等待管理员启用')
    mode.value = 'login'
    form.password = ''
    form.confirmPassword = ''
  } catch (err: any) {
    ElMessage.error(readableAuthError(err, '注册失败'))
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.auth-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.auth-switch {
  border: none;
  background: transparent;
  color: #2563eb;
  cursor: pointer;
  font-size: 13px;
}

.auth-switch:hover {
  text-decoration: underline;
}
</style>
