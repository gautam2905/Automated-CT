#!/usr/bin/env bash
# Starts the CT scan-room simulator and prints its address.  Usage: run_sim.sh [--port N]
set -euo pipefail
SIM_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${SIM_PYTHON:-}" ]]; then
  : # An explicit interpreter takes precedence.
elif [[ -x /mnt/miniconda3/envs/ctm/bin/python ]]; then
  SIM_PYTHON=/mnt/miniconda3/envs/ctm/bin/python
else
  SIM_PYTHON=python3
fi
if [[ ! -f "$SIM_ROOT/client/dist/index.html" ]]; then
  echo "The client is not built: build the client first: cd client && npm run build" >&2
  exit 1
fi
PORT=8770
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  if [[ "${args[i]}" == "--port" && $((i + 1)) -lt ${#args[@]} ]]; then PORT="${args[i + 1]}"; fi
  if [[ "${args[i]}" == --port=* ]]; then PORT="${args[i]#--port=}"; fi
done
echo "Scan-room simulator: open http://127.0.0.1:${PORT}/ in a browser (Ctrl+C to stop)"
export PYTHONPATH="$SIM_ROOT/py${PYTHONPATH:+:$PYTHONPATH}"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
exec "$SIM_PYTHON" -m scansim_server --data "$SIM_ROOT/data" --client "$SIM_ROOT/client/dist" "$@"
