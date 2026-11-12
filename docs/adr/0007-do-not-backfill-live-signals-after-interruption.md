---
status: accepted
---

# Do not backfill live signals after interruption

When a Managed Instance starts or recovers, it establishes a Live Baseline and emits only sequences observed from that point forward. Signals that would have formed during downtime are not delivered because delayed notifications can be misleading and violate the product's real-time meaning; historical evaluation remains a separate replay capability and never sends customer notifications.
