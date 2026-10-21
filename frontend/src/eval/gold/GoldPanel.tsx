import type { ComponentType } from "react";
import { GenericGold } from "./GenericGold";
import { TofuEvalGold } from "./TofuEvalGold";
import "./gold.css";

export interface GoldPanelProps { goldKind: string | null; gold: unknown }
const renderers: Record<string, ComponentType<{ gold: unknown }>> = {
  tofueval_summary_sentences: TofuEvalGold,
};

export function GoldPanel({ goldKind, gold }: GoldPanelProps) {
  const Renderer = goldKind !== null && Object.hasOwn(renderers, goldKind) ? renderers[goldKind] : GenericGold;
  return <Renderer gold={gold} />;
}
