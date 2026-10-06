from pydantic import BaseModel, Field


class Eligibility(BaseModel):
    cnpj: str
    razao_social: str | None = None
    porte: str | None = None
    situacao_cadastral: str | None = None
    natureza_juridica: str | None = None
    natureza_juridica_codigo: str | int | None = None
    micro_ou_pequena: bool
    apta_indicativamente: bool
    motivo: str
    rotulo: str = ""
    oportunidades: list[dict] = Field(default_factory=list)
    pncp_consulta_completa: bool = True


class CompanyLogin(BaseModel):
    cnpj: str
    senha: str = Field(min_length=1, max_length=128)


class AdminLogin(BaseModel):
    usuario: str = Field(min_length=1, max_length=128)
    senha: str = Field(min_length=1, max_length=128)


class CompanyCreate(BaseModel):
    cnpj: str
    senha: str = Field(min_length=8, max_length=128)
    razao_social: str | None = Field(default=None, max_length=200)
    porte: str | None = Field(default=None, max_length=40)


class CompanyUpdate(BaseModel):
    ativo: bool | None = None
    senha: str | None = Field(default=None, min_length=8, max_length=128)
    porte: str | None = Field(default=None, max_length=40)


class SavedSearchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    filters: dict = Field(default_factory=dict)


class SavedSearch(SavedSearchCreate):
    id: str
    created_at: str


