from langchain_deepseek import ChatDeepSeek
from langchain.agents import create_agent
from app.config import settings
from app.agent.prompts import SYSTEM_PROMPT
from app.errors import AppError


def create_model():
    """创建 DeepSeek 模型，密钥统一从 .env 读取。"""
    if not settings.deepseek_api_key.get_secret_value():
        raise AppError(503, 'MODEL_NOT_CONFIGURED', '缺少 DEEPSEEK_API_KEY')
    return ChatDeepSeek(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        api_base=settings.deepseek_base_url,
        temperature=0,
        max_tokens=4096,
        timeout=45,
        max_retries=1,
        # 当前模型默认开启思考；需求提取需要指定工具，因此显式关闭。
        extra_body={'thinking': {'type': 'disabled'}},
    )


def build_agent(tools):
    return create_agent(model=create_model(), tools=tools, system_prompt=SYSTEM_PROMPT)
