import re
from fastapi import HTTPException


def only_digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def validate_cnpj(value: str) -> str:
    cnpj = only_digits(value)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        raise HTTPException(400, "CNPJ inválido")
    weights = ((5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2), (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    for position, weight in enumerate(weights):
        total = sum(int(digit) * factor for digit, factor in zip(cnpj[:12 + position], weight))
        check = 11 - total % 11
        if check >= 10:
            check = 0
        if check != int(cnpj[12 + position]):
            raise HTTPException(400, "CNPJ inválido")
    return cnpj







