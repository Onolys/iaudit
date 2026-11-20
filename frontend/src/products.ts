export const PRODUCTS = [{ id: "eaudit", label: "eaudit" }] as const;

export type ProductId = (typeof PRODUCTS)[number]["id"];
