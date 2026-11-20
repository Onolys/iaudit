import { useEffect, useRef } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";

export function Layout() {
  const { pathname } = useLocation();
  const mainRef = useRef<HTMLElement>(null);

  // A11y (R8): after each route change move focus to the page h1.
  useEffect(() => {
    const h1 = mainRef.current?.querySelector("h1");
    if (h1) {
      h1.setAttribute("tabindex", "-1");
      h1.focus();
    }
  }, [pathname]);

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <header className="app-header">
        <Link to="/" className="brand">
          Onolys
        </Link>
        <nav aria-label="Main">
          <NavLink to="/">Sessions</NavLink>
          <NavLink to="/sessions/new">New session</NavLink>
          <NavLink to="/sample-report">Sample report</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
      </header>
      <main id="main" ref={mainRef}>
        <Outlet />
      </main>
      <footer className="app-footer">
        <p>Onolys</p>
      </footer>
    </div>
  );
}
