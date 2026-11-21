import type { ComponentType } from "react";
import type { AuditDeps } from "./transport/runAudit";
import type { ProductId } from "./products";
import EauditApp from "./EauditApp";
import PauditApp from "./paudit/PauditApp";

export interface ProductViewProps {
  deps?: AuditDeps;
}

// Product id -> view component. Adding a product to PRODUCTS requires an entry here (type-checked).
export const PRODUCT_VIEWS: Record<ProductId, ComponentType<ProductViewProps>> = {
  eaudit: EauditApp,
  paudit: PauditApp,
};
