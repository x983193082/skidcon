"""
SkidCon CrewAI 执行核心
实现 Agent 驱动的多阶段渗透测试流程，支持流式输出回调
"""

import asyncio
import json
from typing import Callable, Dict, List, Optional
from datetime import datetime
from crewai import Crew, Process, Task
from agents import get_all_agents
from tools import execute_tool, get_available_tools, get_all_tools
from attack_chain import AttackChainEngine
from config import TASK_TIMEOUT

# CrewAI 任务超时（秒）
CREW_TASK_TIMEOUT = 300  # 5 分钟


class CrewRunner:
    """CrewAI 执行器 - Agent 驱动的工具选择和执行"""
    
    def __init__(self, target: str, callback: Optional[Callable] = None):
        self.target = target
        self.callback = callback
        self.agents = {}  # 延迟初始化
        self.results = {}
        self.stage_results = {}
        self.attack_chain = AttackChainEngine()
        self.discovered_services = []
        self.available_tools = []  # 缓存可用工具列表
    
    async def _get_agents(self):
        """延迟获取 Agent（避免启动时初始化）"""
        if not self.agents:
            self.agents = get_all_agents()
        return self.agents
    
    async def _get_available_tools(self) -> List[str]:
        """获取可用工具列表（缓存）"""
        if not self.available_tools:
            self.available_tools = get_available_tools()
        return self.available_tools
    
    async def _execute_selected_tools(self, tool_list: List[Dict], stage_name: str = "") -> Dict:
        """执行 Agent 选择的工具列表
        
        Args:
            tool_list: Agent 返回的工具列表，格式为 [{"tool": "nmap", "args": "-sV target", "reason": "端口扫描"}, ...]
            stage_name: 阶段名称（用于日志）
        
        Returns:
            工具执行结果字典
        """
        results = {}
        
        if not tool_list:
            await self._send_callback(f"  ⚠️ {stage_name}: Agent 未选择任何工具，使用默认工具集")
            return results
        
        async def run_tool(tool_info):
            tool_name = tool_info.get("tool", "")
            args = tool_info.get("args", "")
            reason = tool_info.get("reason", "")
            
            if not tool_name:
                return None, "工具名称为空"
            
            if reason:
                await self._send_callback(f"  [{stage_name}] 执行 {tool_name}: {reason}")
            else:
                await self._send_callback(f"  [{stage_name}] 执行 {tool_name}: {args}")
            
            # 使用 execute_kali_tool 的方式执行
            result = await execute_tool("execute_kali_tool", callback=self._send_callback, 
                                        tool=tool_name, args=args)
            return tool_name, result
        
        tasks = [run_tool(t) for t in tool_list]
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        
        for item in completed:
            if isinstance(item, Exception):
                await self._send_callback(f"  ⚠️ 工具执行异常: {item}")
                continue
            name, result = item
            if name is None:
                continue
            if result:
                results[name] = {
                    "success": result.success,
                    "parsed_data": result.parsed_data,
                    "raw_output": result.stdout[:3000] if result.stdout else "",
                    "stderr": result.stderr[:1000] if result.stderr else "",
                    "execution_time": result.execution_time,
                    "command": result.command,
                }
        
        return results
    
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
        """阶段 1: 信息收集（Agent 驱动工具选择 + 并行执行）"""
        results = {}
        agents = await self._get_agents()
        available_tools = await self._get_available_tools()
        
        # 规范化目标格式
        target = self.target
        port = None
        if target.startswith("http://"):
            target = target[7:]
        elif target.startswith("https://"):
            target = target[8:]
        target = target.rstrip("/")
        
        if ":" in target:
            parts = target.split(":")
            target = parts[0]
            port = parts[1]
        
        # 步骤 1: 让 Planner Agent 根据目标选择信息收集工具
        planner = agents["planner"]
        tool_selection_task = Task(
            description=f"""你是渗透测试规划专家。针对目标 {self.target}（主机: {target}, 端口: {port or '默认'}），
请从以下可用工具中选择最适合信息收集阶段的工具，并说明选择理由。

可用工具列表: {', '.join(available_tools)}

请以 JSON 数组格式返回工具选择，每个工具包含:
- tool: 工具名称
- args: 工具参数（使用目标 {target} 和端口 {port or ''}）
- reason: 选择理由

示例:
[
    {{"tool": "nmap", "args": "-sV -sC -O -p {port or '1-1000'} {target}", "reason": "端口扫描和服务识别"}},
    {{"tool": "whois", "args": "{target}", "reason": "域名注册信息查询"}},
    {{"tool": "dig", "args": "{target} ANY", "reason": "DNS 记录查询"}}
]

注意：只选择实际存在的工具，参数中直接使用目标地址。返回纯 JSON，不要包含其他文字。""",
            agent=planner,
            expected_output="JSON 格式的工具选择列表"
        )
        
        crew = Crew(
            agents=[planner],
            tasks=[tool_selection_task],
            process=Process.sequential,
            verbose=True
        )
        
        loop = asyncio.get_running_loop()
        try:
            agent_response = await asyncio.wait_for(
                loop.run_in_executor(None, crew.kickoff),
                timeout=CREW_TASK_TIMEOUT
            )
            agent_text = str(agent_response).strip()
            
            # 解析 Agent 返回的 JSON
            tool_list = self._parse_agent_tool_selection(agent_text)
            await self._send_callback(f"  Planner 选择了 {len(tool_list)} 个工具")
            
        except asyncio.TimeoutError:
            await self._send_callback(f"  ⚠️ Planner Agent 超时，使用默认工具集")
            tool_list = []
        except Exception as e:
            await self._send_callback(f"  ⚠️ Planner Agent 错误: {e}，使用默认工具集")
            tool_list = []
        
        # 步骤 2: 如果 Agent 未选择工具，使用默认工具集
        if not tool_list:
            tool_list = [
                {"tool": "nmap", "args": f"-sV -sC -O {'-p ' + port if port else ''} {target}", "reason": "端口扫描和服务识别"},
                {"tool": "whois", "args": target, "reason": "域名信息查询"},
                {"tool": "dig", "args": f"{target} ANY", "reason": "DNS 记录查询"},
            ]
        
        # 步骤 3: 并行执行工具
        tool_results = await self._execute_selected_tools(tool_list, "信息收集")
        results.update(tool_results)
        
        # 步骤 4: Planner Agent 分析收集结果
        if results:
            analysis_task = Task(
                description=f"""分析以下针对目标 {self.target} 的信息收集结果，制定后续测试策略：

信息收集结果：
{json.dumps(results, ensure_ascii=False, indent=2)[:5000]}

请分析：
1. 开放的端口和服务
2. 使用的技术和框架
3. 潜在的攻击面
4. 推荐的后续测试步骤和工具选择""",
                agent=planner,
                expected_output="详细的攻击策略和后续测试计划"
            )
            
            crew = Crew(
                agents=[planner],
                tasks=[analysis_task],
                process=Process.sequential,
                verbose=True
            )
            
            try:
                analysis_result = await asyncio.wait_for(
                    loop.run_in_executor(None, crew.kickoff),
                    timeout=CREW_TASK_TIMEOUT
                )
                results["planner_analysis"] = str(analysis_result)
            except asyncio.TimeoutError:
                results["planner_analysis"] = "分析超时，请参考工具原始输出"
        
        await self._send_callback(f"  信息收集完成，执行了 {len(results)} 个工具")
        return results
    
    def _parse_agent_tool_selection(self, agent_text: str) -> List[Dict]:
        """解析 Agent 返回的工具选择 JSON"""
        import re
        
        # 尝试直接解析
        try:
            data = json.loads(agent_text)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
        
        # 尝试从文本中提取 JSON 数组
        json_match = re.search(r'\[[\s\S]*\]', agent_text)
        if json_match:
            try:
                data = json.loads(json_match.group())
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass
        
        # 尝试提取 ```json 代码块
        code_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', agent_text)
        if code_match:
            try:
                data = json.loads(code_match.group(1))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass
        
        return []
    
    async def _stage_service_analysis(self) -> Dict:
        """阶段 2: 服务分析（Agent 驱动工具选择）"""
        results = {}
        agents = await self._get_agents()
        available_tools = await self._get_available_tools()
        
        # 规范化目标格式
        target = self.target
        if target.startswith("http://"):
            target = target[7:]
        elif target.startswith("https://"):
            target = target[8:]
        target = target.rstrip("/")
        
        if ":" in target:
            parts = target.split(":")
            target = parts[0]
        
        # 构建服务摘要供 Agent 参考
        service_summary = []
        for s in self.discovered_services:
            service_summary.append(f"端口 {s.port}: {s.service} ({s.version or '未知版本'})")
        
        service_info = "\n".join(service_summary) if service_summary else "未发现开放服务"
        
        # 让 Executor Agent 根据发现的服务选择分析工具
        executor = agents["executor"]
        tool_selection_task = Task(
            description=f"""你是工具执行专家。针对目标 {self.target}，信息收集阶段发现以下服务：

{service_info}

请从以下可用工具中选择最适合服务分析阶段的工具，并说明选择理由。

可用工具列表: {', '.join(available_tools)}

请以 JSON 数组格式返回工具选择，每个工具包含:
- tool: 工具名称
- args: 工具参数
- reason: 选择理由

示例:
[
    {{"tool": "nikto", "args": "-h http://{target}", "reason": "Web 漏洞扫描"}},
    {{"tool": "whatweb", "args": "http://{target}", "reason": "技术栈识别"}},
    {{"tool": "gobuster", "args": "dir -u http://{target} -w /usr/share/wordlists/dirb/common.txt", "reason": "目录枚举"}}
]

注意：根据实际发现的服务类型选择工具。如果发现了 Web 服务，选择 Web 扫描工具；如果发现了 SMB 服务，选择 SMB 枚举工具。返回纯 JSON。""",
            agent=executor,
            expected_output="JSON 格式的工具选择列表"
        )
        
        crew = Crew(
            agents=[executor],
            tasks=[tool_selection_task],
            process=Process.sequential,
            verbose=True
        )
        
        loop = asyncio.get_running_loop()
        try:
            agent_response = await asyncio.wait_for(
                loop.run_in_executor(None, crew.kickoff),
                timeout=CREW_TASK_TIMEOUT
            )
            tool_list = self._parse_agent_tool_selection(str(agent_response))
            await self._send_callback(f"  Executor 选择了 {len(tool_list)} 个工具")
        except asyncio.TimeoutError:
            await self._send_callback(f"  ⚠️ Executor Agent 超时，使用默认工具集")
            tool_list = []
        except Exception as e:
            await self._send_callback(f"  ⚠️ Executor Agent 错误: {e}，使用默认工具集")
            tool_list = []
        
        # 如果 Agent 未选择工具，使用默认工具集
        if not tool_list:
            from config import WORDLISTS_DIR
            wordlist = str(WORDLISTS_DIR / "directories.txt")
            tool_list = [
                {"tool": "nikto", "args": f"-h http://{target}", "reason": "Web 漏洞扫描"},
                {"tool": "enum4linux", "args": target, "reason": "SMB 枚举"},
            ]
        
        # 执行工具
        tool_results = await self._execute_selected_tools(tool_list, "服务分析")
        results.update(tool_results)
        
        await self._send_callback(f"  服务分析完成，执行了 {len(results)} 个工具")
        return results
    
    async def _stage_vulnerability_detection(self) -> Dict:
        """阶段 3: 漏洞检测（Agent 驱动工具选择）"""
        results = {}
        agents = await self._get_agents()
        available_tools = await self._get_available_tools()
        
        # 规范化目标格式
        target = self.target
        if target.startswith("http://"):
            target = target[7:]
        elif target.startswith("https://"):
            target = target[8:]
        target = target.rstrip("/")
        
        if ":" in target:
            parts = target.split(":")
            target = parts[0]
        
        # 构建前两个阶段的结果摘要
        recon_summary = json.dumps(self.stage_results.get("recon", {}), ensure_ascii=False, indent=2)[:3000]
        service_summary = json.dumps(self.stage_results.get("service_analysis", {}), ensure_ascii=False, indent=2)[:3000]
        
        # 让 Analyzer Agent 选择漏洞检测工具
        analyzer = agents["analyzer"]
        tool_selection_task = Task(
            description=f"""你是漏洞分析专家。针对目标 {self.target}，前两个阶段的扫描结果如下：

信息收集结果摘要:
{recon_summary}

服务分析结果摘要:
{service_summary}

请从以下可用工具中选择最适合漏洞检测阶段的工具，并说明选择理由。

可用工具列表: {', '.join(available_tools)}

请以 JSON 数组格式返回工具选择，每个工具包含:
- tool: 工具名称
- args: 工具参数
- reason: 选择理由

示例:
[
    {{"tool": "nuclei", "args": "-u http://{target}", "reason": "已知漏洞扫描"}},
    {{"tool": "sqlmap", "args": "-u http://{target}/page?id=1 --batch", "reason": "SQL 注入检测"}},
    {{"tool": "nikto", "args": "-h http://{target}", "reason": "Web 漏洞扫描"}},
    {{"tool": "searchsploit", "args": "Apache 2.4", "reason": "已知 CVE 搜索"}}
]

注意：根据前两个阶段发现的服务和技术栈，选择针对性的漏洞检测工具。返回纯 JSON。""",
            agent=analyzer,
            expected_output="JSON 格式的工具选择列表"
        )
        
        crew = Crew(
            agents=[analyzer],
            tasks=[tool_selection_task],
            process=Process.sequential,
            verbose=True
        )
        
        loop = asyncio.get_running_loop()
        try:
            agent_response = await asyncio.wait_for(
                loop.run_in_executor(None, crew.kickoff),
                timeout=CREW_TASK_TIMEOUT
            )
            tool_list = self._parse_agent_tool_selection(str(agent_response))
            await self._send_callback(f"  Analyzer 选择了 {len(tool_list)} 个工具")
        except asyncio.TimeoutError:
            await self._send_callback(f"  ⚠️ Analyzer Agent 超时，使用默认工具集")
            tool_list = []
        except Exception as e:
            await self._send_callback(f"  ⚠️ Analyzer Agent 错误: {e}，使用默认工具集")
            tool_list = []
        
        # 如果 Agent 未选择工具，使用默认工具集
        if not tool_list:
            tool_list = [
                {"tool": "nuclei", "args": f"-u http://{target}", "reason": "已知漏洞扫描"},
                {"tool": "searchsploit", "args": target, "reason": "已知 CVE 搜索"},
            ]
        
        # 执行工具
        tool_results = await self._execute_selected_tools(tool_list, "漏洞检测")
        results.update(tool_results)
        
        # Analyzer Agent 分析漏洞结果
        if results:
            analysis_task = Task(
                description=f"""分析以下针对目标 {self.target} 的漏洞扫描结果，识别真实漏洞并降低误报：

扫描结果：
{json.dumps(results, ensure_ascii=False, indent=2)[:5000]}

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
            
            try:
                analysis_result = await asyncio.wait_for(
                    loop.run_in_executor(None, crew.kickoff),
                    timeout=CREW_TASK_TIMEOUT
                )
                results["analyzer_report"] = str(analysis_result)
            except asyncio.TimeoutError:
                await self._send_callback(f"  ⚠️ Analyzer Agent 分析超时")
                results["analyzer_report"] = "分析超时，请参考工具原始输出"
        
        await self._send_callback(f"  漏洞检测完成，执行了 {len(results)} 个工具")
        return results
    
    async def _stage_exploitation(self) -> Dict:
        """阶段 4: 漏洞利用（Agent 驱动）"""
        results = {}
        agents = await self._get_agents()
        available_tools = await self._get_available_tools()
        
        vuln_data = self.stage_results.get("vulnerability_detection", {})
        
        await self._send_callback("  分析可利用的漏洞...")
        
        # 步骤 1: 让 Executor Agent 分析可利用的漏洞并选择工具
        executor = agents["executor"]
        vuln_summary = json.dumps(vuln_data, ensure_ascii=False, indent=2)[:5000]
        
        analysis_task = Task(
            description=f"""你是工具执行专家。根据以下漏洞扫描结果，分析哪些漏洞可以被利用，并选择相应的验证工具。

漏洞扫描结果：
{vuln_summary}

请分析：
1. 哪些漏洞可以被实际利用或验证
2. 应该使用什么工具来验证（从以下可用工具中选择）
3. 每个漏洞的利用方案

可用工具列表: {', '.join(available_tools)}

请以 JSON 格式返回分析结果：
{{
    "exploitable_vulns": [
        {{"name": "漏洞名称", "severity": "Critical/High/Medium/Low", "tool": "验证工具名", "args": "工具参数", "reason": "选择理由"}}
    ],
    "summary": "总体分析总结"
}}

注意：只进行安全的验证（如 searchsploit 搜索、curl 验证），不要执行可能造成破坏的操作。返回纯 JSON。""",
            agent=executor,
            expected_output="JSON 格式的漏洞利用分析结果"
        )
        
        crew = Crew(
            agents=[executor],
            tasks=[analysis_task],
            process=Process.sequential,
            verbose=True
        )
        
        loop = asyncio.get_running_loop()
        try:
            agent_response = await asyncio.wait_for(
                loop.run_in_executor(None, crew.kickoff),
                timeout=CREW_TASK_TIMEOUT
            )
            agent_text = str(agent_response)
            
            # 解析 Agent 返回的分析结果
            exploit_data = self._parse_exploit_analysis(agent_text)
            exploitable_vulns = exploit_data.get("exploitable_vulns", [])
            results["executor_analysis"] = exploit_data.get("summary", agent_text[:2000])
            
        except asyncio.TimeoutError:
            await self._send_callback(f"  ⚠️ Executor Agent 分析超时，使用默认分析")
            exploitable_vulns = self._identify_exploitable_vulns(vuln_data)
            results["executor_analysis"] = "分析超时，使用默认漏洞识别结果"
        except Exception as e:
            await self._send_callback(f"  ⚠️ Executor Agent 错误: {e}")
            exploitable_vulns = self._identify_exploitable_vulns(vuln_data)
            results["executor_analysis"] = f"分析错误: {e}"
        
        if not exploitable_vulns:
            await self._send_callback("  未发现明显可利用的漏洞，跳过漏洞利用阶段")
            results["exploitation_simulation"] = {
                "note": "未发现明显可利用的漏洞",
                "potential_exploits": []
            }
            return results
        
        # 步骤 2: 执行 Agent 选择的验证工具
        await self._send_callback(f"  发现 {len(exploitable_vulns)} 个可利用的漏洞")
        
        for vuln in exploitable_vulns:
            vuln_name = vuln.get("name", "未知漏洞")
            tool_name = vuln.get("tool", "")
            args = vuln.get("args", "")
            reason = vuln.get("reason", "")
            
            await self._send_callback(f"  验证漏洞: {vuln_name} - {reason}")
            
            if tool_name:
                tool_result = await execute_tool(tool_name, callback=self._send_callback, 
                                                  **self._parse_tool_args(args))
                if tool_result:
                    results[f"verify_{vuln_name}"] = {
                        "success": tool_result.success,
                        "raw_output": tool_result.stdout[:2000],
                        "command": tool_result.command,
                    }
            
            # 搜索 exploit
            cve_id = vuln.get("cve_id", "")
            if cve_id:
                await self._send_callback(f"  搜索 {cve_id} 的 exploit...")
                exploit_result = await execute_tool("searchsploit", callback=self._send_callback, query=cve_id)
                if exploit_result:
                    results[f"exploit_search_{cve_id}"] = {
                        "success": exploit_result.success,
                        "exploits": exploit_result.parsed_data.get("exploits", []),
                        "raw_output": exploit_result.stdout[:1000]
                    }
        
        # 步骤 3: 总结
        results["exploitation_summary"] = {
            "total_vulns_analyzed": len(exploitable_vulns),
            "exploits_found": len([k for k in results.keys() if k.startswith("exploit_search_")]),
            "note": "以上为漏洞利用方案分析，未实际执行破坏性操作。实际环境中需要明确授权后才能执行。"
        }
        
        await self._send_callback(f"  漏洞利用分析完成，分析了 {len(exploitable_vulns)} 个漏洞")
        return results
    
    def _parse_exploit_analysis(self, agent_text: str) -> Dict:
        """解析 Agent 返回的漏洞利用分析 JSON"""
        import re
        
        try:
            data = json.loads(agent_text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
        
        json_match = re.search(r'\{[\s\S]*"exploitable_vulns"[\s\S]*\}', agent_text)
        if json_match:
            try:
                data = json.loads(json_match.group())
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
        
        code_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', agent_text)
        if code_match:
            try:
                data = json.loads(code_match.group(1))
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
        
        return {"exploitable_vulns": [], "summary": agent_text[:2000]}
    
    def _parse_tool_args(self, args_str: str) -> Dict:
        """解析工具参数字符串为 kwargs"""
        # 简单解析：如果包含 = 则作为键值对
        if "=" in args_str and not args_str.startswith("-"):
            params = {}
            for part in args_str.split():
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k] = v
            return params
        # 否则作为位置参数
        return {"args": args_str} if args_str else {}
    
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
        """阶段 5: 报告生成（结合 Agent 分析和工具结果）"""
        agents = await self._get_agents()
        reporter = agents["reporter"]
        
        # 构建完整的测试数据摘要
        all_stages_summary = {
            "target": self.target,
            "discovered_services": [
                {"port": s.port, "service": s.service, "version": s.version, "product": s.product}
                for s in self.discovered_services
            ],
            "stage_1_recon": {
                "tools_executed": len([k for k in self.stage_results.get("recon", {}).keys() if k != "planner_analysis"]),
                "planner_analysis": self.stage_results.get("recon", {}).get("planner_analysis", "")[:2000],
            },
            "stage_2_service_analysis": {
                "tools_executed": len(self.stage_results.get("service_analysis", {})),
            },
            "stage_3_vulnerability_detection": {
                "tools_executed": len([k for k in self.stage_results.get("vulnerability_detection", {}).keys() if k != "analyzer_report"]),
                "analyzer_report": self.stage_results.get("vulnerability_detection", {}).get("analyzer_report", "")[:2000],
            },
            "stage_4_exploitation": {
                "analysis": self.stage_results.get("exploitation", {}).get("executor_analysis", "")[:2000],
                "summary": self.stage_results.get("exploitation", {}).get("exploitation_summary", {}),
            },
        }
        
        report_task = Task(
            description=f"""为以下渗透测试结果生成专业的 Markdown 格式报告：

目标: {self.target}
完整测试数据:
{json.dumps(all_stages_summary, ensure_ascii=False, indent=2)[:8000]}

请生成包含以下部分的报告：
1. 执行摘要（测试目标、时间、发现漏洞总数、风险评级）
2. 攻击面分析（开放服务、技术栈识别）
3. 漏洞详情（每个漏洞的名称、风险等级、描述、影响、证据、修复建议）
4. 攻击路径分析（可能的攻击链）
5. 修复建议（按优先级排序）
6. 附录（工具执行详情）

报告格式要求：
- 使用 Markdown 格式
- 结构清晰，层次分明
- 使用表格展示漏洞列表
- 提供具体的修复建议和代码示例
- 如果某个阶段没有发现漏洞，也要说明已执行的测试""",
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
            await self._send_callback(f"  ⚠️ Reporter Agent 执行超时，使用内置报告生成器")
            # 回退到内置报告生成器
            from report import report_generator
            try:
                full_results = {
                    "target": self.target,
                    "stages": self.stage_results,
                    "discovered_services": [
                        {"port": s.port, "service": s.service, "version": s.version}
                        for s in self.discovered_services
                    ],
                }
                # 生成一个临时 task_id
                import uuid
                temp_task_id = str(uuid.uuid4())
                report_path = report_generator.generate_report(
                    task_id=temp_task_id,
                    target=self.target,
                    results=full_results
                )
                with open(report_path, "r", encoding="utf-8") as f:
                    report_content = f.read()
            except Exception as e:
                report_content = f"# 渗透测试报告\n\n目标: {self.target}\n\n报告生成失败: {e}"
        
        return {
            "content": report_content,
            "generated_at": datetime.now().isoformat()
        }


async def run_pentest(target: str, callback: Optional[Callable] = None) -> Dict:
    """便捷函数：执行渗透测试"""
    runner = CrewRunner(target=target, callback=callback)
    return await runner.run()
