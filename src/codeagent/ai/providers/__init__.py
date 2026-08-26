"""模型供应商包:每 provider 一个文件。"""

from . import deepseek, fake, glm, kimi, minimax, openai, qwen
from .all import BUILTIN_PROVIDERS, PROVIDER_CONFIGS, PROVIDERS
from .base import ProviderDefinition, ProviderFactory
from .fake import FakeClient

__all__ = [
    "BUILTIN_PROVIDERS",
    "FakeClient",
    "PROVIDER_CONFIGS",
    "PROVIDERS",
    "ProviderDefinition",
    "ProviderFactory",
    "deepseek",
    "fake",
    "glm",
    "kimi",
    "minimax",
    "openai",
    "qwen",
]
