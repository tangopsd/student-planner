"""Desk API: calendar import, deadlines, profile, and versioned plans."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from planning.gemini_plan import GeminiError, plan_week
from calendar_io import (
    MAX_BYTES,
    CalendarError,
    classify_title,
    course_from_title,
    fetch_ics,
    items_from_ical,
    normalize_instant,
)
from ical_parser import LOCAL_TZ
from models import Block, Item, ItemCreate, ItemPatch, Plan, PlanIn, Profile, ProfileIn
from paths import SAMPLE_ICS_PATH, STATE_PATH
from store import Store, StoreError
from weeks import group_items


class ImportResult(BaseModel):
    created: int
    updated: int
    parsed: int
    items: list[Item]


class WeekOut(BaseModel):
    week_start: str
    week_end: str
    label: str
    relation: Literal["past", "current", "upcoming"]
    items: list[Item]


class WeeksResponse(BaseModel):
    weeks: list[WeekOut]


class GeminiPlanIn(BaseModel):
    request: str
    week_start: str | None = None


class GeminiPlanOut(BaseModel):
    week_start: str
    plan: Plan | None = None
    valid: bool
    errors: list[str]
    attempts: int
    message: str


def create_app(state_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="Desk", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.store = Store(state_path or STATE_PATH)

    @app.get("/")
    def root() -> dict:
        return {"service": "desk", "health": "/api/health"}

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/profile", response_model=Profile)
    def get_profile(store: Store = Depends(get_store)) -> Profile:
        return store.profile()

    @app.put("/api/profile", response_model=Profile)
    def put_profile(body: ProfileIn, store: Store = Depends(get_store)) -> Profile:
        try:
            return store.set_profile(body)
        except StoreError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/items", response_model=list[Item])
    def list_items(store: Store = Depends(get_store)) -> list[Item]:
        return store.items()

    @app.post("/api/items", response_model=Item, status_code=201)
    def post_item(body: ItemCreate, store: Store = Depends(get_store)) -> Item:
        try:
            due = normalize_instant(body.due_or_start)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        item = Item(
            id=str(uuid4()),
            title=body.title,
            course=body.course or course_from_title(body.title),
            type=body.type,
            due_or_start=due,
            source="manual",
            estimated_effort_hours=body.estimated_effort_hours,
            locked=body.type == "exam",
            status="open",
            description=body.description,
        )
        try:
            return store.add_item(item)
        except StoreError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.patch("/api/items/{item_id:path}", response_model=Item)
    def patch_item(
        item_id: str,
        body: ItemPatch,
        store: Store = Depends(get_store),
    ) -> Item:
        changes = item_changes(body)
        try:
            updated = store.update_item(item_id, changes)
        except StoreError as exc:
            raise HTTPException(400, str(exc)) from exc
        if updated is None:
            raise HTTPException(404, "No deadline with that id")
        return updated

    @app.delete("/api/items/{item_id:path}", status_code=204)
    def delete_item(item_id: str, store: Store = Depends(get_store)) -> None:
        try:
            removed = store.delete_item(item_id)
        except StoreError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not removed:
            raise HTTPException(404, "No deadline with that id")

    @app.get("/api/weeks", response_model=WeeksResponse)
    def get_weeks(store: Store = Depends(get_store)) -> WeeksResponse:
        rows = [item.model_dump(mode="json") for item in store.items()]
        return WeeksResponse.model_validate({"weeks": group_items(rows)})

    @app.post("/api/calendar", response_model=ImportResult)
    async def import_calendar(
        request: Request,
        store: Store = Depends(get_store),
    ) -> ImportResult:
        raw = await read_feed(request)
        return import_raw(raw, store)

    @app.post("/api/calendar/sample", response_model=ImportResult)
    def import_sample(store: Store = Depends(get_store)) -> ImportResult:
        if not SAMPLE_ICS_PATH.is_file():
            raise HTTPException(500, "Sample calendar is missing")
        raw = SAMPLE_ICS_PATH.read_text(encoding="utf-8")
        return import_raw(raw, store)

    @app.get("/api/classify")
    def classify(title: str = "") -> dict:
        return classify_title(title)

    @app.get("/api/plans", response_model=list[Plan])
    def list_plans(
        week_start: str | None = None,
        store: Store = Depends(get_store),
    ) -> list[Plan]:
        if week_start is not None:
            week_start = require_monday(week_start)
        return store.plans(week_start)

    @app.post("/api/plans", response_model=Plan)
    def post_plan(body: PlanIn, store: Store = Depends(get_store)) -> Plan:
        week = require_monday(body.week_start)
        blocks = [build_block(raw) for raw in body.blocks]
        seen: set[str] = set()
        for block in blocks:
            if block.id in seen:
                raise HTTPException(400, "Two blocks share an id")
            seen.add(block.id)
        try:
            return store.add_plan(
                week,
                blocks,
                body.summary,
                datetime.now(LOCAL_TZ).isoformat(),
            )
        except StoreError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/plan/gemini", response_model=GeminiPlanOut)
    def post_gemini_plan(
        body: GeminiPlanIn,
        store: Store = Depends(get_store),
    ) -> dict:
        text = body.request.strip()
        if not text:
            raise HTTPException(400, "Say what you want planned")
        if len(text) > 4000:
            raise HTTPException(400, "That request is too long")
        week = require_monday(body.week_start) if body.week_start else None
        try:
            return plan_week(store, text, week)
        except GeminiError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    return app


def get_store(request: Request) -> Store:
    return request.app.state.store


def require_monday(value: str) -> str:
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, "Week start must be YYYY-MM-DD") from exc
    if day.weekday() != 0:
        raise HTTPException(400, "Week start must be a Monday")
    return day.isoformat()


def build_block(raw) -> Block:
    try:
        start = normalize_instant(raw.start)
        end = normalize_instant(raw.end)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if datetime.fromisoformat(end) <= datetime.fromisoformat(start):
        raise HTTPException(400, "Block end must be after the start")
    return Block(
        id=(raw.id or "").strip() or str(uuid4()),
        item_id=raw.item_id,
        start=start,
        end=end,
        kind=raw.kind,
        status=raw.status,
        reason=raw.reason,
    )


def item_changes(body: ItemPatch) -> dict:
    data = body.model_dump(exclude_unset=True)
    if "title" in data:
        title = (data["title"] or "").strip()
        if not title:
            raise HTTPException(400, "Title is required")
        data["title"] = title
    if "course" in data and isinstance(data["course"], str):
        data["course"] = data["course"].strip() or None
    if "description" in data and isinstance(data["description"], str):
        data["description"] = data["description"].strip()
    if "due_or_start" in data and data["due_or_start"] is not None:
        try:
            data["due_or_start"] = normalize_instant(data["due_or_start"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return data


def import_raw(raw: str, store: Store) -> ImportResult:
    try:
        items = items_from_ical(raw)
        result = store.merge_feed_items(items)
    except CalendarError as exc:
        raise HTTPException(400, str(exc)) from exc
    except StoreError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ImportResult.model_validate(result)


async def read_feed(request: Request) -> str:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(400, "Send a JSON body with a url") from exc
        if not isinstance(body, dict) or not str(body.get("url") or "").strip():
            raise HTTPException(400, "Send a JSON body with a url")
        try:
            return fetch_ics(str(body["url"]))
        except CalendarError as exc:
            raise HTTPException(400, str(exc)) from exc
    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        if upload is not None and hasattr(upload, "read"):
            data = await upload.read()
            if len(data) > MAX_BYTES:
                raise HTTPException(400, "That file is too large")
            return data.decode("utf-8-sig", errors="replace")
        url = form.get("url")
        if isinstance(url, str) and url.strip():
            try:
                return fetch_ics(url)
            except CalendarError as exc:
                raise HTTPException(400, str(exc)) from exc
        raise HTTPException(400, "Upload a .ics file or send a feed url")
    raise HTTPException(
        status_code=415,
        detail="Send JSON with a url, or upload a .ics file",
    )


app = create_app()
