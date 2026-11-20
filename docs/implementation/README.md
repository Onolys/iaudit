# Implementation

How is this implemented? Private implementation details.

**Audience:** maintainers and coding agents.

- [frontend.md](frontend.md): eaudit/Eval architecture, transport, saved replay and review UI internals.
- [pipeline.md](pipeline.md): flows, deadline, degradation, metrics.
- [llm-client.md](llm-client.md): the one interface to every model call.
- [prep-atomize.md](prep-atomize.md): dialogue acts and claim extraction.
- [link.md](link.md): finding evidence.
- [check.md](check.md): the verifier and the decision table.
- [assembler.md](assembler.md): positions, repairs and final validation.
- [logging-and-phi.md](logging-and-phi.md): what may be logged.
- [eval-server.md](eval-server.md): evaluation API lifecycle, guards, read projections and schema export.
