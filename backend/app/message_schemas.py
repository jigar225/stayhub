from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SendInput(StrictInput):
    text: str = Field(default="", max_length=4000)
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def content(self) -> "SendInput":
        self.text = self.text.strip()
        if not self.text and not self.attachment_ids:
            raise ValueError("Write a message or attach a photo.")
        if len(set(self.attachment_ids)) != len(self.attachment_ids):
            raise ValueError("Choose each attachment once.")
        return self


class AttachmentInput(StrictInput):
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    bytes: int = Field(ge=1, le=10 * 1024 * 1024)


class ReadInput(StrictInput):
    acknowledged_cursor: str = Field(max_length=12000)


class AttachmentOutput(BaseModel):
    id: UUID
    url: str
    expires_at: datetime
    width: int
    height: int


class MessageOutput(BaseModel):
    id: UUID
    sequence: int
    sender_id: UUID
    text: str
    created_at: datetime
    attachments: list[AttachmentOutput]


class MessagePage(BaseModel):
    items: list[MessageOutput]
    next_cursor: int | None
    acknowledged_cursor: str
    unread_count: int
    reservation_code: str
    listing_title: str


class SendOutput(BaseModel):
    message: MessageOutput


class InboxItem(BaseModel):
    reservation_id: UUID
    reservation_code: str
    listing_title: str
    counterpart_name: str
    unread_count: int
    last_message_preview: str
    updated_at: datetime


class InboxPage(BaseModel):
    items: list[InboxItem]
    next_cursor: UUID | None
    unread_count: int


class AttachmentIntent(BaseModel):
    attachment_id: UUID
    upload_url: str
    expires_at: datetime
