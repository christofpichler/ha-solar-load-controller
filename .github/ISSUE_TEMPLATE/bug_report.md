---
name: Bug report
about: Report unexpected switching behavior, setup problems, or runtime issues
title: "[Bug]: "
labels: bug
---

## What happened?

Describe the unexpected behavior.

## What did you expect to happen?

Describe the expected behavior.

## Environment

- Integration version:
- Home Assistant version:
- Installation method: HACS custom repository / Manual custom_components copy / Other
- PV forecast integration: Solcast by BJReplay / Other / None

## Solar/load setup

Include the values that influence the decision engine.

- PV size:
- Inverter limit:
- Battery size / mode:
- Controlled load:
- Load power:
- Grid import limit:
- Minimum runtime:
- Allowed time window:

## Relevant entity values

Paste the values from the time of the problem if available.

- `decision_reason`:
- `forecast_day_mode`:
- `forecast_day_mode_override`:
- `grid_import`:
- `grid_export`:
- `pv_current_power`:
- `forecast_today`:
- `forecast_remaining_today`:
- `forecast_next_hour`:
- `battery_soc`:
- `battery_power`:
- `load switch state`:

## Decision debug log

If this is about switching behavior, enable the debug sensor in the integration options and include the relevant lines from:

`/config/solar_load_controller_decisions.jsonl`

## Home Assistant logs

Paste warnings or errors from Home Assistant logs if there are any.

## Additional context

Add screenshots, automations, entity history, or anything else that helps.
