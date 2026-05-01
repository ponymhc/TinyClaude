"""
Glob Tool - 使用glob模式搜索文件
"""

import os
import time
from pathlib import Path
from typing import Optional, Type, ClassVar, List, Tuple
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
import fnmatch


class GlobInput(BaseModel):
    """Glob工具输入参数"""
    pattern: str = Field(description="要匹配的glob模式（例如：'*.py', 'src/**/*.ts', 'test_*.{py,js}'）")
    path: Optional[str] = Field(
        default=None,
        description="搜索的目录路径。如果未指定，使用当前工作目录。重要：省略此字段以使用默认目录。不要输入'undefined'或'null'"
    )


class GlobOutput(BaseModel):
    """Glob工具输出结果"""
    duration_ms: int = Field(description="执行搜索所花费的时间（毫秒）")
    num_files: int = Field(description="找到的文件总数")
    filenames: List[str] = Field(description="匹配模式的文件路径数组")
    truncated: bool = Field(description="结果是否被截断（限制为100个文件）")


class GlobTool(BaseTool):
    """
    Glob工具 - 使用glob模式搜索文件
    
    支持通配符模式：
    - * 匹配任意字符（除了路径分隔符）
    - ** 递归匹配任意目录
    - ? 匹配单个字符
    - [abc] 匹配字符集
    - {py,js,ts} 匹配多个扩展名
    """
    
    name: str = "Glob"
    description: str = (
        "使用glob模式搜索文件。支持通配符：*（任意字符），**（递归目录），"
        "?（单个字符），[abc]（字符集），{py,js,ts}（多个扩展名）。"
    )
    args_schema: Type[BaseModel] = GlobInput
    
    # 配置参数
    max_results: int = 100  # 最大结果数，与TypeScript版本一致
    root_dir: str = ""  # 根目录，通常在创建工具时设置
    
    def _get_search_path(self, input_path: Optional[str]) -> str:
        """获取搜索路径"""
        if input_path:
            # 扩展~和环境变量
            expanded = os.path.expanduser(os.path.expandvars(input_path))
            # 如果是相对路径，转换为绝对路径
            if not os.path.isabs(expanded):
                return os.path.join(self.root_dir or os.getcwd(), expanded)
            return expanded
        return self.root_dir or os.getcwd()
    
    def _validate_path(self, search_path: str, original_input: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """验证路径是否存在且是目录"""
        try:
            if not os.path.exists(search_path):
                cwd = self.root_dir or os.getcwd()
                suggestion = ""
                # 尝试在cwd下找到相似路径（如果提供了原始输入）
                if original_input:
                    for root, dirs, _ in os.walk(cwd):
                        for dir_name in dirs:
                            if original_input.lower() in dir_name.lower() or dir_name.lower() in original_input.lower():
                                suggestion = f" 是否指的是 {os.path.relpath(os.path.join(root, dir_name), cwd)}?"
                                break
                        if suggestion:
                            break
                
                return False, f"目录不存在: {search_path}. 当前工作目录: {cwd}.{suggestion}"
            
            if not os.path.isdir(search_path):
                return False, f"路径不是目录: {search_path}"
            
            return True, None
        except Exception as e:
            return False, f"路径验证错误: {str(e)}"
    
    def _matches_pattern(self, file_path: str, pattern: str, search_path: str) -> bool:
        """检查文件路径是否匹配glob模式"""
        try:
            # 将路径转换为相对于搜索路径的相对路径
            try:
                rel_path = os.path.relpath(file_path, search_path)
            except ValueError:
                # 如果路径不在搜索路径下（跨磁盘等），直接比较文件名
                rel_path = os.path.basename(file_path)
            
            # 处理递归模式
            if '**' in pattern:
                # 将**转换为适合fnmatch的格式
                # 注意：这仍然简化了，但对于大多数用例足够
                parts = pattern.split('**')
                if len(parts) == 2:
                    # 模式如：prefix**suffix
                    prefix, suffix = parts
                    if rel_path.startswith(prefix) and rel_path.endswith(suffix):
                        return True
                return fnmatch.fnmatch(rel_path, pattern.replace('**', '*'))
            else:
                return fnmatch.fnmatch(rel_path, pattern)
        except:
            return False
    
    def _expand_braces(self, pattern: str) -> List[str]:
        """扩展花括号模式，如{a,b,c}"""
        import re
        
        # 查找花括号模式
        brace_pattern = r'\{([^{}]+)\}'
        matches = list(re.finditer(brace_pattern, pattern))
        
        if not matches:
            return [pattern]
        
        # 处理第一个花括号
        first_match = matches[0]
        start, end = first_match.span()
        inner = first_match.group(1)
        
        # 分割内部选项
        options = [opt.strip() for opt in inner.split(',') if opt.strip()]
        
        results = []
        for opt in options:
            # 替换花括号为选项
            new_pattern = pattern[:start] + opt + pattern[end:]
            # 递归处理剩余的花括号
            results.extend(self._expand_braces(new_pattern))
        
        return results
    
    def _run_sync(self, pattern: str, path: Optional[str] = None) -> dict:
        """同步执行glob搜索（将被异步调用）"""
        start_time = time.time()
        
        # 获取搜索路径
        search_path = self._get_search_path(path)
        
        # 验证路径
        is_valid, error_msg = self._validate_path(search_path, path)
        if not is_valid:
            return {
                "duration_ms": int((time.time() - start_time) * 1000),
                "num_files": 0,
                "filenames": [],
                "truncated": False,
                "error": error_msg
            }
        
        # 扩展花括号模式
        patterns = self._expand_braces(pattern)
        
        # 收集匹配的文件
        matched_files = []
        truncated = False
        
        try:
            # 使用 pathlib 进行更高效的遍历
            root_path = Path(search_path)
            
            # 根据模式决定是否递归
            if '**' in pattern or any('**' in p for p in patterns):
                # 递归搜索
                for file_path in root_path.rglob('*'):
                    if file_path.is_file():
                        # 检查是否匹配任一模式
                        for pat in patterns:
                            # 使用相对路径进行匹配
                            try:
                                rel_path = str(file_path.relative_to(search_path))
                            except ValueError:
                                rel_path = file_path.name
                            
                            # 简单的模式匹配（生产环境建议使用pathlib的match）
                            if self._matches_pattern(str(file_path), pat, search_path):
                                # 转换为相对于根目录的路径
                                try:
                                    display_path = str(file_path.relative_to(self.root_dir or os.getcwd()))
                                except ValueError:
                                    display_path = str(file_path)
                                
                                matched_files.append(display_path)
                                
                                if len(matched_files) >= self.max_results:
                                    truncated = True
                                    break
                        
                        if truncated:
                            break
            else:
                # 非递归搜索（仅当前目录）
                for file_path in root_path.iterdir():
                    if file_path.is_file():
                        for pat in patterns:
                            if fnmatch.fnmatch(file_path.name, pat):
                                try:
                                    display_path = str(file_path.relative_to(self.root_dir or os.getcwd()))
                                except ValueError:
                                    display_path = str(file_path)
                                
                                matched_files.append(display_path)
                                
                                if len(matched_files) >= self.max_results:
                                    truncated = True
                                    break
                        
                        if truncated:
                            break
        
        except Exception as e:
            return {
                "duration_ms": int((time.time() - start_time) * 1000),
                "num_files": 0,
                "filenames": [],
                "truncated": False,
                "error": f"搜索错误: {str(e)}"
            }
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        return {
            "duration_ms": duration_ms,
            "num_files": len(matched_files),
            "filenames": matched_files,
            "truncated": truncated
        }
    
    async def _arun(self, pattern: str, path: Optional[str] = None) -> dict:
        """
        异步执行glob搜索。
        
        注意：由于文件系统操作的本质限制，使用线程池是正确且高效的实现方式。
        这不会阻塞事件循环，是 Python 异步文件 I/O 的最佳实践。
        """
        import asyncio
        
        # 使用 asyncio.to_thread（Python 3.9+）
        # 这是官方推荐的文件 I/O 异步模式
        return await asyncio.to_thread(self._run_sync, pattern, path)
    
    # 为了向后兼容，保留 _run 方法
    def _run(self, pattern: str, path: Optional[str] = None) -> dict:
        """同步执行（为了兼容性）"""
        return self._run_sync(pattern, path)


def create_glob_tool(root_dir: str = "") -> GlobTool:
    """创建Glob工具实例"""
    tool = GlobTool()
    tool.root_dir = root_dir or os.getcwd()
    return tool