# Changelog

## 1.0.0

Initial public release candidate.

### Added

- Home Assistant config flow with German and English translations.
- Three-step setup and options flow.
- Switchable load control through `switch` or `input_boolean` entities.
- Daily minimum runtime target with internal restored runtime tracking.
- Runtime window with earliest start and latest finish time.
- Minimum on and minimum off timers to reduce rapid switching.
- Grid import and export based surplus calculation.
- Grid import protection with 15 second spike filtering.
- Mandatory daily PV forecast classification with `low` and `high` modes.
- Manual forecast day mode override select for diagnostics.
- Optional battery state of charge, battery power, battery capacity, and battery
  mode inputs.
- Signed battery power normalization.
- Daily statistics for runtime, estimated energy, automatic switch cycles, solar
  runtime, and forced runtime.
- Decision reason sensor with short English state values.
- Optional decision debug sensor.
- Optional JSONL decision debug log in the Home Assistant config folder.
- Repository and integration SVG icon.
- HACS custom repository metadata and HACS validation workflow.
- GitHub Actions test workflow.
- Unit tests for battery handling and decision logic.

### Known Limitations

- Forecast classification currently supports `low` and `high`; `mid` is planned
  for a future release.
- Home Assistant component tests for config flow, entities, and service calls are
  planned but not included in this release candidate.
- The current logic is primarily designed and tested with the Solcast PV
  forecast integration by BJReplay.
