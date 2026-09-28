from src.extract import get_open_cnpj
from src.mappers import normalize_company
from src.transform import assess_eligibility


async def load_company_assessment(cnpj: str):
    company = normalize_company(await get_open_cnpj(cnpj), cnpj)
    return company, assess_eligibility(company)

