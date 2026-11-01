"""
test_gpu_val.py - Enterprise GPU Redfish & PLDM Automated Validation Suite
Tests nominal telemetry, power capping, boundary enforcement, and event logging.
"""
import requests
import pytest
BASE_URL = "http://127.0.0.1:8000"

# ==============================================================================
# 1. NOMINAL VALIDATION
# ==============================================================================
def test_tc01_telemetry_read_nominal():
    """
    TC_01_TELEMETRY_READ:
    Polls /Thermal; verifies HTTP 200, DMTF schema compliance,
    and checks that temperature is within nominal bounds (20°C - 85°C).
    """
    url = f"{BASE_URL}/redfish/v1/Chassis/GPU_0/Thermal"
    response = requests.get(url, timeout=3.0)

    #Verify HTTP Responce code
    assert response.status_code == 200, f"Expected HTTP 200 OK, got {response.status_code}"

    #Verify Redfish Schema Standard 
    data = response.json()
    assert "@odata.type" in data, "Missing DMTF @odata.type in responce"
    assert "Thermal" in data["@odata.type"], "Unexpected schema type"

    #Verify Hardware Telemetry Bounds 
    temp_entry = data["Temperatures"][0]
    temp_val = temp_entry["ReadingCelsius"]
    health = temp_entry["Status"]["Health"]

    print(f"\n[PASS] GPU Tempreture: {temp_val}C, Health: {health}")
    assert 20 <= temp_val <= 85, f"Temperature {temp_val}C out of nominal range (20-85C)!"
    assert health == "OK", f"Unexpected Health status: {health}"

# ==============================================================================
# 2. FUNCTIONAL VALIDATION
# ============================================================================== 

def test_tc02_power_cap_enforce():
    """
    TC_02_POWER_CAP_ENFORCE:
    Sends PATCH to cap power at 250W; verifies BMC and GPU accept and apply it.
    """
    url = f"{BASE_URL}/redfish/v1/Chassis/GPU_0/Power"
    payload = {"PowerLimit": {"LimitInWatts": 250}}
    response = requests.patch(url, json=payload, timeout=3.0)

    #Verify HTTP Responce code
    assert response.status_code == 200, f"Expected HTTP 200 OK, got {response.status_code}: {response.text}"

    #Verify Redfish Schema Standard 
    data = response.json()
    assert data.get("PowerLimitWatts") == 250 or data.get("PowerLimitInWatts") == 250, f"Expected PowerLimitInWatts to be 250, got {data['PowerLimitInWatts']}"
    assert data["Status"] == "Applied", "Power cap is not 'Applied'"
    print(f"\n[PASS] Successfully applied 250W power cap to GPU_0")

# ==============================================================================
# 3. NEGATIVE / BOUNDARY VALIDATION
# ==============================================================================

@pytest.mark.parametrize("invalid_watts", [-50, 0, 9999])
def test_tc03_power_cap_boundary(invalid_watts):
    """
    TC_03_INVALID_POWER_CAP:
    Attempts to set out-of-range power caps (-50W, 0W, 9999W).
    Verifies BMC rejects with HTTP 400 Bad Request to protect hardware.
    """
    url = f"{BASE_URL}/redfish/v1/Chassis/GPU_0/Power"
    payload = {"PowerLimit": {"LimitInWatts": invalid_watts}}
    response = requests.patch(url, json=payload, timeout=3.0)

    print(f"\n[NEGATIVE TEST] Testing illegal power cap: {invalid_watts}W -> Response: {response.status_code} {response.text}")
    # Must reject with HTTP 400 Bad Request
    assert response.status_code == 400, f"Expected HTTP 400 for {invalid_watts}W, but got {response.status_code}!"


# ==============================================================================
# 4. SYSTEM EVENT LOG (SEL) AUDIT
# ==============================================================================
def test_tc04_event_log_audit():
    """
    TC_04_EVENT_LOG_AUDIT:
    Verifies that BMC records events and rejects in the System Event Log.
    """
    url =f"{BASE_URL}/redfish/v1/Systems/1/LogServices/EventLog/Entries"
    response = requests.get(url, timeout=3.0)

    assert response.status_code == 200
    data = response.json()
    assert data["Members@odata.count"] > 0, "System Event Log is empty!"
    print(f"\n[PASS] System Event Log contains {data['Members@odata.count']} verified entries")

