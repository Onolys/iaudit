/**
 * `/sessions/new` (PRD R3): audio, language, optional title; advisory pre-checks; then
 * `POST /sessions` → `POST …/audio` → hand the file to the app-level uploader and open the
 * session page at once.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState, type DragEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { unwrap } from "../../api/client";
import { describeError } from "../../api/errors";
import { useApiClient } from "../../auth/useApiClient";
import { ErrorCard } from "../session/ErrorCard";
import { DEFAULT_LANGUAGE, LANGUAGES } from "./config";
import { checkFile, fileExtension, readDuration, type PrecheckResult } from "./precheck";
import { getJob, registerJob, UploadJob } from "./uploader";

export function NewSessionPage() {
  const client = useApiClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const from = params.get("from");

  const [file, setFile] = useState<File | null>(null);
  const [check, setCheck] = useState<PrecheckResult | null>(null);
  const [language, setLanguage] = useState<string>(DEFAULT_LANGUAGE);
  const [typedTitle, setTypedTitle] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  // One Idempotency-Key per form instance; a changed body needs a new key (and a new session).
  const created = useRef<{ key: string; body: string; id: string } | null>(null);
  const formKey = useRef(globalThis.crypto.randomUUID());

  const previous = useQuery({
    queryKey: ["session", from],
    enabled: from !== null,
    queryFn: async () => unwrap(await client.GET("/sessions/{id}", { params: { path: { id: from ?? "" } } })),
  });
  const title = typedTitle ?? previous.data?.title ?? "";

  const pick = async (f: File | undefined) => {
    setFile(f ?? null);
    setCheck(null);
    if (!f) return;
    const quick = checkFile(f, null);
    if (quick.blocked) return setCheck(quick);
    const duration = await readDuration(f);
    setCheck(checkFile(f, duration));
  };

  const submit = useMutation({
    mutationFn: async (f: File) => {
      const trimmed = title.trim();
      const body = { language, ...(trimmed ? { title: trimmed } : {}) };
      const bodyKey = JSON.stringify(body);
      if (!created.current || created.current.body !== bodyKey) {
        const key = created.current ? globalThis.crypto.randomUUID() : formKey.current;
        const res = unwrap(
          await client.POST("/sessions", { body, params: { header: { "Idempotency-Key": key } } }),
        );
        created.current = { key, body: bodyKey, id: res.session.id };
      }
      const id = created.current.id;
      const request = async () =>
        unwrap(
          await client.POST("/sessions/{id}/audio", {
            params: { path: { id } },
            body: { content_type: f.type, size_bytes: f.size, filename_ext: fileExtension(f.name) },
          }),
        );
      const first = await request();
      registerJob(
        id,
        new UploadJob({
          file: f,
          first,
          requestTarget: request,
          complete: async () =>
            unwrap(await client.POST("/sessions/{id}/audio/complete", { params: { path: { id } } })),
        }),
      );
      return id;
    },
    onSuccess: (id) => {
      void getJob(id)?.start();
      void navigate(`/sessions/${id}`);
    },
  });

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    void pick(e.dataTransfer.files[0]);
  };

  const err = submit.error ? describeError(submit.error) : null;
  const canSubmit = file !== null && check !== null && check.blocked === null && !submit.isPending;

  return (
    <>
      <h1>New session</h1>
      <form
        className="auth-form upload-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (file && canSubmit) submit.mutate(file);
        }}
      >
        <div
          className={`drop-zone${dragging ? " drop-zone-active" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <label>
            Audio recording
            <input
              type="file"
              accept=".mp3,.wav,.m4a,.webm,.ogg,audio/*"
              onChange={(e) => void pick(e.target.files?.[0])}
            />
          </label>
          <p className="form-note">
            Drop a file here or choose one. mp3, wav, m4a, webm or ogg, up to 300 MB, 10 to 20 minutes.
          </p>
          {file ? <p className="form-note">{file.name}</p> : null}
        </div>

        {check?.blocked ? (
          <p className="form-error" role="alert">
            {check.blocked}
          </p>
        ) : null}
        {check?.warning ? (
          <p className="notice" role="status">
            {check.warning}
          </p>
        ) : null}

        <label>
          Language
          <select value={language} onChange={(e) => setLanguage(e.target.value)}>
            {LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          Title (optional)
          <input
            type="text"
            maxLength={200}
            value={title}
            onChange={(e) => setTypedTitle(e.target.value)}
          />
        </label>

        {err ? <ErrorCard code={err.code} reference={err.requestId} /> : null}

        <button type="submit" className="btn btn-primary" disabled={!canSubmit}>
          {submit.isPending ? "Starting…" : "Start"}
        </button>
      </form>
    </>
  );
}
