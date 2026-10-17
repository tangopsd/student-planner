"use client";

import { useEffect, useState } from "react";
import { getProfile, getWeeks } from "@/lib/api";
import { formatHours, formatWhen } from "@/lib/format";
import type { Item, Profile, Week } from "@/lib/types";
import { HoursPanel } from "@/components/hours-panel";
import { ImportPanel } from "@/components/import-panel";
import { ManualForm } from "@/components/manual-form";
import { WeekList } from "@/components/week-list";
import { Button } from "@/components/ui/button";

function nextOpen(items: Item[]): Item | undefined {
  return items
    .filter((item) => item.status === "open")
    .sort(
      (left, right) =>
        new Date(left.due_or_start).getTime() - new Date(right.due_or_start).getTime(),
    )[0];
}

export function Desk() {
  const [weeks, setWeeks] = useState<Week[] | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [profileVersion, setProfileVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function refreshWeeks() {
    return getWeeks().then((weekBody) => {
      setWeeks(weekBody.weeks);
    });
  }

  useEffect(() => {
    let cancelled = false;
    Promise.all([getWeeks(), getProfile()])
      .then(([weekBody, profileBody]) => {
        if (cancelled) return;
        setWeeks(weekBody.weeks);
        setProfile(profileBody);
        setProfileVersion((version) => version + 1);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Couldn't load the desk.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function retry() {
    setLoading(true);
    setError(null);
    Promise.all([getWeeks(), getProfile()])
      .then(([weekBody, profileBody]) => {
        setWeeks(weekBody.weeks);
        setProfile(profileBody);
        setProfileVersion((version) => version + 1);
        setError(null);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Couldn't load the desk.");
      })
      .finally(() => setLoading(false));
  }

  const items = weeks?.flatMap((week) => week.items) ?? [];
  const openCount = items.filter((item) => item.status === "open").length;
  const doneCount = items.filter((item) => item.status === "done").length;
  const upcoming = nextOpen(items);
  const upcomingWhen = upcoming ? formatWhen(upcoming.due_or_start) : null;

  return (
    <>
      <div className="h-1.5 bg-primary" />
      <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col px-4 py-8 md:px-8">
        <header className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
              Student desk
            </p>
            <h1 className="font-heading text-4xl italic leading-none sm:text-5xl">Desk</h1>
            <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground sm:text-base">
              Deadlines, grouped by the week they fall in. Import a Canvas feed, or type one in
              when you don&apos;t have a link.
            </p>
          </div>
          {profile && weeks ? (
            <p className="text-sm text-muted-foreground">
              {openCount} open · {doneCount} done · {formatHours(profile.daily_capacity_hours)}h a
              day
              {upcomingWhen ? ` · Next ${upcomingWhen.weekday}, ${upcomingWhen.date}` : ""}
            </p>
          ) : null}
        </header>

        {error ? (
          <div role="alert" className="mb-6 flex flex-wrap items-center gap-3 rounded-lg border border-destructive/40 bg-card px-4 py-3 text-sm">
            <p className="text-destructive">{error}</p>
            <Button type="button" variant="outline" size="sm" onClick={retry}>
              Try again
            </Button>
          </div>
        ) : null}

        {loading ? (
          <div role="status" className="grid gap-3" aria-label="Loading deadlines">
            <p className="text-sm text-muted-foreground">Loading deadlines…</p>
            <div className="h-24 animate-pulse rounded-xl bg-muted" />
            <div className="h-24 animate-pulse rounded-xl bg-muted" />
            <div className="h-24 animate-pulse rounded-xl bg-muted" />
          </div>
        ) : (
          <div className="grid items-start gap-6 lg:grid-cols-[22rem_minmax(0,1fr)]">
            <div className="grid gap-6">
              <ImportPanel
                onImported={async () => {
                  await refreshWeeks();
                }}
              />
              <ManualForm onCreated={refreshWeeks} />
              {profile ? (
                <HoursPanel key={profileVersion} profile={profile} onSaved={setProfile} />
              ) : null}
            </div>
            <WeekList weeks={weeks ?? []} onChanged={refreshWeeks} />
          </div>
        )}
      </main>
    </>
  );
}
