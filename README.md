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
