import os
from dataclasses import dataclass

@dataclass
class Settings:
    model_name: str
    temperature: float
    max_retries: int
    recursion_limit: int
    deepseek_api_key: str
    deepseek_base_url: str

def load_settings() -> Settings:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")

    if not api_key:
        raise RuntimeError(
            "未检测到 DEEPSEEK_API_KEY，请先在环境变量中配置 API Key。"
        )
    
    return Settings(
        model_name=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        temperature=float(os.getenv("TEMPERATURE", "0")),
        max_retries=int(os.getenv("MAX_RETRIES", "2")),
        recursion_limit=int(os.getenv("RECURSION_LIMIT", "20")),
        deepseek_api_key=api_key,
        deepseek_base_url="https://api.deepseek.com",
    )

settings = load_settings()