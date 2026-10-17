"use client";

import { useEffect, useState } from "react";
import { generatePlan, getPlans } from "@/lib/api";
import { formatWhen } from "@/lib/format";
import type { Block, Item, WeekPlan } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const KIND_LABEL = {
  study: "Study",
  fixed: "Fixed",
  personal: "Personal",
  buffer: "Buffer",
} as const;

function readPart(parts: Intl.DateTimeFormatPart[], type: Intl.DateTimeFormatPartTypes) {
  return parts.find((part) => part.type === type)?.value ?? "";
}

function localDateKey(iso: string): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(iso));
  return `${readPart(parts, "year")}-${readPart(parts, "month")}-${readPart(parts, "day")}`;
}

function defaultWeekStart(now: Date): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const utc = new Date(
    Date.UTC(Number(readPart(parts, "year")), Number(readPart(parts, "month")) - 1, Number(readPart(parts, "day"))),
  );
  const weekday = utc.getUTCDay();
  const mondayOffset = weekday === 0 ? -6 : 1 - weekday;
  utc.setUTCDate(utc.getUTCDate() + mondayOffset);
  if (weekday === 0 || weekday === 6) utc.setUTCDate(utc.getUTCDate() + 7);
  return utc.toISOString().slice(0, 10);
}

function addDays(iso: string, days: number): string {
  const [year, month, day] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day + days));
  return date.toISOString().slice(0, 10);
}

function dayLabel(iso: string): { weekday: string; date: string } {
  const [year, month, day] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return {
    weekday: new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: "UTC" }).format(date),
    date: new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" }).format(date),
  };
}

function pickLatest(plans: WeekPlan[]): WeekPlan | null {
  if (plans.length === 0) return null;
  return [...plans].sort((left, right) => {
    if (left.week_start === right.week_start) return right.version - left.version;
    return left.week_start < right.week_start ? 1 : -1;
  })[0];
}

export function WeekPlanner({ items }: { items: Item[] }) {
  const [remote, setRemote] = useState<WeekPlan | null>(null);
  const [weekStart, setWeekStart] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getPlans()
      .then((rows) => {
        if (cancelled) return;
        const latest = pickLatest(rows);
        setRemote(latest);
        setWeekStart(latest ? latest.week_start : defaultWeekStart(new Date()));
        setLoaded(true);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Couldn't load the weekly plan.");
        setWeekStart(defaultWeekStart(new Date()));
        setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function onPlan() {
    setBusy(true);
    setError(null);
    setErrors([]);
    setNote(null);
    try {
      const result = await generatePlan(
        "Plan study blocks for the target week from the deadlines already on the desk. Do not add or replace those deadlines.",
      );
      setWeekStart(result.week_start);
      setRemote(result.plan);
      setErrors(result.errors);
      setNote(result.message || null);
      if (!result.valid) {
        setError("Gemini could not produce a valid week. The problems are listed below.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not plan the week.");
    } finally {
      setBusy(false);
    }
  }

  const days = weekStart ? Array.from({ length: 7 }, (_, index) => addDays(weekStart, index)) : [];
  const byId = new Map(items.map((item) => [item.id, item]));
  const byDay = new Map<string, Block[]>();
  for (const block of remote?.blocks ?? []) {
    const key = localDateKey(block.start);
    const list = byDay.get(key) ?? [];
    list.push(block);
    byDay.set(key, list);
  }
  const range = days.length
    ? `${dayLabel(days[0]).date} – ${dayLabel(days[6]).date}`
    : "This week";

  return (
    <Card id="weekly-plan">
      <CardHeader>
        <CardTitle>Weekly plan</CardTitle>
        <CardDescription>
          {days.length ? `${range}. ` : ""}
          Gemini places study blocks around the deadlines already on the desk.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muted-foreground">
            The backend reads GEMINI_API_KEY. Existing deadlines stay put.
            {remote ? ` Version ${remote.version}.` : ""}
          </p>
          <Button type="button" onClick={onPlan} disabled={busy}>
            {busy ? "Planning…" : "Plan this week"}
          </Button>
        </div>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        {errors.length > 0 ? (
          <ul role="alert" className="grid gap-1 text-sm text-destructive">
            {errors.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : null}
        {note ? <p className="line-clamp-3 text-sm text-muted-foreground">{note}</p> : null}
        {!loaded ? (
          <p role="status" className="text-sm text-muted-foreground">
            Loading the week…
          </p>
        ) : (
          <div className="grid gap-3 lg:grid-cols-7">
            {days.map((day) => {
              const label = dayLabel(day);
              const blocks = [...(byDay.get(day) ?? [])].sort((left, right) =>
                left.start < right.start ? -1 : 1,
              );
              return (
                <section key={day} className="rounded-lg bg-background px-3 py-2 ring-1 ring-foreground/10">
                  <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                    {label.weekday}
                  </p>
                  <p className="font-heading text-lg leading-tight">{label.date}</p>
                  {blocks.length === 0 ? (
                    <p className="mt-3 text-sm text-muted-foreground">Nothing scheduled</p>
                  ) : (
                    <div className="mt-3 grid gap-2">
                      {blocks.map((block) => {
                        const item = block.item_id ? byId.get(block.item_id) : undefined;
                        const title = item?.title || block.reason || "Open block";
                        const start = formatWhen(block.start);
                        const end = formatWhen(block.end);
                        return (
                          <article
                            key={block.id}
                            className={
                              block.status === "skipped"
                                ? "rounded-md bg-muted px-2 py-1.5 opacity-60"
                                : "rounded-md bg-muted px-2 py-1.5"
                            }
                          >
                            <p className="text-xs text-muted-foreground">
                              {start.time} – {end.time}
                            </p>
                            <p className="mt-1 text-sm leading-snug break-words">{title}</p>
                            <div className="mt-1 flex flex-wrap items-center gap-1">
                              <Badge variant={block.kind === "study" ? "secondary" : "outline"}>
                                {KIND_LABEL[block.kind]}
                              </Badge>
                              {block.status !== "scheduled" ? (
                                <span className="text-xs text-muted-foreground">{block.status}</span>
                              ) : null}
                            </div>
                          </article>
                        );
                      })}
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
