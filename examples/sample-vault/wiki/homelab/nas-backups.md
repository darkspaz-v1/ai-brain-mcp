---
topic: homelab
tags: [backup, nas, restic, cron]
---
# NAS nightly backups

**Decision:** back up the laptop and the media server to the NAS with restic, nightly at 02:30.

## Setup
- Repository lives on the NAS share `//nas/backups/restic`.
- Password file is kept outside the repo folder, mode 600.
- Cron entry: `30 2 * * * restic backup ~/projects ~/notes --exclude-caches`.
- Retention: `restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune`, run Sundays.

## Gotchas
- The first run took 6 hours; later runs finish in minutes.
- A restore drill on the first of each month caught a wrong exclude pattern once.
- Do not point restic at the NAS via a mapped drive letter; use the UNC path.

## See also
- [[router-vlans]] for why the NAS sits on its own VLAN.
