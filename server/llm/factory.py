"""根据安全配置组装模型网关。"""

from server.config import Settings
from server.llm.gateway import DeepSeekChatGateway, FakeLLMGateway, LLMGateway


def create_llm_gateway(settings: Settings) -> LLMGateway:
    """创建选定 Provider；密钥只在适配器构造时解密。"""

    if settings.llm_provider == "fake":
        return FakeLLMGateway()
    if settings.deepseek_api_key is None:
        # Settings 已负责前置校验；这里保留防御式检查，避免未来绕过配置构造器。
        raise ValueError("DeepSeek API key is required")
    return DeepSeekChatGateway(
        api_key=settings.deepseek_api_key.get_secret_value(),
        model=settings.llm_model,
        api_base=settings.llm_api_base,
    )
