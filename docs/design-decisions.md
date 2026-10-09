# Design decisions

The skill says what to do. This says why, and what was rejected — which is usually
the more useful half.

## Core diagnosis

Two failure modes kill systems like this, and both are design problems, not
willpower problems.

**Pull-based capture.** A forgetfulness tool that requires remembering to open it
has the failure mode built in. Fix: scheduled capture prompts, plus geofenced
capture at the moment of purchase.

**No decay.** The system assumes you report eating the chicken. You won't. The
store fills with food that's long gone, reminders start being wrong, you dismiss
reflexively, system dies. Fix: weekly reconciliation with batched confirmation,
and every claim carrying its age.

## Key decisions

| Decision | Reasoning |
|---|---|
| Urgency computed at read time, never stored | Stored urgency rots. "Use immediately" written today is lying by Friday |
| Risk class rides **priority**, not urgency | Priority is stored, so it must carry something that doesn't change. The due date already says when; priority says how bad it is to miss |
| Layered by visibility | The notification shows the title only. Everything else is a tap away, so information is ranked by which field is actually seen |
| Go/no-go leads the title | What kills a 4:30 plan is discovering at 5:10 that two ingredients are missing |
| **Never imply confirmation you don't have** | A title reading `Need pepper` says every other ingredient is verified. If stock is unconfirmed the note must name which ones |
| **Lead time shifts the nudge, not the date** | A frozen protein needs a morning thaw prompt, not a 4pm "cook this" |
| Persistence budget from risk class | One property does two jobs. Red 1 day past, yellow 3, green 7 — then a disposal prompt |
| **Checkbox = confirmation** | One tap, in the app that just notified you. Replaced the delete-to-confirm workaround a calendar backend needs |
| **Cooking is a capture event** | A cook creates new perishables. The tick is the cheapest moment to ask what's left |
| **Capture at the store, not the fridge** | A receipt is itemized, dated and complete. A fridge photo a week later is partial, undated and already wrong |
| **Two lists, two jobs** | The buy-list answers *what do I buy*; the capture list answers *what did I just bring home*. Mixing them puts permanent scaffolding in a list whose whole job is showing six things |
| **Sections beat tags** | A section is visible without a filter; a tag adds a colored word to every title and has to be kept consistent by hand |
| Arrive and exit must name the same branch | A geofence pair pointing at two addresses means one never fires, and silently |
| **An unanswered question gets its own reminder** | Sealed vs opened tofu is a 5x difference. Guessing and burying it hides the guess; a reminder whose title *is* the question gets answered |
| **Cook history outranks file count** | Sixty recipes on file is not sixty in rotation |
| **Only `used` counts toward cadence** | Counting every reappearance helps you re-buy what you throw away — the system working against its own purpose |
| **Report a state, never a failure** | "You've been out of milk since Tuesday" has no timing dependency and nothing to argue with. "You forgot the milk" works for thirty seconds and is an accusation |
| **Recency beats inventory** | A purchase log is a fact; an inventory is an inference that decays the moment you eat something without ticking it |
| **Prices measure waste, not spend** | A bank totals groceries better. What this uniquely knows is what the binned food cost |
| **Outcomes are the only real metrics** | Reminders sent and recipes matched are activity, not outcome. The two outcomes are what got tossed and what got rescued (below) |
| **Rescued sits beside tossed, never netted against it** | A toss figure alone can't tell a good month from a month you barely shopped. "Rescued" is narrow on purpose: used or frozen at `t0`/`t1` only, because milk drunk on day 2 was never at risk. A net figure would turn two different kinds of number into a verdict |
| **The tier is written at close time** | Urgency is never stored, so the moment an item was rescued has to be captured on the close line or it is gone |
| **Your receipts outrank regional averages** | BLS West is a fallback for month one. It stopped tracking most produce years ago, which is exactly what gets thrown out, so receipts fill that gap as they arrive |

## Rejected, with reasons

| Rejected | Why |
|---|---|
| **Urgency tabs** | Tabs hide things, and the hidden tier would be the urgent one. Progressive disclosure is wrong when the concealed content is the critical content |
| **Quantity-tracked pantry** | Only useful if accurate; accuracy needs logging every partial consumption; wrong within a week. A confidently wrong pantry is worse than none |
| **Expiry dates on canned and dried goods** | They don't spoil on a timescale where a nudge helps. One annual audit covers the few that turn |
| **A static dashboard** | Wrong within two days. You'd trust it once, get burned, and take the system down with it |
| **Unbounded "remind until confirmed"** | Mute risk, guilt accumulation, and past a point suggesting recipes for old chicken is unsafe |
| **Two homes for recipes** | Notes *and* files as co-equal libraries means eventually editing the wrong one |
| **Images in the alert** | The notification's job is go/no-go in one glance |
| **Category geofences** | iOS has no POI-category triggers. Named locations only |
| **Seven store reminders** | Seven permanent scaffolding rows in a list whose job is showing six things to buy. Trimmed to three |
| **Telling you what you forgot, on the way out** | A message to turn around in the car park. Missing items stay on the list and surface at the next arrival |
| **Onboarding toggle for recurrence** | Consent collected at the moment of least information, for something that won't act for a month. Ask at evidence, with the finding in hand |
| **Prices in a nudge** | Guilt with a number attached |
| **Budgets and targets** | A target invites failing to hit it, and guilt is what makes people stop opening the app |
| **Cross-store price comparison** | Noisy across sizes, promos and products, and it turns a waste system into a shopping optimizer |
| **"Saved you $X"** | It claims a counterfactual: that the food would have been binned otherwise. "Used before it went off" is a fact; "saved" is a guess |
| **Scaling US prices up to West** | West ÷ US had a median of 1.05 but ran from 0.85 to 1.31. One multiplier would be a precise-looking guess |
| **Estimating a missing price from a similar item** | Cilantro priced from romaine is the confidently-wrong number this system exists to avoid. Unpriced items are counted, and the report says how many |

## Things learned the hard way

- **A confidently wrong reminder is worse than no reminder.** A title reading
  `Need pepper` implied five unverified ingredients were confirmed. Everything
  about readiness claims descends from that mistake.
- **Restructuring a list loses entries.** Diff before and after, or use targeted
  edits. Asserting "nothing was deleted" without checking is how you find out.
- **Scheduled tasks don't inherit folders.** They return `FOLDERS_STATE_NONE` and
  the run silently skips half its job. Pass folders explicitly; verify afterwards.
- **A silent success and a silent failure look identical.** Turn notifications on
  while a scheduled job is unproven, and have it report even on quiet days.
- **Showing a count is not asking a question.** "20 items need review" is
  unanswerable; the twenty lines, grouped, is answerable in one reply.
- **An unconstrained grep will find food words in source code** and offer a test
  file as a dinner suggestion.
