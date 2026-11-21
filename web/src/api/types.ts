/**
 * Thin aliases over the GENERATED contract types (`schema.d.ts` from
 * `api/openapi.json`, `report.d.ts` from `report.schema.json`). Nothing here
 * restates a shape: every name is derived, so `npm run gen:api` stays the only
 * source of truth.
 */
import type { components, paths } from "./schema";
import type { AuditClaim, Report } from "./report";

export type { Report } from "./report";
export type {
  AuditClaim,
  AuditEvidence,
  Diff,
  Explanation,
  Instance,
  Line,
  RunStats,
} from "./report";

export type Schemas = components["schemas"];
export type SessionState = Schemas["SessionRef"]["status"];
export type ClaimVerdict = AuditClaim["verdict"];
export type EvidenceRole = AuditClaim["evidence"][number]["role"];
export type ErrorCode = Schemas["ErrorDetailModel"]["code"];
/** Report body as stored by the API (`ReportView.report` is an opaque object in OpenAPI). */
export type ReportBody = Report;

type StripV1<P> = P extends `/v1${infer R}` ? R : P;
/**
 * The generated `paths` keys carry the `/v1` prefix; the client's base URL is
 * already `/v1` (PRD R7), so call sites use the unprefixed path.
 */
export type ApiPaths = { [K in keyof paths as StripV1<K>]: paths[K] };

/**
 * The rating card is an opaque object in OpenAPI (`card: {[key]: unknown}`); its
 * shape is `rating.schema.json` (SP02), mirrored here for the form and mock.
 * Parity with the schema is asserted in `protocol/miti-items.test.ts`.
 */
export type RatingCard = {
  change_goal?: string | null;
  coded_span?: { from_s: number | null; to_s: number | null } | null;
  globals?: {
    [item_id: string]: {
      score?: number | null;
      reason?: string;
      example?: { at_s: number | null; text: string } | null;
    };
  };
  counts?: { [item_id: string]: { count?: number | null; note?: string } };
  notes?: string;
};
