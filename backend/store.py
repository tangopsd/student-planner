"""Single-file JSON persistence for the planner."""

from __future__ import annotations

import json
import threading
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
    WakingHours,
)


class StoreError(Exception):
    """A write the caller can correct."""


MAX_ITEMS = 5000


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

    def _index(self, item_id: str) -> int | None:
        for index, item in enumerate(self._state.items):
            if item.id == item_id:
                return index
        return None
