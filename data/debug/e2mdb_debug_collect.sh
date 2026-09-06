#!/bin/sh
# e2MDB debug collector
# Collects backend, GUI, scheduler, SQLite and log diagnostics into a ZIP in /tmp.
# The script avoids copying media files. It may copy the e2MDB SQLite database if it is below MAX_DB_COPY_MB.

set -u

PLUGIN_DIR="/usr/lib/enigma2/python/Plugins/Extensions/e2MDB"
CONFIG_DIR="/etc/enigma2/e2mdb"
TMP_DIR="/tmp/e2mdb"
CACHE_ROOT="/media/hdd/e2MDB"
DB_PATH="/media/hdd/e2MDB/results.db"
E2_SETTINGS="/etc/enigma2/settings"
E2_SCHEDULER="/etc/enigma2/scheduler.xml"

MAX_DB_COPY_MB="${MAX_DB_COPY_MB:-250}"

STAMP="$(date +%Y%m%d-%H%M%S 2>/dev/null || echo now)"
HOST="$(hostname 2>/dev/null || echo box)"
OUT_BASE="/tmp/e2mdb-debug-${HOST}-${STAMP}"
WORK_DIR="${OUT_BASE}"
ZIP_FILE="${OUT_BASE}.zip"
TAR_FILE="${OUT_BASE}.tar.gz"

mkdir -p "${WORK_DIR}" "${WORK_DIR}/commands" "${WORK_DIR}/configs" "${WORK_DIR}/logs" "${WORK_DIR}/runtime" "${WORK_DIR}/sqlite" "${WORK_DIR}/filesystem" "${WORK_DIR}/plugin"

log()
{
    echo "[e2MDB debug] $*"
}

run_cmd()
{
    name="$1"
    shift
    {
        echo "### command: $*"
        echo "### date: $(date 2>/dev/null)"
        echo
        "$@" 2>&1
        rc=$?
        echo
        echo "### exit_code: ${rc}"
    } > "${WORK_DIR}/commands/${name}.txt" 2>&1
}

run_sh()
{
    name="$1"
    shift
    {
        echo "### command: $*"
        echo "### date: $(date 2>/dev/null)"
        echo
        sh -c "$*" 2>&1
        rc=$?
        echo
        echo "### exit_code: ${rc}"
    } > "${WORK_DIR}/commands/${name}.txt" 2>&1
}

copy_file()
{
    src="$1"
    dst_dir="$2"
    if [ -f "${src}" ]; then
        mkdir -p "${dst_dir}"
        cp -p "${src}" "${dst_dir}/" 2>/dev/null || cp "${src}" "${dst_dir}/" 2>/dev/null
    fi
}

copy_dir_small_files()
{
    src="$1"
    dst="$2"
    if [ -d "${src}" ]; then
        mkdir -p "${dst}"
        find "${src}" -maxdepth 1 -type f \( -name "*.json" -o -name "*.log" -o -name "*.txt" -o -name "*.pid" -o -name "*.sock" \) -exec cp -p {} "${dst}/" \; 2>/dev/null
    fi
}

redact_file()
{
    file="$1"
    if [ -f "${file}" ]; then
        sed -i \
            -e 's/\("api_key"[[:space:]]*:[[:space:]]*"\)[^"]*/\1***REDACTED***/Ig' \
            -e 's/\("apikey"[[:space:]]*:[[:space:]]*"\)[^"]*/\1***REDACTED***/Ig' \
            -e 's/\("token"[[:space:]]*:[[:space:]]*"\)[^"]*/\1***REDACTED***/Ig' \
            -e 's/\("password"[[:space:]]*:[[:space:]]*"\)[^"]*/\1***REDACTED***/Ig' \
            -e 's/\("secret"[[:space:]]*:[[:space:]]*"\)[^"]*/\1***REDACTED***/Ig' \
            "${file}" 2>/dev/null || true
    fi
}

redact_tree()
{
    find "${WORK_DIR}" -type f \( -name "*.json" -o -name "*.txt" -o -name "*.log" -o -name "*.xml" \) | while read f; do
        redact_file "${f}"
    done
}

sqlite_query()
{
    name="$1"
    query="$2"
    if [ -f "${DB_PATH}" ] && command -v sqlite3 >/dev/null 2>&1; then
        {
            echo ".headers on"
            echo ".mode line"
            echo "${query}"
        } | sqlite3 "${DB_PATH}" > "${WORK_DIR}/sqlite/${name}.txt" 2>&1
    else
        echo "sqlite3 not available or DB missing: ${DB_PATH}" > "${WORK_DIR}/sqlite/${name}.txt"
    fi
}

sqlite_query_column()
{
    name="$1"
    query="$2"
    if [ -f "${DB_PATH}" ] && command -v sqlite3 >/dev/null 2>&1; then
        {
            echo ".headers on"
            echo ".mode column"
            echo "${query}"
        } | sqlite3 "${DB_PATH}" > "${WORK_DIR}/sqlite/${name}.txt" 2>&1
    else
        echo "sqlite3 not available or DB missing: ${DB_PATH}" > "${WORK_DIR}/sqlite/${name}.txt"
    fi
}

log "creating work dir: ${WORK_DIR}"

# System and process state
run_cmd "date" date
run_cmd "uname" uname -a
run_sh "os-release" "cat /etc/os-release /etc/issue 2>/dev/null"
run_sh "python-version" "python3 --version 2>&1"
run_sh "disk-free" "df -h"
run_sh "mounts" "mount"
run_sh "memory" "free 2>/dev/null || cat /proc/meminfo"
run_sh "processes-e2mdb-enigma" "ps w | grep -E 'enigma2|e2mdb|twisted' | grep -v grep"
run_sh "sockets" "ls -la /tmp/e2mdb /tmp/e2MDB 2>/dev/null; find /tmp/e2mdb -maxdepth 1 -type s -o -type f 2>/dev/null | xargs -r ls -la"

# Plugin file inventory, without bytecode
if [ -d "${PLUGIN_DIR}" ]; then
    run_sh "plugin-tree" "find '${PLUGIN_DIR}' -maxdepth 4 \( -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo' \) -prune -o -type f -printf '%p %s bytes\n' 2>/dev/null | sort"
    run_sh "plugin-py-files" "find '${PLUGIN_DIR}' -type f -name '*.py' | sort"
    copy_file "${PLUGIN_DIR}/setup.xml" "${WORK_DIR}/plugin"
    copy_file "${PLUGIN_DIR}/plugin.py" "${WORK_DIR}/plugin"
    copy_file "${PLUGIN_DIR}/e2mdbd.py" "${WORK_DIR}/plugin"
    copy_file "${PLUGIN_DIR}/e2mdbctl.py" "${WORK_DIR}/plugin"
    copy_file "${PLUGIN_DIR}/E2MDBBackendDatabase.py" "${WORK_DIR}/plugin"
    copy_file "${PLUGIN_DIR}/E2MDBBackendProvider.py" "${WORK_DIR}/plugin"
    copy_file "${PLUGIN_DIR}/E2MDBLiveEPG.py" "${WORK_DIR}/plugin"
    copy_file "${PLUGIN_DIR}/E2MDBServiceListPreview.py" "${WORK_DIR}/plugin"
    copy_file "${PLUGIN_DIR}/E2MDBComponentMeta.py" "${WORK_DIR}/plugin"
    copy_file "${PLUGIN_DIR}/Components/Converter/E2MDBEventInfo.py" "${WORK_DIR}/plugin"
fi

# Configs
copy_dir_small_files "${CONFIG_DIR}" "${WORK_DIR}/configs/e2mdb"
copy_file "${E2_SETTINGS}" "${WORK_DIR}/configs/enigma2"
copy_file "${E2_SCHEDULER}" "${WORK_DIR}/configs/enigma2"
copy_file "/etc/enigma2/timers.xml" "${WORK_DIR}/configs/enigma2"

# Runtime files
copy_dir_small_files "${TMP_DIR}" "${WORK_DIR}/runtime/tmp-e2mdb"
copy_dir_small_files "/tmp/e2MDB" "${WORK_DIR}/runtime/tmp-e2MDB"

# Logs
if [ -d "/home/root/logs" ]; then
    find /home/root/logs -maxdepth 1 -type f \( -name "*enigma2*.log" -o -name "*crash*.log" -o -name "*.log" \) -exec cp -p {} "${WORK_DIR}/logs/" \; 2>/dev/null
fi
if [ -d "/var/log" ]; then
    find /var/log -maxdepth 1 -type f \( -name "*enigma2*.log" -o -name "messages*" -o -name "syslog*" -o -name "*.log" \) -exec cp -p {} "${WORK_DIR}/logs/" \; 2>/dev/null
fi
if [ -d "${TMP_DIR}" ]; then
    find "${TMP_DIR}" -maxdepth 1 -type f -name "*.log" -exec cp -p {} "${WORK_DIR}/logs/" \; 2>/dev/null
fi

# Focused log extracts
run_sh "grep-e2mdb-errors" "grep -R -n -E 'e2MDB|e2mdb|recording|scanner|scan|provider|artwork|error|failed|exception|traceback|\\.ts|\\.meta|\\.eit|\\.cuts' /tmp/e2mdb /home/root/logs /var/log 2>/dev/null | tail -1000"
run_sh "grep-live-epg" "grep -R -n -E 'LIVE|EPG|SERVICELIST|BACKEND-NOTIFY|BACKEND-LIVE-BRIDGE|COMPONENTMETA|ADHOC|promoted-event|Queue|worker' /tmp/e2mdb /home/root/logs /var/log 2>/dev/null | tail -1000"

# e2mdbctl diagnostics
if [ -x "${PLUGIN_DIR}/e2mdbctl.py" ] || [ -f "${PLUGIN_DIR}/e2mdbctl.py" ]; then
    cd "${PLUGIN_DIR}" || exit 1

    run_cmd "e2mdbctl-status" python3 e2mdbctl.py status
    run_cmd "e2mdbctl-media-status" python3 e2mdbctl.py media status
    run_cmd "e2mdbctl-cache-status" python3 e2mdbctl.py cache status
    run_cmd "e2mdbctl-scan-paths" python3 e2mdbctl.py scan paths
    run_cmd "e2mdbctl-scan-paths-count" python3 e2mdbctl.py scan paths count
    run_cmd "e2mdbctl-refresh-status" python3 e2mdbctl.py refresh status
    run_cmd "e2mdbctl-jobs-current" python3 e2mdbctl.py jobs current
    run_cmd "e2mdbctl-jobs-queue" python3 e2mdbctl.py jobs queue
    run_cmd "e2mdbctl-jobs-history" python3 e2mdbctl.py jobs history
    run_cmd "e2mdbctl-scheduler-list" python3 e2mdbctl.py scheduler list
    run_cmd "e2mdbctl-scheduler-status" python3 e2mdbctl.py scheduler status
    run_cmd "e2mdbctl-scheduler-e2gui" python3 e2mdbctl.py scheduler e2gui
    run_cmd "e2mdbctl-live-worker-status" python3 e2mdbctl.py live worker status
    run_cmd "e2mdbctl-live-queue-status" python3 e2mdbctl.py live queue status
    run_cmd "e2mdbctl-live-results" python3 e2mdbctl.py live-results 100
    run_cmd "e2mdbctl-live-duplicates" python3 e2mdbctl.py live-duplicates 200
    run_cmd "e2mdbctl-live-results-james-bond" python3 e2mdbctl.py live-results 20 "James Bond"
fi

# Filesystem summaries
run_sh "cache-root-tree" "find '${CACHE_ROOT}' -maxdepth 3 -printf '%y %p %s bytes\n' 2>/dev/null | sort | head -5000"
run_sh "artwork-recordings-tree" "find '${CACHE_ROOT}/artwork/recordings' -maxdepth 3 -printf '%y %p %s bytes\n' 2>/dev/null | sort | head -5000"
run_sh "cache-root-dirs" "find '${CACHE_ROOT}' -maxdepth 2 -type d -printf '%p\n' 2>/dev/null | sort"
run_sh "tmp-e2mdb-tree" "find /tmp/e2mdb /tmp/e2MDB -maxdepth 3 -printf '%y %p %s bytes\n' 2>/dev/null | sort"

# SQLite diagnostics
if [ -f "${DB_PATH}" ]; then
    run_sh "db-files" "ls -lh '${DB_PATH}' '${DB_PATH}-wal' '${DB_PATH}-shm' 2>/dev/null"
fi

sqlite_query_column "tables" "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
sqlite_query "schema" "SELECT sql FROM sqlite_master WHERE type IN ('table','index','trigger','view') ORDER BY type, name;"
sqlite_query_column "table-counts" "
SELECT 'e2mdb_epg_events' AS table_name, COUNT(*) AS rows FROM e2mdb_epg_events
UNION ALL SELECT 'e2mdb_fetch_queue', COUNT(*) FROM e2mdb_fetch_queue
UNION ALL SELECT 'e2mdb_provider_assets', COUNT(*) FROM e2mdb_provider_assets
UNION ALL SELECT 'e2mdb_epg_event_asset_map', COUNT(*) FROM e2mdb_epg_event_asset_map
UNION ALL SELECT 'e2mdb_cleanup_state', COUNT(*) FROM e2mdb_cleanup_state;
"
sqlite_query "recent-epg-events" "
SELECT
  source_key, source_type, service_ref, title, search_title, begin_time, event_end,
  status, metadata_provider, metadata_provider_ids, metadata_media_type, metadata_title,
  metadata_cover_path, metadata_backdrop_path, metadata_image_path, json_path,
  short_desc, last_access, updated_at
FROM e2mdb_epg_events
ORDER BY updated_at DESC
LIMIT 100;
"
sqlite_query "recent-fetch-queue" "
SELECT
  source_key, service_ref, title, search_title, begin_time, event_end,
  reason, state, priority, attempts, not_before, last_error, updated_at
FROM e2mdb_fetch_queue
ORDER BY updated_at DESC
LIMIT 200;
"
sqlite_query "recent-provider-assets" "
SELECT
  asset_key, provider, provider_id, link_provider, media_type, title, original_title,
  cover_path, backdrop_path, image_path, logo_path, json_path,
  updated_at, last_seen, expires_at
FROM e2mdb_provider_assets
ORDER BY updated_at DESC
LIMIT 100;
"
sqlite_query "error-like-rows" "
SELECT
  source_key, title, search_title, status, metadata_provider, metadata_title,
  metadata_cover_path, metadata_backdrop_path, metadata_image_path, updated_at
FROM e2mdb_epg_events
WHERE status LIKE '%error%'
   OR status LIKE '%fail%'
   OR status LIKE '%missing%'
   OR status LIKE '%broken%'
   OR metadata_title = ''
ORDER BY updated_at DESC
LIMIT 200;
"
sqlite_query_column "duplicate-live-events" "
SELECT
  service_ref, title, begin_time, event_end, COUNT(*) AS count
FROM e2mdb_epg_events
GROUP BY service_ref, title, begin_time, event_end
HAVING COUNT(*) > 1
ORDER BY count DESC, begin_time DESC
LIMIT 200;
"

# Copy DB if it is not too large
if [ -f "${DB_PATH}" ]; then
    DB_SIZE_BYTES="$(wc -c < "${DB_PATH}" 2>/dev/null || echo 0)"
    MAX_BYTES=$((MAX_DB_COPY_MB * 1024 * 1024))
    if [ "${DB_SIZE_BYTES}" -le "${MAX_BYTES}" ]; then
        mkdir -p "${WORK_DIR}/database"
        cp -p "${DB_PATH}" "${WORK_DIR}/database/" 2>/dev/null || cp "${DB_PATH}" "${WORK_DIR}/database/" 2>/dev/null
        [ -f "${DB_PATH}-wal" ] && cp -p "${DB_PATH}-wal" "${WORK_DIR}/database/" 2>/dev/null
        [ -f "${DB_PATH}-shm" ] && cp -p "${DB_PATH}-shm" "${WORK_DIR}/database/" 2>/dev/null
        echo "Database copied. Size: ${DB_SIZE_BYTES} bytes" > "${WORK_DIR}/database/README.txt"
    else
        mkdir -p "${WORK_DIR}/database"
        echo "Database not copied because it is larger than ${MAX_DB_COPY_MB} MB. Size: ${DB_SIZE_BYTES} bytes" > "${WORK_DIR}/database/README.txt"
    fi
fi

# Create manifest
{
    echo "e2MDB debug bundle"
    echo "created_at=${STAMP}"
    echo "host=${HOST}"
    echo "plugin_dir=${PLUGIN_DIR}"
    echo "config_dir=${CONFIG_DIR}"
    echo "tmp_dir=${TMP_DIR}"
    echo "cache_root=${CACHE_ROOT}"
    echo "db_path=${DB_PATH}"
    echo
    echo "Files:"
    find "${WORK_DIR}" -type f | sort
} > "${WORK_DIR}/MANIFEST.txt"

# Redact copied text/config files
redact_tree

# Create ZIP with python3 zipfile, fallback to zip/tar if needed
rm -f "${ZIP_FILE}" "${TAR_FILE}"

if command -v python3 >/dev/null 2>&1; then
    python3 - "${WORK_DIR}" "${ZIP_FILE}" <<'PY'
import os
import sys
import zipfile

work_dir = sys.argv[1]
zip_file = sys.argv[2]

with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(work_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith((".pyc", ".pyo")):
                continue
            path = os.path.join(root, name)
            arc = os.path.relpath(path, os.path.dirname(work_dir))
            zf.write(path, arc)
PY
elif command -v zip >/dev/null 2>&1; then
    (cd /tmp && zip -qr "${ZIP_FILE}" "$(basename "${WORK_DIR}")" -x "*/__pycache__/*" "*.pyc" "*.pyo")
else
    tar -czf "${TAR_FILE}" -C /tmp "$(basename "${WORK_DIR}")"
fi

if [ -f "${ZIP_FILE}" ]; then
    log "done: ${ZIP_FILE}"
    ls -lh "${ZIP_FILE}"
elif [ -f "${TAR_FILE}" ]; then
    log "zip creation unavailable; created tar.gz instead: ${TAR_FILE}"
    ls -lh "${TAR_FILE}"
else
    log "ERROR: archive creation failed"
    exit 1
fi

log "work dir kept for inspection: ${WORK_DIR}"
exit 0
