from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TestResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    test_name: str = Field(description="Standardized name of the laboratory test")
    value: str = Field(description="Reported result, including qualitative results")
    unit: str | None = Field(default=None, description="Unit reported by the laboratory")
    reference_range: str | None = Field(
        default=None, description="Reference range reported by the laboratory"
    )
    abnormality_flag: Literal["H", "L", "A"] | None = Field(
        default=None, description="High, low, or abnormal flag"
    )


class LabReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    age_years: int | None = Field(default=None, ge=0, le=150)
    sex: str | None = None
    referred_by: str | None = None
    registration_no: str | None = None
    report_date: str | None = Field(
        default=None, description="Single report or sample date in DD/MM/YYYY format"
    )
    test_results: list[TestResult] = Field(default_factory=list)