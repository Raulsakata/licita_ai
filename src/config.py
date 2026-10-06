from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    port: int = 3000
    frontend_origin: str = "http://localhost:5173"
    pncp_base_url: str = "https://pncp.gov.br/api/consulta/v1"
    open_cnpj_base_url: str = "https://api.opencnpj.org"
    ibge_base_url: str = "https://servicodados.ibge.gov.br/api/v1/localidades"
    database_url: str | None = None
    supabase_url: str | None = None
    supabase_secret_key: str | None = None
    supabase_service_role_key: str | None = None
    auth_secret: str | None = None
    admin_user: str | None = None
    admin_password: str | None = None
    admin_password_hash: str | None = None
    pncp_sync_secret: str | None = None
    external_api_max_retries: int = 2
    pncp_cache_ttl_seconds: int = 300
    ibge_cache_ttl_seconds: int = 86400
    open_cnpj_cache_ttl_seconds: int = 21600


settings = Settings()
