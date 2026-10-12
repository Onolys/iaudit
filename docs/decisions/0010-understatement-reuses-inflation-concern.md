# 0010. Understatement is reported under frequency or severity inflation

**Audience:** contributors.

**Status:** accepted.

**Context.** The mission's check 7 now covers understating as well as exaggerating, but contract 1.0.0 has no separate concern type.

**Decision.** An understated claim gets `partially_supported` and the `frequency_severity_inflation` concern; the explanation says "understates". The mission wording changed and the contract stays 1.0.0.

**Alternatives.** Add a new concern type and bump the contract.

**Consequences.** No contract change for the frontend. A reader has to look at the explanation to see the direction.
