"""Kali Linux direct command executor."""

import subprocess
import shlex
import time
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
        self._skidcon_logger = None

    @property
    def skidcon_logger(self):
        if self._skidcon_logger is None:
            from core.logger import logger as skidcon_logger

            self._skidcon_logger = skidcon_logger
        return self._skidcon_logger

    @staticmethod
    def _needs_shell(command: str) -> bool:
        shell_features = ["|", "&&", "||", ">", ">>", "<", "2>", "&>", "$(", "`"]
        for feature in shell_features:
            if feature in command:
                return True
        return False

    def execute(self, command: str, working_dir: Optional[str] = None) -> str:
        """
        在Kali Linux中执行命令

        Args:
            command: 要执行的shell命令
            working_dir: 工作目录（可选）

        Returns:
            执行结果（stdout + stderr）
        """
        start_time = time.time()
        try:
            use_shell = self._needs_shell(command)

            if use_shell:
                cmd_args = ["bash", "-c", command]
            else:
                cmd_args = shlex.split(command)

            logger.info(f"执行命令: {command}")

            result = subprocess.run(
                cmd_args,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=working_dir,
            )

            duration = time.time() - start_time

            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                if output:
                    output += "\n--- STDERR ---\n"
                output += result.stderr

            if result.returncode != 0:
                logger.warning(
                    f"命令执行失败 (exit code: {result.returncode}): {command}"
                )
                self.skidcon_logger.log_command(
                    command=command,
                    output=output,
                    duration=duration,
                    exit_code=result.returncode,
                    tool_type="shell",
                )
                return f"⚠️ [Exit Code {result.returncode}]\n{output}"

            logger.info(f"命令执行成功: {command}")
            self.skidcon_logger.log_command(
                command=command,
                output=output,
                duration=duration,
                exit_code=0,
                tool_type="shell",
            )
            return output

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            error_msg = f"❌ [Timeout] 命令执行超时 ({self.timeout}秒)"
            logger.error(error_msg)
            self.skidcon_logger.log_command(
                command=command,
                output=error_msg,
                duration=duration,
                exit_code=-1,
                tool_type="shell",
            )
            self.skidcon_logger.log_error(
                "command_timeout",
                error_msg,
                {"command": command[:200], "timeout": self.timeout},
            )
            return error_msg

        except FileNotFoundError as e:
            duration = time.time() - start_time
            error_msg = f"❌ [Command Not Found] 命令不存在: {command}"
            if "playwright-cli" in command:
                error_msg += "\n💡 请先安装Playwright CLI: sudo npm install -g @playwright/cli@latest"
                error_msg += "\n💡 然后安装浏览器: sudo playwright-cli install --with-deps chromium firefox webkit"
            logger.error(error_msg)
            self.skidcon_logger.log_command(
                command=command,
                output=error_msg,
                duration=duration,
                exit_code=127,
                tool_type="shell",
            )
            return error_msg

        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"❌ [System Error]: {str(e)}"
            logger.error(error_msg)
            self.skidcon_logger.log_error(
                "command_system_error", error_msg, {"command": command[:200]}
            )
            self.skidcon_logger.log_command(
                command=command,
                output=error_msg,
                duration=duration,
                exit_code=-2,
                tool_type="shell",
            )
            return error_msg

    def execute_python(self, code: str) -> str:
        """
        执行Python代码

        Args:
            code: Python代码字符串

        Returns:
            执行结果
        """
        start_time = time.time()
        try:
            result = subprocess.run(
                ["python3", "-c", code],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            duration = time.time() - start_time

            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                if output:
                    output += "\n--- STDERR ---\n"
                output += result.stderr

            if result.returncode != 0:
                self.skidcon_logger.log_command(
                    command=code[:500],
                    output=output,
                    duration=duration,
                    exit_code=result.returncode,
                    tool_type="python",
                )
                return f"⚠️ [Python Error - Exit Code {result.returncode}]\n{output}"

            self.skidcon_logger.log_command(
                command=code[:500],
                output=output,
                duration=duration,
                exit_code=0,
                tool_type="python",
            )
            return output

        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"❌ [Python Execution Error]: {str(e)}"
            self.skidcon_logger.log_error(
                "python_execution_error", error_msg, {"code_preview": code[:200]}
            )
            return error_msg
