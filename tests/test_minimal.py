"""Minimal test to verify setup works."""
from custom_components.phyn.const import DOMAIN


def test_domain_exists():
    """Test that the domain constant exists."""
    assert DOMAIN == "phyn"
    assert len(DOMAIN) > 0
