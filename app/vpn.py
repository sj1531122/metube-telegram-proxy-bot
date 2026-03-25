#!/usr/bin/env python3
import os
import sys
import json
import base64
import urllib.request
import urllib.parse
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('vpn_helper')

def fetch_subscription(url):
    logger.info(f"Fetching subscription from: {url}")
    try:
        # Use a real user agent to avoid being blocked by some providers
        req = urllib.request.Request(
            url,
            data=None,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode('utf-8').strip()
    except Exception as e:
        logger.error(f"Failed to fetch subscription: {e}")
        sys.exit(1)

def decode_base64(data):
    # Add padding if necessary
    missing_padding = len(data) % 4
    if missing_padding:
        data += '=' * (4 - missing_padding)
    try:
        return base64.b64decode(data).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to decode base64 data: {e}")
        sys.exit(1)

def parse_vless(uri):
    # vless://uuid@host:port?params#name
    try:
        parsed = urllib.parse.urlparse(uri)
        if parsed.scheme != 'vless':
            return None

        uuid = parsed.username
        host = parsed.hostname
        port = parsed.port
        params = urllib.parse.parse_qs(parsed.query)

        # Extract params
        security = params.get('security', ['none'])[0]
        type_ = params.get('type', ['tcp'])[0]
        sni = params.get('sni', [''])[0] or params.get('peer', [''])[0]
        path = params.get('path', ['/'])[0]
        host_header = params.get('host', [''])[0]
        service_name = params.get('serviceName', [''])[0]
        mode = params.get('mode', [''])[0]

        # Construct outbound config
        outbound = {
            "protocol": "vless",
            "settings": {
                "vnext": [
                    {
                        "address": host,
                        "port": port,
                        "users": [
                            {
                                "id": uuid,
                                "encryption": "none"
                            }
                        ]
                    }
                ]
            },
            "streamSettings": {
                "network": type_,
                "security": security,
            }
        }

        # Configure stream settings based on type
        if type_ == 'ws':
            outbound['streamSettings']['wsSettings'] = {
                "path": path
            }
            if host_header:
                 outbound['streamSettings']['wsSettings']['headers'] = {"Host": host_header}
        elif type_ == 'grpc':
             outbound['streamSettings']['grpcSettings'] = {
                "serviceName": service_name,
                "multiMode": (mode == 'multi')
            }
        elif type_ == 'http': # h2
             outbound['streamSettings']['httpSettings'] = {
                 "path": path,
                 "host": [host_header] if host_header else []
             }

        # Configure security settings
        if security == 'tls':
            outbound['streamSettings']['tlsSettings'] = {
                "serverName": sni if sni else host,
                "allowInsecure": False
            }
        elif security == 'reality':
            # Handle Reality specifics if needed (pbk, sid, spiderX, etc usually in params)
            # This is a basic implementation, might need expansion for reality
            pbk = params.get('pbk', [''])[0]
            sid = params.get('sid', [''])[0]
            fp = params.get('fp', [''])[0]
            outbound['streamSettings']['realitySettings'] = {
                 "show": False,
                 "fingerprint": fp,
                 "serverName": sni if sni else host,
                 "publicKey": pbk,
                 "shortId": sid,
                 "spiderX": ""
            }

        return outbound

    except Exception as e:
        logger.error(f"Error parsing vless URI: {e}")
        return None

def parse_vmess(uri):
    # vmess://base64_json
    try:
        if not uri.startswith('vmess://'):
            return None

        b64_data = uri[8:]
        json_str = decode_base64(b64_data)
        data = json.loads(json_str)

        # Mapping from vmess share link standard to Xray config
        outbound = {
            "protocol": "vmess",
            "settings": {
                "vnext": [
                    {
                        "address": data.get('add'),
                        "port": int(data.get('port')),
                        "users": [
                            {
                                "id": data.get('id'),
                                "alterId": int(data.get('aid', 0)),
                                "security": data.get('scy', 'auto'),
                                "level": 8
                            }
                        ]
                    }
                ]
            },
            "streamSettings": {
                "network": data.get('net', 'tcp'),
                "security": data.get('tls', 'none')
            }
        }

        # Stream settings details
        net = data.get('net')
        if net == 'ws':
            outbound['streamSettings']['wsSettings'] = {
                "path": data.get('path', '/'),
                "headers": {
                    "Host": data.get('host', '')
                }
            }
        elif net == 'grpc':
            outbound['streamSettings']['grpcSettings'] = {
                "serviceName": data.get('path', '') # some clients use path for serviceName
            }

        if data.get('tls') == 'tls':
            outbound['streamSettings']['tlsSettings'] = {
                "serverName": data.get('sni') or data.get('host') or data.get('add'),
                "allowInsecure": False
            }

        return outbound
    except Exception as e:
        logger.error(f"Error parsing vmess URI: {e}")
        return None

def generate_config(node_config):
    return {
        "log": {
            "loglevel": "warning"
        },
        "inbounds": [
            {
                "port": 10808,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {
                    "auth": "noauth",
                    "udp": True
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls"]
                }
            },
            {
                "port": 10809,
                "listen": "127.0.0.1",
                "protocol": "http"
            }
        ],
        "outbounds": [
            node_config,
            {
                "protocol": "freedom",
                "tag": "direct",
                "settings": {}
            }
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                {
                    "type": "field",
                    "ip": ["geoip:private"],
                    "outboundTag": "direct"
                }
            ]
        }
    }

def main():
    url = os.environ.get('VPN_SUBSCRIPTION_URL')
    if not url:
        logger.info("No VPN_SUBSCRIPTION_URL provided.")
        sys.exit(0)

    raw_data = fetch_subscription(url)
    try:
        decoded_data = decode_base64(raw_data)
    except:
        # Maybe it's not base64, just plain list of links?
        decoded_data = raw_data

    lines = decoded_data.splitlines()

    first_node_config = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith('vless://'):
            first_node_config = parse_vless(line)
        elif line.startswith('vmess://'):
            first_node_config = parse_vmess(line)

        if first_node_config:
            logger.info(f"Found valid node: {first_node_config['protocol']}")
            break

    if not first_node_config:
        logger.error("No valid VMess or VLESS node found in subscription.")
        sys.exit(1)

    xray_config = generate_config(first_node_config)

    config_path = '/etc/xray/config.json'
    os.makedirs(os.path.dirname(config_path), exist_ok=True)

    with open(config_path, 'w') as f:
        json.dump(xray_config, f, indent=2)

    logger.info(f"Xray configuration generated at {config_path}")

if __name__ == "__main__":
    main()
