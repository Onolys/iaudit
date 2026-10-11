export function LoadingView({ requestId, onCancel }: { requestId?: string; onCancel: () => void }) {
  return (
    <div role="status">
      <p>Auditing...</p>
      {requestId ? <p>Request {requestId}</p> : null}
      <button type="button" onClick={onCancel}>
        Cancel
      </button>
    </div>
  );
}
