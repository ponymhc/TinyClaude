"""
Tools 模块 - 所有工具的统一入口

提供文件操作、搜索、浏览器、代码执行等工具。
每个工具都是 LangChain BaseTool 的实现。

使用方式：
    from tools import create_bash_tool, create_read_file_tool, create_write_file_tool

    bash = create_bash_tool(Path("/project"))
    read = create_read_file_tool()
    write = create_write_file_tool()
"""

# Bash 工具
from .bash import SafeBashTool, create_bash_tool

# Glob 工具
from .glob_tool import GlobTool, create_glob_tool

# Grep 工具
from .grep_tool import GrepTool, create_grep_tool

# 文件读取工具
from .read_file import (
    ReadFileState,
    FileReadInput,
    FileReadTool,
    FileReadOutput,
    _global_read_file_state,
    expand_path as read_expand_path,
    get_file_modification_time as read_get_file_modification_time,
)

# 文件编辑工具
from .edit_file import (
    FileEditTool,
    FileEditInput,
    FileEditOutput,
    find_actual_string,
    preserve_quote_style,
    get_patch_for_edit,
    validate_settings_file_edit,
    get_edit_tool,
)

# 文件写入工具
from .write_file import (
    FileWriteTool,
    FileWriteInput,
    FileWriteOutput,
    generate_unified_diff,
)

# 浏览器工具
from .browser import BrowserUseTool, create_browser_use_tool

# URL 抓取工具
from .fetch_url import FetchURLTool, create_fetch_url_tool

# Python Execute 工具
from .python_execute import PythonExecuteTool, create_python_execute_tool

# 网络搜索工具
from .tavily_search import TavilySearchTool, create_tavily_search_tool

# 技能工具
from .skill_tool import SkillTool, create_skill_tool

def create_read_file_tool() -> FileReadTool:
    """创建文件读取工具实例"""
    return FileReadTool()


def create_edit_file_tool() -> FileEditTool:
    """创建文件编辑工具实例"""
    return FileEditTool()


def create_write_file_tool() -> FileWriteTool:
    """创建文件写入工具实例"""
    return FileWriteTool()


def get_all_tools(root_dir: str = "", python_path: str = '~/miniconda3/base/python', **kwargs) -> dict:
    """
    返回所有可用的工具实例
    
    Args:
        root_dir: 工具的工作目录，默认为当前目录
        **kwargs: 传递给各个工具创建函数的额外参数
        
    Returns:
        字典，键为工具名称，值为工具实例
    """
    import os
    from pathlib import Path
    
    # 确保root_dir存在
    if not root_dir:
        root_dir = os.getcwd()
    
    # 创建所有工具实例
    tools_dict = {
        "bash": create_bash_tool(Path(root_dir)),
        "glob": create_glob_tool(root_dir),
        "grep": create_grep_tool(root_dir),
        "read": create_read_file_tool(),
        "edit": create_edit_file_tool(),
        "write": create_write_file_tool(),
        "browser": create_browser_use_tool(),
        "fetch_url": create_fetch_url_tool(),
        "python_execute": create_python_execute_tool(python_path=python_path, workdir=root_dir),
        "tavily_search": create_tavily_search_tool(),
    }
    
    # 如果启用了技能工具，则添加
    if kwargs.get("has_skill_tool", False):
        tools_dict["skill"] = create_skill_tool(Path(root_dir).parent)
    
    return tools_dict


def get_all_tools_list(root_dir: str = "", python_path: str = '~/miniconda3/base/python', **kwargs) -> list:
    """
    返回所有可用的工具实例列表
    
    Args:
        root_dir: 工具的工作目录，默认为当前目录
        python_path: python解释器路径
        **kwargs: 传递给各个工具创建函数的额外参数
        
    Returns:
        工具实例列表
    """
    tools_dict = get_all_tools(root_dir, python_path, **kwargs)
    return list(tools_dict.values())


def get_tool_names() -> list:
    """
    返回所有可用工具的名称列表
    
    Returns:
        工具名称列表
    """
    return [
        "bash",
        "glob", 
        "grep",
        "read",
        "edit",
        "write",
        "browser",
        "fetch_url",
        "python_execute",
        "tavily_search",
        "skill",
    ]


def get_tool_descriptions() -> dict:
    """
    返回所有工具的描述信息
    
    Returns:
        字典，键为工具名称，值为工具描述
    """
    return {
        "bash": "执行 shell 命令。工作目录限制在项目根目录。可用于文件操作、安装包、运行脚本等。",
        "glob": "使用glob模式搜索文件。支持通配符：*（任意字符），**（递归目录），?（单个字符），[abc]（字符集），{py,js,ts}（多个扩展名）。",
        "grep": "使用正则表达式搜索文件内容。支持多种输出模式：显示匹配行、显示匹配文件、计数匹配。支持上下文行、行号、大小写敏感、文件类型过滤和分页。",
        "read": "读取文件（文本、图像、PDF、notebook）。对于大文本文件使用offset/limit。",
        "edit": "编辑现有文件中的文本，支持替换、插入、删除操作。",
        "write": "创建新文件或完全覆盖现有文件。",
        "browser": "浏览器工具，用于网页浏览和交互。",
        "fetch_url": "URL抓取工具，用于获取网页内容。",
        "python_execute": "Python REPL工具，用于执行Python代码。",
        "tavily_search": "网络搜索工具，用于搜索互联网信息。",
        "skill": "调用预定义技能。技能是存储在 skills/ 目录下的提示模板，用于执行特定任务（如文档处理、内容生成等）。",
    }


# =============================================================================
# 导出列表
# =============================================================================

__all__ = [
    # Tool 类
    "SafeBashTool",
    "GlobTool",
    "GrepTool",
    "FileReadTool",
    "FileEditTool",
    "FileWriteTool",
    "BrowserUseTool",
    "FetchURLTool",
    "Utf8PythonReplTool",
    "TavilySearchTool",
    "SkillTool",

    # Input/Output 模型
    "GlobInput",
    "GlobOutput",
    "GrepInput",
    "GrepOutput",
    "FileReadInput",
    "FileReadOutput",
    "FileEditInput",
    "FileEditOutput",
    "FileWriteInput",
    "FileWriteOutput",
    "SkillInput",

    # 状态类
    "ReadFileState",
    "_global_read_file_state",

    # 创建函数
    "create_bash_tool",
    "create_glob_tool",
    "create_grep_tool",
    "create_read_file_tool",
    "create_edit_file_tool",
    "create_write_file_tool",
    "create_browser_use_tool",
    "create_fetch_url_tool",
    "create_python_execute_tool",
    "create_tavily_search_tool",
    "create_skill_tool",
    
    # 工具集合函数
    "get_all_tools",
    "get_all_tools_list",
    "get_tool_names",
    "get_tool_descriptions",

    # 辅助函数
    "find_actual_string",
    "preserve_quote_style",
    "get_patch_for_edit",
    "validate_settings_file_edit",
    "get_edit_tool",
    "generate_unified_diff",
    "read_expand_path",
    "read_get_file_modification_time",
]
