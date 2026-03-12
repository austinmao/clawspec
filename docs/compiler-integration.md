# Compiler Integration

ClawSpec works with compiler-managed repositories as long as the compiler emits
native ClawSpec contract files and the repo config points at those locations.

## Recommended layout

Keep runtime targets under the normal OpenClaw paths:

- `skills/**/SKILL.md`
- `agents/**/SOUL.md`

Point ClawSpec at compiler-generated QA files with config:

```yaml
scenario_patterns:
  - "compiler/generated/qa/**/scenarios.yaml"
ledger_path: "docs/testing/coverage-ledger.yaml"
```

## Contract shape

Generated `scenarios.yaml`, handoff, and pipeline files should use the same
schemas that ClawSpec validates in `clawspec/schemas/`.

If your compiler currently emits lightweight QA placeholders, treat those as an
upstream scaffold step and add a render step that upgrades them into native
ClawSpec contracts before running `clawspec run`.

## Host-project cutover

For existing repositories:

1. Keep legacy validate/run/coverage entry points as wrappers during cutover.
2. Install ClawSpec as an editable dependency or pinned package.
3. Move compiler-managed QA outputs onto the configured `scenario_patterns`.
4. Re-run structural validation, smoke scenarios, and coverage parity before
   removing legacy implementations.
