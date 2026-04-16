/**
 * SkidCon WebSocket 客户端
 */

class WebSocketClient {
  constructor() {
    this.ws = null
    this.taskId = null
    this.reconnectAttempts = 0
    this.maxReconnectAttempts = 5
    this.reconnectDelay = 1000
    this.callbacks = {
      onLog: null,
      onStatus: null,
      onCompleted: null,
      onFailed: null,
      onError: null,
      onConnected: null,
      onDisconnected: null
    }
  }

  connect(taskId) {
    this.taskId = taskId
    this.reconnectAttempts = 0
    
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/task/${taskId}`
    
    this.ws = new WebSocket(wsUrl)
    
    this.ws.onopen = () => {
      console.log('WebSocket 连接成功')
      this.reconnectAttempts = 0
      if (this.callbacks.onConnected) {
        this.callbacks.onConnected()
      }
    }
    
    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        this.handleMessage(data)
      } catch (error) {
        console.error('WebSocket 消息解析错误:', error)
      }
    }
    
    this.ws.onclose = () => {
      console.log('WebSocket 连接关闭')
      if (this.callbacks.onDisconnected) {
        this.callbacks.onDisconnected()
      }
      this.attemptReconnect()
    }
    
    this.ws.onerror = (error) => {
      console.error('WebSocket 错误:', error)
      if (this.callbacks.onError) {
        this.callbacks.onError(error)
      }
    }
  }

  handleMessage(data) {
    switch (data.type) {
      case 'log':
        if (this.callbacks.onLog) {
          this.callbacks.onLog(data.message)
        }
        break
      case 'status':
        if (this.callbacks.onStatus) {
          this.callbacks.onStatus(data.status)
        }
        break
      case 'completed':
        if (this.callbacks.onCompleted) {
          this.callbacks.onCompleted(data.result)
        }
        break
      case 'failed':
        if (this.callbacks.onFailed) {
          this.callbacks.onFailed(data.error)
        }
        break
      case 'pong':
        // 心跳响应
        break
      default:
        console.log('未知消息类型:', data.type)
    }
  }

  attemptReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++
      console.log(`尝试重连 (${this.reconnectAttempts}/${this.maxReconnectAttempts})...`)
      setTimeout(() => {
        this.connect(this.taskId)
      }, this.reconnectDelay * this.reconnectAttempts)
    }
  }

  send(message) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(message)
    }
  }

  ping() {
    this.send('ping')
  }

  disconnect() {
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }

  on(event, callback) {
    if (this.callbacks.hasOwnProperty(event)) {
      this.callbacks[event] = callback
    }
  }

  off(event) {
    if (this.callbacks.hasOwnProperty(event)) {
      this.callbacks[event] = null
    }
  }
}

export default WebSocketClient
