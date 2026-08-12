#!/bin/sh
set -eu

token_file="${ANDROID_MCP_TOKEN_FILE:-/run/secrets/android_mcp_token}"
adb_keys_dir="${ADB_VENDOR_KEYS:-/var/lib/skidc/android-adb}"
adb_private_key="${adb_keys_dir%/}/adbkey"
emulator_serial="${ANDROID_EMULATOR_SERIAL:-android-emulator:5555}"
boot_timeout="${ANDROID_BOOT_TIMEOUT_SECONDS:-180}"
bridge_port="${ANDROID_MCP_PORT:-8765}"

if [ ! -f "$token_file" ] || [ ! -r "$token_file" ] || [ ! -s "$token_file" ]; then
    echo "Android Bridge token file is missing or unreadable" >&2
    exit 1
fi

if [ ! -f "$adb_private_key" ] || [ ! -r "$adb_private_key" ] || [ ! -s "$adb_private_key" ]; then
    echo "ADB private key is missing or unreadable" >&2
    exit 1
fi

case "$boot_timeout" in
    ''|*[!0-9]*)
        echo "ANDROID_BOOT_TIMEOUT_SECONDS must be a positive integer" >&2
        exit 1
        ;;
esac
if [ "$boot_timeout" -le 0 ]; then
    echo "ANDROID_BOOT_TIMEOUT_SECONDS must be a positive integer" >&2
    exit 1
fi

mkdir -p "${HOME:-/tmp/skidc-home}" "${UV_CACHE_DIR:-/tmp/uv-cache}"

deadline=$(( $(date +%s) + boot_timeout ))
while :; do
    adb connect "$emulator_serial" >/dev/null 2>&1 || true
    boot_completed="$(adb -s "$emulator_serial" shell getprop sys.boot_completed 2>/dev/null || true)"
    if [ "$(printf '%s' "$boot_completed" | tr -d '\r\n ')" = "1" ]; then
        break
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "Android emulator did not finish booting within ${boot_timeout}s" >&2
        exit 1
    fi
    sleep 2
done

exec uv run --no-sync skidc android-mcp \
    --host 0.0.0.0 \
    --port "$bridge_port" \
    --device-id "$emulator_serial" \
    --artifact-root /artifacts \
    --token-file "$token_file"
