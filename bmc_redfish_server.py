import socket  
import struct
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import datetime

from gpu_pldm_sim import PLDM_TYPE_MONITORING

#Create the FastAPI app
app = FastAPI(title="Mock BMC Redfish service")
GPU_HOST ="127.0.0.1" 
GPU_PORT = 9999

#PLDM Constraints matching DSP0248
PLDM_TYPE_MONITORING = 0x02
CMD_GET_SENSOR_READING = 0x11
CMD_SET_NUMERIC_EFFECTER_VAL = 0x39
SENSOR_ID_TEMPERATURE = 0x01
SENSOR_ID_POWER = 0x02
EFFECTER_ID_POWER_CAP = 0x01


def send_pldm_to_gpu(request_bytes: bytes) -> bytes:
    """
    Connects to the GPU over the internal socket (simulating I2C/MCTP bus),
    sends the raw binary PLDM request, and returns the binary response.
    """

    try:
        #create a TCP client socket
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(2.0) #2 second timeout in case GPU is not responding
        client.connect((GPU_HOST, GPU_PORT))
        client.sendall(request_bytes)
        responce_bytes = client.recv(1024)  # Receive up to 1024 bytes
        return responce_bytes
    except ConnectionRefusedError:
        # In hardware, this would mean the GPU is powered off or bus is disconnected
        raise HTTPException(status_code=503, detail="GPU Management Controller unreachable")



LOG_FILE = "/tmp/gpu_valsim.log" 
def log_event(message: str):
    """Writes a timestamped hardware event to the system log file."""
    timestamp = datetime.datetime.now().isoformat()
    log_line  = f"[{timestamp}] [BMC_EVENT] {message}\n"
    with open(LOG_FILE, "a") as f:
        f.write(log_line)
    print(log_line.strip())  # Also print to console for visibility



#pydantic schemas for redfish Power payload validaion
class PowerLimit(BaseModel):
    LimitInWatts: int
class PowerPatchPayload(BaseModel):
    PowerLimit: PowerLimit

@app.patch("/redfish/v1/Chassis/GPU_0/Power")
def set_gpu_power_cap(payload: PowerPatchPayload):
    """
    Redfish PATCH endpoint to set GPU power limit.
    Translates JSON payload to a PLDM SetNumericEffecterValue binary command.
    """
    requested_watts = payload.PowerLimit.LimitInWatts
    # DEFENSIVE VALIDATION CHECK: Reject negative numbers immediately!
    if requested_watts < 100 or requested_watts > 500:
        log_event(f"POWER_CAP_REJECTED: Requested {requested_watts}W is out of safe range (100W-500W)")
        raise HTTPException(status_code=400, detail=f"Invalid power cap value ({requested_watts}W). Safe operating range is 100-500W.")
    log_event(f"POWER_CAP_REQ: Received request to cap GPU_0 power at {requested_watts}W")

    # Build 5-byte PLDM Effecter packet:
    # '>BBBBH' = Header(0x02), Type(0x02), Cmd(0x39), EffecterID(0x01), Watts(uint16)
    pldm_req = struct.pack(">BBBBH", 0x02, PLDM_TYPE_MONITORING, CMD_SET_NUMERIC_EFFECTER_VAL, EFFECTER_ID_POWER_CAP, requested_watts)

    #Send over socket to GPU
    pldm_resp = send_pldm_to_gpu(pldm_req)

    #GPU returns 4-byte response: 'BBBB' = Header, Type, Cmd, CompletionCode
    hdr,ptype,cmd,cc = struct.unpack("BBBB", pldm_resp)

    #Check GPU completion code
    if cc != 0x00:
        log_event(f"POWER_CAP_REJECTED: GPU rejected {requested_watts}W with PLDM error code {cc}")

        raise HTTPException(status_code=400, detail=f"Invalid power cap value ({requested_watts}W). Safe operating range is 100-500W.")
    log_event(f"POWER_CAP_SUCCESS: GPU_0 power cap successfully updated to {requested_watts}W")
    return {"message": f"Successfully updated GPU_0 power limit to  {requested_watts}W", "PowerLimitWatts": requested_watts, "Status": "Applied"}

@app.get("/redfish/v1/Chassis/GPU_0/Thermal")
def get_gpu_thermal():
    """
    Redfish endpoint for GPU thermals.
    1. Sends binary PLDM command to GPU.
    2. Decodes 16-bit temperature reading.
    3. Returns standard DMTF Redfish JSON.
    """
    # Build 4-byte PLDM Request:
    # Header: 0x01 (Instance 1, Request)
    # Type: 0x02 (Monitoring)
    # Cmd: 0x11 (GetSensorReading)
    # Sensor ID: 0x01 (Temperature)   

    pldm_req = struct.pack(">BBBB", 0x01, PLDM_TYPE_MONITORING, CMD_GET_SENSOR_READING, SENSOR_ID_TEMPERATURE)

    #Send over socket to GPU
    pldm_resp = send_pldm_to_gpu(pldm_req)

    #Unpack responce: '>BBBBH'
    hdr,ptype,cmd,cc,temp_c = struct.unpack(">BBBBH", pldm_resp)

    #Check for PLDM protocol error
    if cc != 0x00:
        log_event(f"PLDM_ERROR: Sensor read failed with completion code {cc}")
        raise HTTPException(status_code=500, detail=f"PLDM Sensor read error")

    #Health logic: If temp exceeds 100C, mark as critical
    health_status = "Critical" if temp_c > 100 else "OK"

    if health_status == "Critical":
        log_event(f"THERMAL_ALERT: High tempreture detected of GPU_0: {temp_c}C (Threshold: 100C)")

    #Standard DMTF Redfish JSON schema
    return{
        "@odata.id": "/redfish/v1/Chassis/GPU_0/Thermal",
        "@odata.type": "#Thermal.v1_7_1.Thermal",
        "Id": "Thermal",
        "Name": "GPU 0 Thermal Subsystem",
        "Temperatures": [
            {
                "@odata.id": "/redfish/v1/Chassis/GPU_0/Thermal#/Temperatures/0",
                "MemberId": "0",
                "Name": "GPU Core Temperature",
                "ReadingCelsius": temp_c,
                "UpperThresholdCritical": 100,
                "Status": {
                    "State": "Enabled",
                    "Health": health_status
                }
            }
        ]
    }

import os 
@app.get("/redfish/v1/Systems/1/LogServices/EventLog/Entries")
def get_event_log_entries():
    """
    Returns the BMC System Event Log (SEL).
    Reads the raw events from /tmp/gpu_valsim.log and formats them into Redfish JSON.
    """
    if not os.path.exists(LOG_FILE):
        return {"Members": [], "Members@odata.count": 0}
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()
    entries = []
    for idx, line in enumerate(lines[-20:]):
        # Return the last 20 events
        entries.append({
            "@odata.id": f"/redfish/v1/Systems/1/LogServices/EventLog/Entries/{idx}",
            "Id": str(idx),
            "Message": line.strip(),
        })

    return {
        "@odata.id": "/redfish/v1/Systems/1/LogServices/EventLog/Entries",
        "@odata.type": "#LogEntryCollection.LogEntryCollection",
        "Name": "System Event Log Entries",
        "Members@odata.count": len(entries),
        "Members": entries
    }