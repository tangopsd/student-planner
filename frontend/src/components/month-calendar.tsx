"use client";

import { useState, useSyncExternalStore } from "react";
import { PACIFIC } from "@/lib/format";
import type { Block, Item, ItemType, WeekPlan } from "@/lib/types";

type Mark = "exam" | "due" | "event";

type CalendarEntry = {
  id: string;
  date: string;
  minutes: number;
  time: string;
  title: string;
  mark: Mark;
};

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function subscribeToday(listener: () => void) {
  const id = window.setInterval(listener, 60_000);
  return () => window.clearInterval(id);
}

function pacificToday(): string {
  return pacificDate(new Date().toISOString());
}

function pacificDate(iso: string): string {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return "";
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: PACIFIC,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(instant);
}

function pacificMinutes(iso: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: PACIFIC,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(iso));
  const read = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value ?? "0";
  const hour = read("hour") === "24" ? 0 : Number(read("hour"));
  return hour * 60 + Number(read("minute"));
}

function compactTime(iso: string): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: PACIFIC,
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).formatToParts(new Date(iso));
  const read = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value ?? "";
  const minute = read("minute");
  const period = read("dayPeriod").toLowerCase().replace(/\./g, "");
  if (minute === "00") return `${read("hour")}${period}`;
  return `${read("hour")}:${minute}${period}`;
}

function markForType(type: ItemType): Mark {
  if (type === "exam") return "exam";
  if (type === "assignment" || type === "quiz") return "due";
  return "event";
}

function deadlineTitle(item: Item): string {
  const title = item.title.trim() || "Untitled";
  if ((item.type === "assignment" || item.type === "quiz") && !/\bdue\b/i.test(title)) {
    return `${title} due`;
  }
  return title;
}

function latestPlans(plans: WeekPlan[]): WeekPlan[] {
  const chosen = new Map<string, WeekPlan>();
  for (const plan of plans) {
    const current = chosen.get(plan.week_start);
    if (!current || plan.version > current.version) chosen.set(plan.week_start, plan);
  }
  return [...chosen.values()];
}

function calendarEntries(items: Item[], plans: WeekPlan[]): CalendarEntry[] {
  const rows: CalendarEntry[] = [];
  const itemDays = new Set<string>();
  for (const item of items) {
    const date = pacificDate(item.due_or_start);
    if (!date) continue;
    itemDays.add(`${item.id}:${date}`);
    rows.push({
      id: `item:${item.id}`,
      date,
      minutes: pacificMinutes(item.due_or_start),
      time: item.due_or_start && pacificMinutes(item.due_or_start) === 0 ? "" : compactTime(item.due_or_start),
      title: deadlineTitle(item),
      mark: markForType(item.type),
    });
  }
  const itemsById = new Map(items.map((item) => [item.id, item]));
  for (const plan of latestPlans(plans)) {
    for (const block of plan.blocks) {
      pushBlock(rows, block, itemsById, itemDays);
    }
  }
  return rows;
}

function pushBlock(
  rows: CalendarEntry[],
  block: Block,
  itemsById: Map<string, Item>,
  itemDays: Set<string>,
) {
  const date = pacificDate(block.start);
  if (!date) return;
  if (block.item_id && itemDays.has(`${block.item_id}:${date}`)) return;
  const linked = block.item_id ? itemsById.get(block.item_id) : undefined;
  rows.push({
    id: `block:${block.id}`,
    date,
    minutes: pacificMinutes(block.start),
      time: pacificMinutes(block.start) === 0 ? "" : compactTime(block.start),
    title: linked?.title?.trim() || block.reason?.trim() || "Scheduled",
    mark: linked ? markForType(linked.type) : block.kind === "study" ? "due" : "event",
  });
}

function shiftMonth(cursor: string, delta: number): string {
  const [year, month] = cursor.split("-").map(Number);
  const next = new Date(Date.UTC(year, month - 1 + delta, 1));
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${next.getUTCFullYear()}-${pad(next.getUTCMonth() + 1)}`;
}

function monthLabel(cursor: string): string {
  const [year, month] = cursor.split("-").map(Number);
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, 1)));
}

function isoFromUtc(year: number, monthIndex: number, day: number): string {
  const date = new Date(Date.UTC(year, monthIndex, day));
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

function monthCells(cursor: string): { date: string; inMonth: boolean }[] {
  const [year, month] = cursor.split("-").map(Number);
  const firstWeekday = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const cells: { date: string; inMonth: boolean }[] = [];
  for (let index = 0; index < firstWeekday; index += 1) {
    cells.push({ date: isoFromUtc(year, month - 1, 1 - (firstWeekday - index)), inMonth: false });
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    cells.push({ date: isoFromUtc(year, month - 1, day), inMonth: true });
  }
  while (cells.length % 7 !== 0) {
    const [lastYear, lastMonth, lastDay] = cells[cells.length - 1].date.split("-").map(Number);
    cells.push({ date: isoFromUtc(lastYear, lastMonth - 1, lastDay + 1), inMonth: false });
  }
  return cells;
}

function MarkDot({ mark }: { mark: Mark }) {
  const hollow = mark === "event";
  return (
    <span
      aria-hidden
      className={`mt-1 h-[5px] w-[5px] shrink-0 rounded-full ${hollow ? "ring-1 ring-foreground" : "bg-foreground"}`}
    />
  );
}

export function MonthCalendar({ items, plans }: { items: Item[]; plans: WeekPlan[] }) {
  const today = useSyncExternalStore(subscribeToday, pacificToday, () => "");
  const [monthCursor, setMonthCursor] = useState<string | null>(null);
  if (today && monthCursor === null) {
    setMonthCursor(today.slice(0, 7));
  }

  const entries = calendarEntries(items, plans);
  const byDate = new Map<string, CalendarEntry[]>();
  for (const entry of entries) {
    const list = byDate.get(entry.date) ?? [];
    list.push(entry);
    byDate.set(entry.date, list);
  }
  for (const list of byDate.values()) {
    list.sort((left, right) => left.minutes - right.minutes || left.title.localeCompare(right.title));
  }

  const cells = monthCursor ? monthCells(monthCursor) : Array.from({ length: 35 }, () => null);
  const label = monthCursor ? monthLabel(monthCursor) : "";

  return (
    <section aria-label="Month calendar" className="font-study">
      <div className="mb-4 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <ul className="flex flex-wrap gap-x-5 gap-y-2 text-[13px] text-foreground">
          <li className="flex items-center gap-2">
            <span aria-hidden className="h-[5px] w-[5px] rounded-full bg-foreground" />
            Exam
          </li>
          <li className="flex items-center gap-2">
            <span aria-hidden className="h-[5px] w-[5px] rounded-full bg-foreground" />
            Due
          </li>
          <li className="flex items-center gap-2">
            <span aria-hidden className="h-[5px] w-[5px] rounded-full ring-1 ring-foreground" />
            Event
          </li>
        </ul>
        <div className="flex items-center gap-3 sm:gap-4">
          <button
            type="button"
            aria-label="Previous month"
            disabled={!monthCursor}
            onClick={() => monthCursor && setMonthCursor(shiftMonth(monthCursor, -1))}
            className="bg-transparent px-1 text-lg leading-none text-foreground disabled:opacity-40"
          >
            ‹
          </button>
          <h2 className="min-w-40 text-center font-study-heading text-2xl font-light sm:text-3xl">{label}</h2>
          <button
            type="button"
            aria-label="Next month"
            disabled={!monthCursor}
            onClick={() => monthCursor && setMonthCursor(shiftMonth(monthCursor, 1))}
            className="bg-transparent px-1 text-lg leading-none text-foreground disabled:opacity-40"
          >
            ›
          </button>
          <button
            type="button"
            disabled={!today}
            onClick={() => today && setMonthCursor(today.slice(0, 7))}
            className="ml-1 border-b border-foreground bg-transparent pb-0.5 text-sm text-foreground disabled:opacity-40"
          >
            Today
          </button>
        </div>
      </div>
      <div className="grid grid-cols-7 border-b border-foreground/15">
        {WEEKDAYS.map((day) => (
          <div key={day} className="px-1 pb-2 text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground sm:px-2 sm:text-[11px]">
            {day}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 border-l border-foreground/15">
        {cells.map((cell, index) => {
          const dayEntries = cell ? (byDate.get(cell.date) ?? []) : [];
          const dayNumber = cell ? Number(cell.date.slice(8)) : null;
          const isToday = Boolean(cell && today && cell.date === today);
          return (
            <div
              key={cell?.date ?? `blank-${index}`}
              className="min-h-24 border-b border-r border-foreground/15 px-1 py-1.5 sm:min-h-32 sm:px-2 sm:py-2"
            >
              {dayNumber != null ? (
                <div className={`mb-1 text-[12px] leading-none sm:text-[13px] ${cell?.inMonth ? "text-foreground" : "text-muted-foreground"}`}>
                  {isToday ? (
                    <span className="inline-flex h-6 w-6 items-center justify-center rounded-full ring-1 ring-foreground">
                      {dayNumber}
                    </span>
                  ) : (
                    dayNumber
                  )}
                </div>
              ) : null}
              <div className="grid gap-0.5">
                {dayEntries.map((entry) => (
                  <p key={entry.id} className="flex min-w-0 items-start gap-1 text-[10px] leading-4 text-foreground sm:text-[11px]">
                    <MarkDot mark={entry.mark} />
                    <span className="min-w-0 truncate">
                      {entry.time ? <span className="text-muted-foreground">{entry.time} </span> : null}
                      {entry.title}
                    </span>
                  </p>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
