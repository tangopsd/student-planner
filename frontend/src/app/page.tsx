import { Desk } from "@/components/desk";
import type { WeekPlan } from "@/lib/types";

async function loadPlans(): Promise<{ plans: WeekPlan[]; error: string | null }> {
  const backend = process.env.BACKEND_URL || "http://127.0.0.1:8741";
  try {
    const response = await fetch(`${backend}/api/plans`, { cache: "no-store" });
    if (!response.ok) {
      return { plans: [], error: `The planner request failed (${response.status}).` };
    }
    const plans = (await response.json()) as WeekPlan[];
    if (!Array.isArray(plans)) {
      return { plans: [], error: "The planner response was not a list of plans." };
    }
    return { plans, error: null };
  } catch (err) {
    return {
      plans: [],
      error: err instanceof Error ? err.message : "Could not load the weekly plan.",
    };
  }
}

export default async function Page() {
  const { plans, error } = await loadPlans();
  return <Desk initialPlans={plans} initialPlanError={error} />;
}
