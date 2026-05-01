import subprocess
from pathlib import Path
from typing import Type, Optional

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class PythonScriptInput(BaseModel):
    """输入：指定要执行的 Python 脚本及命令行参数"""
    script_path: str = Field(description="Path to the Python script to execute (relative or absolute)")
    args: str = Field(default="", description="Optional arguments to pass to the script")


class PythonExecuteTool(BaseTool):
    """使用指定的 Python 解释器执行一个脚本文件，并返回输出。"""

    name: str = "python_execute"
    description: str = (
        "Execute an existing Python script file using the configured Python interpreter. "
        "Provide the path to the script and any optional arguments. "
        "The script will be run in a subprocess and its stdout/stderr will be returned. "
        "This is the preferred way to run any .py file in the project."
    )
    args_schema: Type[BaseModel] = PythonScriptInput

    python_path: str = "python"           # Python 解释器路径（支持 ~）
    timeout: int = 60                     # 超时秒数
    workdir: Optional[str] = None         # 执行时的工作目录

    def _run(self, script_path: str, args: str = "") -> str:
        # 解析解释器路径
        resolved_python = str(Path(self.python_path).expanduser().resolve())
        # 解析脚本路径（支持相对路径和工作目录）
        script = Path(script_path).expanduser()
        # 如果设置了工作目录，且脚本是相对路径，则基于 workdir 解析
        if self.workdir and not script.is_absolute():
            script = Path(self.workdir).expanduser().resolve() / script

        # 构建命令：解释器 + 脚本 + 参数
        cmd = [resolved_python, str(script)]
        if args.strip():
            cmd.extend(args.strip().split())

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.workdir,
            )
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            if result.returncode != 0:
                output = f"Exit code: {result.returncode}\n"
                if stderr:
                    output += f"STDERR:\n{stderr}\n"
                if stdout:
                    output += f"STDOUT:\n{stdout}"
                return output or "(no output)"
            output = stdout or "(script executed successfully with no output)"
            if stderr:
                output += f"\nWarnings/Errors:\n{stderr}"
            if len(output) > 5000:
                output = output[:5000] + "\n...[truncated]"
            return output
        except subprocess.TimeoutExpired:
            return f"Timeout: script execution exceeded {self.timeout} seconds"
        except FileNotFoundError:
            return f"Error: Python interpreter not found at {resolved_python}"
        except Exception as e:
            return f"Execution error: {type(e).__name__}: {e}"

    # 异步执行包装（如果你的 graph 是异步的）
    async def _arun(self, script_path: str, args: str = "") -> str:
        import asyncio
        return await asyncio.to_thread(self._run, script_path, args)


def create_python_execute_tool(
    python_path: str = "python",
    timeout: int = 60,
    workdir: Optional[str] = None,
) -> BaseTool:
    """工厂函数：创建配置好的 Python 脚本执行工具。"""
    return PythonExecuteTool(
        python_path=python_path,
        timeout=timeout,
        workdir=workdir,
    )