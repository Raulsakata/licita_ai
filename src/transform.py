from src.schemas import Eligibility


def assess_eligibility(company: dict) -> Eligibility:
    porte = str(company.get("porte") or "").strip().lower()
    situation = str(company.get("situacao_cadastral") or "").strip().lower()
    nature_code = str(company.get("natureza_juridica_codigo") or "").strip()
    nature_blocks_porte = nature_code[:1] in {"1", "3", "5"}
    is_small = (porte in {"01", "03", "me", "epp", "mei"} or "micro" in porte or "pequeno porte" in porte) and not nature_blocks_porte
    is_active = situation in {"02", "ativa", "ativo"} or "ativa" in situation
    approved = is_small and is_active
    if approved:
        reason = "Empresa ME/EPP e com situação cadastral ativa; elegibilidade é apenas indicativa."
    elif nature_blocks_porte:
        reason = "A natureza jurídica da empresa não admite enquadramento como ME/EPP."
    elif not is_small:
        reason = "A empresa não está classificada como microempresa ou empresa de pequeno porte."
    else:
        reason = "A situação cadastral não está ativa ou não foi informada pela fonte."
    return Eligibility(
        cnpj=company["cnpj"], razao_social=company.get("razao_social"), porte=company.get("porte"),
        situacao_cadastral=company.get("situacao_cadastral"),
        natureza_juridica=company.get("natureza_juridica"),
        natureza_juridica_codigo=company.get("natureza_juridica_codigo"),
        micro_ou_pequena=is_small,
        apta_indicativamente=approved, motivo=reason,
        rotulo="Apta" if approved else "Não Apta",
    )


def normalize_opportunity(item: dict, municipality_code: str | None) -> dict | None:
    pncp_id = item.get("numeroControlePNCP")
    if not pncp_id:
        return None
    unit = item.get("unidadeOrgao") or {}
    try:
        value = float(item.get("valorTotalEstimado") or 0)
    except (TypeError, ValueError):
        value = 0.0
    return {
        "pncp_id": str(pncp_id),
        "municipality_ibge_code": municipality_code or item.get("codigoMunicipioIbge") or unit.get("codigoIbge"),
        "uf": unit.get("ufSigla"),
        "estimated_value": value,
        "title": item.get("objetoCompra") or item.get("objetoContratacao"),
        "modality": item.get("modalidadeNome"),
        "publication_date": item.get("dataPublicacaoPncp"),
        "raw_data": item,
    }
