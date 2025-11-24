#!/usr/bin/env python3
"""Comprehensive tests for the numeric parameter preprocessing function.

Tests the preprocess_numeric_parameters function from common.validation module
covering all edge cases and error handling scenarios.
"""

import pytest
import sys
import os
from typing import Dict, Any, Type, Union

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from revenium_mcp_server.common.validation import preprocess_numeric_parameters


class TestNumericParameterPreprocessing:
    """Test suite for numeric parameter preprocessing function."""
    
    def test_string_to_int_conversion(self):
        """Test conversion of string integers to int type."""
        arguments = {
            "page": "1",
            "size": "10",
            "count": "42",
            "name": "test"  # Non-numeric parameter
        }
        numeric_params = {
            "page": int,
            "size": int,
            "count": int
        }
        
        result = preprocess_numeric_parameters(arguments, numeric_params)
        
        assert result["page"] == 1
        assert result["size"] == 10
        assert result["count"] == 42
        assert result["name"] == "test"  # Unchanged
        assert isinstance(result["page"], int)
        assert isinstance(result["size"], int)
        assert isinstance(result["count"], int)
    
    def test_string_to_float_conversion(self):
        """Test conversion of string floats to float type."""
        arguments = {
            "threshold": "99.5",
            "min_impact": "0.25",
            "percentage": "100.0",
            "description": "test"  # Non-numeric parameter
        }
        numeric_params = {
            "threshold": float,
            "min_impact": float,
            "percentage": float
        }
        
        result = preprocess_numeric_parameters(arguments, numeric_params)
        
        assert result["threshold"] == 99.5
        assert result["min_impact"] == 0.25
        assert result["percentage"] == 100.0
        assert result["description"] == "test"  # Unchanged
        assert isinstance(result["threshold"], float)
        assert isinstance(result["min_impact"], float)
        assert isinstance(result["percentage"], float)
    
    def test_mixed_parameter_types(self):
        """Test conversion with mixed int and float parameters."""
        arguments = {
            "page": "1",
            "size": "10",
            "threshold": "99.5",
            "min_impact": "0.25",
            "action": "test"
        }
        numeric_params = {
            "page": int,
            "size": int,
            "threshold": float,
            "min_impact": float
        }
        
        result = preprocess_numeric_parameters(arguments, numeric_params)
        
        assert result["page"] == 1
        assert result["size"] == 10
        assert result["threshold"] == 99.5
        assert result["min_impact"] == 0.25
        assert result["action"] == "test"
        assert isinstance(result["page"], int)
        assert isinstance(result["size"], int)
        assert isinstance(result["threshold"], float)
        assert isinstance(result["min_impact"], float)
    
    def test_already_numeric_values_unchanged(self):
        """Test that already numeric values are not modified."""
        arguments = {
            "page": 1,
            "size": 10,
            "threshold": 99.5,
            "count": 42
        }
        numeric_params = {
            "page": int,
            "size": int,
            "threshold": float,
            "count": int
        }
        
        result = preprocess_numeric_parameters(arguments, numeric_params)
        
        assert result["page"] == 1
        assert result["size"] == 10
        assert result["threshold"] == 99.5
        assert result["count"] == 42
        assert isinstance(result["page"], int)
        assert isinstance(result["size"], int)
        assert isinstance(result["threshold"], float)
        assert isinstance(result["count"], int)
    
    def test_invalid_string_conversion_graceful_handling(self):
        """Test that invalid strings are kept as-is for downstream error handling."""
        arguments = {
            "page": "invalid",
            "size": "not_a_number",
            "threshold": "abc.def",
            "valid_param": "123"
        }
        numeric_params = {
            "page": int,
            "size": int,
            "threshold": float,
            "valid_param": int
        }
        
        result = preprocess_numeric_parameters(arguments, numeric_params)
        
        # Invalid conversions should remain as strings
        assert result["page"] == "invalid"
        assert result["size"] == "not_a_number"
        assert result["threshold"] == "abc.def"
        # Valid conversion should work
        assert result["valid_param"] == 123
        assert isinstance(result["page"], str)
        assert isinstance(result["size"], str)
        assert isinstance(result["threshold"], str)
        assert isinstance(result["valid_param"], int)
    
    def test_none_values_handling(self):
        """Test that None values are handled correctly."""
        arguments = {
            "page": None,
            "size": "10",
            "threshold": None,
            "count": "42"
        }
        numeric_params = {
            "page": int,
            "size": int,
            "threshold": float,
            "count": int
        }
        
        result = preprocess_numeric_parameters(arguments, numeric_params)
        
        assert result["page"] is None
        assert result["size"] == 10
        assert result["threshold"] is None
        assert result["count"] == 42
    
    def test_empty_string_handling(self):
        """Test that empty strings are kept as-is."""
        arguments = {
            "page": "",
            "size": "10",
            "threshold": "",
            "name": ""
        }
        numeric_params = {
            "page": int,
            "size": int,
            "threshold": float
        }
        
        result = preprocess_numeric_parameters(arguments, numeric_params)
        
        assert result["page"] == ""
        assert result["size"] == 10
        assert result["threshold"] == ""
        assert result["name"] == ""
        assert isinstance(result["page"], str)
        assert isinstance(result["size"], int)
        assert isinstance(result["threshold"], str)
    
    def test_edge_case_numeric_values(self):
        """Test edge cases like zero, negative numbers, and large numbers."""
        arguments = {
            "zero": "0",
            "negative": "-42",
            "large": "999999",
            "decimal": "-123.456",
            "scientific": "1.23e-4"
        }
        numeric_params = {
            "zero": int,
            "negative": int,
            "large": int,
            "decimal": float,
            "scientific": float
        }
        
        result = preprocess_numeric_parameters(arguments, numeric_params)
        
        assert result["zero"] == 0
        assert result["negative"] == -42
        assert result["large"] == 999999
        assert result["decimal"] == -123.456
        assert result["scientific"] == 1.23e-4
        assert isinstance(result["zero"], int)
        assert isinstance(result["negative"], int)
        assert isinstance(result["large"], int)
        assert isinstance(result["decimal"], float)
        assert isinstance(result["scientific"], float)
    
    def test_missing_parameters_in_numeric_map(self):
        """Test that parameters not in numeric_params are unchanged."""
        arguments = {
            "page": "1",
            "size": "10",
            "action": "test",
            "name": "example",
            "threshold": "99.5"
        }
        numeric_params = {
            "page": int,
            "size": int
            # threshold not in numeric_params
        }
        
        result = preprocess_numeric_parameters(arguments, numeric_params)
        
        assert result["page"] == 1
        assert result["size"] == 10
        assert result["action"] == "test"
        assert result["name"] == "example"
        assert result["threshold"] == "99.5"  # Unchanged
        assert isinstance(result["page"], int)
        assert isinstance(result["size"], int)
        assert isinstance(result["threshold"], str)
    
    def test_empty_arguments_dict(self):
        """Test with empty arguments dictionary."""
        arguments = {}
        numeric_params = {"page": int, "size": int}
        
        result = preprocess_numeric_parameters(arguments, numeric_params)
        
        assert result == {}
    
    def test_empty_numeric_params_dict(self):
        """Test with empty numeric_params dictionary."""
        arguments = {"page": "1", "size": "10", "action": "test"}
        numeric_params = {}
        
        result = preprocess_numeric_parameters(arguments, numeric_params)
        
        assert result == arguments  # Should be unchanged
    
    def test_arguments_dict_not_modified(self):
        """Test that the original arguments dictionary is not modified."""
        original_arguments = {
            "page": "1",
            "size": "10",
            "threshold": "99.5"
        }
        arguments = original_arguments.copy()
        numeric_params = {
            "page": int,
            "size": int,
            "threshold": float
        }
        
        result = preprocess_numeric_parameters(arguments, numeric_params)
        
        # Original should be unchanged
        assert arguments == original_arguments
        assert arguments["page"] == "1"  # Still string
        assert arguments["size"] == "10"  # Still string
        assert arguments["threshold"] == "99.5"  # Still string
        
        # Result should be converted
        assert result["page"] == 1  # Now int
        assert result["size"] == 10  # Now int
        assert result["threshold"] == 99.5  # Now float


if __name__ == "__main__":
    # Run tests directly if executed as script
    import sys
    
    test_instance = TestNumericParameterPreprocessing()
    
    test_methods = [
        test_instance.test_string_to_int_conversion,
        test_instance.test_string_to_float_conversion,
        test_instance.test_mixed_parameter_types,
        test_instance.test_already_numeric_values_unchanged,
        test_instance.test_invalid_string_conversion_graceful_handling,
        test_instance.test_none_values_handling,
        test_instance.test_empty_string_handling,
        test_instance.test_edge_case_numeric_values,
        test_instance.test_missing_parameters_in_numeric_map,
        test_instance.test_empty_arguments_dict,
        test_instance.test_empty_numeric_params_dict,
        test_instance.test_arguments_dict_not_modified,
    ]
    
    passed = 0
    total = len(test_methods)
    
    print("🧪 Running comprehensive numeric preprocessing tests...")
    print("=" * 60)
    
    for i, test_method in enumerate(test_methods, 1):
        test_name = test_method.__name__.replace('test_', '').replace('_', ' ').title()
        try:
            print(f"{i:2d}. {test_name}...")
            test_method()
            print(f"    ✅ PASSED")
            passed += 1
        except Exception as e:
            print(f"    ❌ FAILED: {e}")
    
    print(f"\n📊 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Numeric preprocessing function is working correctly.")
        sys.exit(0)
    else:
        print("⚠️  Some tests failed. Function needs fixes.")
        sys.exit(1)
