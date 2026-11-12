---
status: accepted
---

# Central portal with private managed instances

Users will authenticate through one Customer Portal backed by a managed identity service. Managed Instances will not expose their dashboards or control APIs publicly; the portal control plane will be the only route for configuration and lifecycle operations, avoiding duplicated authentication code and preventing customers from reaching process-level controls.
