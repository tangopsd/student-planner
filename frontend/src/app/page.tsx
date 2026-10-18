import { Desk } from "@/components/desk";
import type { Profile, Week, WeekPlan } from "@/lib/types";

const backend = process.env.BACKEND_URL || "http://127.0.0.1:8741";

async function loadJson<T>(path: string): Promise<{ data: T | null; error: string | null }> {
  try {
    const response = await fetch(`${backend}${path}`, { cache: "no-store" });
    if (!response.ok) {
      return { data: null, error: `The desk request failed (${response.status}).` };
    }
    return { data: (await response.json()) as T, error: null };
  } catch (err) {
    return {
      data: null,
      error: err instanceof Error ? err.message : "Could not load the desk.",
    };
  }
}

export default async function Page() {
  const [plansResult, weeksResult, profileResult] = await Promise.all([
    loadJson<WeekPlan[]>("/api/plans"),
    loadJson<{ weeks: Week[] }>("/api/weeks"),
    loadJson<Profile>("/api/profile"),
  ]);
  const plans = Array.isArray(plansResult.data) ? plansResult.data : [];
  const weeks = Array.isArray(weeksResult.data?.weeks) ? weeksResult.data.weeks : null;
  return (
    <Desk
      initialPlans={plans}
      initialPlanError={plansResult.error ?? (Array.isArray(plansResult.data) ? null : "The planner response was not a list of plans.")}
      initialWeeks={weeks}
      initialProfile={profileResult.data}
      initialDeskError={weeksResult.error ?? profileResult.error}
    />
  );
}
