#!/bin/sh

echo "Setting umask to ${UMASK}"
umask ${UMASK}
echo "Creating download directory (${DOWNLOAD_DIR}), state directory (${STATE_DIR}), and temp dir (${TEMP_DIR})"
mkdir -p "${DOWNLOAD_DIR}" "${STATE_DIR}" "${TEMP_DIR}"

# VPN Configuration
if [ -n "$VPN_SUBSCRIPTION_URL" ]; then
    echo "VPN_SUBSCRIPTION_URL detected. Fetching and generating Xray config..."
    python3 app/vpn.py
    if [ $? -ne 0 ]; then
        echo "Error: Failed to setup VPN from subscription. Exiting to prevent IP leak."
        exit 1
    fi
fi

if [ -f "/etc/xray/config.json" ]; then
    echo "Starting Xray..."
    # Start Xray in background
    xray -config /etc/xray/config.json > /tmp/xray.log 2>&1 &

    # Export proxy variables so they are inherited by the main process
    export http_proxy="http://127.0.0.1:10809"
    export https_proxy="http://127.0.0.1:10809"
    # Also set no_proxy to avoid proxying localhost traffic (though Xray handles it, it's good practice)
    export no_proxy="localhost,127.0.0.1,::1"
    echo "VPN started. Proxy environment variables set."
fi

if [ `id -u` -eq 0 ] && [ `id -g` -eq 0 ]; then
    if [ "${UID}" -eq 0 ]; then
        echo "Warning: it is not recommended to run as root user, please check your setting of the UID environment variable"
    fi
    if [ "${CHOWN_DIRS:-true}" != "false" ]; then
        echo "Changing ownership of download and state directories to ${UID}:${GID}"
        chown -R "${UID}":"${GID}" /app "${DOWNLOAD_DIR}" "${STATE_DIR}" "${TEMP_DIR}"
    fi
    echo "Starting BgUtils POT Provider"
    gosu "${UID}":"${GID}" bgutil-pot server >/tmp/bgutil-pot.log 2>&1 &
    echo "Running MeTube as user ${UID}:${GID}"
    exec gosu "${UID}":"${GID}" python3 app/main.py
else
    echo "User set by docker; running MeTube as `id -u`:`id -g`"
    echo "Starting BgUtils POT Provider"
    bgutil-pot server >/tmp/bgutil-pot.log 2>&1 &
    exec python3 app/main.py
fi
