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

const router = useRouter()
const form = reactive({ username: '', password: '' })

async function login() {
  const res = await http.post('/auth/login', form)
  localStorage.setItem('token', res.data.token)
  ElMessage.success('登录成功')
  router.push('/chat')
}
</script>
