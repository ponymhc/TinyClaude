"""
Grep Tool - 使用正则表达式搜索文件内容
参考TypeScript版本实现，使用LangChain框架
"""

import os
import re
import time
from pathlib import Path
from typing import Optional, Type, List, Dict, Any, Union, Tuple, ClassVar
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
import mimetypes
import fnmatch


class GrepInput(BaseModel):
    """Grep工具输入参数"""
    pattern: str = Field(description="要搜索的正则表达式模式")
    path: Optional[str] = Field(
        default=None,
        description="要搜索的文件或目录（rg PATH）。默认为当前工作目录。"
    )
    glob: Optional[str] = Field(
        default=None,
        description="过滤文件的glob模式（例如：'*.js', '*.{ts,tsx}'）- 映射到rg --glob"
    )
    output_mode: Optional[str] = Field(
        default="files_with_matches",
        description="输出模式：'content'显示匹配行（支持-A/-B/-C上下文，-n行号，head_limit），"
                   "'files_with_matches'显示文件路径（支持head_limit），"
                   "'count'显示匹配计数（支持head_limit）。默认为'files_with_matches'。"
    )
    context_before: Optional[int] = Field(
        default=None,
        alias="-B",
        description="每行匹配前显示的行数（rg -B）。需要output_mode: 'content'，否则忽略。"
    )
    context_after: Optional[int] = Field(
        default=None,
        alias="-A",
        description="每行匹配后显示的行数（rg -A）。需要output_mode: 'content'，否则忽略。"
    )
    context: Optional[int] = Field(
        default=None,
        description="每行匹配前后显示的行数（rg -C）。需要output_mode: 'content'，否则忽略。"
    )
    show_line_numbers: Optional[bool] = Field(
        default=True,
        alias="-n",
        description="在输出中显示行号（rg -n）。需要output_mode: 'content'，否则忽略。默认True。"
    )
    case_insensitive: Optional[bool] = Field(
        default=False,
        alias="-i",
        description="不区分大小写搜索（rg -i）"
    )
    type: Optional[str] = Field(
        default=None,
        description="要搜索的文件类型（rg --type）。常见类型：js, py, rust, go, java等。"
    )
    head_limit: Optional[int] = Field(
        default=250,
        description="限制输出到前N行/条目，相当于'| head -N'。适用于所有输出模式："
                   "content（限制输出行数），files_with_matches（限制文件路径），"
                   "count（限制计数条目）。未指定时默认为250。传递0表示无限制（谨慎使用）。"
    )
    offset: Optional[int] = Field(
        default=0,
        description="在应用head_limit之前跳过前N行/条目，相当于'| tail -n +N | head -N'。"
                   "适用于所有输出模式。默认为0。"
    )
    multiline: Optional[bool] = Field(
        default=False,
        description="启用多行模式，其中.匹配换行符，模式可以跨行（rg -U --multiline-dotall）。默认：false。"
    )


class GrepOutput(BaseModel):
    """Grep工具输出结果"""
    mode: Optional[str] = None  # 'content', 'files_with_matches', 'count'
    num_files: int
    filenames: List[str]
    content: Optional[str] = None
    num_lines: Optional[int] = None  # 用于content模式
    num_matches: Optional[int] = None  # 用于count模式
    applied_limit: Optional[int] = None  # 应用的限制（如果有）
    applied_offset: Optional[int] = None  # 应用的偏移量


class GrepTool(BaseTool):
    """
    Grep工具 - 使用正则表达式搜索文件内容
    
    支持多种输出模式和搜索选项，参考TypeScript版本的ripgrep功能。
    """
    
    name: str = "Grep"
    description: str = (
        "使用正则表达式搜索文件内容。支持多种输出模式："
        "显示匹配行、显示匹配文件、计数匹配。"
        "支持上下文行、行号、大小写敏感、文件类型过滤和分页。"
    )
    args_schema: Type[BaseModel] = GrepInput
    
    # 配置参数
    root_dir: str = ""  # 根目录，通常在创建工具时设置
    max_file_size: int = 10 * 1024 * 1024  # 10MB最大文件大小
    default_head_limit: int = 250  # 默认头部限制，与TypeScript版本一致
    
    # 要排除的版本控制系统目录（避免噪声）
    VCS_DIRECTORIES_TO_EXCLUDE: ClassVar[List[str]] = ['.git', '.svn', '.hg', '.bzr', '.jj', '.sl']
    
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
    
    def _validate_path(self, search_path: str) -> Tuple[bool, Optional[str]]:
        """验证路径是否存在"""
        try:
            if not os.path.exists(search_path):
                cwd = self.root_dir or os.getcwd()
                suggestion = ""
                # 尝试在cwd下找到相似路径
                for root, dirs, files in os.walk(cwd):
                    for item in dirs + files:
                        if search_path.lower() in item.lower() or item.lower() in search_path.lower():
                            rel_item = os.path.relpath(os.path.join(root, item), cwd)
                            suggestion = f" 是否指的是 {rel_item}?"
                            break
                    if suggestion:
                        break
                
                return False, f"路径不存在: {search_path}. 当前工作目录: {cwd}.{suggestion}"
            
            return True, None
        except Exception as e:
            return False, f"路径验证错误: {str(e)}"
    
    def _is_text_file(self, file_path: str) -> bool:
        """检查文件是否为文本文件"""
        try:
            # 检查文件大小
            if os.path.getsize(file_path) > self.max_file_size:
                return False
            
            # 检查MIME类型
            mime_type, _ = mimetypes.guess_type(file_path)
            if mime_type and mime_type.startswith('text/'):
                return True
            
            # 检查常见文本文件扩展名
            text_extensions = {'.txt', '.py', '.js', '.ts', '.java', '.c', '.cpp', 
                              '.h', '.hpp', '.md', '.json', '.xml', '.html', '.css',
                              '.yml', '.yaml', '.toml', '.ini', '.cfg', '.conf',
                              '.sh', '.bash', '.zsh', '.ps1', '.bat', '.cmd',
                              '.sql', '.r', '.R', '.m', '.matlab',
                              '.go', '.rs', '.rb', '.php', '.pl', '.pm',
                              '.swift', '.kt', '.scala', '.clj', '.lua', '.tcl'}
            
            return Path(file_path).suffix.lower() in text_extensions
        except:
            return False
    
    def _compile_regex(self, pattern: str, case_insensitive: bool, multiline: bool) -> re.Pattern:
        """编译正则表达式"""
        flags = 0
        if case_insensitive:
            flags |= re.IGNORECASE
        if multiline:
            flags |= re.MULTILINE | re.DOTALL
        
        try:
            return re.compile(pattern, flags)
        except re.error as e:
            # 如果正则表达式无效，尝试作为普通字符串搜索
            escaped_pattern = re.escape(pattern)
            return re.compile(escaped_pattern, flags)
    
    def _search_in_file(self, file_path: str, regex: re.Pattern, 
                       context_before: Optional[int], context_after: Optional[int],
                       context: Optional[int], show_line_numbers: bool) -> List[str]:
        """在单个文件中搜索"""
        results = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            # 确定上下文行数
            before = context if context is not None else (context_before or 0)
            after = context if context is not None else (context_after or 0)
            
            for i, line in enumerate(lines):
                if regex.search(line):
                    # 计算上下文范围
                    start = max(0, i - before)
                    end = min(len(lines), i + after + 1)
                    
                    # 构建结果行
                    for j in range(start, end):
                        line_num = j + 1
                        line_content = lines[j].rstrip('\n')
                        
                        if show_line_numbers:
                            prefix = f"{file_path}:{line_num}:"
                        else:
                            prefix = f"{file_path}:"
                        
                        # 标记匹配行
                        if j == i:
                            results.append(f"{prefix}{line_content}")
                        else:
                            results.append(f"{prefix}{line_content}")
            
            return results
        
        except Exception as e:
            # 如果无法读取文件，跳过
            return []
    
    def _apply_head_limit(self, items: List[Any], limit: Optional[int], offset: int = 0) -> Dict[str, Any]:
        """应用头部限制和偏移量"""
        # 与TypeScript版本逻辑一致：0表示无限制
        if limit == 0:
            sliced = items[offset:]
            return {
                "items": sliced,
                "applied_limit": None,
                "applied_offset": offset if offset > 0 else None
            }
        
        effective_limit = limit or self.default_head_limit
        sliced = items[offset:offset + effective_limit]
        was_truncated = len(items) - offset > effective_limit
        
        return {
            "items": sliced,
            "applied_limit": effective_limit if was_truncated else None,
            "applied_offset": offset if offset > 0 else None
        }
    
    def _run_sync(self, 
                  pattern: str,
                  path: Optional[str] = None,
                  glob: Optional[str] = None,
                  output_mode: str = "files_with_matches",
                  context_before: Optional[int] = None,
                  context_after: Optional[int] = None,
                  context: Optional[int] = None,
                  show_line_numbers: bool = True,
                  case_insensitive: bool = False,
                  type: Optional[str] = None,
                  head_limit: Optional[int] = 250,
                  offset: int = 0,
                  multiline: bool = False) -> dict:
        """同步执行grep搜索（将被异步调用）"""
        start_time = time.time()
        
        # 获取搜索路径
        search_path = self._get_search_path(path)
        
        # 验证路径
        is_valid, error_msg = self._validate_path(search_path)
        if not is_valid:
            return {
                "mode": output_mode,
                "num_files": 0,
                "filenames": [],
                "error": error_msg
            }
        
        # 编译正则表达式
        regex = self._compile_regex(pattern, case_insensitive, multiline)
        
        # 收集要搜索的文件
        files_to_search = []
        
        if os.path.isfile(search_path):
            # 搜索单个文件
            if self._is_text_file(search_path):
                files_to_search.append(search_path)
        else:
            # 搜索目录
            for root, dirs, files in os.walk(search_path):
                # 排除版本控制目录
                dirs[:] = [d for d in dirs if d not in self.VCS_DIRECTORIES_TO_EXCLUDE and not d.startswith('.')]
                
                for file in files:
                    file_path = os.path.join(root, file)
                    
                    # 检查文件类型
                    if not self._is_text_file(file_path):
                        continue
                    
                    # 检查glob模式
                    if glob:
                        # 简单的glob模式匹配
                        try:
                            rel_path = os.path.relpath(file_path, search_path)
                            if not fnmatch.fnmatch(rel_path, glob):
                                continue
                        except:
                            continue
                    
                    # 检查文件类型过滤
                    if type:
                        # 简单的文件类型检查
                        file_ext = Path(file_path).suffix.lower()
                        type_map = {
                            'py': '.py',
                            'js': '.js',
                            'ts': '.ts',
                            'java': '.java',
                            'c': '.c',
                            'cpp': '.cpp',
                            'go': '.go',
                            'rs': '.rs',
                            'rb': '.rb',
                            'php': '.php',
                        }
                        
                        if type in type_map and file_ext != type_map[type]:
                            continue
                    
                    files_to_search.append(file_path)
        
        # 根据输出模式执行搜索
        if output_mode == "content":
            # 收集匹配行
            all_matches = []
            matched_files = set()
            
            for file_path in files_to_search:
                matches = self._search_in_file(
                    file_path, regex, context_before, context_after, 
                    context, show_line_numbers
                )
                
                if matches:
                    all_matches.extend(matches)
                    matched_files.add(file_path)
            
            # 应用头部限制
            limit_result = self._apply_head_limit(all_matches, head_limit, offset)
            
            # 转换为相对路径
            relative_matches = []
            for match in limit_result["items"]:
                # 匹配格式：file:line:content 或 file:content
                parts = match.split(':', 1)
                if len(parts) == 2:
                    file_part, rest = parts
                    try:
                        rel_file = os.path.relpath(file_part, self.root_dir or os.getcwd())
                        relative_matches.append(f"{rel_file}:{rest}")
                    except:
                        relative_matches.append(match)
                else:
                    relative_matches.append(match)
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            return {
                "mode": "content",
                "num_files": len(matched_files),
                "filenames": [os.path.relpath(f, self.root_dir or os.getcwd()) for f in matched_files],
                "content": "\n".join(relative_matches),
                "num_lines": len(relative_matches),
                "applied_limit": limit_result["applied_limit"],
                "applied_offset": limit_result["applied_offset"],
                "duration_ms": duration_ms
            }
        
        elif output_mode == "count":
            # 计数模式
            file_counts = []
            total_matches = 0
            
            for file_path in files_to_search:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    matches = list(regex.finditer(content))
                    match_count = len(matches)
                    
                    if match_count > 0:
                        file_counts.append(f"{file_path}:{match_count}")
                        total_matches += match_count
                
                except:
                    continue
            
            # 应用头部限制
            limit_result = self._apply_head_limit(file_counts, head_limit, offset)
            
            # 转换为相对路径
            relative_counts = []
            for count_line in limit_result["items"]:
                file_part, count_part = count_line.rsplit(':', 1)
                try:
                    rel_file = os.path.relpath(file_part, self.root_dir or os.getcwd())
                    relative_counts.append(f"{rel_file}:{count_part}")
                except:
                    relative_counts.append(count_line)
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            return {
                "mode": "count",
                "num_files": len(limit_result["items"]),
                "filenames": [],
                "content": "\n".join(relative_counts),
                "num_matches": total_matches,
                "applied_limit": limit_result["applied_limit"],
                "applied_offset": limit_result["applied_offset"],
                "duration_ms": duration_ms
            }
        
        else:  # files_with_matches 模式
            # 查找包含匹配的文件
            matched_files = []
            
            for file_path in files_to_search:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    if regex.search(content):
                        matched_files.append(file_path)
                
                except:
                    continue
            
            # 按修改时间排序（降序）
            try:
                matched_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            except:
                # 如果无法获取修改时间，按文件名排序
                matched_files.sort()
            
            # 应用头部限制
            limit_result = self._apply_head_limit(matched_files, head_limit, offset)
            
            # 转换为相对路径
            relative_files = []
            for file_path in limit_result["items"]:
                try:
                    rel_file = os.path.relpath(file_path, self.root_dir or os.getcwd())
                    relative_files.append(rel_file)
                except:
                    relative_files.append(file_path)
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            return {
                "mode": "files_with_matches",
                "num_files": len(relative_files),
                "filenames": relative_files,
                "applied_limit": limit_result["applied_limit"],
                "applied_offset": limit_result["applied_offset"],
                "duration_ms": duration_ms
            }
    
    # 为了向后兼容，保留 _run 方法
    def _run(self, **kwargs) -> dict:
        """同步执行（为了兼容性）"""
        return self._run_sync(**kwargs)
    
    async def _arun(self, **kwargs) -> dict:
        """
        异步执行grep搜索。
        
        注意：由于文件系统操作的本质限制，使用线程池是正确且高效的实现方式。
        这不会阻塞事件循环，是 Python 异步文件 I/O 的最佳实践。
        """
        import asyncio
        
        # 使用 asyncio.to_thread（Python 3.9+）
        # 这是官方推荐的文件 I/O 异步模式
        return await asyncio.to_thread(self._run_sync, **kwargs)


def create_grep_tool(root_dir: str = "") -> GrepTool:
    """创建Grep工具实例"""
    tool = GrepTool()
    tool.root_dir = root_dir or os.getcwd()
    return tool