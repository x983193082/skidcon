"""Agent Runner for three-level agent system - CrewAI 版本"""

import json
import re
from datetime import datetime
from typing import List, Dict, Optional, Any
from colorama import Fore, Style
from crewai import Agent, Task, Crew
from langchain_openai import ChatOpenAI

from core.level1_agent import task_classifier_agent, create_llm as create_level1_llm
from core.level2_agent import (
    agent_information_collection,
    agent_scanning,
    agent_enumeration,
    agent_web_exploitation,
    agent_exploitation,
    agent_password_crypto,
    agent_wireless_attack,
    agent_reverse_engineering,
    agent_forensics,
    agent_post_exploitation,
    agent_custom_code,
)
from core.memory_manager import MemoryManager
from core.chat_agent import chat_agent


TARGET_TO_AGENT = {
    "information_collection": agent_information_collection,
    "scanning": agent_scanning,
    "enumeration": agent_enumeration,
    "web_exploitation": agent_web_exploitation,
    "exploitation": agent_exploitation,
    "password_crypto": agent_password_crypto,
    "wireless_attack": agent_wireless_attack,
    "reverse_engineering": agent_reverse_engineering,
    "forensics": agent_forensics,
    "post_exploitation": agent_post_exploitation,
    "custom_code": agent_custom_code,
}


class AgentRunner:
    """处理三级 Agent 系统的查询和执行（CrewAI 版本）"""
    
    def __init__(self, model_name: str = "z-ai/glm-5.1"):
        """初始化 agent runner"""
        self.memory_manager = MemoryManager(model_name=model_name)
        self.output_collector = None  # 输出收集器，用于收集执行过程中的输出
        self.llm = create_level1_llm()

    def _extract_json_from_text(self, text: str) -> str:
        """
        从文本中提取JSON，处理markdown代码块等情况。
        
        Args:
            text: 可能包含JSON的文本
            
        Returns:
            提取出的JSON字符串
        """
        if not text:
            return text
        
        # 移除前后空白
        text = text.strip()
        
        # 尝试匹配markdown代码块中的JSON（支持```json和```两种格式）
        json_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
        match = re.search(json_pattern, text, re.DOTALL)
        if match:
            json_str = match.group(1).strip()
            # 验证是否是有效的JSON
            try:
                json.loads(json_str)
                return json_str
            except json.JSONDecodeError:
                pass
        
        # 尝试直接匹配JSON对象（更精确的匹配）
        # 找到第一个{和最后一个}之间的内容
        start_idx = text.find('{')
        if start_idx != -1:
            # 从第一个{开始，找到匹配的}
            brace_count = 0
            for i in range(start_idx, len(text)):
                if text[i] == '{':
                    brace_count += 1
                elif text[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        json_str = text[start_idx:i+1]
                        # 验证是否是有效的JSON
                        try:
                            json.loads(json_str)
                            return json_str
                        except json.JSONDecodeError:
                            pass
        
        # 如果都没匹配到，返回原文本（让json.loads来处理）
        return text

    def _build_query_with_history(self, query: str) -> str:
        """
        构建包含历史记录的查询。

        Args:
            query: 当前查询

        Returns:
            包含历史记录的完整查询
        """
        return self.memory_manager.build_context(query)

    def _run_agent(self, agent: Agent, query: str, task_id: str = None) -> str:
        """
        运行单个 Agent 并返回结果
        
        Args:
            agent: CrewAI Agent
            query: 输入查询
            task_id: 可选的任务 ID
            
        Returns:
            Agent 执行结果
        """
        # 创建任务
        task = Task(
            description=query,
            agent=agent,
            expected_output="执行结果"
        )
        
        # 创建 Crew 并执行
        crew = Crew(
            agents=[agent],
            tasks=[task],
            verbose=True
        )
        
        result = crew.kickoff()
        return str(result)

    def route_and_run_level2(self, query: str, task_id: str = None):
        """
        1）用一级 agent 生成 JSON 决策
        2）解析 JSON 拿到 target
        3）根据 target 映射到对应二级 Agent，并执行
        
        Args:
            query: 用户查询
            task_id: 可选的任务 ID
            
        Returns:
            (classification_result, level2_result) 元组
        """
        # 构建包含历史记录的查询
        query_with_history = self._build_query_with_history(query)
        
        # 通知Level 1开始
        self._add_output_sync(task_id, "agent_thinking", {
            "agent": "Level 1 Classifier",
            "status": "thinking",
            "message": "正在分析任务..."
        })

        # 1. 运行一级 Agent 获取分类决策
        print(f"{Fore.CYAN}[Level 1] 正在分类任务...{Style.RESET_ALL}")
        classify_result = self._run_agent(
            task_classifier_agent,
            query_with_history,
            task_id=task_id
        )

        # 提取JSON
        json_text = self._extract_json_from_text(classify_result)

        try:
            decision = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"一级Agent输出不是合法JSON: {classify_result}\n提取的JSON文本: {json_text}\n错误: {e}")

        action = decision.get("action")
        if action not in {"handoff", "chat"}:
            raise ValueError(f"一级Agent输出action非法: {decision}")

        # action=chat：直接进入自然语言闲聊
        if action == "chat":
            self._add_output_sync(task_id, "agent_message", {
                "agent": "Level 1 Classifier",
                "content": "闲聊模式（不调用工具链）"
            })
            self._add_output_sync(task_id, "agent_thinking", {
                "agent": "Chat Agent",
                "status": "thinking",
                "message": "正在生成闲聊回复..."
            })

            print(f"{Fore.CYAN}[Chat] 正在生成回复...{Style.RESET_ALL}")
            chat_result = self._run_agent(
                chat_agent,
                query_with_history,
                task_id=task_id
            )
            return classify_result, chat_result

        # action=handoff：根据 target 映射到二级Agent
        target = decision.get("target")
        if target not in TARGET_TO_AGENT:
            raise ValueError(f"未知target: {target}")

        # 显示Level 1的决策结果
        self._add_output_sync(task_id, "agent_message", {
            "agent": "Level 1 Classifier",
            "content": f"任务分类完成 → **{target}**"
        })

        # 通知Level 2开始
        self._add_output_sync(task_id, "agent_thinking", {
            "agent": f"Level 2 {target.title()} Agent",
            "status": "thinking",
            "message": f"正在执行 {target} 任务..."
        })

        level2_agent = TARGET_TO_AGENT[target]
        
        # 2. 调用对应的二级 Agent
        print(f"{Fore.CYAN}[Level 2] 正在执行 {target} 任务...{Style.RESET_ALL}")
        level2_result = self._run_agent(
            level2_agent,
            query_with_history,
            task_id=task_id
        )

        # Level 2完成
        self._add_output_sync(task_id, "agent_message", {
            "agent": f"Level 2 {target.title()} Agent",
            "content": "✅ 执行完成"
        })

        return classify_result, level2_result

    def run_agent(self, query: str, task_id: str = None) -> Any:
        """
        运行三级 Agent 系统
        
        Args:
            query: 用户的自然语言查询
            task_id: 可选的任务 ID
            
        Returns:
            Agent 执行结果
        """
        print(f"{Fore.CYAN}\nProcessing query: {Fore.WHITE}{query}{Style.RESET_ALL}\n")

        try:
            classify_result, level2_result = self.route_and_run_level2(query, task_id)

            # 保存对话历史
            self._add_to_history(query, level2_result)

            # 任务完成
            self._add_output_sync(task_id, "task_completed", {"success": True})

            return level2_result
        except Exception as e:
            error_msg = str(e)
            print(f"{Fore.RED}Error processing agent request: {e}{Style.RESET_ALL}")
            import traceback
            traceback.print_exc()
            # 即使出错也保存查询（但不保存响应）
            self._add_to_history(query, None)

            # 显示错误
            self._add_output_sync(task_id, "agent_message", {
                "agent": "System",
                "content": f"❌ 执行出错：{error_msg}",
                "is_error": True
            })
            self._add_output_sync(task_id, "task_completed", {"success": False, "error": error_msg})

            return None
    
    def _add_to_history(self, user_query: str, ai_response: Optional[str] = None):
        """
        添加对话到历史记录。

        Args:
            user_query: 用户查询
            ai_response: AI响应（可选）
        """
        self.memory_manager.add_conversation(user_query, ai_response)
    
    def clear_history(self):
        """清空对话历史。"""
        self.memory_manager.clear_memory()
        print(f"{Fore.YELLOW}对话历史已清空{Style.RESET_ALL}")

    def get_memory_stats(self) -> Dict[str, Any]:
        """
        获取记忆统计信息。

        Returns:
            记忆统计字典
        """
        return self.memory_manager.get_memory_stats()

    def get_history_summary(self) -> str:
        """
        获取对话历史摘要。

        Returns:
            历史记录摘要文本
        """
        stats = self.memory_manager.get_memory_stats()

        if stats["total_conversations"] == 0:
            return "暂无对话历史"

        summary = f"""📊 记忆统计信息：
总对话数: {stats["total_conversations"]}
总Token数: {stats["total_tokens"]:,} / {stats["token_limit"]:,} ({stats["token_usage_percent"]:.1f}%)
平均重要性: {stats["average_importance"]}
已总结对话: {stats["summarized_conversations"]}

时间范围: {stats["date_range"]["oldest"]} 至 {stats["date_range"]["newest"]}
"""

        return summary

    def _add_output_sync(self, task_id: str, output_type: str, data: Any) -> None:
        """同步添加输出到收集器"""
        if not task_id:
            return
        
        if self.output_collector:
            try:
                # 如果 output_collector 有异步方法，这里需要同步调用
                if hasattr(self.output_collector, 'add_output'):
                    # 尝试同步调用
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # 如果事件循环正在运行，创建任务
                            asyncio.create_task(self.output_collector.add_output(output_type, data))
                        else:
                            loop.run_until_complete(self.output_collector.add_output(output_type, data))
                    except RuntimeError:
                        # 没有事件循环，直接调用（如果是同步方法）
                        if hasattr(self.output_collector.add_output, '__call__'):
                            self.output_collector.add_output(output_type, data)
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 添加输出到收集器失败: {e}, 输出类型: {output_type}{Style.RESET_ALL}")


# 创建单例实例
agent_runner = AgentRunner()
