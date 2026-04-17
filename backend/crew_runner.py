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
from tools import execute_tool, get_available_tools
from attack_chain import AttackChainEngine
from config import TASK_TIMEOUT

# CrewAI 任务超时（秒）
CREW_TASK_TIMEOUT = 300  # 5 分钟


class CrewRunner:
    """CrewAI 执行器"""
    
    def __init__(self, target: str, callback: Optional[Callable] = None):
        self.target = target
        self.callback = callback
        self.agents = {}  # 延迟初始化
        self.results = {}
        self.stage_results = {}
        self.attack_chain = AttackChainEngine()
        self.discovered_services = []
    
    async def _get_agents(self):
        """延迟获取 Agent（避免启动时初始化）"""
        if not self.agents:
            self.agents = get_all_agents()
        return self.agents
    
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
            # 阶段 1: 信息收集（并行执行）
            await self._send_callback("\n📋 阶段 1: 信息收集中...")
            recon_result = await self._stage_recon()
            self.stage_results["recon"] = recon_result
            
            # 解析发现的服务
            self.discovered_services = self.attack_chain.parse_nmap_results(recon_result)
            await self._send_callback(f"  发现 {len(self.discovered_services)} 个开放服务")
            
            # 阶段 2: 服务分析（根据发现的服务动态选择工具）
            await self._send_callback("\n🔍 阶段 2: 服务分析中...")
            service_result = await self._stage_service_analysis()
            self.stage_results["service_analysis"] = service_result
            
            # 阶段 3: 漏洞检测（动态选择工具）
            await self._send_callback("\n⚠️ 阶段 3: 漏洞检测中...")
            vuln_result = await self._stage_vulnerability_detection()
            self.stage_results["vulnerability_detection"] = vuln_result
            
            # 阶段 4: 漏洞利用（实现实际功能）
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
                "discovered_services": [
                    {"port": s.port, "service": s.service, "version": s.version}
                    for s in self.discovered_services
                ],
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
        """阶段 1: 信息收集（并行执行）"""
        results = {}
        agents = await self._get_agents()
        
        # 规范化目标格式
        target = self.target
        port = None
        # 提取主机名/IP（去掉协议和路径）
        if target.startswith("http://"):
            target = target[7:]
        elif target.startswith("https://"):
            target = target[8:]
        target = target.rstrip("/")
        
        # 分离主机和端口
        if ":" in target:
            parts = target.split(":")
            target = parts[0]
            port = parts[1]
        
        # 使用动态攻击链选择工具
        tools_to_run = self.attack_chain.select_tools_for_recon(target, port)
        
        # 并行执行工具
        async def run_tool(name, kwargs):
            result = await execute_tool(name, callback=self._send_callback, **kwargs)
            return name, result
        
        tasks = [run_tool(name, kwargs) for name, kwargs in tools_to_run]
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        
        for item in completed:
            if isinstance(item, Exception):
                await self._send_callback(f"  ⚠️ 工具执行异常: {item}")
                continue
            name, result = item
            if result:
                results[name] = {
                    "success": result.success,
                    "parsed_data": result.parsed_data,
                    "raw_output": result.stdout[:2000],
                    "execution_time": result.execution_time
                }
        
        # 使用 Planner Agent 分析收集到的信息
        planner = agents["planner"]
        recon_task = Task(
            description=f"""分析以下针对目标 {self.target} 的信息收集结果，制定后续测试策略：

信息收集结果：
{json.dumps(results, ensure_ascii=False, indent=2)}

请分析：
1. 开放的端口和服务
2. 使用的技术和框架
3. 潜在的攻击面
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
        
        # 在线程池中运行以避免阻塞事件循环，添加超时控制
        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, crew.kickoff),
                timeout=CREW_TASK_TIMEOUT
            )
            results["planner_analysis"] = str(result)
        except asyncio.TimeoutError:
            await self._send_callback(f"  ⚠️ Planner Agent 执行超时 ({CREW_TASK_TIMEOUT}s)，跳过分析")
            results["planner_analysis"] = "执行超时，未获得分析结果"
        
        await self._send_callback(f"  信息收集完成，发现 {len(results)} 项结果")
        return results
    
    async def _stage_service_analysis(self) -> Dict:
        """阶段 2: 服务分析（根据发现的服务动态选择工具）"""
        results = {}
        
        # 规范化目标格式
        target = self.target
        if target.startswith("http://"):
            target = target[7:]
        elif target.startswith("https://"):
            target = target[8:]
        target = target.rstrip("/")
        
        # 根据发现的服务动态选择工具
        from config import WORDLISTS_DIR
        wordlist = str(WORDLISTS_DIR / "directories.txt")
        tools_to_run = self.attack_chain.select_tools_for_services(target, self.discovered_services, wordlist)
        
        # 如果没有发现特定服务，使用默认工具
        if not tools_to_run:
            tools_to_run = [
                ("nikto", {"url": f"http://{target}"}),
                ("enum4linux", {"target": target}),
            ]
        
        # 并行执行工具
        async def run_tool(name, kwargs):
            result = await execute_tool(name, callback=self._send_callback, **kwargs)
            return name, result
        
        tasks = [run_tool(name, kwargs) for name, kwargs in tools_to_run]
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        
        for item in completed:
            if isinstance(item, Exception):
                await self._send_callback(f"  ⚠️ 工具执行异常: {item}")
                continue
            name, result = item
            if result:
                results[name] = {
                    "success": result.success,
                    "parsed_data": result.parsed_data,
                    "raw_output": result.stdout[:2000],
                    "execution_time": result.execution_time
                }
        
        await self._send_callback(f"  服务分析完成，执行了 {len(results)} 个工具")
        return results
    
    async def _stage_vulnerability_detection(self) -> Dict:
        """阶段 3: 漏洞检测（动态选择工具）"""
        results = {}
        agents = await self._get_agents()
        
        # 规范化目标格式
        target = self.target
        if target.startswith("http://"):
            target = target[7:]
        elif target.startswith("https://"):
            target = target[8:]
        target = target.rstrip("/")
        
        # 根据发现的服务动态选择漏洞检测工具
        tools_to_run = self.attack_chain.select_tools_for_vulnerability(target, self.discovered_services)
        
        # 并行执行工具
        async def run_tool(name, kwargs):
            result = await execute_tool(name, callback=self._send_callback, **kwargs)
            return name, result
        
        tasks = [run_tool(name, kwargs) for name, kwargs in tools_to_run]
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        
        for item in completed:
            if isinstance(item, Exception):
                await self._send_callback(f"  ⚠️ 工具执行异常: {item}")
                continue
            name, result = item
            if result:
                results[name] = {
                    "success": result.success,
                    "parsed_data": result.parsed_data,
                    "raw_output": result.stdout[:2000],
                    "execution_time": result.execution_time
                }
        
        # 使用 Analyzer Agent 分析漏洞
        analyzer = agents["analyzer"]
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
        
        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, crew.kickoff),
                timeout=CREW_TASK_TIMEOUT
            )
            results["analyzer_report"] = str(result)
        except asyncio.TimeoutError:
            await self._send_callback(f"  ⚠️ Analyzer Agent 执行超时 ({CREW_TASK_TIMEOUT}s)，跳过分析")
            results["analyzer_report"] = "执行超时，未获得分析结果"
        
        await self._send_callback(f"  漏洞检测完成")
        return results
    
    async def _stage_exploitation(self) -> Dict:
        """阶段 4: 漏洞利用（实现实际功能）"""
        results = {}
        
        vuln_data = self.stage_results.get("vulnerability_detection", {})
        
        await self._send_callback("  分析可利用的漏洞...")
        
        # 1. 从漏洞检测结果中提取可利用的漏洞
        exploitable_vulns = self._identify_exploitable_vulns(vuln_data)
        
        if not exploitable_vulns:
            await self._send_callback("  未发现明显可利用的漏洞，跳过漏洞利用阶段")
            results["exploitation_simulation"] = {
                "note": "未发现明显可利用的漏洞",
                "potential_exploits": []
            }
            return results
        
        # 2. 对每个漏洞搜索 exploit
        for vuln in exploitable_vulns:
            await self._send_callback(f"  分析漏洞利用方案: {vuln.get('name', '未知漏洞')}")
            
            # 搜索对应的 exploit
            if vuln.get("cve_id"):
                await self._send_callback(f"  搜索 {vuln['cve_id']} 的 exploit...")
                exploit_result = await execute_tool(
                    "searchsploit", 
                    callback=self._send_callback,
                    query=vuln["cve_id"]
                )
                if exploit_result:
                    results[f"exploit_search_{vuln['cve_id']}"] = {
                        "success": exploit_result.success,
                        "exploits": exploit_result.parsed_data.get("exploits", []),
                        "raw_output": exploit_result.stdout[:1000]
                    }
            
            # 生成利用方案
            exploit_plan = await self._generate_exploit_plan(vuln)
            results[f"exploit_plan_{vuln.get('name', 'unknown')}"] = exploit_plan
        
        # 3. 总结利用可能性
        results["exploitation_summary"] = {
            "total_vulns_analyzed": len(exploitable_vulns),
            "exploits_found": len([k for k in results.keys() if k.startswith("exploit_search_")]),
            "note": "以上为漏洞利用方案分析，未实际执行漏洞利用。实际环境中需要明确授权后才能执行。"
        }
        
        await self._send_callback(f"  漏洞利用分析完成，分析了 {len(exploitable_vulns)} 个漏洞")
        return results
    
    def _identify_exploitable_vulns(self, vuln_data: Dict) -> List[Dict]:
        """从漏洞数据中识别可利用的漏洞"""
        exploitable = []
        
        # 从 Nuclei 结果中提取
        nuclei_result = vuln_data.get("nuclei", {})
        parsed_data = nuclei_result.get("parsed_data", {})
        for vuln in parsed_data.get("vulnerabilities", []):
            severity = vuln.get("severity", "").lower()
            if severity in ["critical", "high"]:
                exploitable.append({
                    "name": vuln.get("name", "未知漏洞"),
                    "severity": vuln.get("severity", "Unknown"),
                    "cve_id": vuln.get("cve", [""])[0] if vuln.get("cve") else "",
                    "url": vuln.get("url", ""),
                    "template": vuln.get("template", ""),
                })
        
        # 从 SQLMap 结果中提取
        sqlmap_result = vuln_data.get("sqlmap", {})
        if sqlmap_result.get("parsed_data", {}).get("vulnerable"):
            exploitable.append({
                "name": "SQL 注入漏洞",
                "severity": "Critical",
                "cve_id": "",
                "url": sqlmap_result.get("command", ""),
                "template": "sql-injection",
            })
        
        return exploitable
    
    async def _generate_exploit_plan(self, vuln: Dict) -> Dict:
        """生成漏洞利用方案"""
        plan = {
            "vuln_name": vuln.get("name", "未知漏洞"),
            "severity": vuln.get("severity", "Unknown"),
            "exploitation_steps": [],
            "required_tools": [],
            "risk_level": "high",
            "notes": ""
        }
        
        # 根据漏洞类型生成利用方案
        if "sql" in vuln.get("name", "").lower() or vuln.get("template") == "sql-injection":
            plan["exploitation_steps"] = [
                "1. 确认 SQL 注入点",
                "2. 使用 sqlmap 进行自动化检测和利用",
                "3. 尝试获取数据库信息",
                "4. 评估数据泄露风险"
            ]
            plan["required_tools"] = ["sqlmap"]
            plan["notes"] = "SQL 注入可能导致数据库完全被控制，风险极高"
        
        elif vuln.get("cve_id"):
            plan["exploitation_steps"] = [
                f"1. 搜索 {vuln['cve_id']} 的公开 exploit",
                "2. 分析 exploit 代码，确认安全性",
                "3. 在测试环境中验证 exploit",
                "4. 评估利用后的影响范围"
            ]
            plan["required_tools"] = ["searchsploit", "metasploit"]
            plan["notes"] = f"需要针对 {vuln['cve_id']} 进行详细分析"
        
        else:
            plan["exploitation_steps"] = [
                "1. 分析漏洞详情和影响范围",
                "2. 搜索相关 exploit 或 PoC",
                "3. 评估利用难度和风险",
                "4. 制定利用方案"
            ]
            plan["required_tools"] = ["searchsploit"]
            plan["notes"] = "需要进一步分析漏洞细节"
        
        return plan
    
    async def _stage_report_generation(self) -> Dict:
        """阶段 5: 报告生成"""
        agents = await self._get_agents()
        reporter = agents["reporter"]
        
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
        
        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, crew.kickoff),
                timeout=CREW_TASK_TIMEOUT
            )
            report_content = str(result)
        except asyncio.TimeoutError:
            await self._send_callback(f"  ⚠️ Reporter Agent 执行超时 ({CREW_TASK_TIMEOUT}s)，使用默认报告")
            report_content = f"# 渗透测试报告\n\n目标: {self.target}\n\n报告生成超时，请参考阶段结果获取详细信息。"
        
        return {
            "content": report_content,
            "generated_at": datetime.now().isoformat()
        }


async def run_pentest(target: str, callback: Optional[Callable] = None) -> Dict:
    """便捷函数：执行渗透测试"""
    runner = CrewRunner(target=target, callback=callback)
    return await runner.run()
