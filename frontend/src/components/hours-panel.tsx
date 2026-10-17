"use client";

import { useState } from "react";
import { saveProfile } from "@/lib/api";
import { DAY_LABEL } from "@/lib/format";
import type { Commitment, Day, Profile, StudyWindow } from "@/lib/types";
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

function clockOrder(start: string, end: string): boolean {
  return Boolean(start) && Boolean(end) && end > start;
}

export function HoursPanel({
  profile,
  onSaved,
}: {
  profile: Profile;
  onSaved: (profile: Profile) => void;
}) {
  const [draft, setDraft] = useState(profile);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function updateWindow(index: number, patch: Partial<StudyWindow>) {
    setDraft((current) => ({
      ...current,
      preferred_study_windows: current.preferred_study_windows.map((window, itemIndex) =>
        itemIndex === index ? { ...window, ...patch } : window,
      ),
    }));
    setSaved(false);
  }

  function updateCommitment(index: number, patch: Partial<Commitment>) {
    setDraft((current) => ({
      ...current,
      fixed_commitments: current.fixed_commitments.map((commitment, itemIndex) =>
        itemIndex === index ? { ...commitment, ...patch } : commitment,
      ),
    }));
    setSaved(false);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Hours you can study</CardTitle>
        <CardDescription>
          Wake, sleep, classes that do not move, and the windows you actually like to work in.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!clockOrder(draft.waking_hours.wake, draft.waking_hours.sleep)) {
              setError("Sleep must be later than wake on the same day.");
              setSaved(false);
              return;
            }
            const capacity = Number(draft.daily_capacity_hours);
            if (!Number.isFinite(capacity) || capacity < 0 || capacity > 18) {
              setError("Daily capacity must be between 0 and 18 hours.");
              setSaved(false);
              return;
            }
            for (const window of draft.preferred_study_windows) {
              if (!clockOrder(window.start, window.end)) {
                setError("Each study window needs an end after its start.");
                setSaved(false);
                return;
              }
            }
            for (const commitment of draft.fixed_commitments) {
              if (!commitment.title.trim()) {
                setError("Name each commitment, or remove the blank one.");
                setSaved(false);
                return;
              }
              if (!clockOrder(commitment.start, commitment.end)) {
                setError("Each commitment needs an end after its start.");
                setSaved(false);
                return;
              }
            }
            const payload: Profile = {
              waking_hours: draft.waking_hours,
              daily_capacity_hours: capacity,
              preferred_study_windows: draft.preferred_study_windows,
              fixed_commitments: draft.fixed_commitments.map((commitment) => ({
                ...(commitment.id ? { id: commitment.id } : {}),
                title: commitment.title.trim(),
                course: commitment.course?.trim() || null,
                day: commitment.day,
                start: commitment.start,
                end: commitment.end,
              })),
            };
            setBusy(true);
            setError(null);
            void saveProfile(payload)
              .then((savedProfile) => {
                setDraft(savedProfile);
                onSaved(savedProfile);
                setSaved(true);
              })
              .catch((err: unknown) => {
                setSaved(false);
                setError(err instanceof Error ? err.message : "Could not save hours.");
              })
              .finally(() => setBusy(false));
          }}
        >
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="wake">Wake</Label>
              <Input
                id="wake"
                type="time"
                value={draft.waking_hours.wake}
                onChange={(event) => {
                  setSaved(false);
                  setDraft((current) => ({
                    ...current,
                    waking_hours: { ...current.waking_hours, wake: event.target.value },
                  }));
                }}
                required
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="sleep">Sleep</Label>
              <Input
                id="sleep"
                type="time"
                value={draft.waking_hours.sleep}
                onChange={(event) => {
                  setSaved(false);
                  setDraft((current) => ({
                    ...current,
                    waking_hours: { ...current.waking_hours, sleep: event.target.value },
                  }));
                }}
                required
              />
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="capacity">Hours you can study in a day</Label>
            <Input
              id="capacity"
              type="number"
              min={0}
              max={18}
              step={0.5}
              value={draft.daily_capacity_hours}
              onChange={(event) => {
                setSaved(false);
                setDraft((current) => ({
                  ...current,
                  daily_capacity_hours: Number(event.target.value),
                }));
              }}
              required
            />
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-medium">Preferred study windows</h3>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setSaved(false);
                  setDraft((current) => ({
                    ...current,
                    preferred_study_windows: [
                      ...current.preferred_study_windows,
                      { day: "mon", start: "19:00", end: "22:00" },
                    ],
                  }));
                }}
              >
                Add window
              </Button>
            </div>
            {draft.preferred_study_windows.length === 0 ? (
              <p className="text-sm text-muted-foreground">No preferred windows yet.</p>
            ) : (
              draft.preferred_study_windows.map((window, index) => (
                <div key={index} className="grid gap-2 rounded-lg border border-border p-3">
                  <ChoiceSelect
                    label={`Study window ${index + 1} day`}
                    value={window.day}
                    items={DAY_LABEL}
                    onValueChange={(value) => updateWindow(index, { day: value as Day })}
                  />
                  <div className="grid grid-cols-2 gap-2">
                    <Input
                      type="time"
                      aria-label={`Study window ${index + 1} start`}
                      value={window.start}
                      onChange={(event) => updateWindow(index, { start: event.target.value })}
                    />
                    <Input
                      type="time"
                      aria-label={`Study window ${index + 1} end`}
                      value={window.end}
                      onChange={(event) => updateWindow(index, { end: event.target.value })}
                    />
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setSaved(false);
                      setDraft((current) => ({
                        ...current,
                        preferred_study_windows: current.preferred_study_windows.filter(
                          (_, itemIndex) => itemIndex !== index,
                        ),
                      }));
                    }}
                  >
                    Remove window
                  </Button>
                </div>
              ))
            )}
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-medium">Fixed weekly commitments</h3>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setSaved(false);
                  setDraft((current) => ({
                    ...current,
                    fixed_commitments: [
                      ...current.fixed_commitments,
                      { title: "", course: null, day: "tue", start: "10:00", end: "11:20" },
                    ],
                  }));
                }}
              >
                Add commitment
              </Button>
            </div>
            {draft.fixed_commitments.length === 0 ? (
              <p className="text-sm text-muted-foreground">No classes or shifts yet.</p>
            ) : (
              draft.fixed_commitments.map((commitment, index) => (
                <div key={commitment.id ?? `new-${index}`} className="grid gap-2 rounded-lg border border-border p-3">
                  <Input
                    aria-label={`Commitment ${index + 1} title`}
                    value={commitment.title}
                    placeholder="CSE 414 lecture"
                    onChange={(event) => updateCommitment(index, { title: event.target.value })}
                  />
                  <div className="grid grid-cols-2 gap-2">
                    <Input
                      aria-label={`Commitment ${index + 1} course`}
                      value={commitment.course ?? ""}
                      placeholder="Course"
                      onChange={(event) =>
                        updateCommitment(index, { course: event.target.value || null })
                      }
                    />
                    <ChoiceSelect
                      label={`Commitment ${index + 1} day`}
                      value={commitment.day}
                      items={DAY_LABEL}
                      onValueChange={(value) => updateCommitment(index, { day: value as Day })}
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <Input
                      type="time"
                      aria-label={`Commitment ${index + 1} start`}
                      value={commitment.start}
                      onChange={(event) => updateCommitment(index, { start: event.target.value })}
                    />
                    <Input
                      type="time"
                      aria-label={`Commitment ${index + 1} end`}
                      value={commitment.end}
                      onChange={(event) => updateCommitment(index, { end: event.target.value })}
                    />
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setSaved(false);
                      setDraft((current) => ({
                        ...current,
                        fixed_commitments: current.fixed_commitments.filter(
                          (_, itemIndex) => itemIndex !== index,
                        ),
                      }));
                    }}
                  >
                    Remove commitment
                  </Button>
                </div>
              ))
            )}
          </div>

          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          {saved ? (
            <p role="status" className="text-sm text-foreground">
              Hours saved.
            </p>
          ) : null}
          <Button type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save hours"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
