from pathlib import Path

from pydantic_settings import BaseSettings

_ROOT = Path(__file__).parent.parent.parent  # api/app/config.py -> project root


class Settings(BaseSettings):
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    steam_api_key: str | None = None
    steam_openid_return_url: str | None = None

    lastfm_api_key: str | None = None
    youtube_api_key: str | None = None

    igdb_client_id: str | None = None
    igdb_client_secret: str | None = None

    upstash_redis_url: str
    upstash_redis_token: str

    session_secret: str = "dev-secret-change-in-production"
    frontend_url: str = "http://localhost:3000"
    environment: str = "development"

    class Config:
        env_file = str(_ROOT / ".env")
        extra = "ignore"


settings = Settings()
