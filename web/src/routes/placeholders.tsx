import type { ReactNode } from "react";
import { Link, useParams } from "react-router";

function Page({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <>
      <h1>{title}</h1>
      {children ?? <p>This page is a placeholder.</p>}
    </>
  );
}

export const Dashboard = () => <Page title="Sessions" />;
export const NewSession = () => <Page title="New session" />;
export const ReportPage = () => {
  const { id, version } = useParams();
  return (
    <Page title="Report">
      <p>
        Session {id}, version {version}
      </p>
    </Page>
  );
};
export const SampleReport = () => <Page title="Sample report" />;
export const Settings = () => <Page title="Settings" />;
export const NotFound = () => (
  <Page title="Page not found">
    <p>
      <Link to="/">Back to your sessions</Link>
    </p>
  </Page>
);
