"use client";

import { useRef, useState } from "react";
import { sendVoiceAudio, sendVoiceText } from "@/lib/api";
import type { VoiceTurn } from "@/lib/types";

function MicMark({ slashed }: { slashed: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M6 11a6 6 0 0 0 12 0" />
      <path d="M12 17v3" />
      <path d="M8 21h8" />
      {slashed ? <path d="M4 4l16 16" /> : null}
    </svg>
  );
}

const buttonStyle = { padding: "8px 12px" };

export function VoiceLoop({
  weekStart,
  onPlanned,
}: {
  weekStart?: string;
  onPlanned: (turn: VoiceTurn) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [speak, setSpeak] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [reply, setReply] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const speakRef = useRef(false);
  const wantRecording = useRef(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const startedAt = useRef(0);

  function showTurn(turn: VoiceTurn) {
    setTranscript(turn.transcript);
    setReply(turn.reply);
    onPlanned(turn);
    if (speakRef.current && turn.reply && typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(turn.reply));
    }
  }

  async function submitText(event?: React.FormEvent) {
    event?.preventDefault();
    const text = inputRef.current?.value.trim() ?? "";
    if (!text || busy || listening) {
      if (!text) setError("Type a request, then press Send.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const turn = await sendVoiceText(text, weekStart);
      if (inputRef.current) inputRef.current.value = "";
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

  function stopTracks(stream: MediaStream) {
    stream.getTracks().forEach((track) => track.stop());
  }

  async function beginRecording() {
    if (listening || busy) return;
    wantRecording.current = true;
    startedAt.current = Date.now();
    setListening(true);
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      wantRecording.current = false;
      setListening(false);
      setError("This browser can't record. Type the request instead.");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      wantRecording.current = false;
      setListening(false);
      setError("Allow the microphone to talk, or type instead.");
      return;
    }
    if (!wantRecording.current) {
      stopTracks(stream);
      setListening(false);
      return;
    }
    const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
    const recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    recorder.onstop = () => {
      stopTracks(stream);
      recorderRef.current = null;
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      void sendRecording(blob);
    };
    recorderRef.current = recorder;
    recorder.start();
    setListening(true);
  }

  function finishRecording() {
    wantRecording.current = false;
    const recorder = recorderRef.current;
    setListening(false);
    if (recorder && recorder.state === "recording") {
      recorder.stop();
      return;
    }
    recorderRef.current = null;
  }

  function onTalkPointerDown(event: React.PointerEvent<HTMLButtonElement>) {
    if (busy) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    if (listening) {
      finishRecording();
      return;
    }
    void beginRecording();
  }

  function onTalkPointerUp(event: React.PointerEvent<HTMLButtonElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    const recorder = recorderRef.current;
    const held = Date.now() - startedAt.current;
    if (recorder?.state === "recording" && held > 350) {
      finishRecording();
    }
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
      <form onSubmit={submitText} style={{ display: "grid", gap: 8 }}>
        <input
          ref={inputRef}
          aria-label="Request"
          placeholder="Move Thursday's quiz, or plan the rest of the week"
          disabled={busy || listening}
          onChange={() => {
            if (error) setError(null);
          }}
          style={{ width: "100%", boxSizing: "border-box", padding: "8px 12px" }}
        />
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <button type="submit" disabled={busy} style={buttonStyle}>
            {busy && !listening ? "Sending…" : "Send"}
          </button>
          <button
            type="button"
            disabled={busy && !listening}
            onPointerDown={onTalkPointerDown}
            onPointerUp={onTalkPointerUp}
            onPointerCancel={onTalkPointerUp}
            style={buttonStyle}
          >
            {listening ? "Stop and send" : "Hold to talk"}
          </button>
          <button
            type="button"
            aria-pressed={speak}
            aria-label={speak ? "Stop speaking replies" : "Speak replies"}
            onClick={toggleSpeak}
            style={{ ...buttonStyle, display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            <MicMark slashed={!speak} />
            {speak ? "Speak on" : "Speak off"}
          </button>
        </div>
      </form>
      <p style={{ margin: "8px 0 0", color: "#666", fontSize: 14 }}>
        Hold the talk button, or press it and press Stop and send. Replies stay on screen. Speech stays off until Speak is on.
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
