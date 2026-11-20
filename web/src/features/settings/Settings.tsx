/** `/settings` (PRD R6, D9): API key management, usage, sign out, account-removal contact. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { unwrap } from "../../api/client";
import { describeError } from "../../api/errors";
import { useAuth } from "../../auth/AuthProvider";
import { useApiClient } from "../../auth/useApiClient";
import { CONTACT_EMAIL, HAS_CONTACT_EMAIL } from "../../config";
import { formatResetTime } from "../../lib/format";
import { ErrorCard } from "../session/ErrorCard";
import { Modal } from "./Modal";

const DOCS_URL = "/v1/docs";
const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : "never");

type Confirm = "regenerate" | "revoke" | null;

export function Settings() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  const { signOut } = useAuth();
  const key = useQuery({ queryKey: ["api-key"], queryFn: async () => unwrap(await client.GET("/api-key")) });
  const usage = useQuery({ queryKey: ["usage"], queryFn: async () => unwrap(await client.GET("/usage")) });

  const [confirm, setConfirm] = useState<Confirm>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  // The one-time secret lives only here (dialog state): not in the query cache, storage or logs.
  const [secret, setSecret] = useState<string | null>(null);
  const [stored, setStored] = useState(false);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  };
  const create = () =>
    run(async () => {
      const created = unwrap(await client.POST("/api-key"));
      setStored(false);
      setSecret(created.api_key);
      await queryClient.invalidateQueries({ queryKey: ["api-key"] });
    });
  const revoke = () =>
    run(async () => {
      unwrap(await client.DELETE("/api-key"));
      await queryClient.invalidateQueries({ queryKey: ["api-key"] });
    });
  const dismissSecret = () => {
    setSecret(null);
    setStored(false);
  };

  const info = key.data;
  const err = error ? describeError(error) : null;
  const removal = HAS_CONTACT_EMAIL ? <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> : <strong>{CONTACT_EMAIL}</strong>;

  return (
    <>
      <h1>Settings</h1>

      <section aria-labelledby="key-h">
        <h2 id="key-h">API key</h2>
        {key.isPending ? <p className="form-note">Loading…</p> : null}
        {key.isError ? <ErrorCard code={describeError(key.error).code} reference={describeError(key.error).requestId} /> : null}
        {err ? <ErrorCard code={err.code} reference={err.requestId} /> : null}
        {info && !info.active ? (
          <>
            <p>No API key yet.</p>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void create()}>
              Create API key
            </button>
          </>
        ) : null}
        {info?.active ? (
          <>
            <dl>
              <dt>Key</dt>
              <dd>
                <code>onolys_{info.key_id}_…</code>
              </dd>
              <dt>Status</dt>
              <dd>Active</dd>
              <dt>Created</dt>
              <dd>{when(info.created)}</dd>
              <dt>Last used</dt>
              <dd>{when(info.last_used_at)}</dd>
            </dl>
            <p className="dialog-actions" style={{ justifyContent: "flex-start" }}>
              <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => setConfirm("regenerate")}>
                Regenerate
              </button>
              <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => setConfirm("revoke")}>
                Revoke
              </button>
            </p>
          </>
        ) : null}
        <h3>Use the API</h3>
        <p>
          <a href={DOCS_URL}>API docs</a>
        </p>
        <pre>
          <code>{`curl -H "X-API-Key: onolys_<id>_<secret>" ${window.location.origin}/v1/usage`}</code>
        </pre>
      </section>

      <section aria-labelledby="usage-h">
        <h2 id="usage-h">Usage</h2>
        {usage.data ? (
          <p>
            {usage.data.runs_today} of {usage.data.daily_cap} runs today
            {formatResetTime(usage.data.resets_at) ? `, resets at ${formatResetTime(usage.data.resets_at)}` : ""}
          </p>
        ) : (
          <p className="form-note">Loading…</p>
        )}
      </section>

      <section aria-labelledby="account-h">
        <h2 id="account-h">Account</h2>
        <p>
          Deleting a session removes its audio, transcript, rating and reports. For account removal, contact {removal}.
        </p>
        <button type="button" className="btn btn-secondary" onClick={() => void signOut()}>
          Sign out
        </button>
      </section>

      {confirm === "regenerate" ? (
        <Modal titleId="regen-title" onEscape={() => setConfirm(null)}>
          <h2 id="regen-title">Regenerate API key?</h2>
          <p>The old key stops working immediately. Anything using it must be updated with the new key.</p>
          <div className="dialog-actions">
            <button type="button" className="btn btn-secondary" onClick={() => setConfirm(null)}>
              Cancel
            </button>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void create()}>
              Regenerate key
            </button>
          </div>
        </Modal>
      ) : null}
      {confirm === "revoke" ? (
        <Modal titleId="revoke-title" onEscape={() => setConfirm(null)}>
          <h2 id="revoke-title">Revoke API key?</h2>
          <p>The key stops working immediately. You can create a new one later.</p>
          <div className="dialog-actions">
            <button type="button" className="btn btn-secondary" onClick={() => setConfirm(null)}>
              Cancel
            </button>
            <button type="button" className="btn btn-danger" disabled={busy} onClick={() => void revoke()}>
              Revoke key
            </button>
          </div>
        </Modal>
      ) : null}
      {secret ? (
        <Modal titleId="secret-title" testId="api-secret-dialog">
          <h2 id="secret-title">Your new API key</h2>
          <p>Copy it now. It is shown only once and can't be retrieved later.</p>
          <p>
            <code data-testid="api-secret" style={{ wordBreak: "break-all" }}>
              {secret}
            </code>
          </p>
          <button type="button" className="btn btn-secondary" onClick={() => void navigator.clipboard.writeText(secret)}>
            Copy
          </button>
          <p>
            <label>
              <input type="checkbox" checked={stored} onChange={(e) => setStored(e.target.checked)} /> I've stored it
            </label>
          </p>
          <div className="dialog-actions">
            <button type="button" className="btn btn-primary" disabled={!stored} onClick={dismissSecret}>
              Done
            </button>
          </div>
        </Modal>
      ) : null}
    </>
  );
}
