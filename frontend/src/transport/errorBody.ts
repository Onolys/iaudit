import type { ValidateFunction } from "ajv";
import { checkError as compiled } from "../generated/errorBody";

// Precompiled by scripts/compile-validators.mjs (no runtime codegen; strict CSP).
const checkError = compiled as ValidateFunction<ErrorBody>;

export interface ErrorDetail {
  code: string;
  message: string;
}

export interface ErrorBody {
  status: number;
  message: string;
  details: ErrorDetail[];
}

/** Display fields of a non-2xx body, only when the complete error body validates. */
export function readErrorBody(text: string): ErrorBody | undefined {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return undefined;
  }
  if (!checkError(raw)) return undefined;
  const { status, message, details } = raw;
  return { status, message, details };
}
