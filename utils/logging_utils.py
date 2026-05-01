"""
共享日志工具模块。

提供统一的日志记录器工厂，支持多模块写入同一日志文件。
使用方式：
    from utils.logging_utils import get_shared_logger

    # 默认路径：logs/default/app.log
    logger = get_shared_logger("MyModule")

    # 自定义路径
    logger = get_shared_logger("MyModule", log_dir="logs/custom", log_file="debug.log")

    # 会话级别日志：每个 session 单独一个文件
    logger = get_session_logger("extract_memories", session_id="abc-123")
    # 生成：logs/extract_memory/abc-123.log
"""

import logging
import os
from typing import Optional


# 默认日志配置
DEFAULT_LOG_DIR = "logs"
DEFAULT_LOG_FILE = "app.log"

# 已创建的 session logger 缓存，避免重复创建 handler
_session_loggers: dict = {}


def get_shared_logger(
    name: str,
    log_dir: Optional[str] = None,
    log_file: Optional[str] = None,
    level: int = logging.DEBUG,
) -> logging.Logger:
    """
    获取共享的日志记录器。

    Args:
        name: logger 名称（会作为 [name] 前缀出现在日志中）
        log_dir: 日志目录，默认使用 logs/default
        log_file: 日志文件名，默认使用 app.log
        level: 日志级别，默认 DEBUG

    Returns:
        配置好的 Logger 实例

    注意：
        - 同一 name 的 logger 只会配置一次 handler
        - 不同 name 的 logger 可以写入同一个文件（通过相同的 log_dir/log_file）
    """
    # 构建完整的日志路径
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    actual_log_dir = log_dir or os.path.join(base_dir, DEFAULT_LOG_DIR, "default")
    actual_log_file = log_file or DEFAULT_LOG_FILE

    os.makedirs(actual_log_dir, exist_ok=True)
    log_path = os.path.join(actual_log_dir, actual_log_file)

    # 获取或创建 logger
    logger = logging.getLogger(name)

    # 如果已有 handler，说明已经配置过，直接返回
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # 文件 handler
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter(
            '[%(asctime)s] [%(name)s] %(message)s',
            datefmt='%H:%M:%S'
        )
    )

    logger.addHandler(file_handler)

    return logger


def get_session_logger(
    name: str,
    session_id: str,
    base_log_dir: str = "logs",
    level: int = logging.DEBUG,
) -> logging.Logger:
    """
    获取会话级别的日志记录器，每个 session 单独一个文件。

    Args:
        name: logger 名称（会作为 [name] 前缀出现在日志中）
        session_id: 会话 ID，用于生成独立的日志文件
        base_log_dir: 日志基础目录，默认 logs
        level: 日志级别，默认 DEBUG

    Returns:
        配置好的 Logger 实例

    生成文件：{base_log_dir}/{name}/{session_id}.log
    例如：logs/extract_memory/session-abc-123.log
    """
    global _session_loggers

    # 构建缓存 key
    cache_key = f"{name}:{session_id}"

    # 已有则返回
    if cache_key in _session_loggers:
        return _session_loggers[cache_key]

    # 构建日志路径
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(base_dir, base_log_dir, name)
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{session_id}.log")

    # 创建 logger
    logger = logging.getLogger(f"{name}.{session_id}")
    logger.setLevel(level)
    logger.propagate = False  # 避免向上传播

    # 文件 handler
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter(
            '[%(asctime)s] %(message)s',
            datefmt='%H:%M:%S'
        )
    )

    logger.addHandler(file_handler)
    _session_loggers[cache_key] = logger

    return logger
