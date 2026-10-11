export function SuggestionBox({ text }: { text: string }) {
  return (
    <section className="cd-suggestion" aria-label="Suggestion">
      <h3>Suggestion — not applied</h3>
      <p>{text}</p>
    </section>
  );
}
