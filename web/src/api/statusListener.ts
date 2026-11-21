/**
 * Status-subscription seam (PRD R4/R7, D7). The session page subscribes to a
 * PHI-free `session_status/{id}` doc. Live mode backs this with Firestore
 * `onSnapshot` (a later task); mock mode uses the in-memory emitter below,
 * driven by the MSW state machine.
 */
import type { SessionState } from "./types";

export interface SessionStatusDoc {
  uid: string;
  state: SessionState;
  step: string | null;
  progress: number;
  error_code: string | null;
  latest_report_version: number | null;
  updated_at: string;
  transcript_ready: boolean;
  speaker_confirmed: boolean;
  rating_submitted: boolean;
  has_rating: boolean;
}

export type Unsubscribe = () => void;

export interface StatusListener {
  /**
   * `onStatus(null)` = the doc does not exist (deleted). `onError` = listener
   * failure or permission-denied; the caller falls back to one `GET /sessions/{id}`.
   */
  subscribe(
    sessionId: string,
    onStatus: (doc: SessionStatusDoc | null) => void,
    onError: (err: Error) => void,
  ): Unsubscribe;
}

export interface MemoryStatusEmitter extends StatusListener {
  emit(sessionId: string, doc: SessionStatusDoc): void;
  emitError(sessionId: string, err: Error): void;
  remove(sessionId: string): void;
  clear(): void;
}

interface Sub {
  onStatus: (doc: SessionStatusDoc | null) => void;
  onError: (err: Error) => void;
}

export function createMemoryStatusEmitter(): MemoryStatusEmitter {
  const docs = new Map<string, SessionStatusDoc>();
  const subs = new Map<string, Set<Sub>>();

  const forEach = (sid: string, fn: (s: Sub) => void) => {
    for (const s of [...(subs.get(sid) ?? [])]) fn(s);
  };

  return {
    subscribe(sessionId, onStatus, onError) {
      const sub: Sub = { onStatus, onError };
      let set = subs.get(sessionId);
      if (!set) subs.set(sessionId, (set = new Set()));
      set.add(sub);
      const current = docs.get(sessionId);
      if (current) onStatus({ ...current });
      return () => {
        subs.get(sessionId)?.delete(sub);
      };
    },
    emit(sessionId, doc) {
      docs.set(sessionId, { ...doc });
      forEach(sessionId, (s) => s.onStatus({ ...doc }));
    },
    emitError(sessionId, err) {
      forEach(sessionId, (s) => s.onError(err));
    },
    remove(sessionId) {
      docs.delete(sessionId);
      forEach(sessionId, (s) => s.onStatus(null));
    },
    clear() {
      docs.clear();
      subs.clear();
    },
  };
}

let active: StatusListener | null = null;

export function setStatusListener(listener: StatusListener | null): void {
  active = listener;
}

export function getStatusListener(): StatusListener {
  if (!active) throw new Error("No status listener registered (set one at app start).");
  return active;
}
