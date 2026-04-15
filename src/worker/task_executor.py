"""
Task Executor - 任务执行器
负责执行具体的渗透测试任务
"""
import json
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
from loguru import logger

from ..agents.recon_agent import ReconAgent
from ..agents.exploit_agent import ExploitAgent
from ..agents.privilege_agent import PrivilegeAgent
from ..agents.report_agent import ReportAgent


class TaskExecutor:
    """任务执行器"""

    def __init__(self, redis_client=None):
        self.redis_client = redis_client
        self.active_tasks: Dict[str, Dict] = {}

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行任务

        Args:
            task_data: 任务数据，包含 task_id, task_type, target, params 等

        Returns:
            执行结果
        """
        task_id = task_data.get("task_id", "unknown")
        task_type = task_data.get("task_type", "unknown")
        target = task_data.get("target", "")

        logger.info(f"Executing task {task_id} type={task_type} target={target}")

        start_time = datetime.now()

        result = {
            "task_id": task_id,
            "task_type": task_type,
            "target": target,
            "status": "running",
            "start_time": start_time.isoformat(),
            "result": None,
            "error": None
        }

        try:
            # 根据任务类型执行不同的逻辑
            if task_type == "scan":
                result["result"] = await self._execute_full_scan(target, task_data)
            elif task_type == "recon":
                result["result"] = await self._execute_recon(target, task_data)
            elif task_type == "exploit":
                result["result"] = await self._execute_exploit(target, task_data)
            elif task_type == "privilege":
                result["result"] = await self._execute_privilege(target, task_data)
            elif task_type == "report":
                result["result"] = await self._execute_report(target, task_data)
            else:
                raise ValueError(f"Unknown task type: {task_type}")

            result["status"] = "completed"
            logger.info(f"Task {task_id} completed successfully")

        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            logger.error(f"Task {task_id} failed: {e}")

        end_time = datetime.now()
        result["end_time"] = end_time.isoformat()
        result["duration"] = (end_time - start_time).total_seconds()

        # 更新 Redis 中的任务状态
        await self._update_task_status(task_id, result)

        return result

    async def _execute_full_scan(self, target: str, params: Dict) -> Dict:
        """执行完整扫描流程：recon → exploit → privilege → report"""
        logger.info(f"Starting full scan workflow for target: {target}")
        
        scan_id = params.get("scan_id", "unknown")
        scan_type = params.get("scan_type", "full")
        scope = params.get("scope", [])
        options = params.get("options", {})
        
        # 更新扫描状态为 running
        await self._update_scan_status(scan_id, "running", current_phase="recon", progress=10)
        
        # 阶段 1: 信息收集
        logger.info(f"[Phase 1/4] Starting reconnaissance on {target}")
        await self._update_scan_status(scan_id, "running", current_phase="recon", progress=15)
        
        recon_result = await self._execute_recon(target, {
            "agent_config": {"name": "ReconAgent", "description": "负责目标信息收集和侦察"},
            "context": {"target": target, "scope": scope, "scan_id": scan_id}
        })
        
        await self._update_scan_status(scan_id, "running", current_phase="recon", progress=30)
        logger.info(f"[Phase 1/4] Reconnaissance completed: {recon_result.get('agent_state', 'unknown')}")
        
        # 阶段 2: 漏洞利用
        logger.info(f"[Phase 2/4] Starting exploitation on {target}")
        await self._update_scan_status(scan_id, "running", current_phase="exploit", progress=35)
        
        # 将 recon 结果传递给 exploit
        exploit_context = {
            "target": target,
            "scope": scope,
            "scan_id": scan_id,
            "recon_result": recon_result.get("recon_result", {}),
            "findings": recon_result.get("agent_report", {}).get("findings", [])
        }
        
        exploit_result = await self._execute_exploit(target, {
            "agent_config": {"name": "ExploitAgent", "description": "负责漏洞验证和利用"},
            "context": exploit_context
        })
        
        await self._update_scan_status(scan_id, "running", current_phase="exploit", progress=60)
        logger.info(f"[Phase 2/4] Exploitation completed: {exploit_result.get('agent_state', 'unknown')}")
        
        # 阶段 3: 权限提升
        logger.info(f"[Phase 3/4] Starting privilege escalation on {target}")
        await self._update_scan_status(scan_id, "running", current_phase="privilege", progress=65)
        
        privilege_context = {
            "target": target,
            "scope": scope,
            "scan_id": scan_id,
            "recon_result": recon_result.get("recon_result", {}),
            "exploit_result": exploit_result.get("exploit_result", {}),
            "findings": exploit_result.get("agent_report", {}).get("findings", [])
        }
        
        privilege_result = await self._execute_privilege(target, {
            "agent_config": {"name": "PrivilegeAgent", "description": "负责权限提升和持久化"},
            "context": privilege_context
        })
        
        await self._update_scan_status(scan_id, "running", current_phase="privilege", progress=80)
        logger.info(f"[Phase 3/4] Privilege escalation completed: {privilege_result.get('agent_state', 'unknown')}")
        
        # 阶段 4: 生成报告
        logger.info(f"[Phase 4/4] Starting report generation for {target}")
        await self._update_scan_status(scan_id, "running", current_phase="reporting", progress=85)
        
        report_context = {
            "target": target,
            "scope": scope,
            "scan_id": scan_id,
            "scan_type": scan_type,
            "recon_result": recon_result,
            "exploit_result": exploit_result,
            "privilege_result": privilege_result,
            "all_findings": []
        }
        
        report_result = await self._execute_report(target, {
            "agent_config": {"name": "ReportAgent", "description": "负责生成渗透测试报告"},
            "context": report_context
        })
        
        await self._update_scan_status(scan_id, "completed", current_phase="completed", progress=100)
        logger.info(f"[Phase 4/4] Report generation completed")
        
        return {
            "scan_id": scan_id,
            "scan_type": scan_type,
            "phases": {
                "recon": recon_result,
                "exploit": exploit_result,
                "privilege": privilege_result,
                "report": report_result
            },
            "success": all([
                recon_result.get("success", False),
                exploit_result.get("success", False),
                privilege_result.get("success", False),
                report_result.get("success", False)
            ])
        }

    async def _update_scan_status(self, scan_id: str, status: str, current_phase: str = "", progress: int = 0):
        """更新扫描状态到 Redis"""
        if self.redis_client:
            try:
                from ..core.scan_manager import ScanManager
                scan_manager = ScanManager.get_instance()
                scan_data = scan_manager.get_status(scan_id)
                if scan_data:
                    scan_data["status"] = status
                    scan_data["current_phase"] = current_phase
                    scan_data["progress"] = progress
                    if status == "completed":
                        from datetime import datetime
                        scan_data["completed_at"] = datetime.now().isoformat()
                    
                    key = scan_manager._get_scan_key(scan_id)
                    import json
                    self.redis_client.setex(key, scan_manager.scan_ttl, json.dumps(scan_data))
            except Exception as e:
                logger.warning(f"Failed to update scan status: {e}")

    async def _execute_recon(self, target: str, params: Dict) -> Dict:
        """执行信息收集任务"""
        logger.info(f"Initializing ReconAgent for target: {target}")
        
        # 从参数中提取 Agent 配置
        agent_config = params.get("agent_config", {})
        context = params.get("context", {})
        
        # 创建 ReconAgent 实例
        agent = ReconAgent(
            name=agent_config.get("name", "ReconAgent"),
            description=agent_config.get("description", "负责目标信息收集和侦察"),
            config=agent_config.get("config", {})
        )
        
        # 执行侦察任务
        logger.info(f"Starting reconnaissance on {target}")
        result = await agent.execute(target, context)
        
        # 验证结果
        if agent.validate_result(result):
            logger.info(f"Reconnaissance completed successfully for {target}")
        else:
            logger.warning(f"Reconnaissance result validation failed for {target}")
        
        # 生成报告
        report = agent.report()
        
        return {
            "recon_result": result,
            "agent_report": report,
            "agent_state": agent.state.value,
            "success": agent.validate_result(result)
        }

    async def _execute_exploit(self, target: str, params: Dict) -> Dict:
        """执行漏洞利用任务"""
        logger.info(f"Initializing ExploitAgent for target: {target}")
        
        # 从参数中提取 Agent 配置和上下文（包含 Recon 结果）
        agent_config = params.get("agent_config", {})
        context = params.get("context", {})
        
        # 创建 ExploitAgent 实例
        agent = ExploitAgent(
            name=agent_config.get("name", "ExploitAgent"),
            description=agent_config.get("description", "负责漏洞验证和利用，获取初始访问"),
            config=agent_config.get("config", {})
        )
        
        # 执行漏洞利用任务
        logger.info(f"Starting exploitation on {target}")
        result = await agent.execute(target, context)
        
        # 验证结果
        if agent.validate_result(result):
            logger.info(f"Exploitation completed successfully for {target}")
        else:
            logger.warning(f"Exploitation result validation failed for {target}")
        
        # 生成报告
        report = agent.report()
        
        return {
            "exploit_result": result,
            "agent_report": report,
            "agent_state": agent.state.value,
            "success": agent.validate_result(result)
        }

    async def _execute_privilege(self, target: str, params: Dict) -> Dict:
        """执行权限提升任务"""
        logger.info(f"Initializing PrivilegeAgent for target: {target}")
        
        # 从参数中提取 Agent 配置和上下文（包含 Exploit 结果）
        agent_config = params.get("agent_config", {})
        context = params.get("context", {})
        
        # 创建 PrivilegeAgent 实例
        agent = PrivilegeAgent(
            name=agent_config.get("name", "PrivilegeAgent"),
            description=agent_config.get("description", "负责权限提升和持久化"),
            config=agent_config.get("config", {})
        )
        
        # 执行权限提升任务
        logger.info(f"Starting privilege escalation on {target}")
        result = await agent.execute(target, context)
        
        # 验证结果
        if agent.validate_result(result):
            logger.info(f"Privilege escalation completed successfully for {target}")
        else:
            logger.warning(f"Privilege escalation result validation failed for {target}")
        
        # 生成报告
        report = agent.report()
        
        return {
            "privilege_result": result,
            "agent_report": report,
            "agent_state": agent.state.value,
            "success": agent.validate_result(result)
        }

    async def _execute_report(self, target: str, params: Dict) -> Dict:
        """执行报告生成任务"""
        logger.info(f"Initializing ReportAgent for target: {target}")
        
        # 从参数中提取 Agent 配置和上下文（包含所有前置任务结果）
        agent_config = params.get("agent_config", {})
        context = params.get("context", {})
        
        # 创建 ReportAgent 实例
        agent = ReportAgent(
            name=agent_config.get("name", "ReportAgent"),
            description=agent_config.get("description", "负责生成渗透测试报告"),
            config=agent_config.get("config", {})
        )
        
        # 执行报告生成任务
        logger.info(f"Starting report generation for {target}")
        result = await agent.execute(target, context)
        
        # 验证结果
        if agent.validate_result(result):
            logger.info(f"Report generation completed successfully for {target}")
        else:
            logger.warning(f"Report generation result validation failed for {target}")
        
        # 生成报告
        report = agent.report()
        
        return {
            "report_result": result,
            "agent_report": report,
            "agent_state": agent.state.value,
            "success": agent.validate_result(result)
        }

    async def _update_task_status(self, task_id: str, result: Dict):
        """更新任务状态到 Redis"""
        if self.redis_client:
            try:
                key = f"task:{task_id}"
                self.redis_client.setex(
                    key,
                    3600,  # 1小时过期
                    json.dumps(result)
                )
            except Exception as e:
                logger.error(f"Failed to update task status: {e}")

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """获取任务状态"""
        if self.redis_client:
            try:
                key = f"task:{task_id}"
                data = self.redis_client.get(key)
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.error(f"Failed to get task status: {e}")
        return None