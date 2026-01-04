"""Mock data for tests."""

from custom_components.philips_airpurifier_coap.const import PhilipsApi

# Sample device status for AC3033 model
SAMPLE_STATUS_AC3033 = {
    PhilipsApi.DEVICE_ID: "ABCD1234567890",
    PhilipsApi.WIFI_VERSION: "AWS_Philips_AIR@1.0.0",
    PhilipsApi.MODEL_ID: "AC3033/10",
    PhilipsApi.NAME: "Living Room",
    PhilipsApi.POWER: "1",
    PhilipsApi.MODE: "AG",
    PhilipsApi.SPEED: "1",
    "pm25": 15,
    "iaql": 1,
    "rh": 45,
    "temp": 22,
}

# Sample device status for new gen model (AC1715)
SAMPLE_STATUS_AC1715 = {
    PhilipsApi.DEVICE_ID: "NEWDEVICE123456",
    PhilipsApi.WIFI_VERSION: "AWS_Philips_AIR@2.0.0",
    PhilipsApi.NEW_MODEL_ID: "AC1715/10",
    PhilipsApi.NEW_NAME: "Bedroom",
    PhilipsApi.NEW_POWER: "ON",
    PhilipsApi.NEW_MODE: "Auto General",
    "pm25": 8,
}

# Sample device status for new2 gen model (AC0950)
SAMPLE_STATUS_AC0950 = {
    PhilipsApi.DEVICE_ID: "NEW2DEVICE12345",
    PhilipsApi.WIFI_VERSION: "AWS_Philips_AIR_Combo@1.0.0",
    PhilipsApi.NEW2_MODEL_ID: "AC0950/10",
    PhilipsApi.NEW2_NAME: "Office",
    PhilipsApi.NEW2_POWER: 1,
    PhilipsApi.NEW2_MODE_B: 0,
    "pm25": 5,
}

# Empty status for edge cases
EMPTY_STATUS = {
    PhilipsApi.DEVICE_ID: "EMPTY123456789",
    PhilipsApi.WIFI_VERSION: "1.0.0",
}

# Status with only legacy keys
LEGACY_ONLY_STATUS = {
    PhilipsApi.DEVICE_ID: "LEGACY12345678",
    PhilipsApi.WIFI_VERSION: "1.0.0",
    PhilipsApi.MODEL_ID: "AC1214/10",
    PhilipsApi.NAME: "Old Device",
}

# Status with only new keys
NEW_ONLY_STATUS = {
    PhilipsApi.DEVICE_ID: "NEWONLY1234567",
    PhilipsApi.WIFI_VERSION: "2.0.0",
    PhilipsApi.NEW_MODEL_ID: "AC1715/10",
    PhilipsApi.NEW_NAME: "New Device",
}

# Status with only new2 keys
NEW2_ONLY_STATUS = {
    PhilipsApi.DEVICE_ID: "NEW2ONLY123456",
    PhilipsApi.WIFI_VERSION: "3.0.0",
    PhilipsApi.NEW2_MODEL_ID: "AC0950/10",
    PhilipsApi.NEW2_NAME: "Newest Device",
}
