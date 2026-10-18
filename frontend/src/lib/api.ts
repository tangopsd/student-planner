import type {
  Block,
  BlockStatus,
  Classification,
  GeminiPlanResult,
  ImportResult,
  Item,
  ItemType,
  Profile,
  VoiceTurn,
  Week,
  WeekPlan,
} from "@/lib/types";

type Issue = { loc?: Array<string | number>; msg?: string };

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string | Issue[] };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((issue) => {
          const msg = (issue.msg || "Check that field").replace(/^Value error,\s*/i, "");
          const loc = (issue.loc || []).filter((part) => part !== "body").join(".");
          return loc ? `${loc}: ${msg}` : msg;
        })
        .join(" ");
    }
  } catch {
    // The body was not JSON.
  }
  return "The desk couldn't complete that request.";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers });
  } catch {
    throw new Error("Can't reach the desk. Start the backend and refresh.");
  }
  if (!response.ok) throw new Error(await errorMessage(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function getWeeks() {
  return request<{ weeks: Week[] }>("/api/weeks");
}

export function getProfile() {
  return request<Profile>("/api/profile");
}

export function saveProfile(profile: Profile) {
  return request<Profile>("/api/profile", {
    method: "PUT",
    body: JSON.stringify(profile),
  });
}

export function importUrl(url: string) {
  return request<ImportResult>("/api/calendar", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

export function importFile(file: File) {
  const body = new FormData();
  body.append("file", file);
  return request<ImportResult>("/api/calendar", { method: "POST", body });
}

export function importSample() {
  return request<ImportResult>("/api/calendar/sample", { method: "POST" });
}

export function createItem(payload: {
  title: string;
  course: string | null;
  type: ItemType;
  due_or_start: string;
  estimated_effort_hours: number | null;
  description: string;
}) {
  return request<Item>("/api/items", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function patchItem(
  id: string,
  payload: Partial<{
    title: string;
    course: string | null;
    type: ItemType;
    due_or_start: string;
    estimated_effort_hours: number | null;
    locked: boolean;
    status: Item["status"];
    description: string;
  }>,
) {
  return request<Item>(`/api/items/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteItem(id: string) {
  return request<void>(`/api/items/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function markBlockStatus(blockId: string, status: BlockStatus) {
  return request<Block>(`/api/blocks/${encodeURIComponent(blockId)}/status`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });
}

export function classify(title: string) {
  return request<Classification>(`/api/classify?title=${encodeURIComponent(title)}`);
}

export function getPlans(weekStart?: string) {
  const query = weekStart ? `?week_start=${encodeURIComponent(weekStart)}` : "";
  return request<WeekPlan[]>(`/api/plans${query}`);
}

export function generatePlan(requestText: string, weekStart?: string) {
  return request<GeminiPlanResult>("/api/plan/gemini", {
    method: "POST",
    body: JSON.stringify({
      request: requestText,
      ...(weekStart ? { week_start: weekStart } : {}),
    }),
  });
}

export function sendVoiceText(text: string, weekStart?: string) {
  return request<VoiceTurn>("/api/voice", {
    method: "POST",
    body: JSON.stringify({
      text,
      ...(weekStart ? { week_start: weekStart } : {}),
    }),
  });
}

