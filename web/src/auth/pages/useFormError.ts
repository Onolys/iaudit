import { useState } from "react";
import { errorCode, mapAuthError, type MappedAuthError } from "../errors";

export function useFormError() {
  const [error, setError] = useState<MappedAuthError | null>(null);
  return {
    error,
    clear: () => setError(null),
    fail: (err: unknown) => setError(mapAuthError(errorCode(err))),
    failWith: (message: string) => setError({ message }),
  };
}
