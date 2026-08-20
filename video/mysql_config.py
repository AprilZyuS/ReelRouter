import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# 本地运行时读取项目根目录的 .env；
# Docker 环境中没有该文件时，会直接读取容器环境变量。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class MySQLSettings:
    host: str
    port: int
    database: str
    user: str
    password: str


def load_mysql_settings() -> MySQLSettings:
    """读取并校验 MySQL 连接配置。"""

    required_names = [
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_DATABASE",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
    ]

    missing_names = [
        name for name in required_names
        if not os.getenv(name)
    ]
    if missing_names:
        raise RuntimeError(
            f"缺少 MySQL 配置：{', '.join(missing_names)}"
        )

    return MySQLSettings(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ["MYSQL_PORT"]),
        database=os.environ["MYSQL_DATABASE"],
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
    )