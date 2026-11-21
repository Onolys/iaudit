// Firestore rules tests (PRD 06-infra R5, D11, D17). Run via the emulator:
//   firebase emulators:exec --config firebase.json --only firestore --project demo-onolys \
//     'npm test --prefix firestore-rules-test'
import { readFileSync } from "node:fs";
import { after, before, beforeEach, describe, it } from "node:test";
import {
  assertFails,
  assertSucceeds,
  initializeTestEnvironment,
} from "@firebase/rules-unit-testing";
import {
  deleteDoc,
  doc,
  getDoc,
  getDocs,
  collection,
  onSnapshot,
  setDoc,
  updateDoc,
} from "firebase/firestore";

const RULES = readFileSync(new URL("../firestore.rules", import.meta.url), "utf8");
const [HOST, PORT] = (process.env.FIRESTORE_EMULATOR_HOST ?? "127.0.0.1:8081").split(":");
const SID = "sess-1";

let env;

// What SP04's POST /sessions writes: owner uid + PHI-free status fields (Admin SDK, bypasses rules).
async function createStatusDoc(sid = SID, uid = "alice") {
  await env.withSecurityRulesDisabled(async (ctx) => {
    await setDoc(doc(ctx.firestore(), "session_status", sid), {
      uid,
      state: "created",
      step: null,
      progress: 0,
      error_code: null,
      latest_report_version: null,
      updated_at: new Date(),
      transcript_ready: false,
      speaker_confirmed: false,
      rating_submitted: false,
    });
  });
}

// First snapshot or error of a listener, as the web app's onSnapshot would see it.
function listen(db, sid) {
  return new Promise((resolve) => {
    const unsub = onSnapshot(
      doc(db, "session_status", sid),
      (snap) => {
        unsub();
        resolve({ ok: true, exists: snap.exists() });
      },
      (err) => {
        resolve({ ok: false, code: err.code });
      },
    );
  });
}

before(async () => {
  env = await initializeTestEnvironment({
    projectId: "demo-onolys",
    firestore: { rules: RULES, host: HOST, port: Number(PORT) },
  });
});
after(async () => env?.cleanup());
beforeEach(async () => {
  await env.clearFirestore();
});

describe("session_status reads", () => {
  it("owner reads own status doc", async () => {
    await createStatusDoc();
    const db = env.authenticatedContext("alice").firestore();
    const snap = await assertSucceeds(getDoc(doc(db, "session_status", SID)));
    if (snap.data().state !== "created") throw new Error("unexpected data");
  });

  it("another user is denied", async () => {
    await createStatusDoc();
    const db = env.authenticatedContext("bob").firestore();
    await assertFails(getDoc(doc(db, "session_status", SID)));
  });

  it("unauthenticated is denied", async () => {
    await createStatusDoc();
    const db = env.unauthenticatedContext().firestore();
    await assertFails(getDoc(doc(db, "session_status", SID)));
  });

  it("get on a missing doc is denied (rule reads resource.data.uid)", async () => {
    const db = env.authenticatedContext("alice").firestore();
    await assertFails(getDoc(doc(db, "session_status", "nope")));
  });

  it("collection list of session_status is denied", async () => {
    await createStatusDoc();
    const db = env.authenticatedContext("alice").firestore();
    await assertFails(getDocs(collection(db, "session_status")));
  });
});

describe("client writes are all denied", () => {
  it("owner cannot create, update or delete session_status", async () => {
    await createStatusDoc();
    const db = env.authenticatedContext("alice").firestore();
    await assertFails(setDoc(doc(db, "session_status", "new"), { uid: "alice", state: "created" }));
    await assertFails(updateDoc(doc(db, "session_status", SID), { state: "done" }));
    await assertFails(deleteDoc(doc(db, "session_status", SID)));
  });

  it("other user and anonymous cannot write session_status", async () => {
    await createStatusDoc();
    const bob = env.authenticatedContext("bob").firestore();
    await assertFails(setDoc(doc(bob, "session_status", SID), { uid: "bob" }));
    const anon = env.unauthenticatedContext().firestore();
    await assertFails(setDoc(doc(anon, "session_status", "x"), { uid: "x" }));
  });
});

describe("every other collection is denied", () => {
  for (const col of ["sessions", "users", "runs", "anything_else"]) {
    it(`${col}: read and write denied even for an owner-looking doc`, async () => {
      await env.withSecurityRulesDisabled(async (ctx) => {
        await setDoc(doc(ctx.firestore(), col, "d1"), { uid: "alice", secret: "x" });
      });
      const db = env.authenticatedContext("alice").firestore();
      await assertFails(getDoc(doc(db, col, "d1")));
      await assertFails(getDocs(collection(db, col)));
      await assertFails(setDoc(doc(db, col, "d2"), { uid: "alice" }));
      await assertFails(updateDoc(doc(db, col, "d1"), { uid: "alice" }));
      await assertFails(deleteDoc(doc(db, col, "d1")));
    });
  }

  it("subcollection of sessions is denied", async () => {
    await env.withSecurityRulesDisabled(async (ctx) => {
      await setDoc(doc(ctx.firestore(), "sessions", SID, "runs", "r1"), { uid: "alice" });
    });
    const db = env.authenticatedContext("alice").firestore();
    await assertFails(getDoc(doc(db, "sessions", SID, "runs", "r1")));
  });

  it("subcollection under session_status is denied", async () => {
    await createStatusDoc();
    const db = env.authenticatedContext("alice").firestore();
    await assertFails(getDoc(doc(db, "session_status", SID, "extra", "e1")));
  });
});

describe("listener cases (D17)", () => {
  it("owner subscribes right after create and succeeds", async () => {
    await createStatusDoc();
    const db = env.authenticatedContext("alice").firestore();
    const res = await listen(db, SID);
    if (!res.ok || !res.exists) throw new Error(`listen failed: ${JSON.stringify(res)}`);
  });

  it("another user's listen on the same doc is denied", async () => {
    await createStatusDoc();
    const db = env.authenticatedContext("bob").firestore();
    const res = await listen(db, SID);
    if (res.ok || res.code !== "permission-denied") throw new Error(`expected denial: ${JSON.stringify(res)}`);
  });

  it("listen on a missing doc is denied", async () => {
    const db = env.authenticatedContext("alice").firestore();
    const res = await listen(db, "does-not-exist");
    if (res.ok || res.code !== "permission-denied") throw new Error(`expected denial: ${JSON.stringify(res)}`);
  });
});
