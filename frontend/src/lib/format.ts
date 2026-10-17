import type { Day, ItemSource, ItemType } from "@/lib/types";

export const PACIFIC = "America/Los_Angeles";

export const TYPE_LABEL: Record<ItemType, string> = {
  assignment: "Assignment",
  quiz: "Quiz",
  exam: "Exam",
  event: "Event",
  personal: "Personal",
};

export const SOURCE_LABEL: Record<ItemSource, string> = {
  canvas: "Canvas",
  manual: "Typed",
  voice: "Voice",
};

export const DAY_LABEL: Record<Day, string> = {
  mon: "Monday",
  tue: "Tuesday",
  wed: "Wednesday",
  thu: "Thursday",
  fri: "Friday",
  sat: "Saturday",
  sun: "Sunday",
};

export const DAYS: Day[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export const RELATION_LABEL = {
  past: "Past",
  current: "This week",
  upcoming: "Upcoming",
} as const;

export function formatHours(value: number): string {
  const rounded = Math.round(value * 100) / 100;
  return String(rounded);
}

export function formatWhen(iso: string): { weekday: string; date: string; time: string } {
  const instant = new Date(iso);
  return {
    weekday: new Intl.DateTimeFormat("en-US", {
      timeZone: PACIFIC,
      weekday: "short",
    }).format(instant),
    date: new Intl.DateTimeFormat("en-US", {
      timeZone: PACIFIC,
      month: "short",
      day: "numeric",
    }).format(instant),
    time: new Intl.DateTimeFormat("en-US", {
      timeZone: PACIFIC,
      hour: "numeric",
      minute: "2-digit",
    }).format(instant),
  };
}

export function toDateTimeLocal(iso: string): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: PACIFIC,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(iso));
  const read = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "";
  const hour = read("hour") === "24" ? "00" : read("hour");
  return `${read("year")}-${read("month")}-${read("day")}T${hour}:${read("minute")}`;
}
