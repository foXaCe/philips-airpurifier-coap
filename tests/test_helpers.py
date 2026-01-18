"""Tests for helper functions."""

from custom_components.philips_airpurifier_coap.const import PhilipsApi
from custom_components.philips_airpurifier_coap.helpers import extract_model, extract_name


class TestExtractName:
    """Tests for extract_name function."""

    def test_extract_name_legacy(self):
        """Test extracting name from legacy API key."""
        status = {PhilipsApi.NAME: "Living Room"}
        assert extract_name(status) == "Living Room"

    def test_extract_name_new(self):
        """Test extracting name from new API key."""
        status = {PhilipsApi.NEW_NAME: "Bedroom"}
        assert extract_name(status) == "Bedroom"

    def test_extract_name_new2(self):
        """Test extracting name from new2 API key."""
        status = {PhilipsApi.NEW2_NAME: "Office"}
        assert extract_name(status) == "Office"

    def test_extract_name_priority(self):
        """Test that legacy name takes priority over new names."""
        status = {
            PhilipsApi.NAME: "Legacy",
            PhilipsApi.NEW_NAME: "New",
            PhilipsApi.NEW2_NAME: "New2",
        }
        assert extract_name(status) == "Legacy"

    def test_extract_name_fallback_to_new(self):
        """Test fallback to new name when legacy is missing."""
        status = {
            PhilipsApi.NEW_NAME: "New",
            PhilipsApi.NEW2_NAME: "New2",
        }
        assert extract_name(status) == "New"

    def test_extract_name_empty_status(self):
        """Test extracting name from empty status."""
        assert extract_name({}) == ""

    def test_extract_name_none_value(self):
        """Test extracting name when value is None."""
        status = {PhilipsApi.NAME: None}
        assert extract_name(status) == ""

    def test_extract_name_empty_string(self):
        """Test extracting name when value is empty string."""
        status = {PhilipsApi.NAME: ""}
        # Empty string is falsy, should continue to next key or return ""
        assert extract_name(status) == ""


class TestExtractModel:
    """Tests for extract_model function."""

    def test_extract_model_legacy(self):
        """Test extracting model from legacy API key."""
        status = {PhilipsApi.MODEL_ID: "AC3033/10"}
        assert extract_model(status) == "AC3033/10"

    def test_extract_model_new(self):
        """Test extracting model from new API key."""
        status = {PhilipsApi.NEW_MODEL_ID: "AC1715/10"}
        assert extract_model(status) == "AC1715/10"

    def test_extract_model_new2(self):
        """Test extracting model from new2 API key."""
        status = {PhilipsApi.NEW2_MODEL_ID: "AC0950/10"}
        assert extract_model(status) == "AC0950/10"

    def test_extract_model_truncates_to_9_chars(self):
        """Test that model is truncated to 9 characters."""
        status = {PhilipsApi.MODEL_ID: "AC3033/10_EXTRA_LONG_STRING"}
        assert extract_model(status) == "AC3033/10"
        assert len(extract_model(status)) == 9

    def test_extract_model_priority(self):
        """Test that legacy model takes priority over new models."""
        status = {
            PhilipsApi.MODEL_ID: "AC1214/10",
            PhilipsApi.NEW_MODEL_ID: "AC1715/10",
            PhilipsApi.NEW2_MODEL_ID: "AC0950/10",
        }
        assert extract_model(status) == "AC1214/10"

    def test_extract_model_fallback_to_new(self):
        """Test fallback to new model when legacy is missing."""
        status = {
            PhilipsApi.NEW_MODEL_ID: "AC1715/10",
            PhilipsApi.NEW2_MODEL_ID: "AC0950/10",
        }
        assert extract_model(status) == "AC1715/10"

    def test_extract_model_empty_status(self):
        """Test extracting model from empty status."""
        assert extract_model({}) == ""

    def test_extract_model_none_value(self):
        """Test extracting model when value is None."""
        status = {PhilipsApi.MODEL_ID: None}
        assert extract_model(status) == ""

    def test_extract_model_short_string(self):
        """Test extracting model shorter than 9 characters."""
        status = {PhilipsApi.MODEL_ID: "AC3033"}
        assert extract_model(status) == "AC3033"
