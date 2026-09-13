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
    # 메신저봇R 앱의 내장 "디버깅 모드"/연결 테스트는 room·sender 없이 message만
    # 보내기도 한다. 그 요청도 422로 튕기지 않도록 기본값을 둔다.
    room: str = "unknown"
    sender: str = "unknown"
    message: str


EventRegion = Literal["kr", "overseas"]


class CollectedEvent(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: EventCategory = "event"
    region: EventRegion = "kr"
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
