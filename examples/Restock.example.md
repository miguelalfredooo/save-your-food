# Restock log

Append-only. Two event kinds, one line each.

    2026-09-28 | milk     | bought | 4.99 | Safeway
    2026-10-05 | milk     | used   |      |
    2026-10-02 | cilantro | tossed |      |

`bought` lines come from a receipt and carry price and store.
`used` / `frozen` / `tossed` come from ticking a reminder off, and carry neither —
a toss gets its cost by joining back to the most recent `bought` of that item.

Three things are read out of this file:

- **Cadence** — how often something comes back. Only `used` counts; `tossed` is an
  anti-signal and must never increase buying. Three cycles with intervals that
  agree before claiming a pattern.
- **Recency** — when something was last bought, which is what the duplicate check
  leads with, because it survives a stale inventory.
- **Cost** — roughly what the tossed items cost. Approximate, never to the cent.

This cannot be reconstructed after the fact. A cycle not written down when it
happens is gone.

Do not edit history. Add lines; never rewrite them.

---
