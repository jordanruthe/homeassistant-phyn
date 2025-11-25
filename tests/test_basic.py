"""Minimal smoke test for Phyn integration."""
import json
from pathlib import Path


def test_manifest_exists():
    """Test that manifest.json exists and is valid."""
    manifest_path = Path(__file__).parent.parent / "custom_components" / "phyn" / "manifest.json"
    
    assert manifest_path.exists(), "manifest.json not found"
    
    with open(manifest_path) as f:
        manifest = json.load(f)
    
    assert manifest["domain"] == "phyn"
    assert manifest["name"] == "Phyn"
    assert "version" in manifest
    assert len(manifest["version"]) > 0


def test_init_file_exists():
    """Test that __init__.py exists."""
    init_path = Path(__file__).parent.parent / "custom_components" / "phyn" / "__init__.py"
    assert init_path.exists(), "__init__.py not found"


def test_strings_file_exists():
    """Test that strings.json exists and is valid."""
    strings_path = Path(__file__).parent.parent / "custom_components" / "phyn" / "strings.json"
    
    assert strings_path.exists(), "strings.json not found"
    
    with open(strings_path) as f:
        strings = json.load(f)
    
    assert "config" in strings
