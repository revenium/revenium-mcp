"""Unit tests for input validation and sanitization."""

import pytest
from datetime import datetime, timezone

from src.revenium_mcp_server.validators import InputValidator
from src.revenium_mcp_server.exceptions import ValidationError, InvalidInputError


class TestStringValidation:
    """Test string validation and sanitization."""
    
    def test_sanitize_string_basic(self):
        """Test basic string sanitization."""
        result = InputValidator.sanitize_string("  Hello World  ")
        assert result == "Hello World"
    
    def test_sanitize_string_html_escape(self):
        """Test HTML escaping in string sanitization."""
        result = InputValidator.sanitize_string("<script>alert('xss')</script>")
        assert "&lt;script&gt;" in result
        assert "alert(&#x27;xss&#x27;)" in result
    
    def test_sanitize_string_control_chars(self):
        """Test removal of control characters."""
        result = InputValidator.sanitize_string("Hello\x00\x01World\x1f")
        assert result == "HelloWorld"
    
    def test_sanitize_string_max_length(self):
        """Test string length validation."""
        long_string = "x" * 100
        
        # Should pass within limit
        result = InputValidator.sanitize_string(long_string, max_length=100)
        assert result == long_string
        
        # Should fail over limit
        with pytest.raises(InvalidInputError):
            InputValidator.sanitize_string(long_string, max_length=50)
    
    def test_validate_anomaly_name_success(self):
        """Test successful anomaly name validation."""
        result = InputValidator.validate_anomaly_name("Valid Anomaly Name")
        assert result == "Valid Anomaly Name"
    
    def test_validate_anomaly_name_empty(self):
        """Test anomaly name validation with empty input."""
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_anomaly_name("")
        assert "name is required" in str(exc_info.value)
    
    def test_validate_anomaly_name_too_short(self):
        """Test anomaly name validation with too short input."""
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_anomaly_name("A")
        assert "at least 2 characters" in str(exc_info.value)
    
    def test_validate_description_success(self):
        """Test successful description validation."""
        result = InputValidator.validate_description("This is a valid description.")
        assert result == "This is a valid description."
        
        # Test with None
        result = InputValidator.validate_description(None)
        assert result is None
        
        # Test with empty string
        result = InputValidator.validate_description("")
        assert result is None


class TestNumericValidation:
    """Test numeric validation."""
    
    def test_validate_numeric_range_success(self):
        """Test successful numeric validation."""
        result = InputValidator.validate_numeric_range(50, "test_field", min_value=0, max_value=100)
        assert result == 50
        
        # Test with float
        result = InputValidator.validate_numeric_range(50.5, "test_field")
        assert result == 50.5
        
        # Test with string
        result = InputValidator.validate_numeric_range("75", "test_field")
        assert result == 75
    
    def test_validate_numeric_range_below_min(self):
        """Test numeric validation below minimum."""
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_numeric_range(-5, "test_field", min_value=0)
        assert "below minimum value" in str(exc_info.value)
    
    def test_validate_numeric_range_above_max(self):
        """Test numeric validation above maximum."""
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_numeric_range(150, "test_field", max_value=100)
        assert "exceeds maximum value" in str(exc_info.value)
    
    def test_validate_numeric_range_zero_not_allowed(self):
        """Test numeric validation when zero is not allowed."""
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_numeric_range(0, "test_field", allow_zero=False)
        assert "cannot be zero" in str(exc_info.value)
    
    def test_validate_numeric_range_invalid_format(self):
        """Test numeric validation with invalid format."""
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_numeric_range("not_a_number", "test_field")
        assert "Invalid test_field format" in str(exc_info.value)


class TestUUIDValidation:
    """Test UUID validation."""
    
    def test_validate_uuid_success(self):
        """Test successful UUID validation."""
        valid_uuid = "123e4567-e89b-12d3-a456-426614174000"
        result = InputValidator.validate_uuid(valid_uuid)
        assert result == valid_uuid.lower()
    
    def test_validate_uuid_invalid_format(self):
        """Test UUID validation with invalid format."""
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_uuid("invalid-uuid")
        assert "Invalid id format" in str(exc_info.value)
    
    def test_validate_uuid_empty(self):
        """Test UUID validation with empty input."""
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_uuid("")
        assert "id is required" in str(exc_info.value)


class TestEmailValidation:
    """Test email validation."""
    
    def test_validate_email_success(self):
        """Test successful email validation."""
        result = InputValidator.validate_email("user@example.com")
        assert result == "user@example.com"
        
        # Test with uppercase
        result = InputValidator.validate_email("USER@EXAMPLE.COM")
        assert result == "user@example.com"
    
    def test_validate_email_invalid_format(self):
        """Test email validation with invalid format."""
        invalid_emails = [
            "invalid-email",
            "@example.com",
            "user@",
            "user.example.com",
            "user@.com"
        ]
        
        for email in invalid_emails:
            with pytest.raises(ValidationError):
                InputValidator.validate_email(email)


class TestTagsValidation:
    """Test tags validation."""
    
    def test_validate_tags_success(self):
        """Test successful tags validation."""
        tags = ["tag1", "tag2", "tag-3", "tag_4"]
        result = InputValidator.validate_tags(tags)
        assert result == tags
    
    def test_validate_tags_empty_list(self):
        """Test tags validation with empty list."""
        result = InputValidator.validate_tags([])
        assert result == []
        
        result = InputValidator.validate_tags(None)
        assert result == []
    
    def test_validate_tags_too_many(self):
        """Test tags validation with too many tags."""
        too_many_tags = [f"tag{i}" for i in range(25)]  # Over MAX_TAGS_COUNT
        
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_tags(too_many_tags)
        assert "Too many tags" in str(exc_info.value)
    
    def test_validate_tags_invalid_format(self):
        """Test tags validation with invalid format."""
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_tags(["valid_tag", "invalid@tag"])
        assert "Invalid tag format" in str(exc_info.value)
    
    def test_validate_tags_removes_duplicates(self):
        """Test that tags validation removes duplicates."""
        tags = ["tag1", "tag2", "tag1", "tag3"]
        result = InputValidator.validate_tags(tags)
        assert result == ["tag1", "tag2", "tag3"]


class TestDetectionRuleValidation:
    """Test detection rule validation."""
    
    def test_validate_detection_rule_success(self):
        """Test successful detection rule validation."""
        rule = {
            "rule_type": "threshold",
            "metric": "cost",
            "operator": ">",
            "value": 100.0,
            "time_window": "5m",
            "aggregation": "avg"
        }
        
        result = InputValidator.validate_detection_rule(rule)
        assert result["rule_type"] == "THRESHOLD"  # Now expects uppercase for API compatibility
        assert result["metric"] == "cost"
        assert result["operator"] == ">"
        assert result["value"] == 100.0
        assert result["time_window"] == "5m"
        assert result["aggregation"] == "avg"
    
    def test_validate_detection_rule_missing_required(self):
        """Test detection rule validation with missing required fields."""
        rule = {
            "rule_type": "threshold",
            "metric": "cost"
            # Missing operator and value
        }
        
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_detection_rule(rule)
        assert "Missing required field" in str(exc_info.value)
    
    def test_validate_detection_rule_invalid_type(self):
        """Test detection rule validation with invalid rule type."""
        rule = {
            "rule_type": "invalid_type",
            "metric": "cost",
            "operator": ">",
            "value": 100.0
        }
        
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_detection_rule(rule)
        assert "Invalid detection rule type" in str(exc_info.value)
    
    def test_validate_detection_rule_invalid_operator(self):
        """Test detection rule validation with invalid operator."""
        rule = {
            "rule_type": "threshold",
            "metric": "cost",
            "operator": "invalid_op",
            "value": 100.0
        }
        
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_detection_rule(rule)
        assert "Invalid operator" in str(exc_info.value)
    
    def test_validate_detection_rule_string_operator(self):
        """Test detection rule validation with string operators."""
        rule = {
            "rule_type": "pattern",
            "metric": "message",
            "operator": "contains",
            "value": "error"
        }

        result = InputValidator.validate_detection_rule(rule)
        assert result["rule_type"] == "PATTERN"  # Now expects uppercase for API compatibility
        assert result["value"] == "error"


class TestThresholdsValidation:
    """Test thresholds validation."""
    
    def test_validate_thresholds_success(self):
        """Test successful thresholds validation."""
        thresholds = {
            "cost": 100.0,
            "usage": 1000,
            "latency": 50.5
        }
        
        result = InputValidator.validate_thresholds(thresholds)
        assert result == thresholds
    
    def test_validate_thresholds_empty(self):
        """Test thresholds validation with empty dictionary."""
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_thresholds({})
        assert "At least one threshold must be defined" in str(exc_info.value)
    
    def test_validate_thresholds_invalid_type(self):
        """Test thresholds validation with invalid type."""
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_thresholds("not_a_dict")
        assert "Thresholds must be a dictionary" in str(exc_info.value)
    
    def test_validate_thresholds_invalid_value(self):
        """Test thresholds validation with invalid value."""
        thresholds = {
            "cost": "not_a_number"
        }
        
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_thresholds(thresholds)
        assert "Invalid threshold[cost] format" in str(exc_info.value)


class TestDateTimeValidation:
    """Test datetime validation."""
    
    def test_validate_datetime_string_success(self):
        """Test successful datetime validation."""
        dt_string = "2024-01-01T12:00:00Z"
        result = InputValidator.validate_datetime_string(dt_string)
        assert isinstance(result, datetime)
        assert result.tzinfo is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 1

    def test_validate_datetime_string_formats(self):
        """Test datetime validation with various formats."""
        formats = [
            "2024-01-01T12:00:00.123456Z",
            "2024-01-01T12:00:00Z",
            "2024-01-01T12:00:00.123456",
            "2024-01-01T12:00:00",
            "2024-01-01 12:00:00",
            "2024-01-01"
        ]

        for dt_string in formats:
            result = InputValidator.validate_datetime_string(dt_string)
            assert isinstance(result, datetime)
            assert result.year == 2024
    
    def test_validate_datetime_string_invalid(self):
        """Test datetime validation with invalid format."""
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_datetime_string("invalid-datetime")
        assert "Invalid datetime format" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__])
