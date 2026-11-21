import { expect, it } from "vitest";
import { PRODUCTS } from "./products";
import { PRODUCT_VIEWS } from "./productViews";

it("registers eaudit first (default tab) and paudit", () => {
  expect(PRODUCTS.map(p => p.id)).toEqual(["eaudit", "paudit"]);
  expect(PRODUCTS[1]).toEqual({ id: "paudit", label: "paudit" });
});

it("maps every registered product id to a view component", () => {
  for (const product of PRODUCTS) expect(typeof PRODUCT_VIEWS[product.id]).toBe("function");
});
