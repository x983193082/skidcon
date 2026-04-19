# SkidCon API 文档

本文档详细描述SkidCon系统提供的所有REST API端点。

## 基础信息

- **Base URL**: `http://localhost:8000`
- **内容类型**: `application/json`
- **CORS**: 已启用（允许所有来源）

## API端点概览

| 方法 | 路径 | 描述 | 认证 |
|------|------|------|------|
| GET | `/` | Web界面主页 | 无 |
| GET | `/api/history` | 获取对话历史 | 无 |
| GET | `/api/history/summary` | 获取对话历史摘要 | 无 |
| GET | `/api/memory/stats` | 获取记忆统计信息 | 无 |
| POST | `/api/history/clear` | 清空对话历史 | 无 |
| POST | `/api/query` | 提交查询并执行Agent | 无 |
| GET | `/api/query/{task_id}/stream` | SSE流式输出 | 无 |

---

## 详细端点说明

### 1. 获取对话历史

**端点**: `GET /api/history`

**描述**: 获取所有对话历史记录

**请求参数**: 无

**响应格式**:
```json
{
  "status": "success",
  "count": 2,
  "history": [
    {
      "role": "user",
      "content": "扫描192.168.1.1的开放端口",
      "timestamp": "2024-01-01T12:00:00"
    },
    {
      "role": "assistant",
      "content": "正在使用nmap扫描192.168.1.1...\n\n扫描结果：\n- 22/tcp open ssh\n- 80/tcp open http",
      "timestamp": "2024-01-01T12:01:00"
    }
  ]
}
```

**响应字段**:
- `status`: 请求状态（"success" 或 "error"）
- `count`: 对话历史数量
- `history`: 对话历史数组
  - `role`: 角色（"user" 或 "assistant"）
  - `content`: 消息内容
  - `timestamp`: 时间戳（ISO格式）

**示例请求**:
```bash
curl http://localhost:8000/api/history
```

**示例响应**:
```json
{
  "status": "success",
  "count": 2,
  "history": [
    {
      "role": "user",
      "content": "扫描192.168.1.1的开放端口",
      "timestamp": "2024-01-01T12:00:00"
    },
    {
      "role": "assistant",
      "content": "正在使用nmap扫描192.168.1.1...\n\n扫描结果：\n- 22/tcp open ssh\n- 80/tcp open http",
      "timestamp": "2024-01-01T12:01:00"
    }
  ]
}
```

**错误响应**:
```json
{
  "status": "error",
  "error": "错误信息"
}
```

---

### 2. 获取对话历史摘要

**端点**: `GET /api/history/summary`

**描述**: 获取对话历史的摘要信息

**请求参数**: 无

**响应格式**:
```json
{
  "status": "success",
  "summary": "对话历史摘要文本..."
}
```

**响应字段**:
- `status`: 请求状态
- `summary`: 对话历史摘要（纯文本）

**示例请求**:
```bash
curl http://localhost:8000/api/history/summary
```

**示例响应**:
```json
{
  "status": "success",
  "summary": "总对话数：2\n最后更新：2024-01-01 12:01:00\n\n最近对话：\n1. 用户：扫描192.168.1.1的开放端口\n   AI：正在使用nmap扫描192.168.1.1..."
}
```

---

### 3. 获取记忆统计信息

**端点**: `GET /api/memory/stats`

**描述**: 获取记忆管理系统的统计信息

**请求参数**: 无

**响应格式**:
```json
{
  "status": "success",
  "stats": {
    "total_conversations": 5,
    "total_tokens": 12345,
    "max_tokens": 8192,
    "model_name": "z-ai/glm-5.1",
    "entries": [
      {
        "index": 0,
        "user_query": "扫描192.168.1.1",
        "timestamp": "2024-01-01T12:00:00",
        "token_count": 150,
        "importance_score": 1.0,
        "is_summarized": false
      }
    ]
  }
}
```

**响应字段**:
- `status`: 请求状态
- `stats`: 统计信息
  - `total_conversations`: 总对话数
  - `total_tokens`: 总token数
  - `max_tokens`: 最大token限制
  - `model_name`: 模型名称
  - `entries`: 对话条目列表
    - `index`: 索引
    - `user_query`: 用户查询
    - `timestamp`: 时间戳
    - `token_count`: token数
    - `importance_score`: 重要性评分（0-1）
    - `is_summarized`: 是否已总结

**示例请求**:
```bash
curl http://localhost:8000/api/memory/stats
```

**错误响应**:
```json
{
  "status": "error",
  "error": "获取记忆统计失败: 错误信息"
}
```

---

### 4. 清空对话历史

**端点**: `POST /api/history/clear`

**描述**: 清空所有对话历史

**请求参数**: 无

**响应格式**:
```json
{
  "status": "success",
  "message": "历史已清空"
}
```

**响应字段**:
- `status`: 请求状态
- `message`: 操作结果消息

**示例请求**:
```bash
curl -X POST http://localhost:8000/api/history/clear
```

**示例响应**:
```json
{
  "status": "success",
  "message": "历史已清空"
}
```

---

### 5. 提交查询

**端点**: `POST /api/query`

**描述**: 提交查询并执行Agent，返回task_id用于流式输出

**请求格式**:
```json
{
  "query": "扫描192.168.1.1的开放端口"
}
```

**请求字段**:
- `query`: 用户查询（必填，字符串）

**响应格式**:
```json
{
  "status": "success",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "查询已提交，正在处理..."
}
```

**响应字段**:
- `status`: 请求状态
- `task_id`: 任务ID（用于SSE流式输出）
- `message`: 操作结果消息

**示例请求**:
```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "扫描192.168.1.1的开放端口"}'
```

**示例响应**:
```json
{
  "status": "success",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "查询已提交，正在处理..."
}
```

**错误响应**:
```json
{
  "status": "error",
  "message": "查询不能为空"
}
```

或

```json
{
  "status": "error",
  "message": "无效的请求格式"
}
```

---

### 6. SSE流式输出

**端点**: `GET /api/query/{task_id}/stream`

**描述**: 使用Server-Sent Events (SSE) 实时获取Agent执行输出

**路径参数**:
- `task_id`: 任务ID（从 `/api/query` 响应中获取）

**响应格式**: SSE事件流

**事件类型**:

#### 6.1 agent_thinking - Agent思考状态

```
event: agent_thinking
data: {"agent": "Level 1 Classifier", "status": "thinking", "message": "正在分析任务..."}
```

**字段**:
- `agent`: Agent名称
- `status`: 状态（"thinking", "completed", "error"）
- `message`: 状态消息

#### 6.2 agent_message - Agent消息

```
event: agent_message
data: {"agent": "Level 1 Classifier", "content": "闲聊模式（不调用工具链）"}
```

**字段**:
- `agent`: Agent名称
- `content`: 消息内容

#### 6.3 tool_call - 工具调用

```
event: tool_call
data: {"tool": "kali_command", "args": {"command": "nmap -sV 192.168.1.1", "rationale": "扫描目标主机的服务版本"}}
```

**字段**:
- `tool`: 工具名称
- `args`: 工具参数
  - `command`: 执行的命令
  - `rationale`: 执行理由

#### 6.4 tool_output - 工具输出

```
event: tool_output
data: {"output": "Starting Nmap 7.94...\nPORT   STATE SERVICE\n22/tcp open  ssh\n80/tcp open  http"}
```

**字段**:
- `output`: 工具执行输出

#### 6.5 agent_done - Agent完成

```
event: agent_done
data: {"result": "扫描完成，发现2个开放端口..."}
```

**字段**:
- `result`: Agent执行结果

#### 6.6 error - 错误

```
event: error
data: {"error": "错误信息"}
```

**字段**:
- `error`: 错误信息

**完整SSE流示例**:
```
event: agent_thinking
data: {"agent": "Level 1 Classifier", "status": "thinking", "message": "正在分析任务..."}

event: agent_thinking
data: {"agent": "Level 1 Classifier", "status": "completed", "message": "分类完成：scanning"}

event: agent_thinking
data: {"agent": "Scanning Expert", "status": "thinking", "message": "正在选择扫描工具..."}

event: tool_call
data: {"tool": "kali_command", "args": {"command": "nmap -sV 192.168.1.1", "rationale": "扫描目标主机的服务版本"}}

event: tool_output
data: {"output": "Starting Nmap 7.94...\nPORT   STATE SERVICE\n22/tcp open  ssh\n80/tcp open  http"}

event: agent_done
data: {"result": "扫描完成，发现2个开放端口..."}
```

**前端JavaScript示例**:
```javascript
const eventSource = new EventSource(`/api/query/${taskId}/stream`);

eventSource.addEventListener('agent_thinking', (event) => {
  const data = JSON.parse(event.data);
  console.log(`[${data.agent}] ${data.message}`);
});

eventSource.addEventListener('tool_call', (event) => {
  const data = JSON.parse(event.data);
  console.log(`调用工具: ${data.tool}`, data.args);
});

eventSource.addEventListener('tool_output', (event) => {
  const data = JSON.parse(event.data);
  console.log('工具输出:', data.output);
});

eventSource.addEventListener('agent_done', (event) => {
  const data = JSON.parse(event.data);
  console.log('Agent完成:', data.result);
  eventSource.close();
});

eventSource.addEventListener('error', (event) => {
  const data = JSON.parse(event.data);
  console.error('错误:', data.error);
  eventSource.close();
});
```

**curl示例**:
```bash
curl -N http://localhost:8000/api/query/550e8400-e29b-41d4-a716-446655440000/stream
```

---

## 错误处理

### 通用错误格式

```json
{
  "status": "error",
  "error": "错误描述",
  "message": "详细错误信息"
}
```

### 常见错误码

| HTTP状态码 | 描述 | 示例场景 |
|-----------|------|----------|
| 400 | 请求错误 | 查询为空、无效格式 |
| 500 | 服务器错误 | Agent执行失败、内部错误 |

### 错误示例

**查询为空**:
```json
{
  "status": "error",
  "message": "查询不能为空"
}
```

**无效请求格式**:
```json
{
  "status": "error",
  "message": "无效的请求格式"
}
```

**Agent执行失败**:
```json
{
  "status": "error",
  "error": "一级Agent输出不是合法JSON: ..."
}
```

---

## 使用示例

### 完整查询流程

#### 步骤1: 提交查询

```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "扫描192.168.1.1的开放端口"}'
```

**响应**:
```json
{
  "status": "success",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "查询已提交，正在处理..."
}
```

#### 步骤2: 监听SSE流

```bash
curl -N http://localhost:8000/api/query/550e8400-e29b-41d4-a716-446655440000/stream
```

**输出**:
```
event: agent_thinking
data: {"agent": "Level 1 Classifier", "status": "thinking", "message": "正在分析任务..."}

event: agent_thinking
data: {"agent": "Level 1 Classifier", "status": "completed", "message": "分类完成：scanning"}

event: agent_thinking
data: {"agent": "Scanning Expert", "status": "thinking", "message": "正在选择扫描工具..."}

event: tool_call
data: {"tool": "kali_command", "args": {"command": "nmap -sV 192.168.1.1"}}

event: tool_output
data: {"output": "PORT   STATE SERVICE\n22/tcp open  ssh\n80/tcp open  http"}

event: agent_done
data: {"result": "扫描完成，发现2个开放端口"}
```

#### 步骤3: 查看历史

```bash
curl http://localhost:8000/api/history
```

**响应**:
```json
{
  "status": "success",
  "count": 2,
  "history": [
    {
      "role": "user",
      "content": "扫描192.168.1.1的开放端口",
      "timestamp": "2024-01-01T12:00:00"
    },
    {
      "role": "assistant",
      "content": "扫描完成，发现2个开放端口...",
      "timestamp": "2024-01-01T12:01:00"
    }
  ]
}
```

---

## Python客户端示例

```python
import requests
import json

BASE_URL = "http://localhost:8000"

def submit_query(query: str):
    """提交查询并获取task_id"""
    response = requests.post(
        f"{BASE_URL}/api/query",
        json={"query": query}
    )
    return response.json()

def get_history():
    """获取对话历史"""
    response = requests.get(f"{BASE_URL}/api/history")
    return response.json()

def get_history_summary():
    """获取历史摘要"""
    response = requests.get(f"{BASE_URL}/api/history/summary")
    return response.json()

def get_memory_stats():
    """获取记忆统计"""
    response = requests.get(f"{BASE_URL}/api/memory/stats")
    return response.json()

def clear_history():
    """清空历史"""
    response = requests.post(f"{BASE_URL}/api/history/clear")
    return response.json()

def listen_stream(task_id: str):
    """监听SSE流"""
    import httpx
    
    with httpx.stream("GET", f"{BASE_URL}/api/query/{task_id}/stream") as response:
        for line in response.iter_lines():
            if line.startswith("event:"):
                event_type = line.split(": ", 1)[1]
            elif line.startswith("data:"):
                data = json.loads(line.split(": ", 1)[1])
                print(f"[{event_type}] {data}")

# 使用示例
if __name__ == "__main__":
    # 提交查询
    result = submit_query("扫描192.168.1.1的开放端口")
    print("Task ID:", result["task_id"])
    
    # 监听流式输出
    listen_stream(result["task_id"])
    
    # 查看历史
    history = get_history()
    print(f"对话数量: {history['count']}")
```

---

## JavaScript客户端示例

```javascript
const BASE_URL = 'http://localhost:8000';

async function submitQuery(query) {
  const response = await fetch(`${BASE_URL}/api/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query })
  });
  return await response.json();
}

async function getHistory() {
  const response = await fetch(`${BASE_URL}/api/history`);
  return await response.json();
}

async function getHistorySummary() {
  const response = await fetch(`${BASE_URL}/api/history/summary`);
  return await response.json();
}

async function getMemoryStats() {
  const response = await fetch(`${BASE_URL}/api/memory/stats`);
  return await response.json();
}

async function clearHistory() {
  const response = await fetch(`${BASE_URL}/api/history/clear`, {
    method: 'POST'
  });
  return await response.json();
}

function listenStream(taskId, callbacks) {
  const eventSource = new EventSource(`${BASE_URL}/api/query/${taskId}/stream`);
  
  eventSource.addEventListener('agent_thinking', (event) => {
    const data = JSON.parse(event.data);
    callbacks.onThinking?.(data);
  });
  
  eventSource.addEventListener('agent_message', (event) => {
    const data = JSON.parse(event.data);
    callbacks.onMessage?.(data);
  });
  
  eventSource.addEventListener('tool_call', (event) => {
    const data = JSON.parse(event.data);
    callbacks.onToolCall?.(data);
  });
  
  eventSource.addEventListener('tool_output', (event) => {
    const data = JSON.parse(event.data);
    callbacks.onToolOutput?.(data);
  });
  
  eventSource.addEventListener('agent_done', (event) => {
    const data = JSON.parse(event.data);
    callbacks.onDone?.(data);
    eventSource.close();
  });
  
  eventSource.addEventListener('error', (event) => {
    const data = JSON.parse(event.data);
    callbacks.onError?.(data);
    eventSource.close();
  });
}

// 使用示例
async function main() {
  // 提交查询
  const result = await submitQuery('扫描192.168.1.1的开放端口');
  console.log('Task ID:', result.task_id);
  
  // 监听流式输出
  listenStream(result.task_id, {
    onThinking: (data) => console.log('[Thinking]', data.message),
    onToolCall: (data) => console.log('[Tool Call]', data.tool, data.args),
    onToolOutput: (data) => console.log('[Tool Output]', data.output),
    onDone: (data) => console.log('[Done]', data.result),
    onError: (data) => console.error('[Error]', data.error)
  });
  
  // 查看历史
  const history = await getHistory();
  console.log('对话数量:', history.count);
}

main();
```

---

## 注意事项

1. **SSE连接**: SSE连接会保持打开直到Agent执行完成或发生错误
2. **任务ID**: 每个查询都会生成唯一的task_id，用于追踪和流式输出
3. **并发**: 系统支持并发查询，每个查询有独立的task_id
4. **超时**: Agent执行有超时限制（默认300秒），超时后会返回错误
5. **历史限制**: 对话历史受Memory Manager管理，超出token限制的旧对话会被总结
6. **CORS**: 开发模式允许所有来源，生产环境应配置适当的CORS策略

---

## 更新日志

- **v1.0**: 初始版本，包含基础API端点
  - GET /api/history
  - GET /api/history/summary
  - GET /api/memory/stats
  - POST /api/history/clear
  - POST /api/query
  - GET /api/query/{task_id}/stream
