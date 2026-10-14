# Driving Reminders and Notes

Operational reference for the Save Your Food skill (`skill/SKILL.md`). Read this before any
`computer_app_*` work; it is not needed for reasoning, only for acting.

Background mode, `com.apple.reminders` and `com.apple.notes`.

**Verify before every write.** Screenshot after each step. A click that reports
success often only placed a caret, and the next keystroke lands somewhere
unintended.

## What works in background mode

- Reading lists, screenshots, the menu bar via `app_menu`
- Typing a new reminder's title and notes: click `Add Reminder`, then click the
  title area and `app_type` at that same coordinate
- Overwriting an existing field with `app_type` + `overwrite_existing: true` — it
  returns the old value so you can restore it
- **Editing a date or time chip that already has a value** — the chips are plain
  text fields. Click, then `app_type` `9:00 AM` with `overwrite_existing`, then
  Return. This sidesteps the picker entirely
- All file work via `device_bash`

## Type, don't click

Most of the fights with this UI end the moment you type instead of aiming.

- **An open date field accepts a typed date.** `12/22/2026` lands directly and the
  calendar follows. Never click through months to reach a distant date.
- **A tag lives in the title string, not in the Tags sheet.** The Tags popover will
  not release one — clicking the token, Delete and Backspace all leave it sitting
  there. Click the title, `cmd+Right` to the end, backspace over the tag text. The
  tag disappears from the sidebar once its last reference goes.
- **Batch repeated keystrokes** in one `computer_batch` call rather than one call each.

## What needs full-screen control

- Any empty picker chip (`Add Date`, `Add Time`, `Add Location`)
- The **Arriving / Leaving** radio — it sits below the window edge, and an open
  popover disables Window → Zoom, so it cannot be brought into view otherwise
- List Type and other dropdowns
- Renaming a section, in practice

## Traps

- **Escape is a delete gesture** when focus is on the sidebar — it raises "Delete
  list?". Dismiss popovers by clicking neutral space, such as an empty part of the
  toolbar.
- **Clicking a sidebar list in background mode lands a caret in its NAME field**,
  not on the list. One keystroke renames it. Reach a list through the search field
  instead, or take full control.
- **Cmd+A with sidebar focus selects every list.** Confirm the caret is in a text
  field first — an editing row shows its date and location chips.
- **Clicking a row in a suggestion popover does nothing.** Down-arrow to highlight,
  screenshot to confirm, then Return. True for both location and date suggestions.
- **Location search wants a short query.** The chain name alone returns several results
  ordered by distance; adding the city to the query returns none at all. The extra words
  silently kill it.
- **The machine's location can resolve to the wrong metro** — it drifted by about forty
  miles early in setup and later read correctly. Spell out the street address, and check
  the map in Edit Details before trusting a geofence. The failure is silent.
- **Typing a store name into the location chip looks like it worked but sets nothing.**
  Check the Location toggle in Edit Details — if it's off, no geofence exists.
- **Reminders parses dates out of titles** and silently attaches them. Keep them in
  the notes.
- **App grants lapse mid-session** without warning, repeatedly. Re-resolve and
  re-request rather than assuming.
- **Date picker menu** offers only Today / Tomorrow / This Weekend / Next Week, then
  Custom. Arrow-key down five times and Return to reach Custom, which opens a real
  calendar — then type the date rather than clicking it.

## Alternative backends

Google Calendar works from the cloud with no device dependency but has no
checkboxes, so confirmation reverts to deleting the event, risk class rides
`colorId` (11 Tomato / 5 Banana / 10 Basil), and geofenced capture is lost
entirely. Apple Notes, iCloud Drive, Drive and Notion cannot serve as the store —
they hold records but can't notify.
