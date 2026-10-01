#!/bin/bash
# Install nginx and a one-page Python app that reads PostgreSQL on the private VM.
# __DB_PASSWORD__ is replaced in memory by deploy.py. The committed file has no password.
set -euo pipefail

DB_PASSWORD='__DB_PASSWORD__'
export DEBIAN_FRONTEND=noninteractive

apt-get update -y
apt-get install -y nginx python3-psycopg2

install -d -o www-data -g www-data -m 755 /opt/twotier
install -d -o www-data -g www-data -m 755 /etc/twotier

umask 077
cat > /etc/twotier/db.env <<EOF
DB_PASSWORD=${DB_PASSWORD}
EOF
chown www-data:www-data /etc/twotier/db.env
chmod 600 /etc/twotier/db.env

cat > /opt/twotier/app.py <<'PY'
#!/usr/bin/env python3
import html
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg2

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            conn = psycopg2.connect(
                host="10.0.2.4",
                port=5432,
                dbname="appdb",
                user="webapp",
                password=os.environ["DB_PASSWORD"],
                connect_timeout=5,
            )
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT version()")
                    version = cur.fetchone()[0]
            finally:
                conn.close()
        except Exception:
            body = "<h1>Secure Two-Tier Web Application</h1><p>database-unreachable</p>"
            status = 503
        else:
            body = (
                "<h1>Secure Two-Tier Web Application</h1>"
                "<p>database-connected</p>"
                f"<p>{html.escape(version)}</p>"
            )
            status = 200
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        return

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8080), Handler).serve_forever()
PY
chown www-data:www-data /opt/twotier/app.py
chmod 644 /opt/twotier/app.py

cat > /etc/systemd/system/twotier-web.service <<'EOF'
[Unit]
Description=Two-tier web page
After=network.target

[Service]
User=www-data
Group=www-data
EnvironmentFile=/etc/twotier/db.env
ExecStart=/usr/bin/python3 /opt/twotier/app.py
Restart=on-failure
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/nginx/sites-available/twotier <<'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8080;
    }
}
EOF
rm -f /etc/nginx/sites-enabled/default
ln -sfn /etc/nginx/sites-available/twotier /etc/nginx/sites-enabled/twotier

systemctl daemon-reload
systemctl enable --now twotier-web
nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo WEB_READY
