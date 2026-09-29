from pydantic import BaseModel, Field


class Eligibility(BaseModel):
    cnpj: str
    razao_social: str | None = None
    porte: str | None = None
    situacao_cadastral: str | None = None
    micro_ou_pequena: bool
    apta_indicativamente: bool
    motivo: str


class SavedSearchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    filters: dict = Field(default_factory=dict)


class SavedSearch(SavedSearchCreate):
    id: str
    created_at: str


