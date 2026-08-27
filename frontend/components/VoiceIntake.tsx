"use client";

import { useRef, useState } from "react";
import { sendVoice } from "@/lib/api";
import { IconMic } from "./Icons";

const languages = [
  ["en-US", "English"],
  ["hi-IN", "Hindi"],
  ["bn-IN", "Bengali"],
  ["es-ES", "Spanish"],
  ["fr-FR", "French"],
  ["ar-SA", "Arabic"],
  ["zh-CN", "Mandarin"],
  ["pt-BR", "Portuguese"],
  ["ru-RU", "Russian"],
];

type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: SpeechRecognitionResultList;
};
type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};
type SpeechRecognitionType = new () => SpeechRecognitionLike;

export default function VoiceIntake({ onSent, onTranscript, submitToBackend = true }: { onSent?: () => void; onTranscript?: (text: string) => void; submitToBackend?: boolean }) {
  const [language, setLanguage] = useState("en-US");
  const [text, setText] = useState("");
  const [status, setStatus] = useState("");
  const [recording, setRecording] = useState(false);
  const recognition = useRef<SpeechRecognitionLike | null>(null);
  const finalText = useRef("");

  function startListening() {
    const SpeechRecognition = (window.SpeechRecognition ||
      window.webkitSpeechRecognition) as SpeechRecognitionType | undefined;
    if (!SpeechRecognition) {
      setStatus(
        "Speech recognition is unavailable. Type the account below instead.",
      );
      return;
    }
    const instance = new SpeechRecognition();
    instance.lang = language;
    instance.continuous = true;
    instance.interimResults = true;
    finalText.current = text ? `${text} ` : "";
    instance.onresult = (event) => {
      let interim = "";
      for (
        let index = event.resultIndex;
        index < event.results.length;
        index++
      ) {
        const transcript = event.results[index][0].transcript;
        if (event.results[index].isFinal) finalText.current += `${transcript} `;
        else interim += transcript;
      }
      setText(`${finalText.current}${interim}`.trim());
    };
    const stop = () => {
      setRecording(false);
      setStatus("");
    };
    instance.onerror = stop;
    instance.onend = stop;
    instance.start();
    recognition.current = instance;
    setRecording(true);
    setStatus("Listening...");
  }

  async function submit() {
    const transcript = text.trim();
    if (!transcript) {
      setStatus("Nothing to send yet.");
      return;
    }
    if (recording) recognition.current?.stop();
    if (!submitToBackend) {
      onTranscript?.(transcript);
      setStatus("Dictation appended to the assessment.");
      setText("");
      return;
    }
    setStatus("Translating & extracting...");
    const result = await sendVoice(transcript, language);
    
    if (result.ok) {
      setStatus(
        `${result.display_id} added - \"${result.complaint}\"${result.age ? `, age ${result.age}` : ""}.`,
      );
      setText("");
      onSent?.();
    } else setStatus(result.error || "Voice intake failed.");
  }

  if (!submitToBackend) return <div className="inline-voice"><button className={`mic ${recording ? "on" : ""}`} onClick={() => recording ? recognition.current?.stop() : startListening()}><IconMic width={15} height={15} />{recording ? "Stop dictation" : "Start dictation"}</button><button className="mini ok" onClick={submit}>Append dictation</button><span className="voice-status">{status}</span></div>;

  return (
    <section className="voice">
      <div className="voice-hd">
        <span className="l0 v">Voice intake</span>
        <b>Speak for a patient who doesn't share your language</b>
        <span className="sub">Translates &amp; extracts on the fly</span>
      </div>
      <div className="voice-body">
        <div className="voice-ctrl">
          <select
            value={language}
            onChange={(event) => setLanguage(event.target.value)}
          >
            {languages.map(([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ))}
          </select>
          <button
            className={`mic ${recording ? "on" : ""}`}
            onClick={() =>
              recording ? recognition.current?.stop() : startListening()
            }
          >
            <IconMic width={15} height={15} />
            {recording ? "Stop" : "Start"}
          </button>
          <button className="mini ok" onClick={submit}>
            Send to PULSE
          </button>
        </div>
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Transcript appears here as you speak - or just type it directly."
        />
        <div className="voice-status">{status}</div>
      </div>
    </section>
  );
}
