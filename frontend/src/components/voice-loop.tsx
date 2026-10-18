"use client";

import { useRef, useState } from "react";
import { sendVoiceAudio, sendVoiceText } from "@/lib/api";
import type { VoiceTurn } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function MicMark({ slashed }: { slashed: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M6 11a6 6 0 0 0 12 0" />
      <path d="M12 17v3" />
      <path d="M8 21h8" />
      {slashed ? <path d="M4 4l16 16" /> : null}
    </svg>
  );
}

export function VoiceLoop({
  weekStart,
  onPlanned,
}: {
  weekStart?: string;
  onPlanned: (turn: VoiceTurn) => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [speak, setSpeak] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [reply, setReply] = useState("");
  const [error, setError] = useState<string | null>(null);
  const speakRef = useRef(false);
  const wantRecording = useRef(false);
  const recorderRef = useRef<MediaRecorder | null>(null);

  function showTurn(turn: VoiceTurn) {
    setTranscript(turn.transcript);
    setReply(turn.reply);
    onPlanned(turn);
    if (speakRef.current && turn.reply && typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(turn.reply));
    }
  }

  async function submitText(event: React.FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy || recording) return;
    setBusy(true);
    setError(null);
    try {
      const turn = await sendVoiceText(text, weekStart);
      setDraft("");
      showTurn(turn);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send that request.");
    } finally {
      setBusy(false);
    }
  }

  async function sendRecording(blob: Blob) {
    if (blob.size < 100) {
      setError("I didn't catch any audio.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const turn = await sendVoiceAudio(blob, weekStart);
      showTurn(turn);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send that recording.");
    } finally {
      setBusy(false);
    }
  }

  async function startTalking() {
    wantRecording.current = true;
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("This browser can't record. Type the request instead.");
      wantRecording.current = false;
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      wantRecording.current = false;
      setError("Allow the microphone to talk, or type instead.");
      return;
    }
    if (!wantRecording.current) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
    const recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    recorder.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      void sendRecording(blob);
    };
    recorderRef.current = recorder;
    recorder.start();
    setRecording(true);
  }

  function stopTalking() {
    wantRecording.current = false;
    const recorder = recorderRef.current;
    if (recorder && recorder.state === "recording") {
      recorder.stop();
    }
    setRecording(false);
  }

  function onPointerDown(event: React.PointerEvent<HTMLButtonElement>) {
    if (busy) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    void startTalking();
  }

  function onPointerUp(event: React.PointerEvent<HTMLButtonElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    stopTalking();
  }

  function toggleSpeak() {
    setSpeak((current) => {
      const next = !current;
      speakRef.current = next;
      if (!next && typeof window !== "undefined" && window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
      return next;
    });
  }

  return (
    <div style={{ marginBottom: 16 }}>
      <form onSubmit={submitText} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <Input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Move Thursday's quiz, or plan the rest of the week"
          aria-label="Request"
          disabled={busy || recording}
          className="min-w-64 flex-1 bg-white"
        />
        <Button type="submit" disabled={busy || recording || !draft.trim()}>
          {busy && !recording ? "Sending…" : "Send"}
        </Button>
        <Button
          type="button"
          variant={recording ? "destructive" : "secondary"}
          disabled={busy && !recording}
          onPointerDown={onPointerDown}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          {recording ? "Listening…" : "Hold to talk"}
        </Button>
        <Button
          type="button"
          variant={speak ? "default" : "outline"}
          size="icon"
          aria-pressed={speak}
          aria-label={speak ? "Stop speaking replies" : "Speak replies"}
          title={speak ? "Replies are spoken" : "Replies are silent"}
          onClick={toggleSpeak}
        >
          <MicMark slashed={!speak} />
        </Button>
      </form>
      <p style={{ margin: "8px 0 0", color: "#666", fontSize: 14 }}>
        Replies stay on screen. Speech stays off until you turn the mic on.
      </p>
      {error ? (
        <p role="alert" style={{ border: "2px solid #b42318", background: "#fff4f2", color: "#7a1b12", padding: 12, borderRadius: 8, marginTop: 8 }}>
          {error}
        </p>
      ) : null}
      {transcript || reply ? (
        <div style={{ marginTop: 12 }}>
          {transcript ? (
            <p style={{ margin: "0 0 6px" }}>
              <strong>You:</strong> {transcript}
            </p>
          ) : null}
          {reply ? (
            <p style={{ margin: 0 }}>
              <strong>Desk:</strong> {reply}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
