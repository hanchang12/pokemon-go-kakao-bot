from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


EventCategory = Literal[
    "event",
    "raid",
    "raid_hour",
    "spotlight_hour",
    "community_day",
    "research_day",
    "max_battle",
    "go_battle",
    "go_fest",
    "special_event",
]


class MessageRequest(BaseModel):
    room: str
    sender: str
    message: str


class CollectedEvent(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: EventCategory = "event"
    start_at: datetime
    end_at: datetime
    description: str = ""
    pokemon: list[str] = Field(default_factory=list)
    bonuses: list[str] = Field(default_factory=list)
    source_name: str = Field(min_length=1, max_length=100)
    source_url: HttpUrl
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_times(self):
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("event timestamps must include a timezone")
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be later than start_at")
        return self


class CollectedEvents(BaseModel):
    events: list[CollectedEvent] = Field(default_factory=list)
