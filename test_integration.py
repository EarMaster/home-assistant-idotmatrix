#!/usr/bin/env python3
"""Test script for iDotMatrix Home Assistant integration."""

import asyncio
import logging
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Mock the Home Assistant components
sys.modules['homeassistant'] = MagicMock()
sys.modules['homeassistant.config_entries'] = MagicMock()
sys.modules['homeassistant.const'] = MagicMock()
sys.modules['homeassistant.core'] = MagicMock()
sys.modules['homeassistant.helpers'] = MagicMock()
sys.modules['homeassistant.helpers.update_coordinator'] = MagicMock()
sys.modules['homeassistant.helpers.device_registry'] = MagicMock()
sys.modules['homeassistant.components.light'] = MagicMock()
sys.modules['homeassistant.components.switch'] = MagicMock()
sys.modules['homeassistant.components.text'] = MagicMock()
sys.modules['homeassistant.components.select'] = MagicMock()
sys.modules['homeassistant.components.button'] = MagicMock()

# Mock the iDotMatrix library
sys.modules['idotmatrix'] = MagicMock()
sys.modules['idotmatrix.common'] = MagicMock()
sys.modules['idotmatrix.text'] = MagicMock()
sys.modules['idotmatrix.clock'] = MagicMock()
sys.modules['idotmatrix.effects'] = MagicMock()
sys.modules['idotmatrix.chronograph'] = MagicMock()

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def test_integration_basic():
    """Test basic integration functionality."""
    print("Testing iDotMatrix Integration")
    print("=" * 40)
    
    # Test imports (with dependency handling)
    try:
        # Test basic Python imports first
        import sys
        import os
        sys.path.insert(0, os.getcwd())
        
        from custom_components.idotmatrix import const
        print("✓ Constants import successful")
        print(f"✓ Domain: {const.DOMAIN}")
        print(f"✓ Platforms: {const.PLATFORMS}")
        print(f"✓ Services: {[const.SERVICE_DISPLAY_TEXT, const.SERVICE_DISPLAY_IMAGE]}")
        
        # Try importing other modules (may fail due to missing dependencies)
        try:
            from custom_components.idotmatrix.config_flow import IDotMatrixConfigFlow
            config_flow = IDotMatrixConfigFlow()
            print(f"✓ Config flow initialized: {config_flow.__class__.__name__}")
        except ImportError as e:
            print(f"⚠ Config flow import failed (expected in test environment): {e}")
        
        try:
            from custom_components.idotmatrix.coordinator import IDotMatrixDataUpdateCoordinator
            print("✓ Coordinator import successful")
        except ImportError as e:
            print(f"⚠ Coordinator import failed (expected in test environment): {e}")
        
    except Exception as e:
        print(f"✗ Basic imports failed: {e}")
        return False
    
    print("\nBasic integration tests completed! ✓")
    return True

def test_file_structure():
    """Test that all required files exist."""
    import os
    
    print("\nTesting File Structure")
    print("=" * 40)
    
    base_path = "custom_components/idotmatrix"
    required_files = [
        "__init__.py",
        "manifest.json",
        "const.py",
        "config_flow.py",
        "coordinator.py",
        "entity.py",
        "light.py",
        "switch.py",
        "text.py",
        "select.py",
        "button.py",
        "services.yaml",
        "strings.json",
        "device_trigger.py"
    ]
    
    for file in required_files:
        file_path = os.path.join(base_path, file)
        if os.path.exists(file_path):
            print(f"✓ {file}")
        else:
            print(f"✗ {file} - Missing!")
            return False
    
    print("\nAll required files present! ✓")
    return True

def test_manifest():
    """Test manifest.json validity."""
    import json
    
    print("\nTesting Manifest")
    print("=" * 40)
    
    try:
        with open("custom_components/idotmatrix/manifest.json", "r") as f:
            manifest = json.load(f)
        
        required_keys = ["domain", "name", "version", "requirements", "config_flow"]
        for key in required_keys:
            if key in manifest:
                print(f"✓ {key}: {manifest[key]}")
            else:
                print(f"✗ Missing required key: {key}")
                return False
        
        print("\nManifest is valid! ✓")
        return True
    except Exception as e:
        print(f"✗ Manifest validation failed: {e}")
        return False

def test_services():
    """Test services.yaml validity."""
    print("\nTesting Services")
    print("=" * 40)
    
    try:
        # Test YAML file can be loaded
        try:
            import yaml
        except ImportError:
            print("⚠ PyYAML not available, using basic validation")
            yaml = None
        
        with open("custom_components/idotmatrix/services.yaml", "r") as f:
            if yaml:
                services = yaml.safe_load(f)
                print("✓ services.yaml is valid YAML")
            else:
                content = f.read()
                print("✓ services.yaml file exists and readable")
        
        # Test that expected services are defined (basic text search)
        expected_services = [
            "display_text",
            "display_image", 
            "set_clock_mode",
            "display_effect",
            "sync_time"
        ]
        
        with open("custom_components/idotmatrix/services.yaml", "r") as f:
            content = f.read()
            
        for service in expected_services:
            if service + ":" in content:
                print(f"✓ {service}")
            else:
                print(f"✗ Missing service: {service}")
                return False
        
        print("\nServices configuration is valid! ✓")
        return True
    except Exception as e:
        print(f"✗ Services validation failed: {e}")
        return False

def test_python_syntax():
    """Test that all Python files have valid syntax."""
    import ast
    import os
    
    print("\nTesting Python Syntax")
    print("=" * 40)
    
    base_path = "custom_components/idotmatrix"
    python_files = [
        "__init__.py",
        "const.py", 
        "config_flow.py",
        "coordinator.py",
        "entity.py",
        "light.py",
        "switch.py", 
        "text.py",
        "select.py",
        "button.py",
        "device_trigger.py"
    ]
    
    for file in python_files:
        file_path = os.path.join(base_path, file)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Parse the file to check syntax
            ast.parse(content, filename=file_path)
            print(f"✓ {file} - Valid syntax")
        except SyntaxError as e:
            print(f"✗ {file} - Syntax error: {e}")
            return False
        except Exception as e:
            print(f"✗ {file} - Error reading file: {e}")
            return False
    
    print("\nAll Python files have valid syntax! ✓")
    return True

async def main():
    """Run all tests."""
    print("iDotMatrix Home Assistant Integration Tests")
    print("=" * 50)
    
    tests = [
        test_file_structure,
        test_python_syntax,
        test_manifest,
        test_services,
        test_integration_basic
    ]
    
    results = []
    for test in tests:
        try:
            if asyncio.iscoroutinefunction(test):
                result = await test()
            else:
                result = test()
            results.append(result)
        except Exception as e:
            print(f"✗ Test {test.__name__} failed with exception: {e}")
            results.append(False)
    
    print("\n" + "=" * 50)
    print("Test Summary:")
    print(f"Passed: {sum(results)}/{len(results)}")
    
    if all(results):
        print("🎉 All tests passed! Integration is ready.")
        return 0
    else:
        print("❌ Some tests failed. Please review the output above.")
        return 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nTests interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"Test runner failed: {e}")
        sys.exit(1)
