"use client";

import { useState } from "react";
import { deleteItem, patchItem } from "@/lib/api";
import { RELATION_LABEL, SOURCE_LABEL, TYPE_LABEL, formatHours, formatWhen } from "@/lib/format";
import type { Item, Week } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { cn } from "cn";

function DeadlineRow({ item, onChanged }: { item: Item; onChanged: () => Promise<void> }) {
  const when = formatWhen(item.due_or_start);
  const [effort, setEffort] = useState(
    item.estimated_effort_hours === null ? "" : formatHours(item.estimated_effort_hours),
  );
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update that deadline.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="grid gap-3 py-4 md:grid-cols-[8.5rem_minmax(0,1fr)]">
      <div>
        <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          {when.weekday}
        </p>
        <p className="font-heading text-xl leading-tight">{when.date}</p>
        <p className="text-sm text-muted-foreground">{when.time}</p>
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={item.type === "exam" ? "destructive" : "secondary"}>
            {TYPE_LABEL[item.type]}
          </Badge>
          {item.locked ? <Badge variant="outline">Locked</Badge> : null}
          {item.course ? <span className="text-sm font-medium">{item.course}</span> : null}
          <span className="text-xs text-muted-foreground">{SOURCE_LABEL[item.source]}</span>
          {item.status === "done" ? (
            <span className="text-xs text-muted-foreground">Done</span>
          ) : null}
        </div>
        <h3
          className={cn(
            "mt-1 text-base leading-snug",
            item.status === "done" && "text-muted-foreground line-through",
          )}
        >
          {item.title}
        </h3>
        {item.description ? (
          <p className="mt-1 line-clamp-3 text-sm whitespace-pre-wrap text-muted-foreground">
            {item.description}
          </p>
        ) : null}
        {item.locked ? (
          <p className="mt-1 text-xs text-muted-foreground">This exam stays fixed.</p>
        ) : null}
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <div className="grid gap-1">
            <Label htmlFor={`effort-${item.id}`} className="text-xs text-muted-foreground">
              Effort (hours)
            </Label>
            <Input
              id={`effort-${item.id}`}
              className="w-24"
              type="number"
              min={0}
              max={100}
              step={0.5}
              value={effort}
              disabled={busy}
              onChange={(event) => setEffort(event.target.value)}
              onBlur={() => {
                const trimmed = effort.trim();
                if (trimmed === "") {
                  if (item.estimated_effort_hours !== null) {
                    void run(() => patchItem(item.id, { estimated_effort_hours: null }));
                  }
                  return;
                }
                const parsed = Number(trimmed);
                if (!Number.isFinite(parsed) || parsed < 0 || parsed > 100) {
                  setError("Effort must be between 0 and 100 hours.");
                  return;
                }
                if (parsed === item.estimated_effort_hours) return;
                void run(() => patchItem(item.id, { estimated_effort_hours: parsed }));
              }}
            />
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() =>
              void run(() =>
                patchItem(item.id, { status: item.status === "done" ? "open" : "done" }),
              )
            }
          >
            {item.status === "done" ? "Reopen" : "Mark done"}
          </Button>
          {confirming ? (
            <>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                disabled={busy}
                onClick={() => void run(() => deleteItem(item.id))}
              >
                Confirm remove
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => setConfirming(false)}
              >
                Cancel
              </Button>
            </>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => setConfirming(true)}
            >
              Remove
            </Button>
          )}
        </div>
        {error ? (
          <p role="alert" className="mt-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </article>
  );
}

function WeekSection({
  week,
  divided,
  onChanged,
}: {
  week: Week;
  divided: boolean;
  onChanged: () => Promise<void>;
}) {
  return (
    <section className={cn(week.relation === "current" && "border-l-2 border-primary pl-4")}>
      {divided ? <Separator className="my-6" /> : null}
      <p className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
        {RELATION_LABEL[week.relation]}
      </p>
      <h2 className="font-heading text-3xl leading-tight">{week.label}</h2>
      <p className="text-sm text-muted-foreground">
        {week.items.length === 1 ? "1 deadline" : `${week.items.length} deadlines`}
      </p>
      <div className="divide-y divide-border">
        {week.items.map((item) => (
          <DeadlineRow key={item.id} item={item} onChanged={onChanged} />
        ))}
      </div>
    </section>
  );
}

export function WeekList({
  weeks,
  onChanged,
}: {
  weeks: Week[];
  onChanged: () => Promise<void>;
}) {
  const active = weeks.filter((week) => week.relation !== "past");
  const past = weeks.filter((week) => week.relation === "past");
  const pastCount = past.reduce((total, week) => total + week.items.length, 0);

  return (
    <Card id="plan">
      <CardHeader>
        <CardTitle>Your plan</CardTitle>
        <CardDescription>
          Deadlines from the feed, starting with this week. Times are Pacific.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {weeks.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border px-4 py-10 text-center">
            <p className="font-heading text-2xl">Nothing on the desk yet</p>
            <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
              Paste a Canvas link above. The week-by-week plan shows up here.
            </p>
          </div>
        ) : (
          <div>
            {(active.length > 0 ? active : past).map((week, index) => (
              <WeekSection
                key={week.week_start}
                week={week}
                divided={index > 0}
                onChanged={onChanged}
              />
            ))}
            {active.length > 0 && past.length > 0 ? (
              <details className="mt-8">
                <summary className="cursor-pointer text-sm font-medium">
                  Earlier weeks ({pastCount} {pastCount === 1 ? "deadline" : "deadlines"})
                </summary>
                <div className="mt-4">
                  {past.map((week, index) => (
                    <WeekSection
                      key={week.week_start}
                      week={week}
                      divided={index > 0}
                      onChanged={onChanged}
                    />
                  ))}
                </div>
              </details>
            ) : null}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
