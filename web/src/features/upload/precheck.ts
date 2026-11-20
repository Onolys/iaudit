/** Advisory client pre-checks (PRD R3 step 2). The server stays authoritative. */
export const MAX_AUDIO_BYTES = 300 * 1024 * 1024;
export const MAX_DURATION_S = 25 * 60;
export const MIN_DURATION_S = 10 * 60;

const EXTENSIONS = new Set(["mp3", "wav", "m4a", "webm", "ogg"]);
const MIME_TYPES = new Set([
  "audio/mpeg",
  "audio/mp3",
  "audio/wav",
  "audio/x-wav",
  "audio/wave",
  "audio/m4a",
  "audio/x-m4a",
  "audio/mp4",
  "audio/webm",
  "audio/ogg",
  "video/webm",
]);

export const SIZE_MESSAGE = "This file is over 300 MB. Export it as m4a or mp3 and upload that instead.";
export const TYPE_MESSAGE = "We can't use this file type. Upload an mp3, wav, m4a, webm or ogg recording.";
export const LONG_MESSAGE = "This recording is longer than 25 minutes. Upload a shorter one.";
export const SHORT_WARNING =
  "This recording is under 10 minutes. Global scores can be unreliable on short sessions.";

export interface PrecheckResult {
  blocked: string | null;
  warning: string | null;
}

export interface FileInfo {
  name: string;
  size: number;
  type: string;
}

export function fileExtension(name: string): string {
  const i = name.lastIndexOf(".");
  return i < 0 ? "" : name.slice(i + 1).toLowerCase();
}

export function checkFile(file: FileInfo, durationSeconds?: number | null): PrecheckResult {
  if (file.size > MAX_AUDIO_BYTES) return { blocked: SIZE_MESSAGE, warning: null };
  if (!EXTENSIONS.has(fileExtension(file.name)) && !MIME_TYPES.has(file.type.toLowerCase())) {
    return { blocked: TYPE_MESSAGE, warning: null };
  }
  if (typeof durationSeconds === "number" && Number.isFinite(durationSeconds)) {
    if (durationSeconds > MAX_DURATION_S) return { blocked: LONG_MESSAGE, warning: null };
    if (durationSeconds < MIN_DURATION_S) return { blocked: null, warning: SHORT_WARNING };
  }
  return { blocked: null, warning: null };
}

/** Duration from audio metadata; `null` when the browser cannot read it (checks then stay silent). */
export function readDuration(file: Blob, timeoutMs = 5000): Promise<number | null> {
  return new Promise((resolve) => {
    if (typeof URL.createObjectURL !== "function") return resolve(null);
    const url = URL.createObjectURL(file);
    const audio = new Audio();
    let done = false;
    const finish = (v: number | null) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      audio.removeAttribute("src");
      URL.revokeObjectURL(url);
      resolve(v);
    };
    const timer = setTimeout(() => finish(null), timeoutMs);
    audio.preload = "metadata";
    audio.onloadedmetadata = () => finish(Number.isFinite(audio.duration) ? audio.duration : null);
    audio.onerror = () => finish(null);
    audio.src = url;
  });
}
