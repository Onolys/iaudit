# Agent instructions

`docs/mission.md` is the governing mission statement. Read it before any work. It wins over other docs when they conflict.

Do not build outside its scope (diagnosis, scoring, protocol review, or file-format support) without the user's explicit approval.

Never invent quotations, speaker identities, or timestamps.

## Where docs go

| Path | Purpose | Audience |
|---|---|---|
| `docs/mission.md` | Governing mission and scope | Everyone |
| `docs/architecture.md` | High-level design: how the system fits together | Everyone |
| `docs/concepts/` | How should I think about this? Behavior that crosses components | Users and contributors |
| `docs/implementation/` | How is this implemented? Private implementation details | Maintainers and coding agents |
| `docs/reference/` | What exactly is supported? Precise, lookup-oriented facts | Users |
| `docs/decisions/` | Why is it like this? Architecture decision records | Contributors |
| `docs/testing/` | How to test, and what to verify before a release | Contributors |
| `docs/specs/` | Normative behavior contracts with acceptance criteria | Contributors and coding agents |
| `docs/examples/` | Runnable public-API usage examples | Users |
| `docs/agent_files/` | Branch-scoped agent artifacts, one folder per branch | Coding agents |

## Agent-generated files

All agent-generated, branch-related files (PRDs, task lists, reviews, plans, notes) go under `docs/agent_files/<branch-name-timestamp>/`.

Replace `/` in the branch name with `-`. Create that folder once per branch and reuse it.
