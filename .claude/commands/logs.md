---
allowed-tools:
  - Bash(curl:*)
  - Bash(grep:*)
  - Bash(sed:*)
  - Bash(tail:*)
---

Use curl with the environment variables $HA_HOST and $HA_TOKEN to fetch recent idotmatrix log entries from Home Assistant. Run all curl commands via Bash. Do NOT use Python. Use grep and sed for filtering. Proceed through these steps and report the result:

1. Fetch the full HA error log and filter for idotmatrix-related entries:
   ```
   curl -s -H "Authorization: Bearer $HA_TOKEN" "http://$HA_HOST:8123/api/error_log" \
     | grep -i "idotmatrix\|IDotMatrix\|IDM-" \
     | tail -50
   ```

2. If the result is empty (no matching entries), fetch the last 100 lines of the raw log to confirm the log is readable:
   ```
   curl -s -H "Authorization: Bearer $HA_TOKEN" "http://$HA_HOST:8123/api/error_log" \
     | tail -100
   ```

Report the filtered log lines, highlighting any ERROR or WARNING entries. If you see exception tracebacks or connection-related messages, include the full surrounding context.
