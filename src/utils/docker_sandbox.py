"""
Docker Sandbox - 安全执行环境
在Docker容器中隔离执行危险操作
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
import asyncio
import json


@dataclass
class ContainerConfig:
    """容器配置"""
    image: str = "python:3.11-slim"
    timeout: int = 300
    memory_limit: str = "512m"
    cpu_limit: float = 1.0
    network_enabled: bool = True
    volumes: Dict[str, str] = field(default_factory=dict)
    environment: Dict[str, str] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    """执行结果"""
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    execution_time: float


class DockerSandbox:
    """
    Docker沙箱环境
    
    用于安全执行：
    - 漏洞利用脚本
    - 不可信代码
    - 危险命令
    """
    
    def __init__(self, docker_client=None):
        self.docker_client = docker_client
        self._containers: Dict[str, Any] = {}
    
    async def initialize(self) -> bool:
        """初始化Docker连接"""
        try:
            import docker
            self.docker_client = docker.from_env()
            return True
        except Exception as e:
            print(f"Failed to initialize Docker: {e}")
            return False
    
    async def create_container(
        self,
        name: str,
        config: ContainerConfig = None
    ) -> Optional[str]:
        """
        创建容器
        
        Args:
            name: 容器名称
            config: 容器配置
        
        Returns:
            容器ID或None
        """
        config = config or ContainerConfig()
        
        try:
            container = self.docker_client.containers.create(
                image=config.image,
                name=name,
                detach=True,
                mem_limit=config.memory_limit,
                cpu_quota=int(config.cpu_limit * 100000),
                network_disabled=not config.network_enabled,
                volumes=config.volumes,
                environment=config.environment
            )
            self._containers[name] = container
            return container.id
        except Exception as e:
            print(f"Failed to create container: {e}")
            return None
    
    async def execute(
        self,
        container_name: str,
        command: str,
        timeout: int = 60
    ) -> ExecutionResult:
        """
        在容器中执行命令
        
        Args:
            container_name: 容器名称
            command: 要执行的命令
            timeout: 超时时间（秒）
        
        Returns:
            ExecutionResult对象
        """
        import time
        start_time = time.time()
        
        if container_name not in self._containers:
            return ExecutionResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="Container not found",
                execution_time=0
            )
        
        container = self._containers[container_name]
        
        try:
            # 启动容器（如果未运行）
            if container.status != "running":
                container.start()
            
            # 执行命令
            exit_code, output = container.exec_run(
                cmd=command,
                timeout=timeout
            )
            
            execution_time = time.time() - start_time
            
            # 分离stdout和stderr
            output_str = output.decode('utf-8', errors='ignore')
            
            return ExecutionResult(
                success=exit_code == 0,
                exit_code=exit_code,
                stdout=output_str,
                stderr="",
                execution_time=execution_time
            )
            
        except asyncio.TimeoutError:
            return ExecutionResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="Execution timeout",
                execution_time=timeout
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                execution_time=time.time() - start_time
            )
    
    async def execute_python(
        self,
        container_name: str,
        code: str,
        timeout: int = 60
    ) -> ExecutionResult:
        """
        在容器中执行Python代码
        
        Args:
            container_name: 容器名称
            code: Python代码
            timeout: 超时时间
        
        Returns:
            ExecutionResult对象
        """
        # 转义代码中的引号
        escaped_code = code.replace('"', '\\"').replace("'", "\\'")
        command = f'python -c "{escaped_code}"'
        return await self.execute(container_name, command, timeout)
    
    async def stop_container(self, name: str) -> bool:
        """停止容器"""
        if name in self._containers:
            try:
                self._containers[name].stop()
                return True
            except Exception:
                return False
        return False
    
    async def remove_container(self, name: str) -> bool:
        """移除容器"""
        if name in self._containers:
            try:
                self._containers[name].remove(force=True)
                del self._containers[name]
                return True
            except Exception:
                return False
        return False
    
    async def cleanup_all(self) -> None:
        """清理所有容器"""
        for name in list(self._containers.keys()):
            await self.remove_container(name)
    
    async def get_container_status(self, name: str) -> Optional[str]:
        """获取容器状态"""
        if name in self._containers:
            try:
                self._containers[name].reload()
                return self._containers[name].status
            except Exception:
                return None
        return None
    
    async def get_container_logs(self, name: str) -> Optional[str]:
        """获取容器日志"""
        if name in self._containers:
            try:
                return self._containers[name].logs().decode('utf-8')
            except Exception:
                return None
        return None