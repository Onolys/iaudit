import { useQuery } from "@tanstack/react-query";
import { unwrap } from "../../api/client";
import { useApiClient } from "../../auth/useApiClient";
import { Transcript, type Highlight } from "./Transcript";
import { useSelectedInstance } from "./useSelectedInstance";

/** Fetches `GET /sessions/{id}/transcript` and renders it; the selection comes from the URL hash. */
export function TranscriptPanel({ sessionId, highlights }: { sessionId: string; highlights: Highlight[] }) {
  const client = useApiClient();
  const [selectedId] = useSelectedInstance();
  const q = useQuery({
    queryKey: ["transcript", sessionId],
    staleTime: 0,
    gcTime: 0,
    queryFn: async () => unwrap(await client.GET("/sessions/{id}/transcript", { params: { path: { id: sessionId } } })),
  });
  if (q.isPending) return <p className="form-note">Loading transcript…</p>;
  if (q.isError) {
    return (
      <p className="notice">
        We couldn't load the transcript.{" "}
        <button type="button" className="link-button" onClick={() => void q.refetch()}>
          Try again
        </button>
      </p>
    );
  }
  return <Transcript turns={q.data.turns} highlights={highlights} selectedId={selectedId} />;
}
