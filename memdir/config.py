"""
memdir 配置模块

使用统一配置 (config/config.py)。

导入方式:
    from config.config import get_automemory_config
    from memdir.config import get_config  # 向后兼容
"""

from config.config import (
    AutoMemoryConfig,
    get_automemory_config as _get_unified_config,
    reload_all_config as _reload_unified_config,
)

# 保持向后兼容的别名
def get_config() -> AutoMemoryConfig:
    """获取自动记忆配置（使用统一配置）"""
    return _get_unified_config()


def reload_config() -> AutoMemoryConfig:
    """重新加载配置"""
    _reload_unified_config()
    return _get_unified_config()


# =============================================================================
# 便捷访问函数（代理到统一配置）
# =============================================================================

def is_auto_memory_enabled() -> bool:
    """检查自动记忆功能是否启用"""
    return get_config().enabled


def get_auto_mem_dirname() -> str:
    """获取记忆子目录名称"""
    return get_config().dirname


def get_auto_mem_entrypoint_name() -> str:
    """获取入口点文件名"""
    return get_config().entrypoint_name


def get_max_entrypoint_lines() -> int:
    """获取入口点最大行数"""
    return get_config().max_entrypoint_lines


def get_max_entrypoint_bytes() -> int:
    """获取入口点最大字节数"""
    return get_config().max_entrypoint_bytes


def get_memory_base_dir() -> str:
    """获取记忆存储完整目录（base_dir + dirname）"""
    import os
    from pathlib import Path
    from config.config import load_unified_config
    config = load_unified_config()
    base = config.base_dir
    if base.startswith("~/"):
        base = os.path.join(Path.home(), base[2:])
    dirname = get_config().dirname
    return os.path.join(base, dirname)


def get_logs_subdir() -> str:
    """获取日志子目录名称"""
    return get_config().logs_subdir


def get_max_memory_files() -> int:
    """获取最大记忆文件数"""
    return get_config().max_memory_files


def get_max_frontmatter_lines() -> int:
    """获取 frontmatter 最大行数"""
    return get_config().max_frontmatter_lines


def get_exclude_patterns() -> list[str]:
    """获取扫描排除模式"""
    return get_config().exclude_patterns


def get_extraction_model() -> str:
    """获取记忆提取专用模型名称"""
    return get_config().extraction_model


def find_config_file() -> str | None:
    """
    查找配置文件路径。
    
    搜索顺序：
    1. MEMDIR_CONFIG_PATH 环境变量
    2. ~/.config/memdir/config.json
    3. 项目目录下的 config/memdir.json
    4. ~/.memdir.json
    """
    import os
    from pathlib import Path
    
    # 1. 环境变量
    env_path = os.environ.get("MEMDIR_CONFIG_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    
    # 2. ~/.config/memdir/config.json
    config_dir = Path.home() / ".config" / "memdir"
    config_file = config_dir / "config.json"
    if config_file.exists():
        return str(config_file)
    
    # 3. 项目目录
    project_config = Path(__file__).parent.parent / "config" / "memdir.json"
    if project_config.exists():
        return str(project_config)
    
    # 4. ~/.memdir.json
    home_config = Path.home() / ".memdir.json"
    if home_config.exists():
        return str(home_config)
    
    return None


def get_config_paths() -> list[str]:
    """获取所有可能的配置文件路径列表"""
    import os
    from pathlib import Path
    
    paths = []
    
    # 环境变量
    env_path = os.environ.get("MEMDIR_CONFIG_PATH")
    if env_path:
        paths.append(env_path)
    
    # ~/.config/memdir/config.json
    paths.append(str(Path.home() / ".config" / "memdir" / "config.json"))
    
    # 项目目录
    paths.append(str(Path(__file__).parent.parent / "config" / "memdir.json"))
    
    # ~/.memdir.json
    paths.append(str(Path.home() / ".memdir.json"))
    
    return paths
