# Security Policy

## Reporting a vulnerability

Please report suspected security issues **privately** — do **not** open a public
issue for a vulnerability.

Use GitHub's [private vulnerability reporting][gh-pvr] ("Report a vulnerability",
under the repository's **Security** tab). It opens an advisory visible only to the
maintainer, so the report stays confidential until a fix is ready. Include enough
to reproduce: the affected version or commit SHA, the steps, and the impact you
observed.

[gh-pvr]: https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability

## Scope and expectations

This is a small, single-maintainer project — an audit/process layer for
agent-driven development, dogfooded on its own development. Response is
**best-effort**: there is no service-level guarantee on triage or fix timelines,
and no guarantee a given report will be acted on. Genuine, clearly-described
issues are prioritized over speculative ones.

Only the tip of the default branch is supported; fixes are not back-ported to
older tags.

## What the gate does and does not guarantee

The harness is a verification layer: deterministic gates an agent runs, plus the
guidance that says when to run them. That is a workflow aid, **not** a
cryptographic attestation. Every part of it — the gate script, the tests it runs,
the records that say what shipped — is an ordinary file in the workspace, so
anything with write access there, including the agent under review, can edit the
check or the evidence it produces. Treat a green gate as an account of what a
cooperating agent did, not as tamper-evident proof against a hostile one. Do not
build a security control on top of it.

## No bug bounty

There is **no bug bounty** program and no monetary reward for reports.
Disclosures are accepted and appreciated on a goodwill basis.
