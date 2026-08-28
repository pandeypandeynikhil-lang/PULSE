"use client";

import { useRef, useState } from "react";
import { sendVoice, translateDictation } from "@/lib/api";
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
      // This dictation lands directly in a chart field a nurse reads — the
      // same reason Voice Intake proper translates before it will show
      // anyone text. Always routed through translation, regardless of the
      // language dropdown: the dropdown is what the *recognizer* used, not
      // a guarantee of what the speaker actually said, and a Hindi speaker
      // dictated against an English recognizer produces exactly the kind
      // of garbled Latin-script mis-transcription that looks nothing like
      // real English and would sail through untouched if we trusted the
      // dropdown. The translation prompt already returns lightly-cleaned
      // text unchanged when it genuinely is English, so this costs an
      // extra round trip on true-English dictation and nothing else.
      setStatus("Translating dictation...");
      const result = await translateDictation(transcript, language);
      if (result.ok && result.translation) {
        onTranscript?.(result.translation);
        setStatus("Dictation translated to English and appended.");
      } else {
        onTranscript?.(transcript);
        setStatus(
          `Translation unavailable — appended as recognised. ${result.error || "Review and translate before submitting."}`,
        );
      }
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
