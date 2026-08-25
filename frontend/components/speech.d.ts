interface SpeechRecognitionEvent extends Event { resultIndex: number; results: SpeechRecognitionResultList; }
interface SpeechRecognition extends EventTarget { lang: string; continuous: boolean; interimResults: boolean; onresult: ((event: SpeechRecognitionEvent) => void) | null; onerror: (() => void) | null; onend: (() => void) | null; start(): void; stop(): void; }
declare var SpeechRecognition: { new (): SpeechRecognition };
declare global { interface Window { SpeechRecognition?: typeof SpeechRecognition; webkitSpeechRecognition?: typeof SpeechRecognition; } }
export {};
