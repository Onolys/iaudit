import "./tokens/tokens.css";
import { ROLE_STYLE, VERDICT_STYLE } from "./tokens";

export default function App() {
  return (
    <main>
      <h1>iaudit review</h1>
      <h2>Verdicts</h2>
      <ul>
        {Object.entries(VERDICT_STYLE).map(([key, v]) => (
          <li key={key} style={{ color: `var(--verdict-${key.replaceAll("_", "-")})` }}>
            <span aria-hidden="true">{v.icon}</span>{" "}
            <span style={{ textDecoration: `underline ${v.underline}` }}>{v.label}</span>
          </li>
        ))}
      </ul>
      <h2>Evidence roles</h2>
      <ul>
        {Object.entries(ROLE_STYLE).map(([key, r]) => (
          <li key={key} style={{ color: `var(--role-${key})` }}>
            {r.label}
          </li>
        ))}
      </ul>
    </main>
  );
}
