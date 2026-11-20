/** MSW handlers over the mock backend: same handlers for dev, Vitest and browser (PRD D5). */
import { delay, http, HttpResponse, type HttpHandler } from "msw";
import type { components } from "../api/schema";
import { mockBackend } from "./backend";
import { MockHttpError, type MockBackend } from "./stateMachine";

const V1 = "*/v1";
const REQUEST_ID = "req_mock";
const FAKE_BEARER = /^Bearer test:([A-Za-z0-9_.-]+)$/;

function errorResponse(status: number, details: components["schemas"]["ErrorDetail"][], message: string) {
  return HttpResponse.json(
    { schema_version: "0.0.1", status, message, details, request_id: REQUEST_ID },
    { status },
  );
}

type Ctx = { uid: string; params: Record<string, string>; request: Request };
type Fn = (c: Ctx) => Response | Promise<Response>;

/** Fake auth (`Bearer test:<uid>`, as SP04 AUTH_MODE=fake) + MockHttpError -> public-error-response. */
function guarded(fn: Fn) {
  return async ({ request, params }: { request: Request; params: Record<string, unknown> }) => {
    const m = FAKE_BEARER.exec(request.headers.get("authorization") ?? "");
    if (!m)
      return errorResponse(401, [{ code: "unauthenticated", message: "Sign-in required." }], "Sign-in required.");
    try {
      const p = Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)]));
      return await fn({ uid: m[1], params: p, request });
    } catch (e) {
      if (e instanceof MockHttpError) return errorResponse(e.status, e.details, e.message);
      throw e;
    }
  };
}

async function body<T>(request: Request): Promise<T> {
  const text = await request.text();
  return (text ? JSON.parse(text) : {}) as T;
}

export function createHandlers(b: MockBackend): HttpHandler[] {
  const json = (data: unknown, status = 200) => HttpResponse.json(data as never, { status });
  return [
    http.get(`${V1}/sessions`, guarded(({ uid, request }) => {
      const q = new URL(request.url).searchParams;
      const limit = q.get("limit");
      return json(b.listSessions(uid, { limit: limit ? Number(limit) : undefined, cursor: q.get("cursor") ?? undefined }));
    })),
    http.post(`${V1}/sessions`, guarded(async ({ uid, request }) =>
      json(
        b.createSession(uid, await body(request), request.headers.get("idempotency-key") ?? undefined),
        201,
      ),
    )),
    http.get(`${V1}/sessions/:id`, guarded(({ uid, params }) => json(b.getSession(uid, params.id)))),
    http.delete(`${V1}/sessions/:id`, guarded(({ uid, params }) => {
      b.deleteSession(uid, params.id);
      return new HttpResponse(null, { status: 204 });
    })),
    http.post(`${V1}/sessions/:id/audio`, guarded(async ({ uid, params, request }) =>
      json(b.requestAudio(uid, params.id, await body(request))),
    )),
    http.post(`${V1}/sessions/:id/audio/complete`, guarded(({ uid, params }) =>
      json(b.completeAudio(uid, params.id), 202),
    )),
    http.get(`${V1}/sessions/:id/rating`, guarded(({ uid, params }) => json(b.getRating(uid, params.id)))),
    http.put(`${V1}/sessions/:id/rating`, guarded(async ({ uid, params, request }) =>
      json(b.putRating(uid, params.id, await body(request)), 202),
    )),
    http.get(`${V1}/sessions/:id/speakers`, guarded(({ uid, params }) => json(b.getSpeakers(uid, params.id)))),
    http.post(`${V1}/sessions/:id/speakers/confirm`, guarded(async ({ uid, params, request }) => {
      const { clinician_speaker } = await body<{ clinician_speaker: string }>(request);
      return json(b.confirmSpeaker(uid, params.id, clinician_speaker), 202);
    })),
    http.get(`${V1}/sessions/:id/transcript`, guarded(({ uid, params }) => json(b.getTranscript(uid, params.id)))),
    http.get(`${V1}/sessions/:id/runs`, guarded(({ uid, params }) => json(b.listRuns(uid, params.id)))),
    http.post(`${V1}/sessions/:id/runs`, guarded(async ({ uid, params, request }) =>
      json(b.startRun(uid, params.id, await body(request)), 202),
    )),
    http.get(`${V1}/runs/:run_id`, guarded(({ uid, params }) => json(b.getRun(uid, params.run_id)))),
    http.get(`${V1}/sessions/:id/reports`, guarded(({ uid, params }) => json(b.listReports(uid, params.id)))),
    http.get(`${V1}/sessions/:id/reports/:version`, guarded(({ uid, params }) =>
      json(b.getReport(uid, params.id, Number(params.version))),
    )),
    http.get(`${V1}/usage`, guarded(({ uid }) => json(b.getUsage(uid)))),

    // Stand-in for the GCS signed URL: pinned to the canonical Content-Type, like the real one.
    http.put("https://uploads.mock.invalid/uploads/:uid/:sid/:upload_id", async ({ request, params }) => {
      const expected = b.uploadContentType(String(params.sid), String(params.upload_id));
      if (!expected || request.headers.get("content-type") !== expected)
        return new HttpResponse("SignatureDoesNotMatch", { status: 403 });
      await delay(0);
      return new HttpResponse(null, { status: 200 });
    }),
  ];
}

export const handlers = createHandlers(mockBackend);
