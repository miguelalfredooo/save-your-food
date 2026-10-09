# Restock log

Append-only. Two event kinds, one line each.

    2026-09-28 | milk     | bought | 4.99 | Safeway
    2026-10-05 | milk     | used   |      |    | t3
    2026-10-06 | chicken  | used   |      |    | t1
    2026-10-02 | cilantro | tossed |      |    | t0

`bought` lines come from a receipt and carry price and store.
`used` / `frozen` / `tossed` come from ticking a reminder off. They carry no price,
but they do carry the **tier** the item was in when it closed (`t0`–`t3`). A toss
or a rescue gets its cost by joining back to the most recent `bought` of that item,
then falling through `_ops/reference-prices-west.md` when there is none.

Three things are read out of this file:

- **Cadence** — how often something comes back. Only `used` counts; `tossed` is an
  anti-signal and must never increase buying. Three cycles with intervals that
  agree before claiming a pattern.
- **Recency** — when something was last bought, which is what the duplicate check
  leads with, because it survives a stale inventory.
- **Cost** — roughly what the tossed items cost. Approximate, never to the cent.
- **Rescue** — roughly what got used or frozen at `t0`/`t1`, right at the edge.
  The chicken line above is one; the milk at `t3` is not. Reported next to the
  toss figure, never subtracted from it.

This cannot be reconstructed after the fact. A cycle not written down when it
happens is gone.

Do not edit history. Add lines; never rewrite them.

---
