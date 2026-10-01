#!/bin/bash
# Install PostgreSQL and allow the web subnet to connect on port 5432.
# __DB_PASSWORD__ is replaced in memory by deploy.py. The committed file has no password.
set -euo pipefail

DB_PASSWORD='__DB_PASSWORD__'
export DEBIAN_FRONTEND=noninteractive

apt-get update -y
apt-get install -y postgresql

PG_VERSION="$(ls /etc/postgresql | head -1)"
CONF="/etc/postgresql/${PG_VERSION}/main/postgresql.conf"
HBA="/etc/postgresql/${PG_VERSION}/main/pg_hba.conf"

if grep -q "^#\?listen_addresses" "$CONF"; then
  sed -i "s/^#\?listen_addresses.*/listen_addresses = '10.0.2.4'/" "$CONF"
else
  echo "listen_addresses = '10.0.2.4'" >> "$CONF"
fi

if ! grep -q "10.0.1.0/24" "$HBA"; then
  echo "host all all 10.0.1.0/24 scram-sha-256" >> "$HBA"
fi

systemctl restart postgresql

sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'webapp') THEN
      CREATE ROLE webapp LOGIN PASSWORD '${DB_PASSWORD}';
   ELSE
      ALTER ROLE webapp WITH LOGIN PASSWORD '${DB_PASSWORD}';
   END IF;
END
\$\$;
SELECT format('CREATE DATABASE appdb OWNER webapp')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'appdb')\gexec
SQL

echo DB_READY
