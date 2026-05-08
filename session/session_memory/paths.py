import os
from pathlib import Path
from typing import Optional


def get_session_memory_path(session_id: Optional[str] = None, sessions_dir: Optional[str] = None) -> str:
    """
    获取 Session Memory 文件路径
    
    格式：{sessions_dir}/{session_id}/session.md
    
    Args:
        session_id: 会话 ID
        sessions_dir: 会话存储目录（默认为 base_dir + storage.dirname）
        
    Returns:
        Session Memory 文件的绝对路径
    """
    if not session_id:
        raise ValueError("session_id is required for get_session_memory_path")
    
    if sessions_dir:
        session_dir = os.path.join(sessions_dir, session_id)
    else:
        # 回退到统一配置
        from config.config import get_session_storage_dir
        base_dir = get_session_storage_dir()
        session_dir = os.path.join(base_dir, session_id)
    
    return os.path.join(session_dir, "session.md")


def ensure_session_memory_dir(session_id: Optional[str] = None, sessions_dir: Optional[str] = None) -> str:
    """
    确保 Session Memory 目录存在
    
    Args:
        session_id: 会话 ID
        sessions_dir: 会话存储目录
        
    Returns:
        Session Memory 目录路径
    """
    if not session_id:
        raise ValueError("session_id is required for ensure_session_memory_dir")
    
    if sessions_dir:
        dir_path = os.path.join(sessions_dir, session_id)
    else:
        # 回退到统一配置
        from config.config import get_session_storage_dir
        base_dir = get_session_storage_dir()
        dir_path = os.path.join(base_dir, session_id)
    
    os.makedirs(dir_path, mode=0o700, exist_ok=True)
    return dir_path


def ensure_session_memory_file(session_id: Optional[str] = None, sessions_dir: Optional[str] = None) -> str:
    """
    确保 Session Memory 文件存在
    
    如果文件不存在，创建目录和文件。
    
    Args:
        session_id: 会话 ID
        sessions_dir: 会话存储目录
        
    Returns:
        Session Memory 文件路径
    """
    from .prompts import load_template
    
    if not session_id:
        raise ValueError("session_id is required for ensure_session_memory_file")
    
    # 确保目录存在
    dir_path = ensure_session_memory_dir(session_id, sessions_dir)
    
    # 获取文件路径
    file_path = get_session_memory_path(session_id, sessions_dir)
    
    # 如果文件不存在，创建并写入模板
    if not os.path.exists(file_path):
        template = load_template()
        with open(file_path, "w", encoding="utf-8") as f:
            os.chmod(file_path, 0o600)
            f.write(template)
    
    return file_path
