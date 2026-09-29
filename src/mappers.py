def pick(data: dict, *keys):
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return None


def normalize_company(data: dict, cnpj: str) -> dict:
    porte = pick(data, "porte_empresa", "porteEmpresa", "porte")
    situacao = pick(data, "situacao_cadastral", "situacaoCadastral")
    if isinstance(situacao, dict):
        situacao = pick(situacao, "descricao", "codigo")
    return {
        "cnpj": cnpj,
        "razao_social": pick(data, "razao_social", "razaoSocial", "nomeEmpresarial"),
        "nome_fantasia": pick(data, "nome_fantasia", "nomeFantasia"),
        "porte": porte,
        "situacao_cadastral": situacao,
        "cnae_principal": pick(data, "cnae_fiscal", "cnaePrincipal", "cnae_principal"),
        "raw_data": data,
    }

