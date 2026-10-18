import type { Block, WeekPlan } from "@/lib/types";

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export type HeaviestDay = {
  day: string;
  detail: string;
  survived: boolean;
};

export type WeekRecapStats = {
  weekStart: string;
  weekLabel: string;
  done: number;
  planned: number;
  streak: number | null;
  heaviest: HeaviestDay | null;
};

export function dateOf(iso: string): string {
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(iso);
  return match ? match[1] : iso.slice(0, 10);
}

export function addDays(isoDate: string, days: number): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  const utc = new Date(Date.UTC(year, month - 1, day + days));
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${utc.getUTCFullYear()}-${pad(utc.getUTCMonth() + 1)}-${pad(utc.getUTCDate())}`;
}

export function mondayOnOrBefore(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  const utc = new Date(Date.UTC(year, month - 1, day));
  const weekday = utc.getUTCDay();
  const delta = weekday === 0 ? 6 : weekday - 1;
  return addDays(isoDate, -delta);
}

function shortDate(isoDate: string): string {
  const [, month, day] = isoDate.split("-").map(Number);
  if (!month || !day) return isoDate;
  return `${MONTHS[month - 1]} ${day}`;
}

function weekdayName(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  const utc = new Date(Date.UTC(year, month - 1, day));
  return WEEKDAYS[utc.getUTCDay()] ?? isoDate;
}

function blockMinutes(block: Block): number {
  const ms = new Date(block.end).getTime() - new Date(block.start).getTime();
  if (!Number.isFinite(ms) || ms <= 0) return 0;
  return Math.round(ms / 60000);
}

function formatSpan(totalMinutes: number): string {
  const minutes = Math.max(0, totalMinutes);
  const hours = Math.floor(minutes / 60);
  const remain = minutes % 60;
  if (hours && remain) return `${hours}h ${remain}m`;
  if (hours) return `${hours}h`;
  return `${remain}m`;
}

export function latestByWeek(plans: WeekPlan[]): WeekPlan[] {
  const map = new Map<string, WeekPlan>();
  for (const plan of plans) {
    const current = map.get(plan.week_start);
    if (!current || plan.version > current.version) map.set(plan.week_start, plan);
  }
  return [...map.values()];
}

function streakEnding(doneDays: Set<string>, today: string): number {
  const start = doneDays.has(today) ? today : addDays(today, -1);
  if (!doneDays.has(start)) return 0;
  let count = 0;
  let cursor = start;
  while (doneDays.has(cursor)) {
    count += 1;
    cursor = addDays(cursor, -1);
  }
  return count;
}

export function buildRecap(plans: WeekPlan[], today: string): WeekRecapStats {
  const latest = latestByWeek(plans);
  const weekStart = today ? mondayOnOrBefore(today) : "";
  const newest = [...latest].sort((left, right) => (left.week_start < right.week_start ? 1 : -1))[0] ?? null;
  const weekPlan = (weekStart && latest.find((plan) => plan.week_start === weekStart)) || newest;
  const blocks = weekPlan?.blocks ?? [];
  const done = blocks.filter((block) => block.status === "done").length;

  const doneDays = new Set<string>();
  for (const plan of latest) {
    for (const block of plan.blocks) {
      if (block.status === "done") doneDays.add(dateOf(block.start));
    }
  }

  const byDay = new Map<string, { minutes: number; done: number; planned: number }>();
  for (const block of blocks) {
    const day = dateOf(block.start);
    const row = byDay.get(day) ?? { minutes: 0, done: 0, planned: 0 };
    row.minutes += blockMinutes(block);
    row.planned += 1;
    if (block.status === "done") row.done += 1;
    byDay.set(day, row);
  }
  const ranked = [...byDay.entries()].sort((left, right) => (left[0] < right[0] ? -1 : 1));
  let heaviest: HeaviestDay | null = null;
  let bestMinutes = -1;
  for (const [day, row] of ranked) {
    if (row.minutes <= bestMinutes) continue;
    bestMinutes = row.minutes;
    const survived = row.planned > 0 && row.done === row.planned;
    heaviest = {
      day: weekdayName(day),
      detail: survived
        ? `${formatSpan(row.minutes)} survived`
        : `${formatSpan(row.minutes)} · ${row.done} of ${row.planned} done`,
      survived,
    };
  }

  const start = weekPlan?.week_start ?? weekStart;
  return {
    weekStart: start,
    weekLabel: start ? `${shortDate(start)} – ${shortDate(addDays(start, 6))}` : "This week",
    done,
    planned: blocks.length,
    streak: today && latest.length > 0 ? streakEnding(doneDays, today) : null,
    heaviest,
  };
}

export function streakLabel(streak: number | null): string {
  if (streak == null) return "—";
  if (streak <= 0) return "None yet";
  return streak === 1 ? "1 day" : `${streak} days`;
}
