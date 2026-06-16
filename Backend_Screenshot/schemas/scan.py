from pydantic import BaseModel, field_validator
from typing import List


class ScanRequest(BaseModel):
    urls: List[str]
    device: str = "desktop"

    @field_validator("device")
    @classmethod
    def normalise_device(cls, v: str) -> str:
        return "mobile" if v.lower() == "mobile" else "desktop"
