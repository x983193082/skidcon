<template>
  <div class="app">
    <header class="header">
        <div class="header-content">
        <h1>🛡️ SkidCon - AI渗透测试助手</h1>
        <div class="header-actions">
          <span v-if="isStreaming" class="streaming-badge">
            <span class="pulse-dot"></span>
            {{ isAutonomous ? '自主测试中' : '实时流式输出中' }}
          </span>
          <button v-if="!isAutonomous" @click="showAutonomousModal = true" class="btn-autonomous" :disabled="isStreaming">🤖 自主测试</button>
          <button @click="clearHistory" class="btn-clear">清空历史</button>
          <button @click="exportHistory" class="btn-export">导出历史</button>
        </div>
      </div>
    </header>

    <main class="main-content">
      <div class="chat-container" ref="chatContainer">
        <div v-if="messages.length === 0 && !isStreaming" class="welcome-message">
          <h2>欢迎使用 SkidCon</h2>
          <p>输入你的渗透测试任务，AI将自动选择工具并执行</p>
          <div class="example-tasks">
            <h3>示例任务：</h3>
            <div class="example-item" @click="sendExample('扫描192.168.1.1的开放端口')">🔍 扫描192.168.1.1的开放端口</div>
            <div class="example-item" @click="sendExample('对http://example.com进行SQL注入测试')">🌐 对http://example.com进行SQL注入测试</div>
            <div class="example-item" @click="sendExample('枚举192.168.1.1的SMB共享')">📋 枚举192.168.1.1的SMB共享</div>
            <div class="example-item" @click="sendExample('使用hashcat破解密码哈希')">🔑 使用hashcat破解密码哈希</div>
          </div>
        </div>

        <div v-for="(msg, index) in messages" :key="index" class="message" :class="msg.role">
          <div class="message-avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
          <div class="message-content">
            <div v-if="msg.role === 'user'" class="user-message">{{ msg.content }}</div>
            <div v-else>
              <div v-if="msg.type === 'agent_status'" class="agent-status" :class="msg.statusClass">
                <span class="agent-icon">{{ msg.icon }}</span>
                <span class="agent-text">{{ msg.content }}</span>
              </div>
              <div v-else-if="msg.type === 'tool_call'" class="tool-call">
                <div class="tool-call-header">
                  <span class="tool-icon">⚡</span>
                  <span class="tool-name">{{ msg.toolName }}</span>
                </div>
                <div v-if="msg.args" class="tool-args" v-html="renderMarkdown(msg.args)"></div>
              </div>
              <div v-else-if="msg.type === 'tool_output'" class="tool-output">
                <div class="tool-output-header">
                  <span class="tool-icon">📤</span>
                  <span>执行结果</span>
                </div>
                <pre class="tool-output-content">{{ msg.output }}</pre>
              </div>
              <div v-else class="ai-message" v-html="renderMarkdown(msg.content)"></div>
            </div>
            <div v-if="msg.thinking" class="thinking-process">
              <details><summary>💭 思考过程</summary><div v-html="renderMarkdown(msg.thinking)"></div></details>
            </div>
          </div>
        </div>

        <div v-if="isStreaming" class="message ai-message streaming-message">
          <div class="message-avatar">🤖</div>
          <div class="message-content">
            <div v-if="currentAgent" class="agent-status active">
              <span class="agent-icon">🔄</span>
              <span class="agent-text">{{ currentAgent }}</span>
              <span class="thinking-dots"><span class="dot"></span><span class="dot"></span><span class="dot"></span></span>
            </div>
            <div v-if="streamingContent" class="ai-message streaming-text">
              <div v-html="renderMarkdown(streamingContent)"></div>
              <span class="cursor"></span>
            </div>
            <div v-if="currentToolCall" class="tool-call active">
              <div class="tool-call-header">
                <span class="tool-icon">⚡</span>
                <span class="tool-name">{{ currentToolCall.toolName }}</span>
                <span class="tool-status">执行中...</span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="isLoading && !isStreaming" class="message ai-message">
          <div class="message-avatar">🤖</div>
          <div class="message-content">
            <div class="loading-indicator">
              <span class="dot"></span><span class="dot"></span><span class="dot"></span>
              <span class="loading-text">{{ loadingText }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="input-area">
        <div class="input-container">
          <textarea v-model="inputMessage" @keydown.enter.exact.prevent="sendMessage" placeholder="输入你的渗透测试任务..." rows="1" class="message-input" :disabled="isStreaming"></textarea>
          <button @click="sendMessage" :disabled="isStreaming || !inputMessage.trim()" class="send-btn">
            <svg v-if="!isStreaming" viewBox="0 0 24 24" width="24" height="24"><path fill="currentColor" d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
            <svg v-else class="stop-icon" viewBox="0 0 24 24" width="24" height="24" @click="stopStreaming"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg>
          </button>
        </div>
      </div>
    </main>

    <!-- 自主测试模态框 -->
    <div v-if="showAutonomousModal" class="modal-overlay" @click.self="showAutonomousModal = false">
      <div class="modal">
        <div class="modal-header">
          <h3>🤖 自主渗透测试</h3>
          <button @click="showAutonomousModal = false" class="modal-close">&times;</button>
        </div>
        <div class="modal-body">
          <p>输入目标IP或域名，系统将自动执行完整的渗透测试流程：</p>
          <div class="phase-list">
            <span class="phase-item">信息收集</span> →
            <span class="phase-item">扫描</span> →
            <span class="phase-item">枚举</span> →
            <span class="phase-item">漏洞识别</span> →
            <span class="phase-item">利用</span> →
            <span class="phase-item">报告</span>
          </div>
          <input v-model="autonomousTarget" type="text" placeholder="输入目标 (如: 192.168.1.1 或 example.com)" class="target-input" @keydown.enter="startAutonomousTest" />
          <div class="modal-actions">
            <button @click="showAutonomousModal = false" class="btn-cancel">取消</button>
            <button @click="startAutonomousTest" :disabled="!autonomousTarget.trim() || isStreaming" class="btn-start">开始测试</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 测试进度面板 -->
    <div v-if="isAutonomous && autonomousState.show" class="autonomous-panel">
      <div class="panel-header">
        <h4>📊 测试进度</h4>
        <span class="step-counter">步骤 {{ autonomousState.currentStep }}/{{ autonomousState.maxSteps }}</span>
      </div>
      <div class="phase-indicator">
        <div v-for="phase in autonomousPhases" :key="phase" class="phase-dot" :class="{ active: autonomousState.phase === phase, completed: autonomousState.completedPhases.includes(phase) }">
          {{ phase.charAt(0).toUpperCase() }}
        </div>
      </div>
      <div class="findings-summary">
        <div class="finding-item"><span class="finding-icon">🖥️</span> 主机: {{ autonomousState.hostsFound }}</div>
        <div class="finding-item"><span class="finding-icon">🔌</span> 服务: {{ autonomousState.servicesFound }}</div>
        <div class="finding-item"><span class="finding-icon">🔓</span> 漏洞: {{ autonomousState.vulnsFound }}</div>
        <div class="finding-item"><span class="finding-icon">🔑</span> 凭据: {{ autonomousState.credsFound }}</div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import axios from 'axios'
import { marked } from 'marked'

export default {
  name: 'App',
  setup() {
    const messages = ref([])
    const inputMessage = ref('')
    const isLoading = ref(false)
    const isStreaming = ref(false)
    const loadingText = ref('正在处理...')
    const chatContainer = ref(null)
    const currentEventSource = ref(null)
    const currentAgent = ref('')
    const streamingContent = ref('')
    const currentToolCall = ref(null)

    const showAutonomousModal = ref(false)
    const autonomousTarget = ref('')
    const isAutonomous = ref(false)
    const autonomousPhases = ['reconnaissance', 'scanning', 'enumeration', 'vulnerability', 'exploitation', 'post_exploitation']
    const autonomousState = ref({
      show: false,
      phase: '',
      currentStep: 0,
      maxSteps: 12,
      hostsFound: 0,
      servicesFound: 0,
      vulnsFound: 0,
      credsFound: 0,
      completedPhases: []
    })

    const scrollToBottom = () => {
      nextTick(() => {
        if (chatContainer.value) chatContainer.value.scrollTop = chatContainer.value.scrollHeight
      })
    }

    const renderMarkdown = (text) => {
      if (!text) return ''
      try { return marked(text) } catch (e) { return text }
    }

    const loadHistory = async () => {
      try {
        const response = await axios.get('/api/history')
        if (response.data.status === 'success') {
          messages.value = response.data.history.map(item => ({
            role: item.role || 'ai', content: item.content, thinking: item.thinking || null
          }))
        }
      } catch (error) { console.error('加载历史失败:', error) }
    }

    const closeSSEStream = () => {
      if (currentEventSource.value) { currentEventSource.value.close(); currentEventSource.value = null }
      isStreaming.value = false
      currentAgent.value = ''
      currentToolCall.value = null
      isLoading.value = false
      if (isAutonomous.value) {
        autonomousState.value.show = false
        isAutonomous.value = false
      }
    }

    const handleSSEMessage = (data) => {
      switch (data.type) {
        case 'autonomous_start':
          isAutonomous.value = true
          autonomousState.value = {
            show: true,
            phase: 'reconnaissance',
            currentStep: 0,
            maxSteps: data.data.max_steps || 12,
            hostsFound: 0,
            servicesFound: 0,
            vulnsFound: 0,
            credsFound: 0,
            completedPhases: []
          }
          messages.value.push({ role: 'ai', type: 'agent_status', icon: '🚀', content: `开始自主渗透测试: ${data.data.target}`, statusClass: 'info' })
          break
        case 'phase_update':
          autonomousState.value.currentStep = data.data.step
          autonomousState.value.phase = data.data.phase
          if (data.data.action) {
            messages.value.push({ role: 'ai', type: 'agent_status', icon: '🔄', content: `[${data.data.phase}] ${data.data.action}`, statusClass: 'info' })
          }
          break
        case 'phase_transition':
          if (!autonomousState.value.completedPhases.includes(data.data.from)) {
            autonomousState.value.completedPhases.push(data.data.from)
          }
          messages.value.push({ role: 'ai', type: 'agent_status', icon: '➡️', content: data.data.message, statusClass: 'success' })
          break
        case 'step_completed':
          autonomousState.value.hostsFound = data.data.findings_count || autonomousState.value.hostsFound
          if (data.data.verified) {
            messages.value.push({ role: 'ai', type: 'agent_status', icon: '✅', content: `步骤${data.data.step}完成 (置信度: ${Math.round(data.data.confidence * 100)}%)`, statusClass: 'success' })
          }
          break
        case 'plan_generated':
          messages.value.push({ role: 'ai', type: 'agent_status', icon: '📋', content: '测试计划已生成，开始执行...', statusClass: 'info' })
          break
        case 'autonomous_complete':
          autonomousState.value.hostsFound = data.data.services_found || 0
          autonomousState.value.servicesFound = data.data.services_found || 0
          autonomousState.value.vulnsFound = data.data.vulnerabilities_found || 0
          autonomousState.value.credsFound = data.data.credentials_found || 0
          messages.value.push({ role: 'ai', type: 'agent_status', icon: '🎉', content: '自主测试完成！正在生成报告...', statusClass: 'success' })
          if (data.data.report_markdown) {
            messages.value.push({ role: 'ai', content: '## 📋 渗透测试报告\n\n' + data.data.report_markdown })
          }
          isAutonomous.value = false
          break
        case 'agent_thinking':
          if (data.data.agent.includes('Level 1')) currentAgent.value = '🔍 正在分析任务...'
          else if (data.data.agent.includes('Level 2')) currentAgent.value = data.data.message || '⚙️ 正在执行任务...'
          else if (data.data.agent.includes('Chat')) currentAgent.value = '💬 正在生成回复...'
          break
        case 'agent_message':
          if (data.data.agent.includes('Level 1') && data.data.content.includes('custom_code')) {
            messages.value.push({ role: 'ai', type: 'agent_status', icon: '🎯', content: '任务分类完成 → 代码执行', statusClass: 'success' })
          } else if (data.data.agent.includes('Level 2')) {
            if (data.data.content.includes('完成')) {
              messages.value.push({ role: 'ai', type: 'agent_status', icon: '✅', content: '执行完成', statusClass: 'success' })
            } else {
              messages.value.push({ role: 'ai', type: 'agent_status', icon: '📋', content: data.data.content, statusClass: 'info' })
            }
          } else if (data.data.agent === 'System') {
            messages.value.push({ role: 'ai', type: 'agent_status', icon: '❌', content: data.data.content, statusClass: 'error' })
          }
          break
        case 'text_delta':
          streamingContent.value += data.data.delta
          scrollToBottom()
          break
        case 'tool_call':
          currentToolCall.value = { toolName: data.data.tool_name === 'python_execute' ? '代码执行' : data.data.tool_name, args: data.data.tool_args }
          break
        case 'tool_output':
          if (currentToolCall.value) {
            messages.value.push({ role: 'ai', type: 'tool_call', toolName: currentToolCall.value.toolName, args: currentToolCall.value.args })
            messages.value.push({ role: 'ai', type: 'tool_output', output: data.data.output })
            currentToolCall.value = null
          }
          break
        case 'task_completed':
          if (data.data.success) {
            if (streamingContent.value) { messages.value.push({ role: 'ai', content: streamingContent.value }); streamingContent.value = '' }
          } else {
            messages.value.push({ role: 'ai', type: 'agent_status', icon: '❌', content: '执行失败: ' + (data.data.error || '未知错误'), statusClass: 'error' })
          }
          closeSSEStream()
          break
        case 'completed':
          if (data.data.response && !streamingContent.value) {
            messages.value.push({ role: 'ai', content: data.data.response })
          } else if (streamingContent.value) {
            messages.value.push({ role: 'ai', content: streamingContent.value }); streamingContent.value = ''
          }
          closeSSEStream()
          break
        case 'error':
          messages.value.push({ role: 'ai', type: 'agent_status', icon: '❌', content: '错误: ' + (data.data.error || '未知错误'), statusClass: 'error' })
          closeSSEStream()
          break
      }
    }

    const stopStreaming = () => {
      closeSSEStream()
      if (streamingContent.value) { messages.value.push({ role: 'ai', content: streamingContent.value + '\n\n*[输出已停止]*' }); streamingContent.value = '' }
    }

    const sendMessage = async () => {
      const message = inputMessage.value.trim()
      if (!message || isLoading.value || isStreaming.value) return

      messages.value.push({ role: 'user', content: message })
      inputMessage.value = ''
      isLoading.value = true
      isStreaming.value = true
      streamingContent.value = ''
      currentAgent.value = '🔍 正在分析任务...'
      scrollToBottom()

      try {
        const response = await axios.post('/api/query', { query: message })
        if (response.data.status === 'success') {
          const taskId = response.data.task_id
          const eventSource = new EventSource('/api/query/' + taskId + '/stream')
          currentEventSource.value = eventSource

          eventSource.onmessage = (event) => {
            try { handleSSEMessage(JSON.parse(event.data)); scrollToBottom() }
            catch (e) { console.error('解析SSE消息失败:', e) }
          }
          eventSource.onerror = () => { if (eventSource.readyState === EventSource.CLOSED) closeSSEStream() }
        }
      } catch (error) {
        messages.value.push({ role: 'ai', type: 'agent_status', icon: '❌', content: '执行失败: ' + (error.response?.data?.message || error.message), statusClass: 'error' })
        closeSSEStream()
      }
    }

    const sendExample = (example) => { inputMessage.value = example; sendMessage() }

    const startAutonomousTest = async () => {
      const target = autonomousTarget.value.trim()
      if (!target || isStreaming.value) return

      showAutonomousModal.value = false
      messages.value.push({ role: 'user', content: `🤖 开始自主渗透测试: ${target}` })
      isLoading.value = true
      isStreaming.value = true
      isAutonomous.value = true
      streamingContent.value = ''
      currentAgent.value = '🤖 正在初始化自主测试...'
      scrollToBottom()

      try {
        const response = await axios.post('/api/autonomous-test', { target })
        if (response.data.status === 'success') {
          const taskId = response.data.task_id
          const eventSource = new EventSource('/api/query/' + taskId + '/stream')
          currentEventSource.value = eventSource

          eventSource.onmessage = (event) => {
            try { handleSSEMessage(JSON.parse(event.data)); scrollToBottom() }
            catch (e) { console.error('解析SSE消息失败:', e) }
          }
          eventSource.onerror = () => { if (eventSource.readyState === EventSource.CLOSED) closeSSEStream() }
        }
      } catch (error) {
        messages.value.push({ role: 'ai', type: 'agent_status', icon: '❌', content: '启动自主测试失败: ' + (error.response?.data?.message || error.message), statusClass: 'error' })
        closeSSEStream()
        isAutonomous.value = false
      }
      autonomousTarget.value = ''
    }

    const clearHistory = async () => {
      if (!confirm('确定要清空所有对话历史吗？')) return
      try { await axios.post('/api/history/clear'); messages.value = [] }
      catch (error) { console.error('清空历史失败:', error); alert('清空历史失败') }
    }

    const exportHistory = () => {
      const data = JSON.stringify(messages.value, null, 2)
      const blob = new Blob([data], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'skidcon-history-' + new Date().toISOString().slice(0, 10) + '.json'
      a.click(); URL.revokeObjectURL(url)
    }

    onMounted(() => { loadHistory() })
    onUnmounted(() => { closeSSEStream() })

    return { messages, inputMessage, isLoading, isStreaming, loadingText, chatContainer, currentAgent, streamingContent, currentToolCall, sendMessage, sendExample, renderMarkdown, clearHistory, exportHistory, stopStreaming, showAutonomousModal, autonomousTarget, isAutonomous, autonomousPhases, autonomousState, startAutonomousTest }
  }
}
</script>

<style scoped>
* { margin: 0; padding: 0; box-sizing: border-box; }
.app { display: flex; flex-direction: column; height: 100vh; background: #f5f5f5; }
.header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 1rem 2rem; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
.header-content { max-width: 1200px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; }
.header h1 { font-size: 1.5rem; font-weight: 600; }
.header-actions { display: flex; gap: 0.75rem; align-items: center; }
.streaming-badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px; background: rgba(255,255,255,0.2); border-radius: 20px; font-size: 0.85rem; }
.pulse-dot { width: 8px; height: 8px; border-radius: 50%; background: #4ade80; animation: pulse 1.5s infinite; }
@keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.5;transform:scale(1.2)} }
.btn-clear, .btn-export { padding: 0.5rem 1rem; border: none; border-radius: 6px; background: rgba(255,255,255,0.2); color: white; cursor: pointer; transition: all 0.2s; font-size: 0.9rem; }
.btn-clear:hover, .btn-export:hover { background: rgba(255,255,255,0.3); }
.main-content { flex: 1; display: flex; flex-direction: column; max-width: 1200px; margin: 0 auto; width: 100%; background: white; }
.chat-container { flex: 1; overflow-y: auto; padding: 2rem; }
.welcome-message { text-align: center; padding: 3rem 1rem; }
.welcome-message h2 { font-size: 2rem; margin-bottom: 1rem; color: #667eea; }
.welcome-message p { color: #666; margin-bottom: 2rem; }
.example-tasks { text-align: left; max-width: 600px; margin: 0 auto; }
.example-tasks h3 { margin-bottom: 1rem; color: #333; }
.example-item { padding: 1rem; margin-bottom: 0.5rem; background: #f8f9fa; border-radius: 8px; cursor: pointer; transition: all 0.2s; border-left: 4px solid #667eea; }
.example-item:hover { background: #e9ecef; transform: translateX(4px); }
.message { display: flex; gap: 1rem; margin-bottom: 1.5rem; padding: 1rem; border-radius: 8px; }
.message.user { background: #f0f4ff; }
.message.ai { background: #f8f9fa; }
.message-avatar { font-size: 1.5rem; flex-shrink: 0; }
.message-content { flex: 1; min-width: 0; }
.user-message { font-size: 1rem; line-height: 1.5; }
.ai-message { font-size: 1rem; line-height: 1.6; }
.ai-message pre { background: #1e1e1e; color: #d4d4d4; padding: 1rem; border-radius: 6px; overflow-x: auto; margin: 0.5rem 0; }
.ai-message code { font-family: 'Courier New', monospace; font-size: 0.9em; }
.agent-status { display: inline-flex; align-items: center; gap: 8px; padding: 8px 16px; border-radius: 20px; font-size: 0.9rem; margin: 4px 0; }
.agent-status.info { background: #e0f2fe; color: #0369a1; }
.agent-status.success { background: #dcfce7; color: #166534; }
.agent-status.error { background: #fee2e2; color: #991b1b; }
.agent-status.active { background: linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%); color: #4338ca; font-weight: 500; }
.agent-icon { font-size: 1rem; }
.tool-call { background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%); border: 1px solid #0ea5e9; border-radius: 8px; padding: 12px 16px; margin: 8px 0; }
.tool-call.active { border-color: #667eea; animation: toolPulse 1.5s infinite; }
@keyframes toolPulse { 0%,100%{box-shadow:0 0 0 0 rgba(102,126,234,0.4)} 50%{box-shadow:0 0 0 8px rgba(102,126,234,0)} }
.tool-call-header { display: flex; align-items: center; gap: 8px; font-weight: 500; color: #0369a1; }
.tool-status { margin-left: auto; font-size: 0.8rem; color: #667eea; font-weight: 500; }
.tool-args { margin-top: 8px; padding: 8px; background: rgba(255,255,255,0.5); border-radius: 4px; font-size: 0.85rem; }
.tool-output { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; margin: 8px 0; }
.tool-output-header { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: #f1f5f9; border-radius: 8px 8px 0 0; font-size: 0.85rem; color: #475569; }
.tool-output-content { padding: 12px; margin: 0; font-size: 0.85rem; line-height: 1.5; max-height: 300px; overflow-y: auto; white-space: pre-wrap; word-break: break-word; }
.thinking-process { margin-top: 0.5rem; padding: 0.5rem; background: #fff3cd; border-radius: 6px; border-left: 4px solid #ffc107; }
.thinking-process details { cursor: pointer; }
.thinking-process summary { font-weight: 500; margin-bottom: 0.5rem; }
.streaming-message { background: linear-gradient(135deg, #f0f4ff 0%, #e8e0ff 100%); border: 1px solid #c7d2fe; }
.streaming-text { position: relative; }
.cursor { display: inline-block; width: 2px; height: 1.2em; background: #667eea; animation: blink 1s infinite; margin-left: 1px; vertical-align: text-bottom; }
@keyframes blink { 0%,50%{opacity:1} 51%,100%{opacity:0} }
.loading-indicator { display: flex; align-items: center; gap: 0.5rem; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #667eea; animation: bounce 1.4s infinite ease-in-out both; }
.dot:nth-child(1) { animation-delay: -0.32s; }
.dot:nth-child(2) { animation-delay: -0.16s; }
@keyframes bounce { 0%,80%,100%{transform:scale(0)} 40%{transform:scale(1)} }
.loading-text { margin-left: 0.5rem; color: #666; font-size: 0.9rem; }
.input-area { padding: 1rem 2rem; background: white; border-top: 1px solid #e0e0e0; }
.input-container { max-width: 1200px; margin: 0 auto; display: flex; gap: 0.5rem; align-items: flex-end; }
.message-input { flex: 1; padding: 0.75rem 1rem; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 1rem; resize: none; font-family: inherit; transition: border-color 0.2s; }
.message-input:focus { outline: none; border-color: #667eea; }
.message-input:disabled { background: #f5f5f5; cursor: not-allowed; }
.send-btn { padding: 0.75rem; background: #667eea; color: white; border: none; border-radius: 8px; cursor: pointer; transition: all 0.2s; display: flex; align-items: center; justify-content: center; }
.send-btn:hover:not(:disabled) { background: #5568d3; }
.send-btn:disabled { background: #ccc; cursor: not-allowed; }
.stop-icon { color: white; }
.btn-autonomous { padding: 0.5rem 1rem; border: none; border-radius: 6px; background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; cursor: pointer; transition: all 0.2s; font-size: 0.9rem; font-weight: 500; }
.btn-autonomous:hover:not(:disabled) { background: linear-gradient(135deg, #059669 0%, #047857 100%); transform: translateY(-1px); }
.btn-autonomous:disabled { background: #ccc; cursor: not-allowed; transform: none; }
.modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0, 0, 0, 0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal { background: white; border-radius: 12px; width: 90%; max-width: 500px; box-shadow: 0 20px 50px rgba(0, 0, 0, 0.2); }
.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 1rem 1.5rem; border-bottom: 1px solid #e0e0e0; }
.modal-header h3 { margin: 0; color: #333; }
.modal-close { background: none; border: none; font-size: 1.5rem; cursor: pointer; color: #666; }
.modal-close:hover { color: #333; }
.modal-body { padding: 1.5rem; }
.modal-body p { margin-bottom: 1rem; color: #666; }
.phase-list { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1.5rem; }
.phase-item { padding: 0.25rem 0.75rem; background: #f0f4ff; border-radius: 20px; font-size: 0.8rem; color: #667eea; }
.target-input { width: 100%; padding: 0.75rem 1rem; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 1rem; margin-bottom: 1rem; }
.target-input:focus { outline: none; border-color: #667eea; }
.modal-actions { display: flex; justify-content: flex-end; gap: 0.75rem; }
.btn-cancel { padding: 0.5rem 1rem; border: 1px solid #e0e0e0; border-radius: 6px; background: white; cursor: pointer; }
.btn-start { padding: 0.5rem 1.5rem; border: none; border-radius: 6px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; cursor: pointer; font-weight: 500; }
.btn-start:hover:not(:disabled) { transform: translateY(-1px); }
.btn-start:disabled { background: #ccc; cursor: not-allowed; }
.autonomous-panel { position: fixed; bottom: 100px; right: 20px; background: white; border-radius: 12px; padding: 1rem; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15); width: 280px; z-index: 100; }
.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; }
.panel-header h4 { margin: 0; color: #333; font-size: 0.95rem; }
.step-counter { font-size: 0.8rem; color: #666; }
.phase-indicator { display: flex; justify-content: space-between; margin-bottom: 1rem; }
.phase-dot { width: 32px; height: 32px; border-radius: 50%; background: #e0e0e0; display: flex; align-items: center; justify-content: center; font-size: 0.7rem; font-weight: bold; color: #666; transition: all 0.3s; }
.phase-dot.active { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; transform: scale(1.1); }
.phase-dot.completed { background: #10b981; color: white; }
.findings-summary { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.finding-item { display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; color: #666; }
.finding-icon { font-size: 1rem; }
</style>
