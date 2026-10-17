"""Single-file JSON persistence for the planner."""

from __future__ import annotations

import json
import threading
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from models import (
    Block,
    ChangeLogEntry,
    Commitment,
    Item,
    Plan,
    Profile,
    ProfileIn,
    State,
    UndoEntry,
    WakingHours,
)


class StoreError(Exception):
    """A write the caller can correct."""


MAX_ITEMS = 5000
UNDO_LIMIT = 20


def _validation_message(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        message = str(err.get("msg", "Invalid value"))
        prefix = "Value error, "
        if message.startswith(prefix):
            message = message[len(prefix) :]
        parts.append(message)
    return "; ".join(parts) or "Invalid value"


def default_state() -> State:
    return State(
        profile=Profile(
            waking_hours=WakingHours(wake="08:00", sleep="23:30"),
            fixed_commitments=[],
            preferred_study_windows=[],
            daily_capacity_hours=4,
        ),
        items=[],
        plans=[],
    )


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._state = self._load()

    def _load(self) -> State:
        if not self.path.exists():
            state = default_state()
            self._write(state)
            return state
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return State.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(f"Could not read planner state at {self.path}: {exc}") from exc

    def _write(self, state: State) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state.model_dump(mode="json"), indent=2) + "\n"
        temporary = self.path.parent / f"{self.path.name}.tmp"
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(self.path)

    def _persist(self) -> None:
        self._write(self._state)

    def profile(self) -> Profile:
        with self._lock:
            return self._state.profile.model_copy(deep=True)

    def set_profile(self, incoming: ProfileIn) -> Profile:
        seen: set[str] = set()
        commitments: list[Commitment] = []
        for item in incoming.fixed_commitments:
            commitment_id = (item.id or "").strip() or str(uuid4())
            if commitment_id in seen:
                raise StoreError("Two commitments share an id")
            seen.add(commitment_id)
            commitments.append(
                Commitment(
                    id=commitment_id,
                    title=item.title,
                    course=item.course,
                    day=item.day,
                    start=item.start,
                    end=item.end,
                )
            )
        profile = Profile(
            waking_hours=incoming.waking_hours,
            fixed_commitments=commitments,
            preferred_study_windows=list(incoming.preferred_study_windows),
            daily_capacity_hours=incoming.daily_capacity_hours,
        )
        with self._lock:
            self._state.profile = profile
            self._persist()
            return profile.model_copy(deep=True)

    def items(self) -> list[Item]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._state.items]

    def add_item(self, item: Item) -> Item:
        with self._lock:
            if any(existing.id == item.id for existing in self._state.items):
                raise StoreError("An item with that id already exists")
            if len(self._state.items) >= MAX_ITEMS:
                raise StoreError("The desk is full")
            stored = item.model_copy(update={"locked": True}) if item.type == "exam" else item
            self._state.items.append(stored)
            self._persist()
            return stored.model_copy(deep=True)

    def update_item(self, item_id: str, changes: dict) -> Item | None:
        with self._lock:
            index = self._index(item_id)
            if index is None:
                return None
            current = self._state.items[index]
            previous_type = current.type
            data = current.model_dump()
            data.update(changes)
            if data.get("type") == "exam":
                data["locked"] = True
            elif previous_type == "exam" and "locked" not in changes:
                data["locked"] = False
            updated = Item.model_validate(data)
            self._state.items[index] = updated
            self._persist()
            return updated.model_copy(deep=True)

    def delete_item(self, item_id: str) -> bool:
        with self._lock:
            linked = any(
                block.item_id == item_id
                for plan in self._state.plans
                for block in plan.blocks
            )
            if linked:
                raise StoreError("That deadline is still linked from a plan")
            index = self._index(item_id)
            if index is None:
                return False
            del self._state.items[index]
            self._persist()
            return True

    def merge_feed_items(self, incoming: list[Item]) -> dict:
        """Refresh feed fields. Effort and status on an existing id are kept."""
        with self._lock:
            items = [item.model_copy(deep=True) for item in self._state.items]
            by_id = {item.id: index for index, item in enumerate(items)}
            created = 0
            updated = 0
            touched: list[Item] = []
            for item in incoming:
                index = by_id.get(item.id)
                if index is None:
                    if len(items) >= MAX_ITEMS:
                        raise StoreError("The desk is full")
                    stored = item.model_copy(update={"locked": True}) if item.type == "exam" else item
                    items.append(stored)
                    by_id[stored.id] = len(items) - 1
                    created += 1
                    touched.append(stored.model_copy(deep=True))
                    continue
                current = items[index]
                was_exam = current.type == "exam"
                if item.type == "exam":
                    locked = True
                elif was_exam:
                    locked = False
                else:
                    locked = current.locked
                merged = current.model_copy(
                    update={
                        "title": item.title,
                        "course": item.course,
                        "type": item.type,
                        "due_or_start": item.due_or_start,
                        "description": item.description,
                        "locked": locked,
                        "source": "canvas",
                    }
                )
                items[index] = merged
                updated += 1
                touched.append(merged.model_copy(deep=True))
            self._state.items = items
            self._persist()
            return {
                "created": created,
                "updated": updated,
                "parsed": len(incoming),
                "items": touched,
            }

    def plans(self, week_start: str | None = None) -> list[Plan]:
        with self._lock:
            rows = self._state.plans
            if week_start is not None:
                rows = [plan for plan in rows if plan.week_start == week_start]
            ordered = sorted(rows, key=lambda plan: (plan.week_start, plan.version))
            return [plan.model_copy(deep=True) for plan in ordered]

    def add_plan(self, week_start: str, blocks: list[Block], summary: str, at: str) -> Plan:
        with self._lock:
            known = {item.id for item in self._state.items}
            for block in blocks:
                if block.item_id is not None and block.item_id not in known:
                    raise StoreError(f"No deadline with id {block.item_id}")
            versions = [
                plan.version for plan in self._state.plans if plan.week_start == week_start
            ]
            version = (max(versions) + 1) if versions else 1
            previous = max(versions) if versions else None
            plan = Plan(
                week_start=week_start,
                blocks=blocks,
                version=version,
                previous_version=previous,
                change_log=[ChangeLogEntry(at=at, summary=summary)],
            )
            self._state.plans.append(plan)
            self._persist()
            return plan.model_copy(deep=True)

    def latest_plan(self, week_start: str) -> Plan | None:
        with self._lock:
            plan = self._latest_for_week_locked(week_start)
            if plan is None:
                return None
            return plan.model_copy(deep=True)

    def add_manual_item(
        self,
        *,
        title: str,
        course: str | None,
        item_type: str,
        due_or_start: str,
        estimated_effort_hours: float | None,
        description: str,
        summary: str,
    ) -> Item:
        cleaned = title.strip()
        if not cleaned:
            raise StoreError("Title is required")
        try:
            item = Item(
                id=str(uuid4()),
                title=cleaned,
                course=course,
                type=item_type,
                due_or_start=due_or_start,
                source="manual",
                estimated_effort_hours=estimated_effort_hours,
                locked=item_type == "exam",
                status="open",
                description=description,
            )
        except ValidationError as exc:
            raise StoreError(_validation_message(exc)) from exc
        with self._lock:
            if len(self._state.items) >= MAX_ITEMS:
                raise StoreError("The desk is full")
            self._push_undo_locked(summary)
            self._state.items.append(item)
            self._persist()
            return item.model_copy(deep=True)

    def move_item(
        self,
        item_id: str,
        summary: str,
        due_or_start: str | None = None,
        estimated_effort_hours: float | None = None,
        update_effort: bool = False,
    ) -> Item:
        with self._lock:
            index = self._index(item_id)
            if index is None:
                raise StoreError(f"No deadline with id {item_id}")
            current = self._state.items[index]
            changes: dict = {}
            if due_or_start is not None and due_or_start != current.due_or_start:
                if current.locked:
                    raise StoreError("That deadline is locked and its time cannot move")
                changes["due_or_start"] = due_or_start
            if update_effort and estimated_effort_hours != current.estimated_effort_hours:
                if estimated_effort_hours is not None and not 0 <= estimated_effort_hours <= 100:
                    raise StoreError("Estimated effort must be between 0 and 100 hours")
                changes["estimated_effort_hours"] = estimated_effort_hours
            if not changes:
                return current.model_copy(deep=True)
            try:
                updated = Item.model_validate({**current.model_dump(), **changes})
            except ValidationError as exc:
                raise StoreError(_validation_message(exc)) from exc
            self._push_undo_locked(summary)
            self._state.items[index] = updated
            self._persist()
            return updated.model_copy(deep=True)

    def create_blocks(self, week_start: str, blocks: list[Block], summary: str, at: str) -> Plan:
        if not blocks:
            raise StoreError("Send at least one block")
        try:
            day = date.fromisoformat(week_start)
        except ValueError as exc:
            raise StoreError("Week start must be YYYY-MM-DD") from exc
        if day.weekday() != 0:
            raise StoreError("Week start must be a Monday")
        week_start = day.isoformat()
        with self._lock:
            known = {item.id for item in self._state.items}
            incoming_ids = [block.id for block in blocks]
            if any(not block_id for block_id in incoming_ids):
                raise StoreError("Every block needs an id")
            if len(incoming_ids) != len(set(incoming_ids)):
                raise StoreError("Two blocks share an id")
            for block in blocks:
                if block.item_id is not None and block.item_id not in known:
                    raise StoreError(f"No deadline with id {block.item_id}")
                if datetime.fromisoformat(block.end) <= datetime.fromisoformat(block.start):
                    raise StoreError(f"Block {block.id} ends before it starts")
            latest = self._latest_for_week_locked(week_start)
            if latest is not None:
                taken = {block.id for block in latest.blocks}.intersection(incoming_ids)
                if taken:
                    raise StoreError(f"Block id {sorted(taken)[0]} already exists")
            self._push_undo_locked(summary)
            if latest is None:
                plan = Plan(
                    week_start=week_start,
                    blocks=list(blocks),
                    version=1,
                    previous_version=None,
                    change_log=[ChangeLogEntry(at=at, summary=summary)],
                )
                self._state.plans.append(plan)
            else:
                latest.blocks.extend(blocks)
                latest.change_log.append(ChangeLogEntry(at=at, summary=summary))
                plan = latest
            self._persist()
            return plan.model_copy(deep=True)

    def move_block(self, block_id: str, start: str, end: str, summary: str, at: str) -> Block:
        if datetime.fromisoformat(end) <= datetime.fromisoformat(start):
            raise StoreError("Block end must be after the start")
        with self._lock:
            found = self._find_block_locked(block_id)
            if found is None:
                raise StoreError(f"No block with id {block_id}")
            plan, index = found
            self._push_undo_locked(summary)
            updated = plan.blocks[index].model_copy(update={"start": start, "end": end})
            plan.blocks[index] = updated
            plan.change_log.append(ChangeLogEntry(at=at, summary=summary))
            self._persist()
            return updated.model_copy(deep=True)

    def delete_block(self, block_id: str, summary: str, at: str) -> str:
        with self._lock:
            found = self._find_block_locked(block_id)
            if found is None:
                raise StoreError(f"No block with id {block_id}")
            plan, index = found
            self._push_undo_locked(summary)
            del plan.blocks[index]
            plan.change_log.append(ChangeLogEntry(at=at, summary=summary))
            self._persist()
            return block_id

    def set_constraint(
        self,
        summary: str,
        wake: str | None = None,
        sleep: str | None = None,
        daily_capacity_hours: float | None = None,
    ) -> Profile:
        with self._lock:
            current = self._state.profile
            next_wake = current.waking_hours.wake if wake is None else wake
            next_sleep = current.waking_hours.sleep if sleep is None else sleep
            next_capacity = (
                current.daily_capacity_hours
                if daily_capacity_hours is None
                else float(daily_capacity_hours)
            )
            try:
                hours = WakingHours(wake=next_wake, sleep=next_sleep)
            except ValidationError as exc:
                raise StoreError(_validation_message(exc)) from exc
            if not 0 <= next_capacity <= 18:
                raise StoreError("Daily capacity must be between 0 and 18 hours")
            unchanged = (
                hours.wake == current.waking_hours.wake
                and hours.sleep == current.waking_hours.sleep
                and next_capacity == current.daily_capacity_hours
            )
            if unchanged:
                return current.model_copy(deep=True)
            self._push_undo_locked(summary)
            updated = current.model_copy(
                update={"waking_hours": hours, "daily_capacity_hours": next_capacity}
            )
            self._state.profile = updated
            self._persist()
            return updated.model_copy(deep=True)

    def mark_item_progress(self, item_id: str, status: str, summary: str) -> Item:
        if status not in ("open", "done"):
            raise StoreError("Deadline status must be open or done")
        with self._lock:
            index = self._index(item_id)
            if index is None:
                raise StoreError(f"No deadline with id {item_id}")
            current = self._state.items[index]
            if current.status == status:
                return current.model_copy(deep=True)
            updated = current.model_copy(update={"status": status})
            self._push_undo_locked(summary)
            self._state.items[index] = updated
            self._persist()
            return updated.model_copy(deep=True)

    def mark_block_progress(self, block_id: str, status: str, summary: str, at: str) -> Block:
        if status not in ("scheduled", "done", "skipped"):
            raise StoreError("Block status must be scheduled, done, or skipped")
        with self._lock:
            found = self._find_block_locked(block_id)
            if found is None:
                raise StoreError(f"No block with id {block_id}")
            plan, index = found
            current = plan.blocks[index]
            if current.status == status:
                return current.model_copy(deep=True)
            updated = current.model_copy(update={"status": status})
            self._push_undo_locked(summary)
            plan.blocks[index] = updated
            plan.change_log.append(ChangeLogEntry(at=at, summary=summary))
            self._persist()
            return updated.model_copy(deep=True)

    def undo(self) -> str:
        with self._lock:
            if not self._state.undo_stack:
                raise StoreError("Nothing to undo")
            entry = self._state.undo_stack.pop()
            self._state.profile = entry.profile
            self._state.items = entry.items
            self._state.plans = entry.plans
            self._persist()
            return entry.summary

    def _push_undo_locked(self, summary: str) -> None:
        text = summary.strip() or "Planner change"
        self._state.undo_stack.append(
            UndoEntry(
                summary=text,
                profile=self._state.profile.model_copy(deep=True),
                items=[item.model_copy(deep=True) for item in self._state.items],
                plans=[plan.model_copy(deep=True) for plan in self._state.plans],
            )
        )
        if len(self._state.undo_stack) > UNDO_LIMIT:
            self._state.undo_stack = self._state.undo_stack[-UNDO_LIMIT:]

    def _latest_for_week_locked(self, week_start: str) -> Plan | None:
        rows = [plan for plan in self._state.plans if plan.week_start == week_start]
        if not rows:
            return None
        return max(rows, key=lambda plan: plan.version)

    def _find_block_locked(self, block_id: str) -> tuple[Plan, int] | None:
        latest: dict[str, Plan] = {}
        for plan in self._state.plans:
            current = latest.get(plan.week_start)
            if current is None or plan.version > current.version:
                latest[plan.week_start] = plan
        for plan in latest.values():
            for index, block in enumerate(plan.blocks):
                if block.id == block_id:
                    return plan, index
        return None

    def _index(self, item_id: str) -> int | None:
        for index, item in enumerate(self._state.items):
            if item.id == item_id:
                return index
        return None
