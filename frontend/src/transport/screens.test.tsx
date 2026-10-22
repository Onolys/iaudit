// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AuditResponse } from "../contract";
import { ErrorScreen } from "./ErrorScreen";
import type { LoadError } from "./errors";
import { LoadingView } from "./LoadingView";
import { WarningsBanner } from "./WarningsBanner";

afterEach(cleanup);

const issues = [{ path: "/transcript", message: "must have at least 1 items" }];

const titles: [LoadError, string, boolean][] = [
  [{ kind: "invalid_request_file", reason: "empty" }, "Invalid request file", false],
  [{ kind: "invalid_request_file", reason: "not_json", message: "Unexpected token" }, "Invalid request file", false],
  [{ kind: "invalid_request_file", reason: "schema", issues }, "Invalid request file", false],
  [{ kind: "config_missing" }, "Audit service not configured", false],
  [{ kind: "mock_no_match", requestId: "r-1" }, "No mock audit for this request", false],
  [{ kind: "network", url: "https://a.example/x" }, "Couldn't reach the audit service.", true],
  [{ kind: "timeout", seconds: 120 }, "Request timed out", true],
  [{ kind: "cancelled" }, "Cancelled.", true],
  [{ kind: "http_4xx", status: 400, message: "bad" }, "Request rejected (400)", false],
  [{ kind: "http_4xx", status: 408 }, "Request rejected (408)", true],
  [{ kind: "http_4xx", status: 429 }, "Request rejected (429)", true],
  [{ kind: "http_5xx", status: 503 }, "Audit service error (503).", true],
  [{ kind: "invalid_response", reason: "empty" }, "Invalid audit response", false],
  [{ kind: "invalid_response", reason: "not_json", message: "oops" }, "Invalid audit response", false],
  [{ kind: "invalid_response", reason: "not_object" }, "Invalid audit response", false],
  [{ kind: "invalid_response", reason: "wrong_version" }, "Invalid audit response", false],
  [{ kind: "invalid_response", reason: "schema", issues }, "Invalid audit response", false],
  [{ kind: "invalid_response", reason: "duplicate_claim_id", claimId: "c1" }, "Invalid audit response", false],
  [{ kind: "request_id_mismatch", expected: "a", received: "b" }, "Response doesn't match this request.", false],
];

describe("ErrorScreen", () => {
  it("shows saved-response errors without a choose-file action", () => {
    render(<ErrorScreen error={{ kind: "invalid_response", reason: "wrong_version" }} />);
    expect(screen.getByRole("alert").textContent).toContain("unsupported schema version");
    expect(screen.queryByRole("button", { name: "Choose another file" })).toBeNull();
  });

  it.each(titles)("%j", (error, title, retry) => {
    const onRetry = vi.fn();
    const onChooseFile = vi.fn();
    render(<ErrorScreen error={error} onRetry={onRetry} onChooseFile={onChooseFile} />);
    const alert = screen.getByRole("alert");
    expect(alert.querySelector("h2")?.textContent).toBe(title);
    expect(!!screen.queryByRole("button", { name: "Retry" })).toBe(retry);
    if (retry) {
      fireEvent.click(screen.getByRole("button", { name: "Retry" }));
      expect(onRetry).toHaveBeenCalledOnce();
    }
    const choose = screen.queryByRole("button", { name: "Choose another file" });
    expect(!!choose).toBe(error.kind !== "network" && error.kind !== "timeout" && error.kind !== "cancelled" && error.kind !== "http_5xx");
    if (choose) {
      fireEvent.click(choose);
      expect(onChooseFile).toHaveBeenCalledOnce();
    }
  });

  it("omits Retry when no handler is given", () => {
    render(<ErrorScreen error={{ kind: "timeout", seconds: 120 }} onChooseFile={() => {}} />);
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("shows details", () => {
    render(<ErrorScreen error={{ kind: "network", url: "https://a.example/x" }} onRetry={() => {}} onChooseFile={() => {}} />);
    expect(screen.getByRole("alert").textContent).toContain("https://a.example/x");
    cleanup();
    render(<ErrorScreen error={{ kind: "mock_no_match" }} onChooseFile={() => {}} />);
    expect(screen.getByRole("alert").textContent).toContain("none");
    cleanup();
    render(<ErrorScreen error={{ kind: "timeout", seconds: 120 }} onRetry={() => {}} onChooseFile={() => {}} />);
    expect(screen.getByRole("alert").textContent).toContain("120 s");
    cleanup();
    render(<ErrorScreen error={{ kind: "request_id_mismatch", expected: "aaa", received: "bbb" }} onChooseFile={() => {}} />);
    expect(screen.getByRole("alert").textContent).toMatch(/aaa.*bbb/);
  });

  it("lists issues with path and message", () => {
    render(<ErrorScreen error={{ kind: "invalid_request_file", reason: "schema", issues }} onChooseFile={() => {}} />);
    const li = screen.getByRole("listitem");
    expect(li.textContent).toContain("/transcript");
    expect(li.textContent).toContain("must have at least 1 items");
  });

  it("caps issues at 50 with 'and N more'", () => {
    const many = Array.from({ length: 73 }, (_, i) => ({ path: `/p${i}`, message: "bad" }));
    render(<ErrorScreen error={{ kind: "invalid_response", reason: "schema", issues: many }} onChooseFile={() => {}} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(51);
    expect(screen.getByText("and 23 more")).toBeTruthy();
  });

  it("renders server text literally, never as HTML", () => {
    const evil = "<b>bold</b><img src=x onerror=alert(1)>";
    const { container } = render(<ErrorScreen error={{ kind: "http_4xx", status: 400, message: evil }} onChooseFile={() => {}} />);
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain(evil);
  });

  it("shows no body text when the 5xx body was not a valid error", () => {
    render(<ErrorScreen error={{ kind: "http_5xx", status: 500 }} onRetry={() => {}} onChooseFile={() => {}} />);
    expect(screen.getByRole("alert").querySelectorAll("p")).toHaveLength(0);
  });
});

describe("LoadingView", () => {
  it("shows Auditing..., request id when known, and Cancel", () => {
    const onCancel = vi.fn();
    const { rerender } = render(<LoadingView onCancel={onCancel} />);
    expect(screen.getByText("Auditing...")).toBeTruthy();
    expect(screen.queryByText(/example-001/)).toBeNull();
    rerender(<LoadingView requestId="example-001" onCancel={onCancel} />);
    expect(screen.getByText(/example-001/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});

describe("WarningsBanner", () => {
  const base: AuditResponse = { schema_version: "1.2.0", status: "complete", warnings: [], claims: [] };

  it("is absent for a clean complete response", () => {
    const { container } = render(<WarningsBanner response={base} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows for warnings-only with code, message, 0-based Section N and claim id", () => {
    render(
      <WarningsBanner
        response={{
          ...base,
          warnings: [
            { code: "section_not_processed", message: "Skipped it.", section_index: 0 },
            { code: "span_out_of_range", message: "Off the end.", claim_id: "c-9", section_index: 2 },
          ],
        }}
      />,
    );
    expect(screen.getByText("Audit completed with warnings")).toBeTruthy();
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain("Skipped it.");
    expect(items[0].textContent).toContain("Section 1");
    expect(items[1].textContent).toContain("Section 3");
    expect(items[1].textContent).toContain("c-9");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the partial heading", () => {
    render(<WarningsBanner response={{ ...base, status: "partial" }} />);
    expect(screen.getByText("Audit is partial: some sections were not processed")).toBeTruthy();
  });

  it("renders warning text literally", () => {
    const { container } = render(
      <WarningsBanner response={{ ...base, warnings: [{ code: "other", message: "<i>x</i>" }] }} />,
    );
    expect(container.querySelector("i")).toBeNull();
    expect(container.textContent).toContain("<i>x</i>");
  });
});
