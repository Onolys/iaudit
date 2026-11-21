export const PRODUCTS = [
  { id: "eaudit", label: "eaudit" },
  { id: "paudit", label: "paudit" },
] as const;

export type ProductId = (typeof PRODUCTS)[number]["id"];
