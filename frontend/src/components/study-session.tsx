"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { getPlans, markBlockStatus } from "@/lib/api";
import { PACIFIC } from "@/lib/format";
import type { Block, Item, WeekPlan } from "@/lib/types";

type Mode = "timer" | "stopwatch";

type Step = {
  id: string;
  text: string;
  done: boolean;
  finishedAt: number;
};

type StudyTask = {
  id: string;
  text: string;
  done: boolean;
  blockId: string | null;
  detail: string;
  order: number;
  finishedAt: number;
};

type Playlist = {
  id: string;
  name: string;
};

const PLAYLISTS: Playlist[] = [
  { id: "37i9dQZF1DWZeKCadgRdKQ", name: "Deep focus" },
  { id: "37i9dQZF1DWWQRwui0ExPn", name: "Lo-fi" },
  { id: "37i9dQZF1DX4sWSpwq3LiO", name: "Instrumental" },
];

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const EMPTY_STEPS: Step[] = [];

function pacificToday(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: PACIFIC,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function subscribeToday(onChange: () => void) {
  const id = window.setInterval(onChange, 60_000);
  return () => window.clearInterval(id);
}

function dateOf(iso: string): string {
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(iso);
  return match ? match[1] : iso.slice(0, 10);
}

function clock(iso: string): string {
  const match = /T(\d{2}):(\d{2})/.exec(iso);
  if (!match) return iso;
  const hour24 = Number(match[1]);
  const suffix = hour24 >= 12 ? "pm" : "am";
  const hour = hour24 % 12 || 12;
  return `${hour}:${match[2]}${suffix}`;
}

function dayHeading(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  if (!year || !month || !day) return isoDate;
  const utc = new Date(Date.UTC(year, month - 1, day));
  return `${WEEKDAYS[utc.getUTCDay()]} ${MONTHS[month - 1]} ${day}`;
}

function latestPlan(plans: WeekPlan[]): WeekPlan | null {
  if (plans.length === 0) return null;
  return [...plans].sort((left, right) => {
    if (left.week_start === right.week_start) return right.version - left.version;
    return left.week_start < right.week_start ? 1 : -1;
  })[0];
}

function blockTitle(block: Block, items: Item[]): string {
  const linked = block.item_id ? items.find((item) => item.id === block.item_id) : undefined;
  return linked?.title || block.reason || "Untitled block";
}

function blockMinutes(block: Block): number {
  const ms = new Date(block.end).getTime() - new Date(block.start).getTime();
  if (!Number.isFinite(ms) || ms <= 0) return 25;
  return Math.max(1, Math.min(12 * 60, Math.round(ms / 60000)));
}

function formatClock(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remain = seconds % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  if (hours > 0) return `${hours}:${pad(minutes)}:${pad(remain)}`;
  return `${pad(minutes)}:${pad(remain)}`;
}

function formatSpan(totalSeconds: number): string {
  const minutes = Math.max(0, Math.round(totalSeconds / 60));
  const hours = Math.floor(minutes / 60);
  const remain = minutes % 60;
  if (hours && remain) return `${hours}h ${remain}m`;
  if (hours) return `${hours}h`;
  return `${remain}m`;
}

const CUSTOM_KEY = "desk-study-tasks";

let stepCacheKey = "";
let stepCache: Step[] = EMPTY_STEPS;
const stepListeners = new Set<() => void>();

function readSteps(): Step[] {
  if (typeof window === "undefined") return EMPTY_STEPS;
  const raw = window.localStorage.getItem(CUSTOM_KEY) ?? "";
  const cacheKey = `${CUSTOM_KEY}:${raw}`;
  if (cacheKey === stepCacheKey) return stepCache;
  let steps = EMPTY_STEPS;
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as Step[];
      if (Array.isArray(parsed)) {
        steps = parsed
          .filter((step) => step && typeof step.id === "string" && typeof step.text === "string")
          .map((step) => ({
            id: step.id,
            text: step.text,
            done: Boolean(step.done),
            finishedAt: typeof step.finishedAt === "number" ? step.finishedAt : 0,
          }));
      }
    } catch {
      steps = EMPTY_STEPS;
    }
  }
  stepCacheKey = cacheKey;
  stepCache = steps;
  return steps;
}

function writeSteps(steps: Step[]) {
  const raw = JSON.stringify(steps);
  window.localStorage.setItem(CUSTOM_KEY, raw);
  stepCacheKey = `${CUSTOM_KEY}:${raw}`;
  stepCache = steps;
  stepListeners.forEach((listener) => listener());
}

function subscribeSteps(onChange: () => void) {
  stepListeners.add(onChange);
  return () => stepListeners.delete(onChange);
}

const FINISHED_KEY = "desk-study-finished";
const EMPTY_FINISHED: Record<string, number> = {};
let finishedCacheKey = "";
let finishedCache: Record<string, number> = EMPTY_FINISHED;

function readFinished(): Record<string, number> {
  if (typeof window === "undefined") return EMPTY_FINISHED;
  const raw = window.localStorage.getItem(FINISHED_KEY) ?? "";
  if (raw === finishedCacheKey) return finishedCache;
  let next = EMPTY_FINISHED;
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as Record<string, number>;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) next = parsed;
    } catch {
      next = EMPTY_FINISHED;
    }
  }
  finishedCacheKey = raw;
  finishedCache = next;
  return next;
}

function rememberFinished(blockId: string, at: number | null) {
  const next = { ...readFinished() };
  if (at == null) delete next[blockId];
  else next[blockId] = at;
  const raw = JSON.stringify(next);
  window.localStorage.setItem(FINISHED_KEY, raw);
  finishedCacheKey = raw;
  finishedCache = next;
  stepListeners.forEach((listener) => listener());
}

function nowMs(): number {
  return Date.now();
}

function secondsLeft(endAt: number): number {
  return Math.max(0, (endAt - nowMs()) / 1000);
}

function endAtFrom(remainingSeconds: number): number {
  return nowMs() + remainingSeconds * 1000;
}

function elapsedSince(startAt: number, base: number): number {
  return base + (nowMs() - startAt) / 1000;
}

function linkClass(active: boolean): string {
  return `border-b-[1.5px] bg-transparent px-0.5 py-1.5 text-sm text-foreground ${
    active ? "border-foreground font-normal" : "border-transparent font-light"
  }`;
}

function actionClass(): string {
  return "border-b border-foreground bg-transparent px-0 py-1.5 text-sm font-light text-foreground";
}

export function StudySession({
  items,
  initialPlans,
  active,
}: {
  items: Item[];
  initialPlans: WeekPlan[];
  active: boolean;
}) {
  const today = useSyncExternalStore(subscribeToday, pacificToday, () => "");
  const [plans, setPlans] = useState(initialPlans);
  const [planError, setPlanError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("timer");
  const [durationSec, setDurationSec] = useState(25 * 60);
  const [hourText, setHourText] = useState("0");
  const [minuteText, setMinuteText] = useState("25");
  const [running, setRunning] = useState(false);
  const [remainingSec, setRemainingSec] = useState(25 * 60);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [note, setNote] = useState("");
  const [playlistId, setPlaylistId] = useState(PLAYLISTS[0].id);
  const [stepDraft, setStepDraft] = useState("");
  const [command, setCommand] = useState("");
  const [timerBlockId, setTimerBlockId] = useState<string | null>(null);
  const endAtRef = useRef<number | null>(null);
  const startAtRef = useRef<number | null>(null);
  const elapsedBaseRef = useRef(0);
  const finishedRef = useRef(false);
  const markingRef = useRef(false);
  const markDoneRef = useRef<() => void>(() => {});

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    getPlans()
      .then((next) => {
        if (!cancelled) {
          setPlans(next);
          setPlanError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setPlanError(err instanceof Error ? err.message : "Couldn't load the week.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [active]);

  const plan = latestPlan(plans);
  const blocks = Array.isArray(plan?.blocks) ? plan.blocks : [];
  const sorted = [...blocks].sort((left, right) => (left.start < right.start ? -1 : 1));
  const todays = today ? sorted.filter((block) => dateOf(block.start) === today) : [];
  const scheduled = (block: Block) => block.status === "scheduled";
  const current = today
    ? (todays.find(scheduled) ?? sorted.find(scheduled) ?? null)
    : null;
  if (timerBlockId === null && current) {
    setTimerBlockId(current.id);
    const minutes = blockMinutes(current);
    const seconds = minutes * 60;
    setDurationSec(seconds);
    setRemainingSec(seconds);
    setHourText(String(Math.floor(minutes / 60)));
    setMinuteText(String(minutes % 60));
    setElapsedSec(0);
    setRunning(false);
  }

  const steps = useSyncExternalStore(subscribeSteps, readSteps, () => EMPTY_STEPS);
  const finished = useSyncExternalStore(subscribeSteps, readFinished, () => EMPTY_FINISHED);
  const blockTasks: StudyTask[] = (today ? sorted : [])
    .filter((block) => block.status === "scheduled" || dateOf(block.start) >= today)
    .map((block, index) => {
      const done = block.status !== "scheduled";
      const minutes = Math.max(1, Math.round((new Date(block.end).getTime() - new Date(block.start).getTime()) / 60000));
      const when = dateOf(block.start) === today ? clock(block.end) : `${dayHeading(dateOf(block.start))} ${clock(block.end)}`;
      return {
        id: `block:${block.id}`,
        text: blockTitle(block, items),
        done,
        blockId: block.id,
        detail: `${formatSpan(minutes * 60)}, ends ${when}`,
        order: index,
        finishedAt: done ? (finished[block.id] ?? index + 1) : 0,
      };
    });
  const customTasks: StudyTask[] = steps.map((step, index) => ({
    id: step.id,
    text: step.text,
    done: step.done,
    blockId: null,
    detail: "",
    order: blockTasks.length + index,
    finishedAt: step.finishedAt,
  }));
  const openBlocks = blockTasks.filter((task) => !task.done);
  const openCustom = customTasks.filter((task) => !task.done);
  const openTasks = openBlocks.length > 0 ? [openBlocks[0], ...openCustom, ...openBlocks.slice(1)] : openCustom;
  const doneTasks = [...blockTasks, ...customTasks]
    .filter((task) => task.done)
    .sort((left, right) => left.finishedAt - right.finishedAt || left.order - right.order);
  const tasks = [...openTasks, ...doneTasks];
  const currentTask = openTasks[0] ?? null;

  function stopClock() {
    if (mode === "timer" && endAtRef.current != null) {
      const left = secondsLeft(endAtRef.current);
      setRemainingSec(left);
      endAtRef.current = null;
    }
    if (mode === "stopwatch" && startAtRef.current != null) {
      elapsedBaseRef.current = elapsedSince(startAtRef.current, elapsedBaseRef.current);
      setElapsedSec(elapsedBaseRef.current);
      startAtRef.current = null;
    }
    setRunning(false);
  }

  function play() {
    if (running) {
      stopClock();
      return;
    }
    if (mode === "timer") {
      if (remainingSec <= 0) {
        setNote("Set a time, then play.");
        return;
      }
      endAtRef.current = endAtFrom(remainingSec);
    } else {
      startAtRef.current = nowMs();
    }
    setNote("");
    setRunning(true);
  }

  function applyMinutes(totalMinutes: number) {
    const minutes = Math.round(totalMinutes);
    if (!Number.isFinite(minutes) || minutes <= 0 || minutes > 12 * 60) {
      setNote("Set a time above 0.");
      return;
    }
    setHourText(String(Math.floor(minutes / 60)));
    setMinuteText(String(minutes % 60));
    const seconds = minutes * 60;
    setDurationSec(seconds);
    setRemainingSec(seconds);
    setElapsedSec(0);
    elapsedBaseRef.current = 0;
    endAtRef.current = null;
    startAtRef.current = null;
    finishedRef.current = false;
    setRunning(false);
    setNote("");
  }

  function setFromInputs() {
    const hours = hourText.trim() === "" ? 0 : Number(hourText);
    const minutes = minuteText.trim() === "" ? 0 : Number(minuteText);
    if (!Number.isInteger(hours) || !Number.isInteger(minutes) || hours < 0 || minutes < 0 || minutes > 59) {
      setNote("Use whole hours and minutes, with minutes under 60.");
      return;
    }
    applyMinutes(hours * 60 + minutes);
  }

  function reset() {
    endAtRef.current = null;
    startAtRef.current = null;
    elapsedBaseRef.current = 0;
    finishedRef.current = false;
    setRemainingSec(durationSec);
    setElapsedSec(0);
    setRunning(false);
    setNote("");
  }

  function addMinutes(extra: number) {
    if (!Number.isFinite(extra) || extra <= 0) return;
    const add = Math.round(extra) * 60;
    setDurationSec((value) => value + add);
    if (mode === "timer") {
      setRemainingSec((value) => value + add);
      if (endAtRef.current != null) endAtRef.current += add * 1000;
      finishedRef.current = false;
    }
    setNote(`Added ${Math.round(extra)} minutes.`);
  }

  async function markDone() {
    if (!current || markingRef.current) return;
    const title = blockTitle(current, items);
    if (current.status === "done") {
      setNote(`${title} is already done.`);
      return;
    }
    markingRef.current = true;
    stopClock();
    try {
      const updated = await markBlockStatus(current.id, "done");
      rememberFinished(current.id, nowMs());
      setPlans((prev) =>
        prev.map((entry) => {
          if (entry.week_start !== plan?.week_start || entry.version !== plan.version) return entry;
          return {
            ...entry,
            blocks: entry.blocks.map((block) => (block.id === updated.id ? { ...block, status: updated.status } : block)),
          };
        }),
      );
      setNote(`Marked ${title} done.`);
    } catch (err) {
      finishedRef.current = false;
      setNote(err instanceof Error ? err.message : "Couldn't update that block.");
    } finally {
      markingRef.current = false;
    }
  }

  useEffect(() => {
    markDoneRef.current = () => {
      void markDone();
    };
  });

  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => {
      if (mode === "timer") {
        const end = endAtRef.current;
        if (end == null) return;
        const left = secondsLeft(end);
        setRemainingSec(left);
        if (left <= 0) {
          endAtRef.current = null;
          setRunning(false);
          if (!finishedRef.current) {
            finishedRef.current = true;
            markDoneRef.current();
          }
        }
      } else {
        const start = startAtRef.current;
        if (start == null) return;
        setElapsedSec(elapsedSince(start, elapsedBaseRef.current));
      }
    }, 200);
    return () => window.clearInterval(id);
  }, [running, mode]);

  function switchMode(next: Mode) {
    if (next === mode) return;
    endAtRef.current = null;
    startAtRef.current = null;
    elapsedBaseRef.current = 0;
    finishedRef.current = false;
    setMode(next);
    setRunning(false);
    setRemainingSec(durationSec);
    setElapsedSec(0);
    setNote("");
  }

  async function toggleTask(task: StudyTask) {
    if (task.blockId) {
      const nextStatus = task.done ? "scheduled" : "done";
      try {
        const updated = await markBlockStatus(task.blockId, nextStatus);
        rememberFinished(task.blockId, nextStatus === "done" ? nowMs() : null);
        setPlans((prev) =>
          prev.map((entry) => {
            if (entry.week_start !== plan?.week_start || entry.version !== plan.version) return entry;
            return {
              ...entry,
              blocks: entry.blocks.map((block) => (block.id === updated.id ? { ...block, status: updated.status } : block)),
            };
          }),
        );
      } catch (err) {
        setNote(err instanceof Error ? err.message : "Couldn't update that block.");
      }
      return;
    }
    writeSteps(
      readSteps().map((step) =>
        step.id === task.id
          ? { ...step, done: !step.done, finishedAt: step.done ? 0 : nowMs() }
          : step,
      ),
    );
  }

  function addStep(event: React.FormEvent) {
    event.preventDefault();
    const text = stepDraft.trim();
    if (!text) return;
    writeSteps([...readSteps(), { id: `${nowMs()}`, text, done: false, finishedAt: 0 }]);
    setStepDraft("");
  }

  function runCommand(event: React.FormEvent) {
    event.preventDefault();
    const text = command.trim();
    if (!text) return;
    const extend = /(?:extend|add|need)(?:\s+by)?\s+(\d+)\s*(?:min|minutes|m)\b/i.exec(text);
    if (extend) {
      addMinutes(Number(extend[1]));
      setCommand("");
      return;
    }
    if (/^(pause|stop)$/i.test(text)) {
      if (running) stopClock();
      setNote("Paused.");
      setCommand("");
      return;
    }
    if (/^(play|resume|start)$/i.test(text)) {
      if (!running) play();
      setCommand("");
      return;
    }
    if (/^reset$/i.test(text)) {
      reset();
      setCommand("");
      return;
    }
    if (/^done$/i.test(text)) {
      void markDone();
      setCommand("");
      return;
    }
    setNote("Try: extend by 20 minutes");
  }

  const shown = mode === "timer" ? remainingSec : elapsedSec;
  const title = currentTask?.text ?? "Nothing scheduled";
  const todayIndex = current ? todays.findIndex((block) => block.id === current.id) : -1;
  const meta = currentTask?.detail
    ? currentTask.detail
    : current
      ? todayIndex >= 0
        ? `Block ${todayIndex + 1} of ${todays.length} today, ends ${clock(current.end)}`
        : `${dayHeading(dateOf(current.start))}, ends ${clock(current.end)}`
      : "The timer still runs. It will not change the week.";
  const playlist = PLAYLISTS.find((item) => item.id === playlistId) ?? PLAYLISTS[0];

  return (
    <section aria-label="Study session" className="font-study text-foreground">
      <div className="grid items-start gap-10 lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-12">
        <div className="flex flex-col items-start gap-8 sm:flex-row sm:items-center sm:gap-12">
          <div className="shrink-0">
            <div className="font-study-heading text-7xl font-light leading-none tracking-tight sm:text-8xl">{formatClock(shown)}</div>
            <div className="mt-3 text-[13px] font-light text-muted-foreground">
              {mode === "timer" ? `of ${formatSpan(durationSec)}` : `elapsed, of ${formatSpan(durationSec)}`}
            </div>
          </div>

          <div className="min-w-0 w-full flex-1">
            <div className="mb-1.5 flex gap-5">
              <button type="button" className={linkClass(mode === "timer")} onClick={() => switchMode("timer")}>
                Timer
              </button>
              <button type="button" className={linkClass(mode === "stopwatch")} onClick={() => switchMode("stopwatch")}>
                Stopwatch
              </button>
            </div>
            <p className="mb-6 text-xs font-light text-muted-foreground">
              Timer counts down your block. Stopwatch counts up for open-ended sessions.
            </p>

            <div className="mb-7">
              <div className="mb-2 text-[11px] font-normal uppercase tracking-[0.08em] text-muted-foreground">Set time</div>
              <div className="flex flex-wrap items-end gap-5">
                <label className="flex flex-col gap-0.5 text-xs text-muted-foreground">
                  Hours
                  <input
                    type="number"
                    min={0}
                    max={12}
                    inputMode="numeric"
                    value={hourText}
                    onChange={(event) => setHourText(event.target.value)}
                    className="h-10 w-14 border-0 border-b border-foreground bg-transparent font-study-heading text-[26px] font-light text-foreground outline-none"
                  />
                </label>
                <label className="flex flex-col gap-0.5 text-xs text-muted-foreground">
                  Minutes
                  <input
                    type="number"
                    min={0}
                    max={59}
                    inputMode="numeric"
                    value={minuteText}
                    onChange={(event) => setMinuteText(event.target.value)}
                    className="h-10 w-14 border-0 border-b border-foreground bg-transparent font-study-heading text-[26px] font-light text-foreground outline-none"
                  />
                </label>
                <button type="button" className={linkClass(true)} onClick={setFromInputs}>
                  Set
                </button>
                <span className="pb-1.5 text-[13px] text-muted-foreground">or</span>
                {[25, 45, 90].map((preset) => (
                  <button key={preset} type="button" className={actionClass()} onClick={() => applyMinutes(preset)}>
                    {preset} min
                  </button>
                ))}
              </div>
            </div>

            <div className="text-[11px] font-normal uppercase tracking-[0.08em] text-muted-foreground">Now studying</div>
            <h2 className="mb-1.5 mt-2 font-study-heading text-4xl font-light leading-tight">{title}</h2>
            <p className="mb-6 text-sm font-light text-muted-foreground">{meta}</p>
            {planError ? (
              <p role="alert" className="mb-4 text-sm text-destructive">
                {planError}
              </p>
            ) : null}
            {note ? <p className="mb-4 text-sm font-light text-muted-foreground">{note}</p> : null}

            <div className="mb-9 flex flex-wrap gap-7">
              <button type="button" className={actionClass()} onClick={play}>
                {running ? "Pause" : "Play"}
              </button>
              <button type="button" className={actionClass()} onClick={reset}>
                Reset
              </button>
              <button type="button" className={`${actionClass()} disabled:opacity-40`} onClick={() => void markDone()} disabled={!current}>
                Done early
              </button>
              <button type="button" className={actionClass()} onClick={() => addMinutes(15)}>
                Need more time
              </button>
            </div>

            <div className="mb-1 text-[11px] font-normal uppercase tracking-[0.08em] text-muted-foreground">Tasks</div>
            {tasks.length === 0 ? (
              <p className="border-t border-foreground/15 py-3 text-sm font-light text-muted-foreground">
                Nothing else on the week. Add a task to study it here.
              </p>
            ) : (
              <ul className="m-0 list-none p-0">
                {tasks.map((task) => (
                  <li key={task.id} className="border-t border-foreground/15">
                    <label className="flex cursor-pointer items-center gap-3 py-2.5 text-sm font-light">
                      <input
                        type="checkbox"
                        checked={task.done}
                        onChange={() => void toggleTask(task)}
                        className="h-[18px] w-[18px] shrink-0 accent-primary"
                      />
                      <span className={task.done ? "text-muted-foreground line-through" : ""}>{task.text}</span>
                      {task.detail ? (
                        <span className="ml-auto shrink-0 text-[13px] text-muted-foreground">{task.detail}</span>
                      ) : null}
                    </label>
                  </li>
                ))}
              </ul>
            )}
            <form onSubmit={addStep} className="flex gap-4 border-t border-foreground/15 py-2">
              <input
                value={stepDraft}
                onChange={(event) => setStepDraft(event.target.value)}
                placeholder="Add a task"
                aria-label="Add a task"
                className="min-w-0 flex-1 border-0 bg-transparent text-sm font-light text-foreground outline-none placeholder:text-muted-foreground"
              />
              <button type="submit" className={actionClass()}>
                Add
              </button>
            </form>
          </div>
        </div>

        <aside className="flex flex-col gap-4 border-t border-foreground/20 pt-5">
          <h2 className="font-study-heading text-2xl font-light">Focus music</h2>
          <div className="flex flex-wrap gap-4">
            {PLAYLISTS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={linkClass(item.id === playlist.id)}
                onClick={() => setPlaylistId(item.id)}
              >
                {item.name}
              </button>
            ))}
          </div>
          <iframe
            title={`${playlist.name} on Spotify`}
            src={`https://open.spotify.com/embed/playlist/${playlist.id}?utm_source=generator&theme=0`}
            className="h-[152px] w-full rounded-[14px] border border-dashed border-foreground"
            allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
            loading="lazy"
          />
          <p className="text-sm font-light leading-relaxed">When the timer ends, this block is marked done.</p>
          <form onSubmit={runCommand} className="mt-2">
            <label htmlFor="study-command" className="sr-only">
              Type a command
            </label>
            <input
              id="study-command"
              type="text"
              value={command}
              onChange={(event) => setCommand(event.target.value)}
              placeholder="Try: extend by 20 minutes"
              className="box-border h-11 w-full border-0 border-b border-foreground bg-transparent text-sm font-light text-foreground outline-none placeholder:text-muted-foreground"
            />
          </form>
        </aside>
      </div>
    </section>
  );
}
