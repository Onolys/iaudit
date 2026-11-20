import type { ReactNode } from "react";
import { Link } from "react-router";

function Page({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <>
      <h1>{title}</h1>
      {children ?? <p>This page is a placeholder.</p>}
    </>
  );
}

export const Settings = () => <Page title="Settings" />;
export const NotFound = () => (
  <Page title="Page not found">
    <p>
      <Link to="/">Back to your sessions</Link>
    </p>
  </Page>
);
