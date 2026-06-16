from pydantic import BaseModel
from typing import List, Optional


class CreativeFile(BaseModel):
    name: str
    size: int
    width: Optional[int] = None
    height: Optional[int] = None


class CreativesListResponse(BaseModel):
    count: int
    files: List[CreativeFile]
