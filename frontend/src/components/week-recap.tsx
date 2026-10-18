"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { getPlans } from "@/lib/api";
import { PACIFIC } from "@/lib/format";
import { buildRecap, streakLabel, type WeekRecapStats } from "@/lib/recap";
import type { WeekPlan } from "@/lib/types";
import { Button } from "@/components/ui/button";

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

function colors(): { bg: string; fg: string; muted: string } {
  const body = getComputedStyle(document.body);
  const probe = document.createElement("span");
  probe.className = "text-muted-foreground";
  document.body.appendChild(probe);
  const muted = getComputedStyle(probe).color;
  probe.remove();
  return { bg: body.backgroundColor, fg: body.color, muted };
}

async function drawRecap(recap: WeekRecapStats): Promise<Blob> {
  await document.fonts.load('italic 300 86px Fraunces');
  await document.fonts.load("300 220px Fraunces");
  await document.fonts.load('300 28px "DM Sans"');
  const width = 1080;
  const height = 1350;
  const canvas = document.createElement("canvas");
  canvas.width = width * 2;
  canvas.height = height * 2;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Couldn't draw the recap.");
  const { bg, fg, muted } = colors();
  ctx.scale(2, 2);
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = fg;
  ctx.globalAlpha = 0.16;
  ctx.lineWidth = 2;
  ctx.strokeRect(40, 40, width - 80, height - 80);
  ctx.globalAlpha = 1;
  ctx.textBaseline = "top";

  ctx.fillStyle = fg;
  ctx.font = "italic 300 92px Fraunces, Georgia, serif";
  ctx.fillText("Quill", 88, 108);

  ctx.fillStyle = muted;
  ctx.font = '300 30px "DM Sans", sans-serif';
  ctx.fillText(recap.weekLabel, 88, 220);

  ctx.fillStyle = fg;
  ctx.font = "300 240px Fraunces, Georgia, serif";
  ctx.fillText(String(recap.done), 88, 360);

  ctx.fillStyle = muted;
  ctx.font = '300 40px "DM Sans", sans-serif';
  ctx.fillText(recap.planned === 0 ? "No blocks planned" : `of ${recap.planned} blocks`, 92, 630);

  const ratio = recap.planned === 0 ? 0 : recap.done / recap.planned;
  ctx.fillStyle = fg;
  ctx.globalAlpha = 0.12;
  ctx.fillRect(88, 720, width - 176, 3);
  ctx.globalAlpha = 1;
  ctx.fillRect(88, 720, Math.max(0, (width - 176) * ratio), 3);

  ctx.fillStyle = muted;
  ctx.font = '400 22px "DM Sans", sans-serif';
  ctx.fillText("STREAK", 88, 790);
  ctx.fillStyle = fg;
  ctx.font = "300 64px Fraunces, Georgia, serif";
  ctx.fillText(streakLabel(recap.streak), 88, 832);

  ctx.fillStyle = muted;
  ctx.font = '400 22px "DM Sans", sans-serif';
  ctx.fillText("HEAVIEST DAY SURVIVED", 88, 980);
  ctx.fillStyle = fg;
  ctx.font = "300 64px Fraunces, Georgia, serif";
  ctx.fillText(recap.heaviest?.day ?? "—", 88, 1022);
  ctx.fillStyle = muted;
  ctx.font = '300 30px "DM Sans", sans-serif';
  ctx.fillText(recap.heaviest?.detail ?? "Nothing on the week yet", 88, 1104);

  ctx.fillText("Focus", 88, 1224);

  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("Couldn't save the recap.");
  return blob;
}

export function WeekRecap({
  plans,
  active,
  onPlans,
}: {
  plans: WeekPlan[];
  active: boolean;
  onPlans: (plans: WeekPlan[]) => void;
}) {
  const today = useSyncExternalStore(subscribeToday, pacificToday, () => "");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const recap = buildRecap(plans, today);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    getPlans()
      .then((next) => {
        if (!cancelled) onPlans(next);
      })
      .catch(() => {
        if (!cancelled) setNote("Couldn't refresh the recap.");
      });
    return () => {
      cancelled = true;
    };
  }, [active, onPlans]);

  async function download() {
    setBusy(true);
    setNote("");
    try {
      const blob = await drawRecap(recap);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `quill-${recap.weekStart || "week"}.png`;
      link.click();
      URL.revokeObjectURL(url);
      setNote("Downloaded the recap.");
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Couldn't download the recap.");
    } finally {
      setBusy(false);
    }
  }

  async function copyOrShare() {
    setBusy(true);
    setNote("");
    try {
      const blob = await drawRecap(recap);
      const file = new File([blob], `quill-${recap.weekStart || "week"}.png`, { type: "image/png" });
      if (typeof navigator.share === "function" && navigator.canShare?.({ files: [file] })) {
        try {
          await navigator.share({ files: [file], title: "Quill" });
          setNote("Shared the recap.");
          return;
        } catch (err) {
          if (err instanceof Error && err.name === "AbortError") return;
        }
      }
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
      setNote("Copied the recap.");
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Couldn't copy the recap. Download it instead.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Weekly recap" className="flex flex-col gap-4 sm:flex-row sm:items-end">
      <article className="font-study flex aspect-[4/5] w-full max-w-[320px] flex-col border border-foreground/15 bg-background p-6 text-foreground">
        <p className="font-study-heading text-4xl font-light italic leading-none">Quill</p>
        <p className="mt-2 text-xs font-light uppercase tracking-[0.08em] text-muted-foreground">{recap.weekLabel}</p>
        <p className="mt-8 font-study-heading text-7xl font-light leading-none">{recap.done}</p>
        <p className="mt-2 text-sm font-light text-muted-foreground">
          {recap.planned === 0 ? "No blocks planned" : `of ${recap.planned} blocks`}
        </p>
        <div className="mt-5 h-[3px] w-full bg-foreground/15">
          <div
            className="h-full bg-foreground"
            style={{ width: recap.planned === 0 ? "0%" : `${Math.round((recap.done / recap.planned) * 100)}%` }}
          />
        </div>
        <p className="mt-5 text-[11px] font-normal uppercase tracking-[0.08em] text-muted-foreground">Streak</p>
        <p className="font-study-heading text-3xl font-light leading-tight">{streakLabel(recap.streak)}</p>
        <p className="mt-4 text-[11px] font-normal uppercase tracking-[0.08em] text-muted-foreground">Heaviest day survived</p>
        <p className="font-study-heading text-3xl font-light leading-tight">{recap.heaviest?.day ?? "—"}</p>
        <p className="mt-1 text-sm font-light text-muted-foreground">{recap.heaviest?.detail ?? "Nothing on the week yet"}</p>
        <p className="mt-auto pt-6 text-sm font-light text-muted-foreground">Focus</p>
      </article>
      <div className="flex flex-col items-start gap-2">
        <Button type="button" variant="outline" disabled={busy} onClick={() => void download()}>
          Download
        </Button>
        <Button type="button" variant="outline" disabled={busy} onClick={() => void copyOrShare()}>
          Copy or share
        </Button>
        <p className="max-w-xs text-sm text-muted-foreground">{note || "A picture of this week for a story or a group chat."}</p>
      </div>
    </section>
  );
}
