from langchain_openai import ChatOpenAI
from config import settings

llm = ChatOpenAI(
    model=settings.model_name,
    api_key=settings.deepseek_api_key,
    base_url=settings.deepseek_base_url,
    temperature=settings.temperature,
)