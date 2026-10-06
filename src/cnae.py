import re
import unicodedata

STOPWORDS = {
    "de", "da", "do", "das", "dos", "e", "em", "para", "com", "por", "a", "o", "os", "as", "ao", "na", "no", "nas", "nos", "ou",
    "comercio", "comercial", "varejista", "atacadista", "varejo", "atacado", "servicos", "servico", "atividades", "atividade",
    "outras", "outros", "outro", "outra", "nao", "especificadas", "especificados", "especificada", "especificado", "anteriormente",
    "geral", "produtos", "produto", "exceto", "inclusive", "relacionados", "relacionadas", "demais", "similares", "tipo", "tipos",
    "uso", "sob", "contrato", "prestados", "prestacao", "empresas", "empresa", "principalmente", "quando", "bem", "bens", "mediante",
    "pessoas", "administracao", "apoio", "gestao", "especializado", "especializados", "especializada", "especializadas", "associados",
}
# Termos genéricos só valem em conjunto com outro termo para evitar falsos positivos.
WEAK = {
    "manutencao", "reparacao", "instalacao", "instalacoes", "aluguel", "locacao", "construcao", "obras", "fabricacao", "treinamento",
    "consultoria", "montagem", "equipamentos", "materiais", "material", "artigos", "pecas", "acessorios", "sistemas", "programas",
    "execucao", "edificios", "limpeza", "transporte", "industrial", "tecnica", "tecnicos", "tecnico", "profissionais", "publica", "publico",
}


def normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", stripped.lower())


def company_cnaes(raw_data: dict | None, fallback_code: str | None = None) -> list[dict]:
    raw = raw_data or {}
    entries = [{"codigo": str(item.get("codigo") or ""), "descricao": item.get("descricao") or ""} for item in raw.get("cnaes") or [] if isinstance(item, dict)]
    if not entries and raw.get("cnae_fiscal_descricao"):
        entries.append({"codigo": str(raw.get("cnae_fiscal") or fallback_code or ""), "descricao": raw["cnae_fiscal_descricao"]})
    return [entry for entry in entries if entry["descricao"]]


def keywords(cnaes: list[dict]) -> tuple[set[str], set[str]]:
    strong, weak = set(), set()
    for entry in cnaes:
        for token in normalize(entry["descricao"]).split():
            if token in STOPWORDS or len(token) < 3 or token.isdigit():
                continue
            (weak if token in WEAK else strong).add(token)
    return strong, weak


def _pattern(token: str) -> re.Pattern:
    stem = re.escape(token[:6]) + r"\w*" if len(token) >= 7 else re.escape(token) + r"(?:s|es)?"
    return re.compile(rf"\b{stem}\b")


def build_matcher(cnaes: list[dict]):
    strong, weak = keywords(cnaes)
    strong_patterns = {token: _pattern(token) for token in strong}
    weak_patterns = {token: _pattern(token) for token in weak}

    def match(text: str) -> list[str]:
        normalized = normalize(text)
        hits = [token for token, pattern in strong_patterns.items() if pattern.search(normalized)]
        weak_hits = [token for token, pattern in weak_patterns.items() if pattern.search(normalized)]
        if hits or len(weak_hits) >= 2:
            return sorted(hits + weak_hits)
        return []

    return match, sorted(strong | weak)
