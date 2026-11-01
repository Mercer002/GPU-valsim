
import struct 
import os
import sys
import socket 

# =====================================================================
# PLDM Specification Constants (DMTF DSP0240 & DSP0248)
# =====================================================================

# 1. PLDM Type: What category of command is this?
# 0x02 means "Platform Monitoring & Control" (thermals, power, sensors)

PLDM_TYPE_MONITORING = 0x02

# 2. Command Codes: What action do we want to perform?
# 0x11 = Read a sensor (like temperature)
# 0x39 = Set a control value (like power limit)

CMD_GET_SENSOR_READING = 0x11
CMD_SET_NUMERIC_EFFECTER_VAL = 0x39

# 3. Completion Codes: Did the GPU succeed or fail?
# 0x00 is always SUCCESS in PLDM

PLDM_SUCCESS = 0x00
PLDM_ERROR_INVALID_DATA = 0x02

# 4. Sensor & Effecter IDs: WHICH sensor or control?
SENSOR_ID_TEMPERATURE = 0x01
SENSOR_ID_POWER = 0x02
EFFECTER_ID_POWER_CAP = 0x01

class VirtualGPU:
    def __init__(self):
         # Simulated hardware telemetry registers
         self.state = { 
              "temp_c": 65,  # Current temperature in Celsius
              "power_w": 280,  # Current power consumption in Watts
              "power_cap_w": 400,  # Current power cap in Watts
              "pcie_link_speed": "Gen5",  # Current PCIe link speed in GT/s
              "fw_version": "1.4.2",  # Current firmware version
         }

    def process_pldm_request(self, raw_bytes: bytes) -> bytes:
        """
        Receives raw binary PLDM bytes, decodes the header,
        and returns a raw binary PLDM response.
        """
        # Safety check: header must be at least 3 bytes!
        if len(raw_bytes) < 3:
          # Return error packet: 0x80 (Resp), 0x00, 0x00, Error
          return struct.pack("BBBB", 0x80, 0x00, 0x00, 0x01)

        # Unpack first 3 bytes: 'BBB' means 3 unsigned 1-byte integers
        hdr_byte0, pldm_type, cmd = struct.unpack("BBB", raw_bytes[:3])
        payload = raw_bytes[3:] # Any bytes after the 3-byte header

        # Extract bits from Byte 0
        instance_id = hdr_byte0 & 0x1F  # Lower 6 bits are instance ID
        # Bits 4:0 = Instance ID (0-31)
        resp_hdr_byte0 = 0x80 | instance_id # Bit 7 = 1 (marks it as a Response)

        # -------------------------------------------------------------
        # Command 0x11: GetSensorReading (Temperature or Power)
        # -------------------------------------------------------------

        if cmd == CMD_GET_SENSOR_READING:
            sensor_id = payload[0] # First byte of payload is WHICH sensor

            if sensor_id == SENSOR_ID_TEMPERATURE:
                if os.getenv("INJECT_THERMAL_SPIKE") == "1":
                    # Simulate a thermal spike for testing
                    current_temp = 105

                else:

                    current_temp = int(self.state["temp_c"])
                # Pack response:
                # Byte 0: Response Header
                # Byte 1: PLDM Type (0x02)
                # Byte 2: Command (0x11)
                # Byte 3: Completion Code (0x00 = SUCCESS)
                # Bytes 4-5: 16-bit int ('H') for temperature reading

                return struct.pack(">BBBBH", resp_hdr_byte0, pldm_type, cmd, PLDM_SUCCESS, current_temp)
            elif sensor_id == SENSOR_ID_POWER:
                current_power = int(self.state["power_w"])
                return struct.pack(">BBBBH", resp_hdr_byte0, pldm_type, cmd, PLDM_SUCCESS, current_power)
            # If we don't recognize the command, return an error
            return struct.pack("BBBB", resp_hdr_byte0, pldm_type, cmd, PLDM_ERROR_INVALID_DATA)

        # -------------------------------------------------------------
        # Command 0x39: SetNumericEffecterValue (e.g. Power Cap)
        # -------------------------------------------------------------

        elif cmd == CMD_SET_NUMERIC_EFFECTER_VAL:

            # Unpack the payload: 1 byte for effecter ID, 2 bytes for requested value
            effecter_id, requested_val = struct.unpack(">BH", payload[:3]) # 1 byte + 2 bytes

            if effecter_id == EFFECTER_ID_POWER_CAP:

                # Validate the requested power cap value
                if requested_val <100 or requested_val > 500:

                    # Reject values outside the 100-500W range
                    return struct.pack("BBBB", resp_hdr_byte0, pldm_type, cmd, PLDM_ERROR_INVALID_DATA)

                #set new cap
                self.state["power_cap_w"] = float(requested_val)

                #Hardware Throttling: if current power consumption exceeds new cap, throttle it down
                if self.state["power_w"] > self.state["power_cap_w"]:
                    self.state["power_w"] = self.state["power_cap_w"]

                # Return success response
                return struct.pack("BBBB", resp_hdr_byte0, pldm_type, cmd, PLDM_SUCCESS)

            return struct.pack("BBBB", resp_hdr_byte0, pldm_type, cmd, PLDM_ERROR_INVALID_DATA)


def run_gpu_server( host="127.0.0.1", port=9999):
    """
    Listens on a TCP socket to simulate the physical bus (I2C/PCIe)
    between the BMC and the GPU.
    """
    gpu = VirtualGPU()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Allow reusing the same address to avoid "Address already in use" errors
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(5)
    print(f"[*]Virtual AMD GPU PLDM simulator listening on {host}:{port}")

    try:
        while True:
            #Wait for a connection from the BMC
            conn, addr = server.accept()
            try:
                #Receive up to 1024 raw bytes from the BMC
                raw_bytes = conn.recv(1024)

                if raw_bytes:
                    #Process the binary PLDM packet 
                    response_bytes = gpu.process_pldm_request(raw_bytes)
                    #Send binary response back to the BMC
                    conn.sendall(response_bytes)

            except Exception as e:
                print(f"[!]Error processing request from {e}")
            finally:
                conn.close()
    except KeyboardInterrupt:
        print("\n[*]Shutting down the GPU simulator.")

    finally:
        server.close()

if __name__ == "__main__":
    #If run directly: python3 gpu_pldm_sim.py
    run_gpu_server()


        