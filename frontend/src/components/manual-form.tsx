"use client";

import { useEffect, useState } from "react";
import { classify, createItem } from "@/lib/api";
import { TYPE_LABEL } from "@/lib/format";
import type { ItemType } from "@/lib/types";
import { ChoiceSelect } from "@/components/choice-select";
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
import { Textarea } from "@/components/ui/textarea";

const TYPES = Object.keys(TYPE_LABEL) as ItemType[];

export function ManualForm({ onCreated }: { onCreated: () => Promise<void> }) {
  const [title, setTitle] = useState("");
  const [course, setCourse] = useState("");
  const [type, setType] = useState<ItemType>("assignment");
  const [typeTouched, setTypeTouched] = useState(false);
  const [due, setDue] = useState("");
  const [effort, setEffort] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const trimmed = title.trim();
    if (typeTouched || trimmed.length < 3) return;
    let cancelled = false;
    const handle = window.setTimeout(() => {
      void classify(trimmed)
        .then((result) => {
          if (cancelled || !result.matched) return;
          setType(result.type);
        })
        .catch(() => {
          // A suggestion is optional. The typed deadline still saves.
        });
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [title, typeTouched]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Add by hand</CardTitle>
        <CardDescription>
          Use this when there is no feed. A course code in the title, like CSE 414, is picked up
          automatically.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            const trimmedTitle = title.trim();
            if (!trimmedTitle || !due) {
              setError("Add a title and a due time.");
              return;
            }
            let estimated: number | null = null;
            if (effort.trim()) {
              estimated = Number(effort);
              if (!Number.isFinite(estimated) || estimated < 0 || estimated > 100) {
                setError("Effort must be between 0 and 100 hours.");
                return;
              }
            }
            setBusy(true);
            setError(null);
            void createItem({
              title: trimmedTitle,
              course: course.trim() || null,
              type,
              due_or_start: due,
              estimated_effort_hours: estimated,
              description: notes.trim(),
            })
              .then(async () => {
                setTitle("");
                setCourse("");
                setNotes("");
                setEffort("");
                setDue("");
                setType("assignment");
                setTypeTouched(false);
                await onCreated();
              })
              .catch((err: unknown) => {
                setError(err instanceof Error ? err.message : "Could not add that deadline.");
              })
              .finally(() => setBusy(false));
          }}
        >
          <div className="grid gap-1.5">
            <Label htmlFor="manual-title">Title</Label>
            <Input
              id="manual-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="MATH 207 problem set 4"
              disabled={busy}
              required
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="manual-course">Course</Label>
              <Input
                id="manual-course"
                value={course}
                onChange={(event) => setCourse(event.target.value)}
                placeholder="Optional"
                disabled={busy}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="manual-type">Type</Label>
              <ChoiceSelect
                id="manual-type"
                label="Type"
                value={type}
                items={TYPE_LABEL}
                onValueChange={(value) => {
                  if (TYPES.includes(value as ItemType)) {
                    setTypeTouched(true);
                    setType(value as ItemType);
                  }
                }}
              />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="manual-due">Due (Pacific time)</Label>
              <Input
                id="manual-due"
                type="datetime-local"
                value={due}
                onChange={(event) => setDue(event.target.value)}
                disabled={busy}
                required
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="manual-effort">Effort (hours)</Label>
              <Input
                id="manual-effort"
                type="number"
                min={0}
                max={100}
                step={0.5}
                value={effort}
                onChange={(event) => setEffort(event.target.value)}
                placeholder="Optional"
                disabled={busy}
              />
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="manual-notes">Notes</Label>
            <Textarea
              id="manual-notes"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Optional"
              disabled={busy}
            />
          </div>
          {type === "exam" ? (
            <p className="text-sm text-muted-foreground">
              Exams are locked, so a later schedule will not move them.
            </p>
          ) : null}
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          <Button type="submit" disabled={busy}>
            {busy ? "Adding…" : "Add deadline"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
