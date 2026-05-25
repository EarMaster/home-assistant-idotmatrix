---
allowed-tools:
  - Bash(curl:*)
  - Bash(grep:*)
  - Bash(sed:*)
  - Bash(tail:*)
---

Use curl with the environment variables $HA_HOST and $HA_TOKEN to fetch recent idotmatrix log entries from Home Assistant. Run all curl commands via Bash. Do NOT use Python. Use grep and sed for filtering. Proceed through these steps and report the result:

Note: HA 2025.11+ removed `/api/error_log`. The correct endpoint is now the Supervisor API proxy at `/api/hassio/core/logs`.

1. Fetch recent core logs via the Supervisor API and filter for idotmatrix-related entries:
   ```
   curl -s \
     -H "Authorization: Bearer $HA_TOKEN" \
     "http://$HA_HOST:8123/api/hassio/core/logs?lines=500" \
     | grep -i "idotmatrix\|IDotMatrix\|IDM-" \
     | tail -50
   ```

2. If the result is empty (no matching entries), fetch the last 100 lines of the raw log to confirm the endpoint is readable:
   ```
   curl -s \
     -H "Authorization: Bearer $HA_TOKEN" \
     "http://$HA_HOST:8123/api/hassio/core/logs?lines=100"
   ```

3. If step 1 returns a non-200 HTTP status (check with `-w "%{http_code}"`), fall back to the legacy endpoint for older HA versions:
   ```
   curl -s -H "Authorization: Bearer $HA_TOKEN" "http://$HA_HOST:8123/api/error_log" \
     | grep -i "idotmatrix\|IDotMatrix\|IDM-" \
     | tail -50
   ```

Report the filtered log lines, highlighting any ERROR or WARNING entries. If you see exception tracebacks or connection-related messages, include the full surrounding context.
