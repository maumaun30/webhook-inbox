from datetime import datetime, timezone

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Hook(SQLModel, table=True):
    __tablename__ = "hooks"

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True, max_length=64)
    method: str = Field(max_length=10)
    url: str
    headers: dict = Field(default_factory=dict, sa_column=Column(JSON))
    body: str = Field(default="", sa_column=Column(Text))
    body_is_base64: bool = False
    content_type: str | None = None
    ip: str | None = None
    signature_status: str = Field(default="unchecked", max_length=16)  # valid | invalid | unchecked
    received_at: datetime = Field(default_factory=_now, index=True)
