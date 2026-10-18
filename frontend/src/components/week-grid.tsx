"use client";

import { useRef, useState } from "react";
import { sendVoiceText } from "@/lib/api";
import type { Block, Item, ToolCall, WeekPlan } from "@/lib/types";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function latestPlan(plans: WeekPlan[]): WeekPlan | null {
  if (plans.length === 0) return null;
  return [...plans].sort((left, right) => {
    if (left.week_start === right.week_start) return right.version - left.version;
    return left.week_start < right.week_start ? 1 : -1;
  })[0];
}

function dateOf(iso: string): string {
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(iso);
  return match ? match[1] : iso.slice(0, 10);
}

function clock(iso: string): string {
  const match = /T(\d{2}):(\d{2})/.exec(iso);
  if (!match) return iso;
  const hour24 = Number(match[1]);
  const suffix = hour24 >= 12 ? "PM" : "AM";
  const hour = hour24 % 12 || 12;
  return `${hour}:${match[2]} ${suffix}`;
}

function dayHeading(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  if (!year || !month || !day) return isoDate;
  const utc = new Date(Date.UTC(year, month - 1, day));
  return `${WEEKDAYS[utc.getUTCDay()]} ${MONTHS[month - 1]} ${day}`;
}

function addDays(isoDate: string, days: number): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  const utc = new Date(Date.UTC(year, month - 1, day + days));
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${utc.getUTCFullYear()}-${pad(utc.getUTCMonth() + 1)}-${pad(utc.getUTCDate())}`;
}

function formatCall(call: ToolCall): string {
  const args = Object.entries(call.args || {})
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(", ");
  return `${call.name}(${args})`;
}

function blockTitle(block: Block, items: Item[]): string {
  const linked = block.item_id ? items.find((item) => item.id === block.item_id) : undefined;
  return linked?.title || block.reason || "Untitled block";
}

export function WeekPlanner({
  items,
  initialPlans,
  initialPlanError,
  onPlan,
}: {
  items: Item[];
  initialPlans: WeekPlan[];
  initialPlanError: string | null;
  onPlan?: (plan: WeekPlan) => void;
}) {
  const starting = latestPlan(initialPlans);
  const [plan, setPlan] = useState<WeekPlan | null>(starting);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(initialPlanError);
  const [reply, setReply] = useState("");
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [debug, setDebug] = useState(() =>
    JSON.stringify(starting ? { source: "saved plan", plan: starting } : { source: "saved plan", plans: initialPlans }, null, 2),
  );
  const inputRef = useRef<HTMLInputElement>(null);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const text = inputRef.current?.value.trim() ?? "";
    if (!text || busy) {
      if (!text) setError("Type a request, then press Send.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const turn = await sendVoiceText(text, plan?.week_start);
      if (inputRef.current) inputRef.current.value = "";
      setReply(turn.reply);
      setToolCalls(turn.tool_calls ?? []);
      setDebug(JSON.stringify(turn, null, 2));
      if (turn.plan) {
        setPlan(turn.plan);
        onPlan?.(turn.plan);
      }
      if (turn.errors?.length) setError(turn.errors.join(" "));
      else if (!turn.valid) setError(turn.reply || "The planner could not update the week.");
      else setError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not send that request.";
      setError(message);
      setDebug(JSON.stringify({ error: message }, null, 2));
    } finally {
      setBusy(false);
    }
  }

  const blocks = Array.isArray(plan?.blocks) ? plan.blocks : [];
  const weekStart = plan?.week_start ?? null;
  const days = weekStart ? Array.from({ length: 7 }, (_, index) => addDays(weekStart, index)) : [];
  const daySet = new Set(days);
  const grouped = new Map<string, Block[]>();
  const outside: Block[] = [];
  for (const block of [...blocks].sort((left, right) => (left.start < right.start ? -1 : 1))) {
    const key = dateOf(block.start);
    if (days.length > 0 && !daySet.has(key)) {
      outside.push(block);
      continue;
    }
    const list = grouped.get(key) ?? [];
    list.push(block);
    grouped.set(key, list);
  }
  const shownDays = days.length > 0 ? days : [...grouped.keys()];

  return (
    <section id="weekly-plan" style={{ border: "1px solid #d7d0c4", borderRadius: 12, padding: 16, background: "#fffdf8" }}>
      <h2 style={{ fontSize: 28, margin: "0 0 8px" }}>Weekly plan</h2>
      <p style={{ margin: "0 0 12px" }}>
        {blocks.length > 0
          ? `${blocks.length} blocks for the week of ${weekStart}.`
          : "No blocks yet."}
      </p>
      <form onSubmit={onSubmit} style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        <input
          ref={inputRef}
          name="request"
          aria-label="What should change this week"
          placeholder="Add a rehearsal Friday from 7 to 9pm"
          style={{ flex: "1 1 220px", padding: "8px 10px" }}
        />
        <button type="submit" disabled={busy} style={{ padding: "8px 12px" }}>
          {busy ? "Updating…" : "Send"}
        </button>
      </form>
      {error ? (
        <p role="alert" style={{ border: "2px solid #b42318", background: "#fff4f2", color: "#7a1b12", padding: 12, borderRadius: 8 }}>
          {error}
        </p>
      ) : null}
      <aside
        aria-label="Tool calls"
        style={{ border: "2px solid #1f3a2e", background: "#f3f7f4", borderRadius: 12, padding: 12, marginBottom: 16 }}
      >
        <h3 style={{ margin: "0 0 8px", fontSize: 18 }}>Tool calls</h3>
        {toolCalls.length === 0 ? (
          <p style={{ margin: 0 }}>No tool calls yet. Type a change and press Send.</p>
        ) : (
          <ol style={{ margin: 0, paddingLeft: 20 }}>
            {toolCalls.map((call, index) => (
              <li key={`${call.name}-${index}`} style={{ marginBottom: 6 }}>
                <code style={{ fontSize: 13 }}>{formatCall(call)}</code>
              </li>
            ))}
          </ol>
        )}
        <h3 style={{ margin: "16px 0 8px", fontSize: 18 }}>Explanation</h3>
        <p style={{ margin: 0 }}>{reply || "The short explanation will show here."}</p>
      </aside>
      <div id="week-grid">
        {blocks.length === 0 ? (
          <p>The planner response has no blocks to show.</p>
        ) : (
          shownDays.map((day) => {
            const dayBlocks = grouped.get(day) ?? [];
            return (
              <div key={day} style={{ marginTop: 16 }}>
                <h3 style={{ margin: "0 0 6px", fontSize: 18 }}>{dayHeading(day)}</h3>
                {dayBlocks.length === 0 ? (
                  <p style={{ margin: 0, color: "#666" }}>Nothing scheduled</p>
                ) : (
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {dayBlocks.map((block) => (
                      <li key={block.id} style={{ marginBottom: 6 }}>
                        <strong>
                          {clock(block.start)} – {clock(block.end)}
                        </strong>{" "}
                        {blockTitle(block, items)}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })
        )}
        {outside.length > 0 ? (
          <div style={{ marginTop: 16 }}>
            <h3 style={{ margin: "0 0 6px", fontSize: 18 }}>Also returned</h3>
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {outside.map((block) => (
                <li key={block.id}>
                  <strong>
                    {dateOf(block.start)} {clock(block.start)} – {clock(block.end)}
                  </strong>{" "}
                  {blockTitle(block, items)}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
      <h3 style={{ marginTop: 20, fontSize: 16 }}>Planner response</h3>
      <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, background: "#f4f1ea", padding: 12, maxHeight: 280, overflow: "auto" }}>
        {debug}
      </pre>
    </section>
  );
}
