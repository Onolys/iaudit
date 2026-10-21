// @vitest-environment jsdom
import { createRef } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Header } from "./Header";

afterEach(cleanup);

it("renders saved-item identity and children without upload controls", () => {
  const { container } = render(
    <Header mock={false} fileName="run - item" requestId="saved-001"><span>Verdicts</span></Header>,
  );
  expect(screen.getByText("run - item")).toBeTruthy();
  expect(screen.getByText("saved-001")).toBeTruthy();
  expect(screen.getByText("Verdicts")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Upload request/ })).toBeNull();
  expect(container.querySelector('input[type="file"]')).toBeNull();
});

it("preserves upload selection when a handler and input ref are passed", () => {
  const inputRef = createRef<HTMLInputElement>();
  const onFile = vi.fn();
  render(<Header mock={false} inputRef={inputRef} onFile={onFile} />);
  const click = vi.spyOn(inputRef.current!, "click");
  fireEvent.click(screen.getByRole("button", { name: /Upload request/ }));
  expect(click).toHaveBeenCalledOnce();
  const file = new File(["{}"], "request.json");
  fireEvent.change(inputRef.current!, { target: { files: [file] } });
  expect(onFile).toHaveBeenCalledWith(file);
});
