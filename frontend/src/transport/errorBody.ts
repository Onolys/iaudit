import Ajv2020 from "ajv/dist/2020";
import errorSchema from "@contracts/error-response.schema.json";

// Same options as ../contract/validate.ts; kept local so the contract core is untouched.
const ajv = new Ajv2020({ allErrors: true, allowUnionTypes: true, strictTypes: false });
const checkError = ajv.compile<ErrorBody>(errorSchema);

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
