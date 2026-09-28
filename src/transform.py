from src.schemas import Eligibility


def assess_eligibility(company: dict) -> Eligibility:
    porte = str(company.get("porte") or "").strip().lower()
    situation = str(company.get("situacao_cadastral") or "").strip().lower()
    is_small = porte in {"01", "03", "me", "epp"} or "micro" in porte or "pequeno porte" in porte
    is_active = situation in {"02", "ativa", "ativo"} or "ativa" in situation
    approved = is_small and is_active
    if approved:
        reason = "Empresa ME/EPP e com situação cadastral ativa; elegibilidade é apenas indicativa."
    elif not is_small:
        reason = "A empresa não está classificada como microempresa ou empresa de pequeno porte."
    else:
        reason = "A situação cadastral não está ativa ou não foi informada pela fonte."
    return Eligibility(
        cnpj=company["cnpj"], razao_social=company.get("razao_social"), porte=company.get("porte"),
        situacao_cadastral=company.get("situacao_cadastral"), micro_ou_pequena=is_small,
        apta_indicativamente=approved, motivo=reason
    )


def normalize_opportunity(item: dict, municipality_code: str | None) -> dict | None:
    pncp_id = item.get("numeroControlePNCP")
    if not pncp_id:
        return None
    return {
        "pncp_id": str(pncp_id),
        "municipality_ibge_code": municipality_code or item.get("codigoMunicipioIbge"),
        "title": item.get("objetoCompra") or item.get("objetoContratacao"),
        "modality": item.get("modalidadeNome"),
        "publication_date": item.get("dataPublicacaoPncp"),
        "raw_data": item,
    }
