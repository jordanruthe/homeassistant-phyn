# homeassistant-phyn

Home Assistant custom component for interfacing with [Phyn](https://www.phyn.com) Smart Water Assistant and Kohler H2Wise+ by Phyn.

This integration currently provides the following capabilities:

- Daily water usage (compatible with Energy dashboard)
- Average water temperature, pressure, and flow (realtime not available)
- Shutoff valve control
- Away mode control

# Installation via HACS

This custom component can be integrated into [HACS](https://github.com/hacs/integration), so you can track future updates. If you have do not have have HACS installed, please see [their installation guide](https://hacs.xyz/docs/installation/manual).

1. Select HACS from the left-hand navigation menu.

2. Click _Integrations_.

3. Click the three dots in the upper right-hand corner and select _Custom Repositories_.

4. Paste "https://github.com/jordanruthe/homeassistant-phyn" into _Repository_, select "Integration" as _Category_, and click Add.

5. Close the Custom repositories dialog after it updates with the new integration.

6. "Phyn Smart Water Assistant" will appear in your list of repositories. Click to open, click the following Download buttons.

# Configuration

Configuration is done via the UI. Add the "Phyn" integration via the Integration settings and provide existing Phyn username and password.

* In the Home Assistant UI, go to Settings > Devices & services, go to the Devices tab, and click "+ Add Device" on the bottom right.

* Search for and select "Phyn".

* A prompt will appear for you to enter your Phyn Account username and password. (This could sometimes take 2-3 minutes, or longer).

# Tracking usage since a date (e.g. cistern fills)

If you draw water from a cistern (or any fixed-capacity tank) and need to know how much has been used since the last fill — so you can trigger a "refill needed" notification — you can do this entirely with built-in Home Assistant helpers. No extra integration code is required.

## Which sensor to use

**Phyn Plus (PP1/PP2) devices** expose a **"Total Water Usage"** sensor
(`sensor.<device>_total_water_usage`) that is a cumulative, ever-increasing meter sourced
from the device's real-time MQTT feed. This is the best source for this use-case.

**Phyn Classic (PC1) devices** do not have a cumulative meter; use the **"Daily water usage"**
sensor (`sensor.<device>_daily_consumption`) instead. The `utility_meter` will accumulate
daily totals across days without resetting automatically.

## Step 1 — Create a utility_meter helper

Add the following to your `configuration.yaml` (adjust the `source` entity ID to match
your actual device):

```yaml
utility_meter:
  cistern_usage_since_fill:
    source: sensor.phyn_total_water_usage   # adjust to your entity id
    # No "cycle:" key → meter accumulates indefinitely until manually reset
```

Restart Home Assistant. A new sensor `sensor.cistern_usage_since_fill` will appear,
showing gallons used since the meter was last reset.

> **Tip:** Find your exact entity ID in **Settings → Devices & services → Phyn → entities**.

## Step 2 — Record the fill date (optional)

Create an **Input Datetime** helper to log when each fill happened
(**Settings → Devices & services → Helpers → + Create helper → Date and/or time**),
e.g. named `Cistern fill date` → entity `input_datetime.cistern_fill_date`.

## Step 3 — Reset the meter on each fill

When you refill the cistern, reset the `utility_meter` via **Developer Tools → Actions**:

| Field | Value |
|-------|-------|
| Action | `utility_meter.reset` |
| Targets (entity) | `sensor.cistern_usage_since_fill` |

Or, in an automation triggered by a dashboard button, a physical button helper, etc.:

```yaml
action:
  - service: utility_meter.reset
    target:
      entity_id: sensor.cistern_usage_since_fill
  - service: input_datetime.set_datetime
    target:
      entity_id: input_datetime.cistern_fill_date
    data:
      datetime: "{{ now().isoformat() }}"
```

## Step 4 — Automate the refill alert

```yaml
automation:
  - alias: "Cistern refill needed"
    trigger:
      - platform: numeric_state
        entity_id: sensor.cistern_usage_since_fill
        above: 900        # gallons used since fill; adjust to your cistern capacity
    action:
      - service: notify.notify
        data:
          title: "Cistern refill needed"
          message: >
            {{ states('sensor.cistern_usage_since_fill') }} gal used since the
            last fill on {{ states('input_datetime.cistern_fill_date') }}.
```

For longer-term trends, the **"Daily water usage"** sensor is already compatible with the
Home Assistant **Energy / Water** dashboard.

**Further reading:**
- [utility_meter integration](https://www.home-assistant.io/integrations/utility_meter/)
- [input_datetime integration](https://www.home-assistant.io/integrations/input_datetime/)

# Known Issues

* Phyn home name (in the Phyn App > Settings > Home > Address > Home Name) cannot be set to "Home" or integration configuration and setup will fail.

* If get an (API) error when trying to first initialize saying "User Not Found" then take note that Phyn username e-mail address is case sensitive.

## Changelog

_2023.01.00_

- Initial release

_2023.08.00_

- Added away mode control

## Developer note

The base entity classes have been consolidated into a single canonical location: `custom_components/phyn/entities/base.py`. The legacy `custom_components/phyn/entity.py` file has been completely removed to eliminate duplicate class definitions. If you maintain local forks or external code that imports from the old path, please update imports to use `..entities.base` (for internal package imports) or `custom_components.phyn.entities.base` as appropriate.

## Development and Testing

This integration includes automated tests to ensure quality and reliability.

### Running Tests Locally

```bash
# Install test dependencies
pip install -r requirements_test.txt

# Run all tests
pytest tests/

# Run with coverage report
pytest tests/ --cov=custom_components.phyn --cov-report=term-missing -v

# Run specific test file
pytest tests/test_config_flow.py -v
```

### Continuous Integration

Tests run automatically on every pull request via GitHub Actions. The test suite validates:
- Config flow (user setup, authentication, error handling)
- Integration setup and teardown
- Configuration migration
- Reauth and reconfigure flows

This ensures compatibility with Home Assistant 2024.2.0+ and helps maintain Bronze tier quality standards.
