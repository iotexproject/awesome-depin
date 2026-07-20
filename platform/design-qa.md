# Design QA

## Scope

- Homepage: `/`
- Investor and procurement evidence: `/evidence`
- Authenticated Pro generation workspace: `/app/studio`
- Procurement Gate workflow: `/app/gates`
- Billing QR flow: `/app/billing`
- Mobile checks: 390 × 844

## Source, implementation, and comparison

| Surface | Source | Implementation | Same-input comparison |
|---|---|---|---|
| Homepage | `design-references/home.png` | `design-qa-artifacts/home-implementation-pass2.png` | `design-qa-artifacts/home-comparison-final.png` |
| Evidence | `design-references/evidence.png` | `design-qa-artifacts/evidence-implementation-pass3.png` | `design-qa-artifacts/evidence-comparison-final.png` |
| Pro console | `design-references/console.png` | `design-qa-artifacts/console-implementation-final.png` | `design-qa-artifacts/console-comparison-final.png` |
| Procurement Gate | `design-references/console.png` | `design-qa-artifacts/procurement-desktop-pass2.png` | `design-qa-artifacts/procurement-comparison-pass2.png` |

Desktop references and implementations were captured at the same viewport and state, placed side by side, and inspected as a single comparison image.

## Iterations

1. Homepage: corrected headline wrapping and hero density to match the selected source.
2. Evidence: corrected title wrapping, card density, status dots, icons, and vertical rhythm.
3. Console: restored the source sidebar width, converted the form to the source's single-column anatomy, added helper copy, collapsed advanced settings, and aligned the four-gate timeline.
4. Responsive: verified homepage, evidence, and console at 390 × 844 with no horizontal overflow; added accessible labels to compact navigation.
5. Procurement: reused the console shell, tokens, typography, panels, status colors, and Gate rail; verified the evidence workbench at 1488 × 1058 and 390 × 844 (`design-qa-artifacts/procurement-mobile-390.png`) with no horizontal overflow.

## Functional interaction checks

- Homepage navigation and conversion links
- Registration, session persistence, login, logout, and protected-route redirect
- API application submission and operator approval
- WeChat order, visible real QR asset, payment reference submission, and operator confirmation
- Pro entitlement refresh and one-time API key reveal
- CSV contract format check
- Real Q-Tail generation completion and authenticated ZIP download
- Procurement project creation from a completed Pro generation job
- Gate 1 evidence field validation, evidence hash creation, submission, and review-pending state
- Operator approval plus Gate 2/3 threshold evaluation, contract-ready creation, and signed-reference archival
- Mobile navigation accessible names

## Browser console

Errors: 0  
Warnings: 0

## Accepted intentional differences

- The generation workspace accepts a real CSV contract instead of the mock's Markdown task brief.
- Gate labels distinguish a complete input contract from trajectory execution and buyer validation.
- Personal QR codes use manual operator verification because no signed merchant callback exists.
- The procurement page extends the console source rather than copying its task form: the left workbench records evidence while the right rail preserves the same four-Gate anatomy.

These differences are required for functional correctness and an honest procurement claim; they do not create P0, P1, or P2 visual defects.

Final result: passed
