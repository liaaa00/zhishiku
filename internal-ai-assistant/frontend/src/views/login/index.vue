<template>
  <div class="page-center">
    <el-card class="card">
      <template #header>员工登录</template>
      <el-form :model="form" @submit.prevent>
        <el-form-item label="账号"><el-input v-model="form.username" autocomplete="username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password autocomplete="current-password" /></el-form-item>
        <el-button type="primary" @click="login">登录</el-button>
      </el-form>
      <div class="tip">请使用管理员分配的公司账号登录。</div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../../api'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const form = reactive({ username: '', password: '' })

function readableLoginError(err: any) {
  const detail = err?.response?.data?.detail || err?.message || '登录失败'
  if (/failed to fetch|network error/i.test(String(detail))) {
    return '登录失败：无法连接到服务，请确认前端 5174 与后端 8000 正常运行后重试。'
  }
  return String(detail || '登录失败')
}

async function login() {
  try {
    const res = await http.post('/auth/login', form)
    auth.setAuthPayload(res.data || {})
    try {
      await auth.loadCurrentUser()
    } catch {
      auth.setUser(res.data?.user || null)
    }
    ElMessage.success('登录成功')
    router.push('/chat')
  } catch (err: any) {
    ElMessage.error(readableLoginError(err))
  }
}
</script>
