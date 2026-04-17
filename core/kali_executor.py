"""Kali Linux direct command executor."""

import subprocess
import shlex
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class KaliExecutor:
    """直接在Kali Linux环境中执行命令，不使用Docker"""
    
    def __init__(self, timeout: int = 300):
        """
        初始化Kali执行器
        
        Args:
            timeout: 命令执行超时时间（秒），默认300秒
        """
        self.timeout = timeout

    def execute(self, command: str, working_dir: Optional[str] = None) -> str:
        """
        在Kali Linux中执行命令
        
        Args:
            command: 要执行的shell命令
            working_dir: 工作目录（可选）
            
        Returns:
            执行结果（stdout + stderr）
        """
        try:
            # 使用shlex分割命令，防止注入
            cmd_parts = shlex.split(command)
            
            logger.info(f"执行命令: {command}")
            
            # 执行命令
            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=working_dir,
                shell=False  # 不使用shell=True防止注入
            )
            
            # 组合stdout和stderr
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                if output:
                    output += "\n--- STDERR ---\n"
                output += result.stderr
            
            # 检查退出码
            if result.returncode != 0:
                logger.warning(f"命令执行失败 (exit code: {result.returncode}): {command}")
                return f"⚠️ [Exit Code {result.returncode}]\n{output}"
            
            logger.info(f"命令执行成功: {command}")
            return output
            
        except subprocess.TimeoutExpired:
            error_msg = f"❌ [Timeout] 命令执行超时 ({self.timeout}秒)"
            logger.error(error_msg)
            return error_msg
            
        except FileNotFoundError:
            error_msg = f"❌ [Command Not Found] 命令不存在: {command}"
            logger.error(error_msg)
            return error_msg
            
        except Exception as e:
            error_msg = f"❌ [System Error]: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def execute_python(self, code: str) -> str:
        """
        执行Python代码
        
        Args:
            code: Python代码字符串
            
        Returns:
            执行结果
        """
        try:
            result = subprocess.run(
                ['python3', '-c', code],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                if output:
                    output += "\n--- STDERR ---\n"
                output += result.stderr
            
            if result.returncode != 0:
                return f"⚠️ [Python Error - Exit Code {result.returncode}]\n{output}"
            
            return output
            
        except Exception as e:
            return f"❌ [Python Execution Error]: {str(e)}"
