from typing import Literal

from pydantic import BaseModel


class DocumentWarningOut(BaseModel):
    code: Literal["no_text", "truncated"]
    message: str


class InterviewDocumentOut(BaseModel):
    kind: Literal["cover_letter", "resume", "portfolio"]
    text: str
    warnings: list[DocumentWarningOut]
