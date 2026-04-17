<template>
  <div class="app">
    <header class="header">
      <div class="header-content">
        <h1>🛡️ SkidCon - AI渗透测试助手</h1>
        <div class="header-actions">
          <button @click="clearHistory" class="btn-clear">清空历史</button>
          <button @click="exportHistory" class="btn-export">导出历史</button>
        </div>
      </div>
    </header>

    <main class="main-content">
      <div class="chat-container" ref="chatContainer">
        <div v-if="messages.length === 0" class="welcome-message">
          <h2>欢迎使用 SkidCon</h2>
          <p>输入你的渗透测试任务，AI将自动选择工具并执行</p>
          <div class="example-tasks">
            <h3>示例任务：</h3>
            <div class="example-item" @click="sendExample('扫描192.168.1.1的开放端口')">
              🔍 扫描192.168.1.1的开放端口
            </div>
            <div class="example-item" @click="sendExample('对http://example.com进行SQL注入测试')">
              🌐 对http://example.com进行SQL注入测试
            </div>
            <div class="example-item" @click="sendExample('枚举192.168.1.1的SMB共享')">
              📋 枚举192.168.1.1的SMB共享
            </div>
            <div class="example-item" @click="sendExample('使用hashcat破解密码哈希')">
              🔑 使用hashcat破解密码哈希
            </div>
          </div>
        </div>

        <div v-for="(msg, index) in messages" :key="index" class="message" :class="msg.role">
          <div class="message-avatar">
            {{ msg.role === 'user' ? '👤' : '🤖' }}
          </div>
          <div class="message-content">
            <div v-if="msg.role === 'user'" class="user-message">{{ msg.content }}</div>
            <div v-else class="ai-message" v-html="renderMarkdown(msg.content)"></div>
            <div v-if="msg.thinking" class="thinking-process">
              <details>
                <summary>💭 思考过程</summary>
                <div v-html="renderMarkdown(msg.thinking)"></div>
              </details>
            </div>
          </div>
        </div>

        <div v-if="isLoading" class="message ai-message">
          <div class="message-avatar">🤖</div>
          <div class="message-content">
            <div class="loading-indicator">
              <span class="dot"></span>
              <span class="dot"></span>
              <span class="dot"></span>
              <span class="loading-text">{{ loadingText }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="input-area">
        <div class="input-container">
          <textarea
            v-model="inputMessage"
            @keydown.enter.exact.prevent="sendMessage"
            placeholder="输入你的渗透测试任务..."
            rows="1"
            class="message-input"
          ></textarea>
          <button @click="sendMessage" :disabled="isLoading || !inputMessage.trim()" class="send-btn">
            <svg viewBox="0 0 24 24" width="24" height="24">
              <path fill="currentColor" d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
            </svg>
          </button>
        </div>
      </div>
    </main>
  </div>
</template>

<script>
import { ref, onMounted, nextTick } from 'vue'
import axios from 'axios'
import { marked } from 'marked'

export default {
  name: 'App',
  setup() {
    const messages = ref([])
    const inputMessage = ref('')
    const isLoading = ref(false)
    const loadingText = ref('正在处理...')
    const chatContainer = ref(null)

    const scrollToBottom = () => {
      nextTick(() => {
        if (chatContainer.value) {
          chatContainer.value.scrollTop = chatContainer.value.scrollHeight
        }
      })
    }

    const renderMarkdown = (text) => {
      if (!text) return ''
      return marked(text)
    }

    const loadHistory = async () => {
      try {
        const response = await axios.get('/api/history')
        if (response.data.status === 'success') {
          messages.value = response.data.history.map(item => ({
            role: item.role || 'ai',
            content: item.content,
            thinking: item.thinking || null
          }))
        }
      } catch (error) {
        console.error('加载历史失败:', error)
      }
    }

    const sendMessage = async () => {
      const message = inputMessage.value.trim()
      if (!message || isLoading.value) return

      messages.value.push({ role: 'user', content: message })
      inputMessage.value = ''
      isLoading.value = true
      loadingText.value = '正在分析任务...'
      scrollToBottom()

      try {
        const response = await axios.post('/api/query', { query: message })
        
        if (response.data.status === 'success') {
          const taskId = response.data.task_id
          
          // 轮询获取结果
          let result = null
          let attempts = 0
          const maxAttempts = 300 // 最多等待30秒 (300 * 100ms)
          
          while (attempts < maxAttempts) {
            await new Promise(resolve => setTimeout(resolve, 100))
            attempts++
            
            const statusResponse = await axios.get(`/api/query/${taskId}`)
            if (statusResponse.data.status === 'completed') {
              result = statusResponse.data
              break
            } else if (statusResponse.data.status === 'error') {
              throw new Error(statusResponse.data.error)
            }
            
            // 更新加载状态
            if (statusResponse.data.current_step) {
              loadingText.value = statusResponse.data.current_step
            }
          }
          
          if (result) {
            messages.value.push({
              role: 'ai',
              content: result.final_response || '执行完成',
              thinking: result.thinking || null
            })
          }
        }
      } catch (error) {
        console.error('发送消息失败:', error)
        messages.value.push({
          role: 'ai',
          content: `❌ 执行失败: ${error.response?.data?.message || error.message}`
        })
      } finally {
        isLoading.value = false
        scrollToBottom()
      }
    }

    const sendExample = (example) => {
      inputMessage.value = example
      sendMessage()
    }

    const clearHistory = async () => {
      if (!confirm('确定要清空所有对话历史吗？')) return
      
      try {
        await axios.post('/api/history/clear')
        messages.value = []
      } catch (error) {
        console.error('清空历史失败:', error)
        alert('清空历史失败')
      }
    }

    const exportHistory = () => {
      const data = JSON.stringify(messages.value, null, 2)
      const blob = new Blob([data], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `skidcon-history-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
    }

    onMounted(() => {
      loadHistory()
    })

    return {
      messages,
      inputMessage,
      isLoading,
      loadingText,
      chatContainer,
      sendMessage,
      sendExample,
      renderMarkdown,
      clearHistory,
      exportHistory
    }
  }
}
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif;
  background: #f5f5f5;
  color: #333;
}

.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
}

.header {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 1rem 2rem;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
}

.header-content {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header h1 {
  font-size: 1.5rem;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 0.5rem;
}

.btn-clear, .btn-export {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.2);
  color: white;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 0.9rem;
}

.btn-clear:hover, .btn-export:hover {
  background: rgba(255, 255, 255, 0.3);
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
  background: white;
}

.chat-container {
  flex: 1;
  overflow-y: auto;
  padding: 2rem;
}

.welcome-message {
  text-align: center;
  padding: 3rem 1rem;
}

.welcome-message h2 {
  font-size: 2rem;
  margin-bottom: 1rem;
  color: #667eea;
}

.welcome-message p {
  color: #666;
  margin-bottom: 2rem;
}

.example-tasks {
  text-align: left;
  max-width: 600px;
  margin: 0 auto;
}

.example-tasks h3 {
  margin-bottom: 1rem;
  color: #333;
}

.example-item {
  padding: 1rem;
  margin-bottom: 0.5rem;
  background: #f8f9fa;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  border-left: 4px solid #667eea;
}

.example-item:hover {
  background: #e9ecef;
  transform: translateX(4px);
}

.message {
  display: flex;
  gap: 1rem;
  margin-bottom: 1.5rem;
  padding: 1rem;
  border-radius: 8px;
}

.message.user {
  background: #f0f4ff;
}

.message.ai {
  background: #f8f9fa;
}

.message-avatar {
  font-size: 1.5rem;
  flex-shrink: 0;
}

.message-content {
  flex: 1;
  min-width: 0;
}

.user-message {
  font-size: 1rem;
  line-height: 1.5;
}

.ai-message {
  font-size: 1rem;
  line-height: 1.6;
}

.ai-message pre {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 1rem;
  border-radius: 6px;
  overflow-x: auto;
  margin: 0.5rem 0;
}

.ai-message code {
  font-family: 'Courier New', monospace;
  font-size: 0.9em;
}

.ai-message p {
  margin-bottom: 0.5rem;
}

.ai-message ul, .ai-message ol {
  margin-left: 1.5rem;
  margin-bottom: 0.5rem;
}

.thinking-process {
  margin-top: 0.5rem;
  padding: 0.5rem;
  background: #fff3cd;
  border-radius: 6px;
  border-left: 4px solid #ffc107;
}

.thinking-process details {
  cursor: pointer;
}

.thinking-process summary {
  font-weight: 500;
  margin-bottom: 0.5rem;
}

.loading-indicator {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #667eea;
  animation: bounce 1.4s infinite ease-in-out both;
}

.dot:nth-child(1) { animation-delay: -0.32s; }
.dot:nth-child(2) { animation-delay: -0.16s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}

.loading-text {
  margin-left: 0.5rem;
  color: #666;
  font-size: 0.9rem;
}

.input-area {
  padding: 1rem 2rem;
  background: white;
  border-top: 1px solid #e0e0e0;
}

.input-container {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  gap: 0.5rem;
  align-items: flex-end;
}

.message-input {
  flex: 1;
  padding: 0.75rem 1rem;
  border: 2px solid #e0e0e0;
  border-radius: 8px;
  font-size: 1rem;
  resize: none;
  font-family: inherit;
  transition: border-color 0.2s;
}

.message-input:focus {
  outline: none;
  border-color: #667eea;
}

.send-btn {
  padding: 0.75rem;
  background: #667eea;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.send-btn:hover:not(:disabled) {
  background: #5568d3;
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 768px) {
  .header-content {
    flex-direction: column;
    gap: 1rem;
    text-align: center;
  }
  
  .chat-container {
    padding: 1rem;
  }
  
  .input-area {
    padding: 1rem;
  }
}
</style>
