/**
 * Live status listener (PRD R4, R7, R8, D7): Firestore `onSnapshot` on the PHI-free
 * `session_status/{id}` doc. Firestore is initialised with a memory cache (no IndexedDB),
 * the named database from `VITE_FIRESTORE_DATABASE` and, in dev, the emulator from
 * `VITE_FIRESTORE_EMULATOR` (`host:port`). `firebase/firestore` loads lazily.
 */
import type { SessionStatusDoc, StatusListener } from "./statusListener";

export interface FirestoreListenerConfig {
  /** `staging` or `(default)`. */
  database?: string;
  /** `host:port` of the Firestore emulator; omit in deployed builds. */
  emulator?: string;
}

type Firestore = import("firebase/firestore").Firestore;
let dbPromise: Promise<Firestore> | null = null;

/** Test seam: forget the cached Firestore instance. */
export function resetFirestoreForTests(): void {
  dbPromise = null;
}

function getDb(config: FirestoreListenerConfig): Promise<Firestore> {
  dbPromise ??= (async () => {
    const [{ getApp }, fs] = await Promise.all([import("firebase/app"), import("firebase/firestore")]);
    const db = fs.initializeFirestore(getApp(), { localCache: fs.memoryLocalCache() }, config.database || "(default)");
    if (config.emulator) {
      const [host, port] = config.emulator.split(":");
      fs.connectFirestoreEmulator(db, host, Number(port));
    }
    return db;
  })();
  dbPromise.catch(() => {
    dbPromise = null; // allow a retry on the next subscribe
  });
  return dbPromise;
}

const iso = (v: unknown): string => {
  if (typeof v === "string") return v;
  if (v && typeof (v as { toDate?: unknown }).toDate === "function") return (v as { toDate(): Date }).toDate().toISOString();
  return new Date(0).toISOString();
};

function toStatusDoc(d: Record<string, unknown>): SessionStatusDoc {
  return {
    uid: String(d.uid ?? ""),
    state: d.state as SessionStatusDoc["state"],
    step: (d.step as string | null | undefined) ?? null,
    progress: Number(d.progress ?? 0),
    error_code: (d.error_code as string | null | undefined) ?? null,
    latest_report_version: (d.latest_report_version as number | null | undefined) ?? null,
    updated_at: iso(d.updated_at),
    transcript_ready: d.transcript_ready === true,
    speaker_confirmed: d.speaker_confirmed === true,
    rating_submitted: d.rating_submitted === true,
    has_rating: d.has_rating === true,
  };
}

export function createFirestoreStatusListener(config: FirestoreListenerConfig = {}): StatusListener {
  return {
    subscribe(sessionId, onStatus, onError) {
      let cancelled = false;
      let off: (() => void) | undefined;
      void (async () => {
        try {
          const db = await getDb(config);
          if (cancelled) return;
          const { doc, onSnapshot } = await import("firebase/firestore");
          if (cancelled) return;
          off = onSnapshot(
            doc(db, "session_status", sessionId),
            (snap) => onStatus(snap.exists() ? toStatusDoc(snap.data() as Record<string, unknown>) : null),
            (err) => onError(err),
          );
        } catch (e) {
          if (!cancelled) onError(e instanceof Error ? e : new Error(String(e)));
        }
      })();
      return () => {
        cancelled = true;
        off?.();
      };
    },
  };
}
