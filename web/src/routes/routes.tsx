import type { RouteObject } from "react-router";
import { ForgotPassword } from "../auth/pages/ForgotPassword";
import { Login } from "../auth/pages/Login";
import { Signup } from "../auth/pages/Signup";
import { VerifyEmail } from "../auth/pages/VerifyEmail";
import { PublicOnly, RequireUnverified, RequireVerified } from "../auth/guards";
import { Dashboard } from "../features/dashboard/Dashboard";
import { SampleReportPage } from "../features/report/SampleReportPage";
import { ReportPage } from "../features/report/ReportPage";
import { NewSessionPage } from "../features/upload/NewSessionPage";
import { SessionPage } from "../features/session/SessionPage";
import { Layout } from "./Layout";
import { Settings } from "../features/settings/Settings";
import * as P from "./placeholders";

export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      {
        element: <PublicOnly />,
        children: [
          { path: "/signup", element: <Signup /> },
          { path: "/login", element: <Login /> },
          { path: "/forgot-password", element: <ForgotPassword /> },
        ],
      },
      { element: <RequireUnverified />, children: [{ path: "/verify-email", element: <VerifyEmail /> }] },
      {
        element: <RequireVerified />,
        children: [
          { path: "/", element: <Dashboard /> },
          { path: "/sessions/new", element: <NewSessionPage /> },
          { path: "/sessions/:id", element: <SessionPage /> },
          { path: "/sessions/:id/reports/:version", element: <ReportPage /> },
          { path: "/settings", element: <Settings /> },
        ],
      },
      { path: "/sample-report", element: <SampleReportPage /> },
      { path: "*", element: <P.NotFound /> },
    ],
  },
];
