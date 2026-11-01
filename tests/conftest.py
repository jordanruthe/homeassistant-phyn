"""Test fixtures for Phyn integration."""
import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

# Add the project root to the Python path so imports work.
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def pytest_configure(config: pytest.Config) -> None:
    """Pre-register the project's custom_components namespace package.

    Home Assistant's loader._async_mount_config_dir() temporarily inserts its
    own testing_config directory into sys.path and then calls
    ``import custom_components``.  If the namespace package has NOT yet been
    cached in sys.modules, that import will create a sys.modules entry whose
    ``__path__`` only contains the plugin's testing_config/custom_components
    directory -- leaving our project's custom_components invisible.

    By importing the namespace here (while the project root IS in sys.path)
    we ensure sys.modules['custom_components'].__path__ already includes our
    project directory.  The subsequent HA import becomes a no-op (cached
    module), so our path is preserved for the lifetime of the test session.
    """
    project_cc = str(project_root / "custom_components")
    if "custom_components" not in sys.modules:
        importlib.import_module("custom_components")
    cc = sys.modules.get("custom_components")
    if cc is not None and project_cc not in list(cc.__path__):
        cc.__path__.append(project_cc)

# Only load the HA custom-component test plugin when it is installed.
# This lets pure-unit tests (which have no HA runtime dependency) run
# in environments where only the base pytest stack is available, while
# the full harness is still enabled in CI where requirements_test.txt
# has been installed.
if importlib.util.find_spec("pytest_homeassistant_custom_component"):
    pytest_plugins = "pytest_homeassistant_custom_component"

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Enable custom integrations."""
        yield
