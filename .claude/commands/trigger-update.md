---
allowed-tools:
  - Bash(curl:*)
  - Bash(grep:*)
  - Bash(sed:*)
  - Bash(sleep:*)
---

Use curl with the environment variables $HA_HOST and $HA_TOKEN to update and reload the idotmatrix integration in Home Assistant. Run all curl commands via Bash. Do NOT use Python. Use grep and sed for JSON parsing. Proceed through these steps and report the result of each:

1. Find the idotmatrix update entity:
   ```
   curl -s -H "Authorization: Bearer $HA_TOKEN" http://$HA_HOST:8123/api/states | grep -o '"entity_id":"update\.[^"]*idotmatrix[^"]*"' | sed 's/"entity_id":"//;s/"//'
   ```
   If an entity_id is returned, proceed to step 2. If empty, skip to step 3.

2. Trigger the HACS update:
   ```
   curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" -H "Content-Type: application/json" \
     -d "{\"entity_id\": \"<entity_id from step 1>\"}" \
     http://$HA_HOST:8123/api/services/update/install
   ```
   Then run `sleep 10` to wait for the download to complete before continuing.

3. Find the idotmatrix config entry ID:
   ```
   curl -s -H "Authorization: Bearer $HA_TOKEN" http://$HA_HOST:8123/api/config/config_entries | grep -o '"entry_id":"[^"]*","domain":"idotmatrix"' | grep -o '"entry_id":"[^"]*"' | sed 's/"entry_id":"//;s/"//'
   ```

4. Reload the integration using the entry_id from step 3:
   ```
   curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
     http://$HA_HOST:8123/api/config/config_entries/entry/<entry_id>/reload
   ```

Report whether the update was found and installed, and whether the reload succeeded.
