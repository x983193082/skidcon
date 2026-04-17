<template>
  <div class="skidcon-app">
    <!-- 头部 -->
    <header class="app-header">
      <h1>🚀 SkidCon - AI 渗透测试系统</h1>
      <div class="health-status" :class="healthStatus">
        {{ healthStatus === 'ok' ? '✅ 系统正常' : '❌ 系统异常' }}
      </div>
    </header>

    <!-- 目标输入区 -->
    <section class="target-section">
      <div class="input-group">
        <label>测试目标:</label>
        <input 
          v-model="target" 
          type="text" 
          placeholder="输入目标 IP 或 URL (例如: 192.168.1.1 或 example.com)"
          :disabled="isRunning"
          @keyup.enter="startTest"
        />
        <button @click="startTest" :disabled="isRunning || !target" class="btn-primary">
          {{ isRunning ? '测试中...' : '开始测试' }}
        </button>
        <button @click="clearTarget" :disabled="isRunning" class="btn-secondary">
          清空
        </button>
      </div>
    </section>

    <!-- 主内容区 -->
    <main class="main-content" v-if="currentTask">
      <!-- 左侧：任务进度 -->
      <aside class="progress-panel">
        <h3>📊 任务进度</h3>
        <div class="task-info">
          <p><strong>任务 ID:</strong> {{ currentTask.id }}</p>
          <p><strong>目标:</strong> {{ currentTask.target }}</p>
          <p><strong>状态:</strong> <span :class="statusClass">{{ currentTask.status }}</span></p>
        </div>

        <div class="stages">
          <div 
            v-for="(stage, index) in stages" 
            :key="index"
            class="stage-item"
            :class="getStageClass(stage.name)"
          >
            <span class="stage-icon">{{ getStageIcon(stage.name) }}</span>
            <span class="stage-name">{{ stage.label }}</span>
          </div>
        </div>

        <!-- 历史任务 -->
        <div class="history-section">
          <h3>📜 历史任务</h3>
          <div class="task-list">
            <div 
              v-for="task in taskList" 
              :key="task.id"
              class="task-item"
              @click="loadTask(task.id)"
              :class="{ active: task.id === currentTask.id }"
            >
              <span class="task-target">{{ task.target }}</span>
              <span class="task-status" :class="task.status">{{ task.status }}</span>
            </div>
          </div>
        </div>
      </aside>

      <!-- 右侧：实时输出 -->
      <section class="output-panel">
        <h3>💻 实时输出</h3>
        <div class="output-container" ref="outputContainer">
          <div 
            v-for="(log, index) in logs" 
            :key="index"
            class="log-line"
            v-html="formatLog(log)"
          ></div>
          <div v-if="logs.length === 0" class="empty-state">
            等待任务开始...
          </div>
        </div>
      </section>
    </main>

    <!-- 报告区域 -->
    <section class="report-section" v-if="showReport">
      <div class="report-header">
        <h3>📝 测试报告</h3>
        <div class="report-actions">
          <button @click="exportMarkdown" class="btn-primary">导出 Markdown</button>
          <button @click="exportPDF" class="btn-secondary">导出 PDF</button>
        </div>
      </div>
      <div class="report-content" v-html="renderedReport"></div>
    </section>

    <!-- 无任务状态 -->
    <section class="empty-state-main" v-if="!currentTask">
      <div class="welcome-message">
        <h2>欢迎使用 SkidCon</h2>
        <p>输入目标 IP 或 URL，点击"开始测试"启动自动化渗透测试</p>
        <div class="features">
          <div class="feature-item">✅ 50+ 渗透测试工具</div>
          <div class="feature-item">✅ 多阶段链式攻击</div>
          <div class="feature-item">✅ 实时输出推送</div>
          <div class="feature-item">✅ 自动报告生成</div>
          <div class="feature-item">✅ 并发任务支持</div>
        </div>
      </div>
    </section>
  </div>
</template>

<script>
import { createTask, getTaskStatus, getTaskList, getReport, downloadReport, healthCheck } from './api.js'
import WebSocketClient from './ws.js'

export default {
  name: 'App',
  data() {
    return {
      target: '',
      currentTask: null,
      logs: [],
      taskList: [],
      reportContent: '',
      showReport: false,
      isRunning: false,
      healthStatus: 'unknown',
      wsClient: null,
      stages: [
        { name: 'recon', label: '信息收集' },
        { name: 'service_analysis', label: '服务分析' },
        { name: 'vulnerability_detection', label: '漏洞检测' },
        { name: 'exploitation', label: '漏洞利用' },
        { name: 'report', label: '报告生成' }
      ],
      completedStages: [],
      currentStage: null,
      pollInterval: null
    }
  },
  computed: {
    statusClass() {
      if (!this.currentTask) return ''
      return `status-${this.currentTask.status}`
    },
    renderedReport() {
      if (!this.reportContent) return ''
      // 简单的 Markdown 渲染
      return this.reportContent
        .replace(/^# (.*$)/gim, '<h1>$1</h1>')
        .replace(/^## (.*$)/gim, '<h2>$1</h2>')
        .replace(/^### (.*$)/gim, '<h3>$1</h3>')
        .replace(/\*\*(.*)\*\*/gim, '<strong>$1</strong>')
        .replace(/\*(.*)\*/gim, '<em>$1</em>')
        .replace(/```([\s\S]*?)```/gim, '<pre><code>$1</code></pre>')
        .replace(/`([^`]+)`/gim, '<code>$1</code>')
        .replace(/\n/gim, '<br>')
    }
  },
  mounted() {
    this.checkHealth()
    this.loadTaskList()
    // 定期检查任务列表
    this.pollTaskList = setInterval(() => {
      this.loadTaskList()
    }, 5000)
  },
  beforeUnmount() {
    if (this.wsClient) {
      this.wsClient.disconnect()
    }
    if (this.pollTaskList) {
      clearInterval(this.pollTaskList)
    }
    if (this.pollInterval) {
      clearInterval(this.pollInterval)
    }
  },
  methods: {
    async checkHealth() {
      try {
        const health = await healthCheck()
        this.healthStatus = health.status
      } catch (error) {
        console.error('健康检查失败:', error)
        this.healthStatus = 'error'
      }
    },
    async loadTaskList() {
      try {
        this.taskList = await getTaskList()
      } catch (error) {
        console.error('加载任务列表失败:', error)
      }
    },
    async startTest() {
      if (!this.target || this.isRunning) return
      
      this.isRunning = true
      this.logs = []
      this.completedStages = []
      this.currentStage = null
      this.showReport = false
      
      try {
        const task = await createTask(this.target)
        this.currentTask = task
        this.connectWebSocket(task.id)
        this.startPolling(task.id)
      } catch (error) {
        console.error('创建任务失败:', error)
        this.logs.push(`❌ 创建任务失败: ${error.message}`)
        this.isRunning = false
      }
    },
    connectWebSocket(taskId) {
      if (this.wsClient) {
        this.wsClient.disconnect()
      }
      
      this.wsClient = new WebSocketClient()
      
      this.wsClient.on('onLog', (message) => {
        this.logs.push(message)
        this.scrollToBottom()
        this.updateStage(message)
      })
      
      this.wsClient.on('onStatus', (status) => {
        if (this.currentTask) {
          this.currentTask.status = status
        }
      })
      
      this.wsClient.on('onCompleted', async (result) => {
        this.isRunning = false
        this.logs.push('✅ 测试完成!')
        
        // 加载报告（使用 this.currentTask.id 确保获取正确的 taskId）
        try {
          const report = await getReport(this.currentTask.id)
          this.reportContent = report.content
          this.showReport = true
        } catch (error) {
          console.error('加载报告失败:', error)
        }
        
        this.loadTaskList()
      })
      
      this.wsClient.on('onFailed', (error) => {
        this.isRunning = false
        this.logs.push(`❌ 任务失败: ${error}`)
        this.loadTaskList()
      })
      
      this.wsClient.connect(taskId)
    },
    startPolling(taskId) {
      if (this.pollInterval) {
        clearInterval(this.pollInterval)
      }
      
      this.pollInterval = setInterval(async () => {
        try {
          const task = await getTaskStatus(taskId)
          this.currentTask = task
          
          if (task.status === 'completed' || task.status === 'failed') {
            clearInterval(this.pollInterval)
            this.isRunning = false
          }
        } catch (error) {
          console.error('轮询任务状态失败:', error)
        }
      }, 2000)
    },
    async loadTask(taskId) {
      try {
        const task = await getTaskStatus(taskId)
        this.currentTask = task
        this.logs = task.logs || []
        this.isRunning = task.status === 'running'
        
        if (task.status === 'completed') {
          try {
            const report = await getReport(taskId)
            this.reportContent = report.content
            this.showReport = true
          } catch (error) {
            console.error('加载报告失败:', error)
          }
        }
        
        if (this.isRunning) {
          this.connectWebSocket(taskId)
          this.startPolling(taskId)
        }
      } catch (error) {
        console.error('加载任务失败:', error)
      }
    },
    updateStage(message) {
      // 根据日志消息更新阶段状态
      if (message.includes('阶段 1') || message.includes('信息收集')) {
        this.currentStage = 'recon'
      } else if (message.includes('阶段 2') || message.includes('服务分析')) {
        this.completedStages.push('recon')
        this.currentStage = 'service_analysis'
      } else if (message.includes('阶段 3') || message.includes('漏洞检测')) {
        this.completedStages.push('service_analysis')
        this.currentStage = 'vulnerability_detection'
      } else if (message.includes('阶段 4') || message.includes('漏洞利用')) {
        this.completedStages.push('vulnerability_detection')
        this.currentStage = 'exploitation'
      } else if (message.includes('阶段 5') || message.includes('报告生成')) {
        this.completedStages.push('exploitation')
        this.currentStage = 'report'
      } else if (message.includes('完成')) {
        this.completedStages.push('report')
        this.currentStage = null
      }
    },
    getStageClass(stageName) {
      if (this.completedStages.includes(stageName)) {
        return 'completed'
      }
      if (this.currentStage === stageName) {
        return 'active'
      }
      return 'pending'
    },
    getStageIcon(stageName) {
      if (this.completedStages.includes(stageName)) {
        return '✅'
      }
      if (this.currentStage === stageName) {
        return '🔄'
      }
      return '⏳'
    },
    formatLog(log) {
      // 高亮关键信息
      return log
        .replace(/✅/g, '<span class="success">✅</span>')
        .replace(/❌/g, '<span class="error">❌</span>')
        .replace(/🔄/g, '<span class="warning">🔄</span>')
    },
    scrollToBottom() {
      this.$nextTick(() => {
        const container = this.$refs.outputContainer
        if (container) {
          container.scrollTop = container.scrollHeight
        }
      })
    },
    clearTarget() {
      this.target = ''
    },
    exportMarkdown() {
      const blob = new Blob([this.reportContent], { type: 'text/markdown' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `skidcon_report_${this.currentTask.id}.md`
      a.click()
      URL.revokeObjectURL(url)
    },
    exportPDF() {
      // 简单实现：打印为 PDF
      window.print()
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
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  background: #0a0e27;
  color: #e0e0e0;
  line-height: 1.6;
}

.skidcon-app {
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px;
}

.app-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 10px;
  margin-bottom: 20px;
}

.app-header h1 {
  font-size: 28px;
  color: white;
}

.health-status {
  padding: 8px 16px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.2);
  color: white;
  font-weight: bold;
}

.target-section {
  background: #1a1f3a;
  padding: 20px;
  border-radius: 10px;
  margin-bottom: 20px;
}

.input-group {
  display: flex;
  gap: 10px;
  align-items: center;
}

.input-group label {
  font-weight: bold;
  min-width: 80px;
}

.input-group input {
  flex: 1;
  padding: 12px 16px;
  border: 2px solid #2d3561;
  border-radius: 8px;
  background: #0a0e27;
  color: #e0e0e0;
  font-size: 14px;
}

.input-group input:focus {
  outline: none;
  border-color: #667eea;
}

.btn-primary, .btn-secondary {
  padding: 12px 24px;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: bold;
  cursor: pointer;
  transition: all 0.3s;
}

.btn-primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.btn-secondary {
  background: #2d3561;
  color: #e0e0e0;
}

.btn-secondary:hover:not(:disabled) {
  background: #3d4571;
}

button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.main-content {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 20px;
  margin-bottom: 20px;
}

.progress-panel, .output-panel {
  background: #1a1f3a;
  padding: 20px;
  border-radius: 10px;
}

.progress-panel h3, .output-panel h3 {
  margin-bottom: 15px;
  color: #667eea;
}

.task-info {
  margin-bottom: 20px;
  padding: 15px;
  background: #0a0e27;
  border-radius: 8px;
}

.task-info p {
  margin: 8px 0;
}

.status-pending { color: #ffa500; }
.status-running { color: #00ff00; }
.status-completed { color: #00ff88; }
.status-failed { color: #ff4444; }

.stages {
  margin-bottom: 20px;
}

.stage-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  margin: 8px 0;
  border-radius: 8px;
  background: #0a0e27;
}

.stage-item.pending {
  opacity: 0.5;
}

.stage-item.active {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.2) 0%, rgba(118, 75, 162, 0.2) 100%);
  border-left: 4px solid #667eea;
}

.stage-item.completed {
  background: rgba(0, 255, 136, 0.1);
  border-left: 4px solid #00ff88;
}

.history-section {
  margin-top: 20px;
  border-top: 2px solid #2d3561;
  padding-top: 20px;
}

.task-list {
  max-height: 300px;
  overflow-y: auto;
}

.task-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px;
  margin: 5px 0;
  background: #0a0e27;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.task-item:hover {
  background: #2d3561;
}

.task-item.active {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.3) 0%, rgba(118, 75, 162, 0.3) 100%);
}

.task-target {
  font-weight: bold;
}

.task-status {
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: bold;
}

.task-status.completed {
  background: rgba(0, 255, 136, 0.2);
  color: #00ff88;
}

.task-status.running {
  background: rgba(0, 255, 0, 0.2);
  color: #00ff00;
}

.task-status.failed {
  background: rgba(255, 68, 68, 0.2);
  color: #ff4444;
}

.output-container {
  background: #0a0e27;
  padding: 15px;
  border-radius: 8px;
  height: 500px;
  overflow-y: auto;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.8;
}

.log-line {
  margin: 2px 0;
}

.success { color: #00ff88; }
.error { color: #ff4444; }
.warning { color: #ffa500; }

.empty-state {
  text-align: center;
  color: #666;
  padding: 50px;
}

.empty-state-main {
  text-align: center;
  padding: 100px 20px;
}

.welcome-message h2 {
  font-size: 36px;
  margin-bottom: 20px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.welcome-message p {
  font-size: 18px;
  color: #888;
  margin-bottom: 40px;
}

.features {
  display: flex;
  justify-content: center;
  gap: 20px;
  flex-wrap: wrap;
}

.feature-item {
  padding: 12px 20px;
  background: #1a1f3a;
  border-radius: 8px;
  font-size: 14px;
}

.report-section {
  background: #1a1f3a;
  padding: 20px;
  border-radius: 10px;
  margin-bottom: 20px;
}

.report-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.report-header h3 {
  color: #667eea;
}

.report-actions {
  display: flex;
  gap: 10px;
}

.report-content {
  background: #0a0e27;
  padding: 20px;
  border-radius: 8px;
  max-height: 600px;
  overflow-y: auto;
}

.report-content h1, .report-content h2, .report-content h3 {
  color: #667eea;
  margin: 20px 0 10px 0;
}

.report-content pre {
  background: #1a1f3a;
  padding: 15px;
  border-radius: 6px;
  overflow-x: auto;
}

.report-content code {
  background: #1a1f3a;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
}

/* 滚动条样式 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: #0a0e27;
}

::-webkit-scrollbar-thumb {
  background: #2d3561;
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: #3d4571;
}
</style>
