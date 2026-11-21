// Precompiles every Ajv validator the browser bundle uses into plain ESM (Ajv standalone code), so
// no `new Function` runs at runtime and the strict CSP (no 'unsafe-eval') holds. Output: src/generated/
// (gitignored; run by predev/prebuild/pretest/pretypecheck). Ajv options per group mirror the former
// runtime instances exactly.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import standaloneCode from "ajv/dist/standalone/index.js";

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const load = (p) => JSON.parse(readFileSync(here(p), "utf8"));
const out = here("../src/generated/");
mkdirSync(out, { recursive: true });

const contract = { allErrors: true, allowUnionTypes: true, strictTypes: false };
const loose = { allErrors: true, allowUnionTypes: true, strict: false };
const esm = { source: true, esm: true };

// `build` registers schemas on the instance and returns { exportName: schemaKey }.
function emit(file, options, build) {
  const ajv = new Ajv2020({ ...options, code: esm });
  const validators = build(ajv);
  // Ajv emits `require("ajv/dist/runtime/...")` helpers even with esm:true; hoist them to imports
  // (a bare `require` does not exist in the browser).
  const imports = [];
  const code = standaloneCode(ajv, validators).replace(
    /const (\w+) = require\("([^"]+)"\)\.default;/g,
    (_, name, mod) => (imports.push(`import ${name}_mod from "${mod}.js";const ${name} = ${name}_mod.default ?? ${name}_mod;`), ""),
  );
  if (/\brequire\(/.test(code.replace(/"(?:[^"\\]|\\.)*"/g, '""'))) throw new Error(`${file}: unhandled require() in standalone output`);
  writeFileSync(out + file + ".js", imports.join("\n") + (imports.length ? "\n" : "") + code);
  const names = Object.keys(validators);
  writeFileSync(
    out + file + ".d.ts",
    `import type { ValidateFunction } from "ajv";\n${names.map((n) => `export const ${n}: ValidateFunction;`).join("\n")}\n`,
  );
}

const single = (ajv, name, path) => {
  ajv.addSchema(load(path), name);
  return { [name]: name };
};

emit("contract", contract, (ajv) => ({
  ...single(ajv, "checkRequest", "../../docs/contracts/audit-request.schema.json"),
  ...single(ajv, "checkResponse", "../../docs/contracts/audit-response.schema.json"),
}));
emit("errorBody", contract, (ajv) => single(ajv, "checkError", "../../docs/contracts/error-response.schema.json"));
emit("paudit", loose, (ajv) => single(ajv, "checkResult", "../../engines/paudit/schemas/paudit-result.schema.json"));
emit("evalApi", loose, (ajv) => {
  const schema = load("../../eval/api/eval-api.schema.json");
  ajv.addSchema(schema);
  // Keyed by the schema name evalApi.ts looks up: every x-routes target plus ErrorResponse.
  const validators = {};
  for (const name of new Set([...Object.values(schema["x-routes"]), "ErrorResponse"])) {
    const array = name.endsWith("[]");
    const ref = { $ref: `${schema.$id}#/$defs/${array ? name.slice(0, -2) : name}` };
    ajv.addSchema(array ? { type: "array", items: ref } : ref, name);
    validators[name.replace("[]", "List")] = name;
  }
  return validators;
});
