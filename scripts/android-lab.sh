#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$script_dir/.." && pwd)

runtime_root=${ANDROID_LAB_RUNTIME_ROOT:-"$project_root"}
compose_project_name=${ANDROID_LAB_COMPOSE_PROJECT_NAME:-"$(basename "$runtime_root")"}
compose_file="$project_root/docker-compose.yaml"
android_compose_file="$project_root/docker-compose.android.yaml"
data_dir=${ANDROID_LAB_DATA_DIR:-"$runtime_root/datas/android-lab"}
artifact_dir=${ANDROID_LAB_ARTIFACT_DIR:-"$runtime_root/datas/android-artifacts"}
adb_dir="$data_dir/adb"
secrets_dir="$data_dir/secrets"
adb_private_key="$adb_dir/adbkey"
adb_public_key="$adb_dir/adbkey.pub"
token_file="$secrets_dir/android_mcp_token"

kvm_path=${ANDROID_LAB_KVM_PATH:-/dev/kvm}
meminfo_file=${ANDROID_LAB_MEMINFO_FILE:-/proc/meminfo}
minimum_memory_kib=${ANDROID_LAB_MIN_MEMORY_KIB:-14680064}
minimum_disk_kib=${ANDROID_LAB_MIN_DISK_KIB:-31457280}
bridge_port=${ANDROID_LAB_BRIDGE_PORT:-8765}
smoke_timeout=${ANDROID_LAB_SMOKE_TIMEOUT_SECONDS:-15}
server_url=${ANDROID_LAB_SERVER_URL:-http://127.0.0.1:8000}
bridge_url=${ANDROID_LAB_BRIDGE_URL:-http://127.0.0.1:8765}

failures=0

pass() {
    printf 'PASS %s\n' "$1"
}

fail() {
    printf 'FAIL %s: %s\n' "$1" "$2"
    failures=$((failures + 1))
}

is_non_negative_integer() {
    case ${1:-} in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

usage() {
    printf '%s\n' \
        'Usage: android-lab.sh doctor|init|build|up|down|status|smoke' >&2
}

validate_runtime_root() {
    case $runtime_root in
        /*) ;;
        *)
            printf '%s\n' 'Android Lab runtime root must be an absolute path.' >&2
            return 1
            ;;
    esac
    if [ ! -d "$runtime_root" ]; then
        printf '%s\n' "Android Lab runtime root does not exist: $runtime_root" >&2
        return 1
    fi
    if [ ! -r "$runtime_root/dispatch.yaml" ]; then
        printf '%s\n' \
            "dispatch.yaml is missing or unreadable in Android Lab runtime root: $runtime_root" >&2
        return 1
    fi
}

run_compose() {
    docker compose \
        --project-directory "$runtime_root" \
        --project-name "$compose_project_name" \
        -f "$compose_file" \
        -f "$android_compose_file" \
        "$@"
}

validate_compose_ownership() {
    for container_name in skidc-server skidc-dispatcher; do
        if container_project=$(docker inspect \
            --format '{{ index .Config.Labels "com.docker.compose.project" }}' \
            "$container_name" 2>/dev/null); then
            if [ "$container_project" != "$compose_project_name" ]; then
                if [ -z "$container_project" ]; then
                    container_project=unmanaged
                fi
                printf '%s\n' \
                    "Container $container_name belongs to Compose project $container_project; requested project is $compose_project_name. Set ANDROID_LAB_RUNTIME_ROOT and ANDROID_LAB_COMPOSE_PROJECT_NAME to the owning project instead." >&2
                return 1
            fi
        fi
    done
}

resolve_git_dir() {
    git_marker="$project_root/.git"
    if [ -d "$git_marker" ]; then
        printf '%s\n' "$git_marker"
        return
    fi
    if [ ! -f "$git_marker" ]; then
        printf '%s\n' 'Cannot locate the project Git directory.' >&2
        return 1
    fi

    git_location=$(sed -n 's/^gitdir: //p' "$git_marker")
    case $git_location in
        [A-Za-z]:/*)
            git_drive=$(printf '%s' "${git_location%%:*}" | tr '[:upper:]' '[:lower:]')
            printf '/mnt/%s%s\n' "$git_drive" "${git_location#?:}"
            ;;
        /*)
            printf '%s\n' "$git_location"
            ;;
        *)
            (CDPATH= cd -- "$project_root/$git_location" && pwd)
            ;;
    esac
}

build_images() {
    if ! command -v git >/dev/null 2>&1; then
        printf '%s\n' 'git is required to prepare the clean build context.' >&2
        return 1
    fi
    if ! command -v docker >/dev/null 2>&1; then
        printf '%s\n' 'Docker is required to build the Android Lab images.' >&2
        return 1
    fi

    git_dir=$(resolve_git_dir)
    build_tmp=$(mktemp -d "${TMPDIR:-/tmp}/skidc-android-build.XXXXXX")
    case $build_tmp in
        "${TMPDIR:-/tmp}"/skidc-android-build.*) ;;
        *)
            printf '%s\n' 'Refusing to use an unexpected temporary build path.' >&2
            return 1
            ;;
    esac
    cleanup_build() {
        rm -rf -- "$build_tmp"
    }
    trap cleanup_build 0
    trap 'cleanup_build; exit 1' 1 2 15

    build_context="$build_tmp/context"
    source_archive="$build_tmp/source.tar"
    mkdir -p "$build_context"
    git --git-dir="$git_dir" archive --format=tar --output="$source_archive" HEAD
    tar -xf "$source_archive" -C "$build_context"

    docker build --pull=false -t skidc-app:latest \
        -f "$build_context/Dockerfile" "$build_context"
    docker build --pull=false -t skidc-worker:latest \
        -f "$build_context/container/Dockerfile" "$build_context/container"
    docker build --pull=false -t skidc-android-bridge:latest \
        -f "$build_context/container/android-bridge/Dockerfile" "$build_context"
}

initialize_lab() {
    validate_runtime_root

    pair_ready=false
    if [ -e "$adb_private_key" ] || [ -e "$adb_public_key" ]; then
        if [ -s "$adb_private_key" ] && [ -s "$adb_public_key" ]; then
            pair_ready=true
        else
            printf '%s\n' 'ADB keypair is incomplete; refusing to overwrite it.' >&2
            return 1
        fi
    fi
    if [ -e "$token_file" ] && [ ! -s "$token_file" ]; then
        printf '%s\n' 'Android MCP token is incomplete; refusing to overwrite it.' >&2
        return 1
    fi

    if [ "$pair_ready" != true ] \
        && ! docker image inspect skidc-android-bridge:latest >/dev/null 2>&1; then
        printf '%s\n' \
            'Android Bridge image is unavailable; run ./scripts/android-lab.sh build first.' >&2
        return 1
    fi

    umask 077
    mkdir -p "$data_dir" "$adb_dir" "$secrets_dir" "$artifact_dir"
    chmod 700 "$data_dir" "$adb_dir" "$secrets_dir" "$artifact_dir"

    token_tmp=
    key_stage=
    cleanup_init() {
        if [ -n "$token_tmp" ]; then
            rm -f -- "$token_tmp"
        fi
        if [ -n "$key_stage" ]; then
            case $key_stage in
                "$adb_dir"/.keygen.*) rm -rf -- "$key_stage" ;;
            esac
        fi
    }
    trap cleanup_init 0
    trap 'cleanup_init; exit 1' 1 2 15

    if [ ! -s "$token_file" ]; then
        token_tmp=$(mktemp "$secrets_dir/.android_mcp_token.XXXXXX")
        openssl rand -hex 32 > "$token_tmp"
        if [ ! -s "$token_tmp" ]; then
            printf '%s\n' 'Failed to generate the Android MCP token.' >&2
            return 1
        fi
        chmod 600 "$token_tmp"
    fi

    if [ "$pair_ready" != true ]; then
        key_stage=$(mktemp -d "$adb_dir/.keygen.XXXXXX")
        docker run --rm \
            --user "$(id -u):$(id -g)" \
            --entrypoint adb \
            -v "$key_stage:/keys" \
            skidc-android-bridge:latest \
            keygen /keys/adbkey
        if [ ! -s "$key_stage/adbkey" ] || [ ! -s "$key_stage/adbkey.pub" ]; then
            printf '%s\n' 'Failed to generate a complete ADB keypair.' >&2
            return 1
        fi
        chmod 600 "$key_stage/adbkey" "$key_stage/adbkey.pub"
    fi

    if [ -n "$key_stage" ]; then
        mv "$key_stage/adbkey" "$key_stage/adbkey.pub" "$adb_dir/"
        rmdir "$key_stage"
        key_stage=
    fi
    if [ -n "$token_tmp" ]; then
        mv "$token_tmp" "$token_file"
        token_tmp=
    fi

    chmod 600 "$token_file" "$adb_private_key" "$adb_public_key"
    printf '%s\n' 'Android Lab credentials and artifact directory are ready.'
}

start_lab() {
    doctor
    validate_runtime_root
    validate_compose_ownership

    if [ ! -s "$token_file" ]; then
        printf '%s\n' \
            'Android MCP token is missing or empty; run ./scripts/android-lab.sh init first.' >&2
        return 1
    fi
    if [ ! -s "$adb_private_key" ]; then
        printf '%s\n' \
            'ADB private key is missing or empty; run ./scripts/android-lab.sh init first.' >&2
        return 1
    fi
    if ! docker image inspect skidc-android-bridge:latest >/dev/null 2>&1; then
        printf '%s\n' \
            'Android Bridge image is unavailable; run ./scripts/android-lab.sh build first.' >&2
        return 1
    fi

    ANDROID_ADBKEY=$(cat "$adb_private_key")
    export ANDROID_ADBKEY
    run_compose --profile android up -d \
        skidc-server skidc-dispatcher android-emulator android-bridge
    unset ANDROID_ADBKEY
}

stop_lab() {
    validate_runtime_root
    run_compose --profile android down
}

show_status() {
    validate_runtime_root
    run_compose --profile android ps \
        skidc-server skidc-dispatcher android-emulator android-bridge
}

smoke_public_check() {
    check_name=$1
    request_method=$2
    request_url=$3
    if curl \
        --disable \
        --fail \
        --silent \
        --show-error \
        --max-time "$smoke_timeout" \
        --output /dev/null \
        --request "$request_method" \
        "$request_url" >/dev/null 2>&1; then
        pass "$check_name"
    else
        fail "$check_name" 'request failed'
    fi
}

smoke_authenticated_check() {
    check_name=$1
    request_method=$2
    request_url=$3
    if printf 'header = "Authorization: Bearer %s"\n' "$smoke_token" \
        | curl \
            --disable \
            --config - \
            --fail \
            --silent \
            --show-error \
            --max-time "$smoke_timeout" \
            --output /dev/null \
            --request "$request_method" \
            "$request_url" >/dev/null 2>&1; then
        pass "$check_name"
    else
        fail "$check_name" 'request failed'
    fi
}

smoke_worker_client_check() {
    if docker run --rm \
        --network host \
        --env "ANDROID_MCP_URL=$bridge_url" \
        --env "ANDROID_MCP_TOKEN_FILE=/run/secrets/android_mcp_token" \
        --env "ANDROID_MCP_TIMEOUT=$smoke_timeout" \
        --volume "$token_file:/run/secrets/android_mcp_token:ro" \
        skidc-worker:latest \
        android-mcp GET /health/ready >/dev/null 2>&1; then
        pass 'Android worker client'
    else
        fail 'Android worker client' 'authenticated worker request failed'
    fi
}

smoke_lab() {
    validate_runtime_root
    if ! command -v curl >/dev/null 2>&1; then
        printf '%s\n' 'curl is required for Android Lab smoke checks.' >&2
        return 1
    fi
    if ! is_non_negative_integer "$smoke_timeout" || [ "$smoke_timeout" -eq 0 ]; then
        printf '%s\n' 'Android Lab smoke timeout must be a positive integer.' >&2
        return 1
    fi
    if [ ! -s "$token_file" ]; then
        printf '%s\n' \
            'Android MCP token is missing or empty; run ./scripts/android-lab.sh init first.' >&2
        return 1
    fi

    smoke_token=$(cat "$token_file")
    if [ -z "$smoke_token" ]; then
        printf '%s\n' 'Android MCP token is empty.' >&2
        return 1
    fi

    failures=0
    server_url=${server_url%/}
    bridge_url=${bridge_url%/}
    smoke_public_check 'Web Server health' GET "$server_url/projects"
    smoke_authenticated_check 'Android Bridge readiness' GET "$bridge_url/health/ready"
    smoke_authenticated_check 'ADB device listing' GET "$bridge_url/devices"
    smoke_authenticated_check 'Android screenshot' GET "$bridge_url/observe/screenshot"
    smoke_authenticated_check 'Android UI tree' GET "$bridge_url/observe/ui"
    smoke_authenticated_check 'Android HOME key' POST "$bridge_url/input/home"
    smoke_worker_client_check
    unset smoke_token

    if [ "$failures" -ne 0 ]; then
        return 1
    fi
}

doctor() {
    failures=0

    if kernel_release=$(uname -r 2>/dev/null); then
        case $kernel_release in
            *[Mm]icrosoft*|*WSL*|*wsl*) pass 'WSL 2 environment' ;;
            *) fail 'WSL 2 environment' "unexpected kernel: $kernel_release" ;;
        esac
    else
        fail 'WSL 2 environment' 'cannot read kernel release'
    fi

    if [ -c "$kvm_path" ]; then
        pass 'KVM device'
    else
        fail 'KVM device' "$kvm_path is not a character device"
    fi

    docker_ready=false
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        docker_ready=true
        pass 'Docker daemon'
    else
        fail 'Docker daemon' 'docker info failed'
    fi

    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        pass 'Docker Compose'
    else
        fail 'Docker Compose' 'docker compose version failed'
    fi

    if ! is_non_negative_integer "$minimum_memory_kib"; then
        fail 'visible memory' 'invalid minimum memory threshold'
    elif [ ! -r "$meminfo_file" ]; then
        fail 'visible memory' "$meminfo_file is unreadable"
    else
        visible_memory_kib=$(awk '/^MemTotal:/ { print $2; exit }' "$meminfo_file")
        if is_non_negative_integer "$visible_memory_kib" \
            && [ "$visible_memory_kib" -ge "$minimum_memory_kib" ]; then
            pass 'visible memory'
        else
            fail 'visible memory' "requires at least ${minimum_memory_kib} KiB"
        fi
    fi

    if ! is_non_negative_integer "$minimum_disk_kib"; then
        fail 'Docker storage' 'invalid minimum disk threshold'
    elif [ "$docker_ready" != true ]; then
        fail 'Docker storage' 'Docker root directory is unavailable'
    else
        docker_root=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)
        if [ -z "$docker_root" ] || [ ! -e "$docker_root" ]; then
            fail 'Docker storage' 'Docker root directory is unavailable'
        else
            available_disk_kib=$(df -Pk "$docker_root" | awk 'NR == 2 { print $4 }')
            if is_non_negative_integer "$available_disk_kib" \
                && [ "$available_disk_kib" -ge "$minimum_disk_kib" ]; then
                pass 'Docker storage'
            else
                fail 'Docker storage' "requires at least ${minimum_disk_kib} KiB free"
            fi
        fi
    fi

    if ! is_non_negative_integer "$bridge_port"; then
        fail "Bridge port $bridge_port" 'invalid port'
    elif ! command -v ss >/dev/null 2>&1; then
        fail "Bridge port $bridge_port" 'ss executable not found'
    elif ss -ltn 2>/dev/null \
        | awk -v suffix=":$bridge_port" '$4 ~ (suffix "$") { found = 1 } END { exit found ? 0 : 1 }'; then
        fail "Bridge port $bridge_port" 'already in use'
    else
        pass "Bridge port $bridge_port"
    fi

    if [ "$failures" -ne 0 ]; then
        return 1
    fi
}

cd "$project_root"

case ${1:-} in
    doctor) doctor ;;
    build) build_images ;;
    init) initialize_lab ;;
    up) start_lab ;;
    down) stop_lab ;;
    status) show_status ;;
    smoke) smoke_lab ;;
    *)
        usage
        exit 2
        ;;
esac
