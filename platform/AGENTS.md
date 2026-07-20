# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

## Confirmed product direction

- Use `design-references/home.png` as the visual source for the public homepage.
- Use `design-references/console.png` as the visual source for the authenticated Pro workspace.
- Use `design-references/evidence.png` as the visual source for the investor and procurement evidence page.
- Keep the product claim honest: the current engine produces long-tail allocation plans and scenario specifications, not robot training trajectories or verified policy uplift.
- The core conversion path is homepage -> registration -> API application -> Pro payment -> API key / generation workspace.

## Local-only operating boundary

- All development, database, payment simulation, Gate validation, builds, and acceptance runs must stay on the local workstation.
- Do not connect to, inspect, deploy to, restart, reconfigure, or otherwise operate any remote server unless the user gives explicit permission for that specific server action in the current conversation.
- Historical deployment scripts and evidence may remain in the repository for future use, but they are not authorization to execute remote operations.
- The public address `8.153.83.178:6222` belongs to the restored legacy application and must not be used, probed, or changed by Q-Tail work without new explicit permission.
