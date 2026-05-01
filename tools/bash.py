import asyncio
import sys
from pathlib import Path
from typing import Type, Optional, ClassVar

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
import os
import re
import subprocess

class BashInput(BaseModel):
    command: str = Field(description="要执行的 shell 命令")


class SafeBashTool(BaseTool):
    name: str = "Bash"
    description: str = (
        "执行 shell 命令。工作目录限制在项目根目录。"
        "可用于文件操作、安装包、运行脚本等。"
    )
    args_schema: Type[BaseModel] = BashInput
    root_dir: str = ""
    timeout: int = 30
    max_output_chars: int = 5000

    DANGEROUS_PATTERNS: ClassVar[list] = [
        (r"\brm\s+(-rf?|--recursive)?\s+(/|/\*|~|\.\./\.\.|\./\*)", "危险删除操作"),
        (r"\bmkfs\b", "格式化文件系统"),
        (r"\bdd\s+.*of=/dev/", "原始磁盘写入"),
        (r":\(\)\s*\{.*:\|:.*\}", "fork 炸弹"),
        (r"\bchmod\s+-R\s+777\s+/", "根目录递归 777"),
        (r"\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b", "关机/重启命令"),
        (r"\|?\s*(sudo\s+)?(bash|sh|zsh|dash)(\s|$)", "管道到 shell 的危险操作"),
    ]

    def _is_safe(self, command: str) -> bool:
        cmd_lower = command.lower()
        for pattern, _ in self.DANGEROUS_PATTERNS:
            if re.search(pattern, cmd_lower):
                return False

        # 只允许 cd 到 root_dir 目录
        if "cd " in cmd_lower:
            root = self.root_dir.rstrip("/")
            if root:
                cd_match = re.search(r"cd\s+([^\s;|]+)", command)
                if cd_match:
                    target = cd_match.group(1).strip("'\"").rstrip("/")
                    if not (target == root or target.startswith(root + "/")):
                        return False

        return True

    def _run(self, command: str) -> str:
        if not self._is_safe(command):
            return f"❌ 命令被安全策略阻止: {command}"

        is_win = sys.platform == "win32"
        try:
            if is_win:
                wrapped = f"chcp 65001 >nul 2>&1 && {command}"
                result = subprocess.run(
                    wrapped,
                    shell=True,
                    cwd=self.root_dir,
                    capture_output=True,
                    timeout=self.timeout,
                )
                stdout = self._decode(result.stdout)
                stderr = self._decode(result.stderr)
            else:
                clean_env = self._get_clean_env()
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=self.root_dir,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    encoding="utf-8",
                    errors="replace",
                    env=clean_env,
                )
                stdout = result.stdout
                stderr = result.stderr

            output = stdout
            if stderr:
                output += f"\n[stderr]: {stderr}"
            if not output.strip():
                output = "(命令执行完成，无输出)"

            if len(output) > self.max_output_chars:
                output = output[:self.max_output_chars] + "\n...[输出过长已截断]"
            return output
        except subprocess.TimeoutExpired:
            return f"❌ 命令执行超时（{self.timeout}秒限制）"
        except Exception as e:
            return f"❌ 执行错误: {str(e)}"

    async def _arun(self, command: str) -> str:
        """异步版本"""
        if not self._is_safe(command):
            return f"❌ 命令被安全策略阻止: {command}"

        is_win = sys.platform == "win32"
        try:
            if is_win:
                # Windows 异步仍然使用同步版本（asyncio 子进程在 Windows 上较复杂）
                return self._run(command)
            else:
                # Unix 使用 asyncio 子进程
                clean_env = self._get_clean_env()
                proc = await asyncio.create_subprocess_shell(
                    command,
                    cwd=self.root_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=clean_env,
                )
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout
                )
                stdout = stdout_bytes.decode("utf-8", errors="replace")
                stderr = stderr_bytes.decode("utf-8", errors="replace")

                output = stdout
                if stderr:
                    output += f"\n[stderr]: {stderr}"
                if not output.strip():
                    output = "(命令执行完成，无输出)"
                if len(output) > self.max_output_chars:
                    output = output[:self.max_output_chars] + "\n...[输出过长已截断]"
                return output
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"❌ 命令执行超时（{self.timeout}秒限制）"
        except Exception as e:
            return f"❌ 执行错误: {str(e)}"

    @staticmethod
    def _decode(raw: bytes) -> str:
        if not raw:
            return ""
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
        try:
            return raw.decode("gbk")
        except UnicodeDecodeError:
            pass
        return raw.decode("latin-1")

    @staticmethod
    def _get_clean_env() -> dict:
        """返回一个最小化的安全环境变量"""
        clean_env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": os.environ.get("HOME", ""),
            "USER": os.environ.get("USER", ""),
            "LANG": "C.UTF-8",
        }
        if sys.platform == "win32":
            clean_env["SystemRoot"] = os.environ.get("SystemRoot", "")
            clean_env["PATH"] = os.environ.get("PATH", "")
        return clean_env


def create_bash_tool(base_dir: Path) -> SafeBashTool:
    return SafeBashTool(root_dir=str(base_dir))
