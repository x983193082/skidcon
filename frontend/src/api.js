/**
 * SkidCon API 请求封装
 */

import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 创建任务
export async function createTask(target) {
  const response = await api.post('/task', { target })
  return response.data
}

// 获取任务状态
export async function getTaskStatus(taskId) {
  const response = await api.get(`/task/${taskId}`)
  return response.data
}

// 获取所有任务
export async function getTaskList() {
  const response = await api.get('/tasks')
  return response.data
}

// 获取报告
export async function getReport(taskId) {
  const response = await api.get(`/report/${taskId}`)
  return response.data
}

// 下载报告
export function downloadReport(taskId) {
  window.open(`/api/report/${taskId}/download`, '_blank')
}

// 健康检查
export async function healthCheck() {
  const response = await api.get('/health')
  return response.data
}

export default api
