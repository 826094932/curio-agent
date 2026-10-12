from pathlib import Path
from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT / '.env', ROOT / 'backend' / '.env'),
        env_file_encoding='utf-8', extra='ignore',
    )
    mysql_dsn: str = ''
    deepseek_api_key: SecretStr = SecretStr('')
    deepseek_model: str = 'deepseek-flash'
    deepseek_base_url: str = 'https://api.deepseek.com'
    tavily_api_key: SecretStr = SecretStr('')
    web_search_timeout_seconds: int = Field(default=15, ge=1, le=30)
    web_search_cache_hours: int = Field(default=6, ge=1, le=168)
    web_search_max_calls: int = Field(default=2, ge=1, le=3)
    jwt_secret: SecretStr = SecretStr('')
    cookie_secure: bool = False
    cors_origins: list[str] = ['http://localhost:5173', 'http://127.0.0.1:5173']
    admin_emails: list[str] = []
    chroma_persist_directory: str = str(ROOT / 'data' / 'chroma_db')
    embedding_model: str = 'BAAI/bge-small-zh-v1.5'
    embedding_device: str = 'cpu'
    embedding_dimension: int = 512
    max_agent_steps: int = 10
    request_timeout: int = 120
    price_stale_hours: int = 24
    crawler_domains: list[str] = []

    @property
    def chroma_path(self):
        path = Path(self.chroma_persist_directory)
        return str(path if path.is_absolute() else ROOT / path)


settings = Settings()
