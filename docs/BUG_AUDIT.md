# Deep code review and bug-fix record

## Review baseline

- Repository baseline: 2a955397d80c5cfa92bb31a4fbc8f48ade8516d7.
- Review included Python modules, SQL migrations, control YAML, both GitHub Actions workflows, packaging/dependency files, README, acceptance documentation and existing tests.
- No production database, provider key, mailbox, or SMTP server was used during this review.

## Findings addressed in this reviewed copy

| Priority | Finding | Fix / regression coverage |
|---|---|---|
| High | A resumed blocked real campaign could be stuck when every durable Google Places query cursor was marked exhausted. The next run could show zero Places requests and return a generic incomplete-target result. | On a resumed real campaign, reset discovery pagination only when all currently configured unique queries have durable exhausted cursors. Partial/in-progress cursors are retained. Add a PostgreSQL integration test verifying that a second invocation actually requests discovery again. |
| High | Website research used only the first validated public DNS address. A connection/header failure on that address discarded other validated addresses. | Try the other addresses from the same fully validated DNS result when connection/request-header setup fails. Keep host-based SNI/certificate checks, same-origin redirect checks, TLS downgrade rejection, public-address validation, resource limits and robots enforcement. Certificate-verification failures fail closed without address failover. Add pinned-IP and certificate-failure tests. |
| Medium | Redirect loops were discovered only after consuming the fixed redirect-hop allowance. | Track normalized, non-canonicalized URL hops and reject a repeated hop. A www to bare-host redirect is not collapsed for loop identity. Add a redirect-loop regression test. |
| Medium | The crawler's text fallback ran only if it found no standard text blocks. Websites with short heading fragments and useful prose inside generic containers could be rejected as having no usable evidence. | If a page contributes no usable evidence, inspect filtered div, section, address and blockquote content; run the same sentence-quality filters; keep each snippet in the page text so validation can verify provenance. Add a generic-container evidence test. |
| Medium | Malformed LLM JSON/schema failures were collapsed into one generic message; malformed observation shapes could raise an unexpected Python error before deterministic validation. | Emit fixed, secret-free categories for missing choices/content, JSON parse, missing fields and invalid field types. Harden rendering for malformed observation containers. Add diagnostic and malformed-observation tests; never log raw model output. |
| Medium | Provider timeouts and connection failures shared one diagnostic, making event breakdowns less useful; a Places authorization failure could repeat for each query. | Split transport diagnostics into fixed messages and fail fast on provider-wide Places authorization failures without burning calls on other queries. |
| Low | The POSTAL_ADDRESS environment override was applied only while iterating control-file sections, so a valid empty YAML mapping skipped the override. | Apply the environment override after merging the optional control sections; add an empty-YAML regression test. |
| Low | Failure-state persistence interpolated the table name into SQL, although callers currently passed only internal constant names. | Replace dynamic SQL construction with a fixed allowlist of prebuilt statements for candidate and lead work rows. |
| Maintenance | Both workflows used Node 20-based action major versions and produced deprecation notices in the supplied run logs. | Update checkout and setup-python actions to their Node 24-compatible v7 majors; verify the project test suite after the workflow edit. |

## Verification performed

- Targeted, network-mocked suite: tests/test_providers.py, tests/test_config.py, tests/test_scheduling.py.
- Full suite against an isolated local PostgreSQL 15 database: 278 passed.
- Python compilation: python -m py_compile attachai/*.py tests/*.py.
- Static checks: Ruff unused-import checks passed; Bandit passed after documenting the custom SafeLoader and removing dynamic table-name SQL construction; pip-audit found no known vulnerabilities in requirements.txt.
- The project CI workflow uses PostgreSQL 16; this sandbox run used PostgreSQL 15 and did not use production secrets.
- Provider, SMTP and IMAP tests use mocks. These results are not a test of live Google Places/LLM quotas, SMTP deliverability, or the production Supabase project.

## Recovery after deploying

For an unfinished campaign, retain the original target and reset_state=false. Check that the next run has a positive places_requests count when discovery is needed. Do not re-run real sending just to test code. First run CI, then the read-only database diagnostic, then a deliberate safe dry-run and inspect state. Resolve any review/ambiguous SMTP messages only with authoritative provider evidence; do not reset state to clear them.

## Remaining limitations

Static review and regression tests reduce known defects; they cannot prove the absence of all bugs. Live provider authorization, quotas, business inventory, mailbox settings, actual production data, sender health and deliverability remain deployment-specific. No live production run was triggered by this review.
