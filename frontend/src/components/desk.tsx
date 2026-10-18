"use client";

import { useEffect, useState } from "react";
import { getProfile, getWeeks } from "@/lib/api";
import { formatHours, formatWhen } from "@/lib/format";
import type { Item, Profile, Week, WeekPlan } from "@/lib/types";
import { HoursPanel } from "@/components/hours-panel";
import { ImportPanel } from "@/components/import-panel";
import { ManualForm } from "@/components/manual-form";
import { StudySession } from "@/components/study-session";
import { WeekList } from "@/components/week-list";
import { WeekPlanner } from "@/components/week-grid";
import { Button } from "@/components/ui/button";

function nextOpen(items: Item[]): Item | undefined {
  return items
    .filter((item) => item.status === "open")
    .sort(
      (left, right) =>
        new Date(left.due_or_start).getTime() - new Date(right.due_or_start).getTime(),
    )[0];
}

export function Desk({
  initialPlans = [],
  initialPlanError = null,
  initialWeeks = null,
  initialProfile = null,
  initialDeskError = null,
}: {
  initialPlans?: WeekPlan[];
  initialPlanError?: string | null;
  initialWeeks?: Week[] | null;
  initialProfile?: Profile | null;
  initialDeskError?: string | null;
}) {
  const [weeks, setWeeks] = useState<Week[] | null>(initialWeeks);
  const [profile, setProfile] = useState<Profile | null>(initialProfile);
  const [profileVersion, setProfileVersion] = useState(0);
  const [loading, setLoading] = useState(initialWeeks === null && !initialDeskError);
  const [error, setError] = useState<string | null>(initialDeskError);
  const [view, setView] = useState<"week" | "study">("week");

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
    setError(null);
    if (weeks === null) setLoading(true);
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
      .finally(() => {
        setLoading(false);
      });
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
            <p className="font-study text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
              Focus
            </p>
            <h1 className="font-study-heading text-4xl font-light leading-none sm:text-5xl">Quill</h1>
            <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground sm:text-base">
              Import a Canvas feed, then plan the week around the deadlines already on the desk.
            </p>
          </div>
          <div className="flex flex-col items-start gap-3 md:items-end">
            <nav aria-label="Views" className="flex gap-5 text-sm">
              <button
                type="button"
                aria-current={view === "week" ? "page" : undefined}
                onClick={() => setView("week")}
                className={`border-b-[1.5px] px-0.5 py-1.5 ${view === "week" ? "border-foreground font-medium text-foreground" : "border-transparent text-muted-foreground"}`}
              >
                Week
              </button>
              <button
                type="button"
                aria-current={view === "study" ? "page" : undefined}
                onClick={() => setView("study")}
                className={`border-b-[1.5px] px-0.5 py-1.5 ${view === "study" ? "border-foreground font-medium text-foreground" : "border-transparent text-muted-foreground"}`}
              >
                Study
              </button>
            </nav>
            {profile && weeks ? (
              <p className="text-sm text-muted-foreground">
                {openCount} open · {doneCount} done · {formatHours(profile.daily_capacity_hours)}h a
                day
                {upcomingWhen ? ` · Next ${upcomingWhen.weekday}, ${upcomingWhen.date}` : ""}
              </p>
            ) : null}
          </div>
        </header>

        {error ? (
          <div role="alert" className="mb-6 flex flex-wrap items-center gap-3 rounded-lg border border-destructive/40 bg-card px-4 py-3 text-sm">
            <p className="text-destructive">{error}</p>
            <Button type="button" variant="outline" size="sm" onClick={retry}>
              Try again
            </Button>
          </div>
        ) : null}

        <div className={view === "week" ? "mb-6" : "hidden"}>
          <ImportPanel
            onImported={async () => {
              await refreshWeeks();
              document.getElementById("weekly-plan")?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
          />
        </div>

        <div className={view === "week" ? "mb-6" : "hidden"}>
          <WeekPlanner
            items={items}
            initialPlans={initialPlans}
            initialPlanError={initialPlanError}
          />
        </div>

        <div className={view === "study" ? "mb-6" : "hidden"}>
          <StudySession items={items} initialPlans={initialPlans} active={view === "study"} />
        </div>

        {loading && weeks === null && !error ? (
          <div role="status" className={`mb-6 grid gap-3 ${view === "week" ? "" : "hidden"}`} aria-label="Loading deadlines">
            <p className="text-sm text-muted-foreground">Loading your plan…</p>
            <div className="h-24 animate-pulse rounded-xl bg-muted" />
            <div className="h-24 animate-pulse rounded-xl bg-muted" />
          </div>
        ) : weeks ? (
          <div className={view === "week" ? "mb-6" : "hidden"}>
            <WeekList weeks={weeks} onChanged={refreshWeeks} />
          </div>
        ) : null}

        <details className={`rounded-xl bg-card px-4 py-3 ring-1 ring-foreground/10 ${view === "week" ? "" : "hidden"}`}>
          <summary className="cursor-pointer text-sm font-medium">
            Add a deadline by hand, or set your hours
          </summary>
          <div className="mt-4 grid gap-6">
            <ManualForm onCreated={refreshWeeks} />
            {profile ? (
              <HoursPanel key={profileVersion} profile={profile} onSaved={setProfile} />
            ) : null}
          </div>
        </details>
      </main>
    </>
  );
}
