#!/bin/bash
# run_validation.sh - Automated CI/CD Execution Harness for GPU-ValSim

echo "=========================================================="
echo " Starting GPU-ValSim Enterprise Validation Pipeline"
echo "=========================================================="

# 1. Clean up old logs and test reports
rm -f /tmp/gpu_valsim.log results.xml

# Ensure background processes get killed if the script exits or is canceled
cleanup() {
    echo ""
    echo "[*] Tearing down test environment..."
    kill $GPU_PID $BMC_PID 2>/dev/null
    echo "[*] Cleanup complete."
}
trap cleanup EXIT

# 2. Start the Virtual GPU in the background (&)
echo "[1/4] Starting Virtual AMD GPU Simulator..."
python3 gpu_pldm_sim.py > /dev/null 2>&1 &
GPU_PID=$!
echo "      -> GPU Daemon started with PID: $GPU_PID"

# 3. Start the Mock BMC Server in the background (&)
echo "[2/4] Starting Mock BMC Redfish Server..."
uvicorn bmc_redfish_server:app --port 8000 > /dev/null 2>&1 &
BMC_PID=$!
echo "      -> BMC Daemon started with PID: $BMC_PID"

# Wait 2 seconds for services to fully initialize
echo "[3/4] Waiting for services to initialize..."
sleep 2

# 4. Execute the Pytest Validation Suite with JUnit XML generation
echo "[4/4] Executing Pytest Validation Matrix..."
echo "----------------------------------------------------------"
pytest -v -s --junitxml=results.xml test_gpu_val.py
TEST_EXIT_CODE=$?
echo "----------------------------------------------------------"

if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo ">> VALIDATION STATUS: ALL TEST SUITES PASSED (RC=0) <<"
else
    echo ">> VALIDATION STATUS: FAILURES DETECTED (RC=$TEST_EXIT_CODE) <<"
fi

exit $TEST_EXIT_CODE