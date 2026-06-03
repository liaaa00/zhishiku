<template>
  <div class="chat-shell">
    <div class="chat-header">
      <h2>公司内部AI助手</h2>
      <p>只基于你有权限访问的内部文档回答</p>
    </div>
    <div class="chat-body">
      <el-card v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
        <div v-html="m.content.replace(/\n/g, '<br/>')"></div>
      </el-card>
      <el-card v-if="waiting" class="msg assistant">
        <div>{{ waitText }}</div>
      </el-card>
    </div>
    <div class="chat-input">
      <el-input v-model="question" type="textarea" :rows="3" placeholder="请输入你的问题" />
      <el-button type="primary" :loading="waiting" @click="send">发送</el-button>
    </div>
    <el-divider />
    <div v-if="sources.length">
      <h4>引用来源</h4>
      <el-card v-for="s in sources" :key="s.document_id" class="source-card">
        <div>{{ s.document_title }} - 第 {{ s.page_number || '未知' }} 页</div>
        <div>{{ s.content }}</div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../../api'
import { useRouter } from 'vue-router'

const router = useRouter()
const question = ref('')
const sessionId = ref('')
const messages = ref<any[]>([{ role: 'assistant', content: '你好，我会基于你有权限的内部文档回答。' }])
const sources = ref<any[]>([])
const waiting = ref(false)
const waitSeconds = ref(0)
let waitTimer: ReturnType<typeof window.setInterval> | null = null

const waitText = computed(() => {
  if (waitSeconds.value <= 0) return '正在连接知识库'
  return `正在检索知识库并等待模型回答，已等待 ${waitSeconds.value} 秒`
})

function startWaitTimer() {
  stopWaitTimer()
  waiting.value = true
  waitSeconds.value = 0
  waitTimer = window.setInterval(() => {
    waitSeconds.value += 1
  }, 1000)
}

function stopWaitTimer() {
  if (waitTimer !== null) {
    window.clearInterval(waitTimer)
    waitTimer = null
  }
  waiting.value = false
  waitSeconds.value = 0
}

async function send() {
  if (!question.value.trim() || waiting.value) return
  const userText = question.value
  messages.value.push({ role: 'user', content: userText })
  question.value = ''
  startWaitTimer()
  try {
    const res = await http.post('/chat', { question: userText, session_id: sessionId.value || null })
    sessionId.value = res.data.session_id
    stopWaitTimer()
    messages.value.push({ role: 'assistant', content: res.data.answer })
    sources.value = res.data.sources || []
  } catch (e: any) {
    stopWaitTimer()
    if (e.response?.status === 401) router.push('/login')
    else ElMessage.error(e.response?.data?.detail || '发送失败')
  }
}

onUnmounted(() => {
  stopWaitTimer()
})
</script>
