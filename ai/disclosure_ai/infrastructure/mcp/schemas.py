from typing import Literal

from pydantic import Field

from disclosure_ai.domain.models.base import Model


class FinancialQuery(Model):
    corp_code: str = Field(pattern=r"^[0-9]{8}$")
    bsns_year: int = Field(ge=2015, le=2100)
    reprt_code: Literal["11011", "11012", "11013", "11014"]
    fs_div: Literal["CFS", "OFS"]
