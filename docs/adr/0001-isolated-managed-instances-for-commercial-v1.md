---
status: accepted
---

# Isolated managed instances for commercial V1

Commercial V1 will run one Managed Instance per Customer Account instead of immediately converting the scanner into a shared multi-tenant service. This preserves the proven scanner and SQLite runtime model, gives each account a strong data and credential boundary, and is operationally reasonable for fewer than 100 concurrent accounts; shared market ingestion and multi-tenant workers will be reconsidered only after demand and pricing are validated.

## Consequences

The platform must provision, monitor, update, back up, and retire instances consistently. Repeated market-data requests and per-instance resource overhead are accepted for V1 in exchange for lower isolation and migration risk.
