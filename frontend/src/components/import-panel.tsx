"use client";

import { useRef, useState } from "react";
import { importFile, importSample, importUrl } from "@/lib/api";
import type { ImportResult } from "@/lib/types";
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
import { cn } from "cn";

function summary(result: ImportResult): string {
  if (result.parsed === 0) return "No events in that feed.";
  const parts: string[] = [];
  if (result.created) parts.push(`${result.created} added`);
  if (result.updated) parts.push(`${result.updated} updated`);
  const lead = parts.length ? `${parts.join(", ")}.` : "Nothing new in that feed.";
  return `${lead} Your plan is just below.`;
}

export function ImportPanel({ onImported }: { onImported: () => Promise<void> }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  async function run(label: string, action: () => Promise<ImportResult>) {
    setBusy(label);
    setError(null);
    setMessage(null);
    try {
      const result = await action();
      await onImported();
      setMessage(summary(result));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Import Canvas feed</CardTitle>
        <CardDescription>
          Paste a Canvas iCal link, or drop a .ics file. Exams and midterms stay locked.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <form
          className="grid gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            const trimmed = url.trim();
            if (!trimmed) {
              setError("Paste a calendar URL first.");
              setMessage(null);
              return;
            }
            void run("url", () => importUrl(trimmed));
          }}
        >
          <Label htmlFor="feed-url">Canvas feed URL</Label>
          <Input
            id="feed-url"
            type="url"
            inputMode="url"
            placeholder="https://canvas.example.edu/feeds/calendars/user.ics"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            disabled={busy !== null}
          />
          <Button type="submit" disabled={busy !== null}>
            {busy === "url" ? "Importing…" : "Import Canvas feed"}
          </Button>
        </form>

        <div
          className={cn(
            "grid gap-2 rounded-lg border border-dashed border-border p-3",
            dragging && "border-primary bg-accent",
          )}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            const file = event.dataTransfer.files?.[0];
            if (!file || busy) return;
            void run("file", () => importFile(file));
          }}
        >
          <p className="text-sm text-muted-foreground">Or drop an .ics file here.</p>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={busy !== null}
              onClick={() => fileRef.current?.click()}
            >
              {busy === "file" ? "Reading file…" : "Choose .ics file"}
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={busy !== null}
              onClick={() => void run("sample", importSample)}
            >
              {busy === "sample" ? "Loading sample…" : "Load sample calendar"}
            </Button>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept=".ics,.ical,text/calendar"
            className="sr-only"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (!file) return;
              void run("file", () => importFile(file));
            }}
          />
        </div>

        {message ? (
          <p role="status" className="text-sm text-foreground">
            {message}
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
