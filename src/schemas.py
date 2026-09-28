from pydantic import BaseModel


class Eligibility(BaseModel):
    cnpj: str
    razao_social: str | None = None
    porte: str | None = None
    situacao_cadastral: str | None = None
    micro_ou_pequena: bool
    apta_indicativamente: bool
    motivo: str

