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
    supabase_service_role_key: str | None = None


settings = Settings()
