"""
SkidCon CrewAI 执行核心
实现多阶段链式攻击流程，支持流式输出回调
"""

import asyncio
import json
from typing import Callable, Dict, List, Optional
from datetime import datetime
from crewai import Crew, Process, Task
from agents import get_all_agents
from tools import execute_tool, get_all_tools
from config import TASK_TIMEOUT


class CrewRunner:
    """CrewAI 执行器"""
    
    def __init__(self, target: str, callback: Optional[Callable] = None):
        self.target = target
        self.callback = callback
        self.agents = get_all_agents()
        self.results = {}
        self.stage_results = {}
    
    async def _send_callback(self, message: str):
        """发送回调消息"""
        if self.callback:
            if asyncio.iscoroutinefunction(self.callback):
                await self.callback(message)
            else:
                self.callback(message)
    
    async def run(self) -> Dict:
        """执行完整的渗透测试流程"""
        await self._send_callback(f"🚀 开始对目标 {self.target} 进行渗透测试")
        await self._send_callback(f"⏰ 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            # 阶段 1: 信息收集
            await self._send_callback("\n📋 阶段 1: 信息收集中...")
            recon_result = await self._stage_recon()
            self.stage_results["recon"] = recon_result
            
            # 阶段 2: 服务分析
            await self._send_callback("\n🔍 阶段 2: 服务分析中...")
            service_result = await self._stage_service_analysis()
            self.stage_results["service_analysis"] = service_result
            
            # 阶段 3: 漏洞检测
            await self._send_callback("\n⚠️ 阶段 3: 漏洞检测中...")
            vuln_result = await self._stage_vulnerability_detection()
            self.stage_results["vulnerability_detection"] = vuln_result
            
            # 阶段 4: 漏洞利用（可选）
            await self._send_callback("\n💥 阶段 4: 漏洞利用中...")
            exploit_result = await self._stage_exploitation()
            self.stage_results["exploitation"] = exploit_result
            
            # 阶段 5: 报告生成
            await self._send_callback("\n📝 阶段 5: 生成报告中...")
            report_result = await self._stage_report_generation()
            self.stage_results["report"] = report_result
            
            await self._send_callback(f"\n✅ 渗透测试完成! 结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            return {
                "target": self.target,
                "start_time": datetime.now().isoformat(),
                "end_time": datetime.now().isoformat(),
                "stages": self.stage_results,
                "report": report_result
            }
            
        except Exception as e:
            await self._send_callback(f"\n❌ 执行错误: {str(e)}")
            return {
                "target": self.target,
                "error": str(e),
                "stages": self.stage_results
            }
    
    async def _stage_recon(self) -> Dict:
        """阶段 1: 信息收集"""
        results = {}
        
        # 使用工具进行信息收集
        tools_to_run = [
            ("nmap", {"target": self.target}),
            ("subfinder", {"domain": self.target}),
            ("whatweb", {"url": f"http://{self.target}"}),
            ("whois", {"domain": self.target}),
            ("dig", {"domain": self.target}),
        ]
        
        for tool_name, kwargs in tools_to_run:
            await self._send_callback(f"  执行 {tool_name}...")
            result = await execute_tool(tool_name, callback=self._send_callback, **kwargs)
            if result:
                results[tool_name] = {
                    "success": result.success,
                    "parsed_data": result.parsed_data,
                    "raw_output": result.stdout[:2000]  # 限制输出长度
                }
        
        # 使用 Planner Agent 分析收集到的信息
        planner = self.agents["planner"]
        recon_task = Task(
            description=f"""分析以下针对目标 {self.target} 的信息收集结果，制定后续测试策略：

信息收集结果：
{json.dumps(results, ensure_ascii=False, indent=2)}

请分析：
1. 开放的端口和服务
2. 使用的技术和框架
3. 潜在的攻擊面
4. 推荐的后续测试步骤""",
            agent=planner,
            expected_output="详细的攻击策略和后续测试计划"
        )
        
        crew = Crew(
            agents=[planner],
            tasks=[recon_task],
            process=Process.sequential,
            verbose=True
        )
        
        result = crew.kickoff()
        results["planner_analysis"] = str(result)
        
        await self._send_callback(f"  信息收集完成，发现 {len(results)} 项结果")
        return results
    
    async def _stage_service_analysis(self) -> Dict:
        """阶段 2: 服务分析"""
        results = {}
        
        # 根据发现的端口运行服务枚举
        recon_data = self.stage_results.get("recon", {})
        
        tools_to_run = [
            ("nikto", {"url": f"http://{self.target}"}),
            ("enum4linux", {"target": self.target}),
            ("smbclient", {"target": self.target}),
        ]
        
        for tool_name, kwargs in tools_to_run:
            await self._send_callback(f"  执行 {tool_name}...")
            result = await execute_tool(tool_name, callback=self._send_callback, **kwargs)
            if result:
                results[tool_name] = {
                    "success": result.success,
                    "parsed_data": result.parsed_data,
                    "raw_output": result.stdout[:2000]
                }
        
        await self._send_callback(f"  服务分析完成")
        return results
    
    async def _stage_vulnerability_detection(self) -> Dict:
        """阶段 3: 漏洞检测"""
        results = {}
        
        tools_to_run = [
            ("sqlmap", {"url": f"http://{self.target}"}),
            ("nuclei", {"url": f"http://{self.target}"}),
            ("searchsploit", {"query": self.target}),
        ]
        
        for tool_name, kwargs in tools_to_run:
            await self._send_callback(f"  执行 {tool_name}...")
            result = await execute_tool(tool_name, callback=self._send_callback, **kwargs)
            if result:
                results[tool_name] = {
                    "success": result.success,
                    "parsed_data": result.parsed_data,
                    "raw_output": result.stdout[:2000]
                }
        
        # 使用 Analyzer Agent 分析漏洞
        analyzer = self.agents["analyzer"]
        analysis_task = Task(
            description=f"""分析以下针对目标 {self.target} 的漏洞扫描结果，识别真实漏洞并降低误报：

扫描结果：
{json.dumps(results, ensure_ascii=False, indent=2)}

请分析：
1. 确认真实存在的漏洞
2. 排除误报
3. 评估每个漏洞的风险等级（Critical/High/Medium/Low）
4. 提供漏洞利用的可能性分析""",
            agent=analyzer,
            expected_output="详细的漏洞分析报告，包含风险评级"
        )
        
        crew = Crew(
            agents=[analyzer],
            tasks=[analysis_task],
            process=Process.sequential,
            verbose=True
        )
        
        result = crew.kickoff()
        results["analyzer_report"] = str(result)
        
        await self._send_callback(f"  漏洞检测完成")
        return results
    
    async def _stage_exploitation(self) -> Dict:
        """阶段 4: 漏洞利用（可选）"""
        results = {}
        
        vuln_data = self.stage_results.get("vulnerability_detection", {})
        
        # 根据发现的漏洞尝试利用
        await self._send_callback("  分析可利用的漏洞...")
        
        # 这里可以根据实际发现的漏洞动态选择利用工具
        # 为安全起见，默认不执行实际利用，只做模拟分析
        results["exploitation_simulation"] = {
            "note": "出于安全考虑，实际环境中需要授权后才能执行漏洞利用",
            "potential_exploits": []
        }
        
        await self._send_callback(f"  漏洞利用分析完成")
        return results
    
    async def _stage_report_generation(self) -> Dict:
        """阶段 5: 报告生成"""
        reporter = self.agents["reporter"]
        
        report_task = Task(
            description=f"""为以下渗透测试结果生成专业的 Markdown 格式报告：

目标: {self.target}
测试阶段结果:
{json.dumps(self.stage_results, ensure_ascii=False, indent=2)}

请生成包含以下部分的报告：
1. 执行摘要（测试目标、时间、发现漏洞总数、风险评级）
2. 漏洞详情（每个漏洞的名称、风险等级、描述、影响、证据、修复建议）
3. 附录（完整工具输出）

报告格式要求：
- 使用 Markdown 格式
- 结构清晰，层次分明
- 使用表格展示漏洞列表
- 提供具体的修复建议和代码示例""",
            agent=reporter,
            expected_output="完整的 Markdown 格式渗透测试报告"
        )
        
        crew = Crew(
            agents=[reporter],
            tasks=[report_task],
            process=Process.sequential,
            verbose=True
        )
        
        result = crew.kickoff()
        report_content = str(result)
        
        return {
            "content": report_content,
            "generated_at": datetime.now().isoformat()
        }


async def run_pentest(target: str, callback: Optional[Callable] = None) -> Dict:
    """便捷函数：执行渗透测试"""
    runner = CrewRunner(target=target, callback=callback)
    return await runner.run()
