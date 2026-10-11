import Ajv2020 from "ajv/dist/2020";
import errorSchema from "@contracts/error-response.schema.json";

// Same options as ../contract/validate.ts; kept local so the contract core is untouched.
const ajv = new Ajv2020({ allErrors: true, allowUnionTypes: true, strictTypes: false });
const checkError = ajv.compile(errorSchema);

/** `error.message` of a non-2xx body, only when the body validates against the error schema. */
export function readErrorMessage(text: string): string | undefined {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return undefined;
  }
  if (!checkError(raw)) return undefined;
  return (raw as { error: { message: string } }).error.message;
}
