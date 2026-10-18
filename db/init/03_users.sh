#!/bin/bash
# Creates least-privilege database users from environment variables (no secrets in git).
# Sourced by the official mysql entrypoint, so docker_process_sql is available.
#
#   atlas_app    - Python API: reads catalogue/metrics/purchases, writes logs and tickets.
#                  Can read clients.id and clients.company only (never contact_email).
#   atlas_ro     - SQL tool: SELECT on the reports catalogue ONLY. No metrics, no clients.
#   atlas_portal - CodeIgniter portal: conversations, feedback, fallback tickets.

docker_process_sql --database=mysql <<-EOSQL
  CREATE USER IF NOT EXISTS '${MYSQL_APP_USER}'@'%' IDENTIFIED BY '${MYSQL_APP_PASSWORD}';
  GRANT SELECT ON atlas.reports TO '${MYSQL_APP_USER}'@'%';
  GRANT SELECT ON atlas.market_metrics TO '${MYSQL_APP_USER}'@'%';
  GRANT SELECT ON atlas.client_purchases TO '${MYSQL_APP_USER}'@'%';
  GRANT SELECT (id, company) ON atlas.clients TO '${MYSQL_APP_USER}'@'%';
  GRANT SELECT, INSERT ON atlas.escalations TO '${MYSQL_APP_USER}'@'%';
  GRANT SELECT, INSERT ON atlas.request_log TO '${MYSQL_APP_USER}'@'%';
  GRANT SELECT, INSERT ON atlas.security_events TO '${MYSQL_APP_USER}'@'%';

  CREATE USER IF NOT EXISTS '${MYSQL_RO_USER}'@'%' IDENTIFIED BY '${MYSQL_RO_PASSWORD}'
    WITH MAX_QUERIES_PER_HOUR 2000;
  GRANT SELECT ON atlas.reports TO '${MYSQL_RO_USER}'@'%';

  CREATE USER IF NOT EXISTS '${MYSQL_PORTAL_USER}'@'%' IDENTIFIED BY '${MYSQL_PORTAL_PASSWORD}';
  GRANT SELECT (id, company) ON atlas.clients TO '${MYSQL_PORTAL_USER}'@'%';
  GRANT SELECT, INSERT ON atlas.conversations TO '${MYSQL_PORTAL_USER}'@'%';
  GRANT SELECT, INSERT, UPDATE ON atlas.feedback TO '${MYSQL_PORTAL_USER}'@'%';
  GRANT INSERT ON atlas.escalations TO '${MYSQL_PORTAL_USER}'@'%';

  FLUSH PRIVILEGES;
EOSQL
