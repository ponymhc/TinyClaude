"""
LLM 模型工厂模块

使用统一配置 (config/config.py) 加载模型配置。

模型配置文件：config/models.yaml
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from langchain_litellm import ChatLiteLLM
from pydantic import BaseModel, Field

# 加载 .env 文件
_dotenv_path = Path(__file__).parent.parent.parent / "config" / ".env"
load_dotenv(_dotenv_path)


class LLMConfig(BaseModel):
    """LLM 模型配置"""
    provider: str = Field(description="provider name")
    model: str = Field(description="model name")
    api_key: str = Field(description="api key 环境变量名")
    base_url: Optional[str] = Field(default=None, description="base url 环境变量名")
    temperature: float = Field(default=0.7, description="temperature")
    streaming: bool = Field(default=True, description="streaming")
    reasoning_effort: Optional[str] = Field(default=None, description="reasoning effort")
    timeout: Optional[int] = Field(default=None, description="request timeout in seconds")


class LLMFactory:
    """LLM 模型工厂"""

    @classmethod
    def _load_config(cls) -> dict:
        """从统一配置加载模型配置"""
        from config.config import load_models_config
        models = load_models_config()
        # 遍历 model_dump() 的结果，过滤 None 值
        return {k: v for k, v in models.model_dump().items() if v is not None}

    @classmethod
    def create_llm(
        cls,
        model_name: str,
        **kwargs
    ) -> ChatLiteLLM:
        """
        创建 LLM 实例

        Args:
            model_name: 模型名称（如 qwen3_8b, deepseek_chat 等）
            **kwargs: 额外参数

        Returns:
            ChatLiteLLM 实例
        """
        raw_config = cls._load_config()

        if model_name not in raw_config:
            raise ValueError(f"模型 '{model_name}' 不存在于配置中")

        model_cfg = LLMConfig(**raw_config[model_name])

        llm_kwargs = {
            "model": model_cfg.provider + "/" + model_cfg.model,
            "temperature": model_cfg.temperature,
            "streaming": model_cfg.streaming,
        }

        # API Key
        if model_cfg.api_key:
            api_key = os.getenv(model_cfg.api_key)
            if not api_key:
                raise ValueError(f"环境变量 {model_cfg.api_key} 未设置")
            llm_kwargs["api_key"] = api_key

        # Base URL
        if model_cfg.base_url:
            base_url = os.getenv(model_cfg.base_url)
            if base_url:
                llm_kwargs["api_base"] = base_url

        # Reasoning Effort
        if model_cfg.reasoning_effort:
            llm_kwargs["reasoning_effort"] = model_cfg.reasoning_effort

        # Timeout
        if model_cfg.timeout:
            llm_kwargs["request_timeout"] = model_cfg.timeout

        # 合并额外参数
        llm_kwargs.update(kwargs)

        return ChatLiteLLM(**llm_kwargs)

    @classmethod
    def reload_config(cls) -> None:
        """重新加载配置（清除缓存）"""
        from config.config import reload_all_config
        reload_all_config()
