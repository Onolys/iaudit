import type { RouteObject } from "react-router";
import { Layout } from "./Layout";
import * as P from "./placeholders";

export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      { path: "/signup", element: <P.Signup /> },
      { path: "/login", element: <P.Login /> },
      { path: "/forgot-password", element: <P.ForgotPassword /> },
      { path: "/verify-email", element: <P.VerifyEmail /> },
      { path: "/", element: <P.Dashboard /> },
      { path: "/sessions/new", element: <P.NewSession /> },
      { path: "/sessions/:id", element: <P.SessionDetail /> },
      { path: "/sessions/:id/reports/:version", element: <P.ReportPage /> },
      { path: "/sample-report", element: <P.SampleReport /> },
      { path: "/settings", element: <P.Settings /> },
      { path: "*", element: <P.NotFound /> },
    ],
  },
];
