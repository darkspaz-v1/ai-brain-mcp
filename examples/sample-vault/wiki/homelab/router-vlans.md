---
topic: homelab
tags: [network, vlan, router]
---
# Router VLAN layout

Three VLANs: trusted (10), IoT (20), servers (30). The NAS and media server sit on VLAN 30.

- IoT devices can reach the internet but not the other VLANs.
- Trusted can reach servers on ports 445 (SMB) and 8096 (media).
- Changes are made on the router's admin page, then exported to `router-config.bak`.
