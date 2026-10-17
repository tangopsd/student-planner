"""Core planner records. Persisted as one JSON document."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ItemType = Literal["assignment", "quiz", "exam", "event", "personal"]
ItemSource = Literal["canvas", "voice", "manual"]
ItemStatus = Literal["open", "done"]
BlockKind = Literal["study", "fixed", "personal", "buffer"]
BlockStatus = Literal["scheduled", "done", "skipped"]

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _clock(value: str) -> str:
    if not _TIME.fullmatch(value):
        raise ValueError("Use 24-hour HH:MM")
    return value


class WakingHours(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wake: str
    sleep: str

    @field_validator("wake", "sleep")
    @classmethod
    def clock(cls, value: str) -> str:
        return _clock(value)

    @model_validator(mode="after")
    def sleep_after_wake(self) -> WakingHours:
        if self.sleep <= self.wake:
            raise ValueError("Sleep must be later than wake on the same day")
        return self


class StudyWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: Day
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def clock(cls, value: str) -> str:
        return _clock(value)

    @model_validator(mode="after")
    def end_after_start(self) -> StudyWindow:
        if self.end <= self.start:
            raise ValueError("Study window end must be after the start")
        return self


class CommitmentIn(BaseModel):
    """Fixed weekly commitment as sent by the client. Id is optional."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    course: str | None = None
    day: Day
    start: str
    end: str

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Commitment needs a title")
        return value

    @field_validator("course")
    @classmethod
    def blank_course(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("start", "end")
    @classmethod
    def clock(cls, value: str) -> str:
        return _clock(value)

    @model_validator(mode="after")
    def end_after_start(self) -> CommitmentIn:
        if self.end <= self.start:
            raise ValueError("Commitment end must be after the start")
        return self


class Commitment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    course: str | None = None
    day: Day
    start: str
    end: str


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    waking_hours: WakingHours
    fixed_commitments: list[CommitmentIn] = Field(default_factory=list, max_length=40)
    preferred_study_windows: list[StudyWindow] = Field(default_factory=list, max_length=21)
    daily_capacity_hours: float = Field(ge=0, le=18)


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    waking_hours: WakingHours
    fixed_commitments: list[Commitment]
    preferred_study_windows: list[StudyWindow]
    daily_capacity_hours: float = Field(ge=0, le=18)


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    course: str | None = None
    type: ItemType
    due_or_start: str
    source: ItemSource
    estimated_effort_hours: float | None = None
    locked: bool
    status: ItemStatus
    description: str = ""


class ItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    course: str | None = None
    type: ItemType
    due_or_start: str
    estimated_effort_hours: float | None = Field(default=None, ge=0, le=100)
    description: str = Field(default="", max_length=5000)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title is required")
        return value

    @field_validator("course")
    @classmethod
    def blank_course(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        return value.strip()


class ItemPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=300)
    course: str | None = None
    type: ItemType | None = None
    due_or_start: str | None = None
    estimated_effort_hours: float | None = Field(default=None, ge=0, le=100)
    locked: bool | None = None
    status: ItemStatus | None = None
    description: str | None = Field(default=None, max_length=5000)


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    item_id: str | None = None
    start: str
    end: str
    kind: BlockKind
    status: BlockStatus = "scheduled"
    reason: str = ""


class BlockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    item_id: str | None = None
    start: str
    end: str
    kind: BlockKind
    status: BlockStatus = "scheduled"
    reason: str = Field(default="", max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip()


class ChangeLogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: str
    summary: str


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_start: str
    blocks: list[Block]
    version: int
    previous_version: int | None = None
    change_log: list[ChangeLogEntry]


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_start: str
    blocks: list[BlockIn] = Field(default_factory=list, max_length=200)
    summary: str = Field(default="Updated the plan", max_length=500)

    @field_validator("summary")
    @classmethod
    def strip_summary(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A plan change needs a summary")
        return value


class State(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: Profile
    items: list[Item]
    plans: list[Plan]
