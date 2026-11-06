---
name: Automatic Media Archive
description: A LAN web UI for a disc-ripping pipeline, laid out as a record-shop browser bin.
colors:
  ground: "#E9EAEC"
  sheet: "#F7F7F8"
  well: "#FFFFFF"
  ink: "#17181A"
  ink-2: "#53565C"
  ink-3: "#7C8087"
  rule: "#C9CBCF"
  ripping-cobalt: "#2C4FA3"
  review-tomato: "#C43D22"
  encoding-mustard: "#E8B730"
  archived-teal: "#1F7A74"
  failed-oxide: "#8E2A1B"
  ripping-ink: "#2C4FA3"
  review-ink: "#B23A20"
  archived-ink: "#1B6B66"
  encoding-ink: "#7A5A00"
  thumb: "#D6D8DC"
  thumb-ink: "#3E4146"
  drive-cell: "#24262A"
  log-ground: "#17181A"
  log-text: "#D9DBDF"
  log-dim: "#8E929A"
  log-error: "#F08A70"
  log-error-band: "#3A1E17"
  notice: "#FBEDE9"
  notice-line: "#E6B3A6"
  focus: "#2C4FA3"
  white: "#FFFFFF"
  log-thumb: "#3A3C42"
  ground-dark: "#111214"
  sheet-dark: "#1B1C1F"
  well-dark: "#232428"
  ink-dark: "#ECEDEF"
  ink-2-dark: "#A6A9B0"
  ink-3-dark: "#8E929A"
  rule-dark: "#34363B"
  ripping-cobalt-dark: "#3B62C4"
  failed-oxide-dark: "#E06A55"
  ripping-ink-dark: "#8FA9EC"
  review-ink-dark: "#F08A70"
  archived-ink-dark: "#5CC2B8"
  encoding-ink-dark: "#F0C85A"
  thumb-dark: "#2C2E33"
  thumb-ink-dark: "#B9BCC2"
  notice-dark: "#2A1B17"
  notice-line-dark: "#6B3426"
  focus-dark: "#8FA9EC"
typography:
  display:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "44px"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "34px"
    fontWeight: 800
    lineHeight: 1.1
    letterSpacing: "-0.015em"
  title:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.005em"
  body:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "tnum"
  body-sm:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
  label-tab:
    fontFamily: "Archivo Narrow, sans-serif"
    fontSize: "15px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.06em"
  label-sticker:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.08em"
  mono:
    fontFamily: "ui-monospace, SF Mono, Menlo, Consolas, monospace"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  control: "3px"
  tab-lead: "6px"
  tab-cut: "16px"
  sticker-lead: "13px"
  sticker-tail: "4px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  row: "18px"
  xl: "24px"
  section: "28px"
  gutter: "32px"
components:
  button-default:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 18px"
    height: "44px"
  button-default-hover:
    backgroundColor: "{colors.well}"
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.control}"
    padding: "0 18px"
    height: "44px"
  button-primary-disabled:
    backgroundColor: "{colors.well}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.control}"
    height: "44px"
  skip-link:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.control}"
    height: "44px"
  mark:
    textColor: "{colors.ink-2}"
    typography: "{typography.body-sm}"
  button-danger:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.review-ink}"
    rounded: "{rounded.control}"
    height: "44px"
  input:
    backgroundColor: "{colors.well}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "44px"
  tab-ripping:
    backgroundColor: "{colors.ripping-cobalt}"
    textColor: "{colors.white}"
    typography: "{typography.label-tab}"
    padding: "0 20px 0 14px"
    height: "34px"
  tab-review:
    backgroundColor: "{colors.review-tomato}"
    textColor: "{colors.white}"
    typography: "{typography.label-tab}"
    height: "34px"
  tab-encoding:
    backgroundColor: "{colors.encoding-mustard}"
    textColor: "{colors.ink}"
    typography: "{typography.label-tab}"
    height: "34px"
  tab-archived:
    backgroundColor: "{colors.archived-teal}"
    textColor: "{colors.white}"
    typography: "{typography.label-tab}"
    height: "34px"
  bin-box:
    backgroundColor: "{colors.sheet}"
    padding: "22px 24px"
  sticker-ripping:
    backgroundColor: "{colors.ripping-cobalt}"
    textColor: "{colors.white}"
    typography: "{typography.label-sticker}"
    padding: "0 11px 0 9px"
    height: "26px"
  sticker-review:
    backgroundColor: "{colors.review-tomato}"
    textColor: "{colors.white}"
    typography: "{typography.label-sticker}"
    height: "26px"
  sticker-encoding:
    backgroundColor: "{colors.encoding-mustard}"
    textColor: "{colors.ink}"
    typography: "{typography.label-sticker}"
    height: "26px"
  sticker-archived:
    backgroundColor: "{colors.archived-teal}"
    textColor: "{colors.white}"
    typography: "{typography.label-sticker}"
    height: "26px"
  sticker-failed:
    textColor: "{colors.failed-oxide}"
    typography: "{typography.label-sticker}"
    height: "26px"
  disc-type-cell:
    backgroundColor: "{colors.thumb}"
    textColor: "{colors.thumb-ink}"
    size: "56px"
  notice:
    backgroundColor: "{colors.notice}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "16px 18px"
  notice-ok:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "16px 18px"
  log:
    backgroundColor: "{colors.log-ground}"
    textColor: "{colors.log-text}"
    typography: "{typography.mono}"
    padding: "16px 18px"
---

# Design System: Automatic Media Archive

## Overview

**Creative North Star: "The Browser Bin"**

The pipeline is a record-shop browser bin. Every Disc stands behind the divider of the stage it is in, and its status is the one price-gun sticker on its corner. Stages are bins, not cards: a coloured die-cut tab sits on top of a near-white sheet whose top edge picks up the tab's colour. A Disc that changes stage moves behind the next divider.

The world is cool grey and printed, not glossy. A grey bin ground, near-white sheets, near-black ink in three values, one 1px hairline rule weight, and four divider colours that each own one stage. Depth comes from the tab-on-sheet stack and the hairline grid, never from shadows. Size ranks urgency: the Disc in the drive is the largest thing on the page, and the bins beside it are small.

The interface is an Operate surface used on a phone at the drive and on a desktop for Review. Density is moderate. Targets are at least 44px on phones and at least 24px on desktop (controls stay 44px tall). It refuses the default sidebar, equal cards and status-badge table.

**Key Characteristics:**
- Four stage colours, each owning one stage: Ripping cobalt, Needs Review tomato, Encoding mustard, Archived teal.
- Die-cut divider tabs with an asymmetric cut (6px lead corner, 16px trailing corner).
- One sticker per Disc, pill-left / square-right, with a dot.
- One rule weight (1px `rule`), except a 3px stage-coloured top edge on bin sheets.
- Three ink values (`ink`, `ink-2`, `ink-3`; `ink-3` never carries meaning as text) and tabular numerals everywhere.
- Flat surfaces; state shown as a mark (sticker, notice, tab colour), never a toast.

## Colors

A cool neutral sheet-and-ink base with four saturated stage colours, plus a separate text-safe "-ink" tone for each stage colour used on sheets. Every token is redefined for dark mode.

### Primary (stage colours)
- **Ripping Cobalt** (`ripping-cobalt`): Ripping tab, sticker and progress bar fill. Also the light-mode focus ring. Dark: `#3B62C4` (focus becomes `#8FA9EC`).
- **Review Tomato** (`review-tomato`): Needs Review tab and sticker, the Review count badge in the top bar, and a full scratch meter. The colour that asks for the user.
- **Encoding Mustard** (`encoding-mustard`): Encoding tab, sticker and progress bar. It always carries `ink` text, never white. Also the text-selection colour.
- **Archived Teal** (`archived-teal`): Archived tab and sticker. Done.

### Secondary (text-safe stage tones)
- **Ripping / Review / Archived / Encoding Ink** (`ripping-ink`, `review-ink`, `archived-ink`, `encoding-ink`): used when a stage colour has to be text or an icon on a sheet, such as the danger button label, the notice alert icon or the "ok" check. They are darker in light mode and lighter in dark mode (`#8FA9EC`, `#F08A70`, `#5CC2B8`, `#F0C85A`).
- **Failed Oxide** (`failed-oxide`): outline-only Failed sticker. In dark mode it becomes `#E06A55`.

### Neutral
- **Bin Ground** (`ground`): page background. Dark: `#111214`.
- **Sheet** (`sheet`): top bar, bin boxes, default buttons. Dark: `#1B1C1F`.
- **Well** (`well`): inputs, meter and bar tracks, hover fill, selected radio row. Dark: `#232428`.
- **Ink / Ink 2 / Ink 3** (`ink`, `ink-2`, `ink-3`): primary text, secondary text, and non-text marks only (input placeholders, done step segments, waiting step icons). Text that carries meaning, including "Waiting", is `ink-2`. Dark: `#ECEDEF`, `#A6A9B0`, `#8E929A`.
- **Rule** (`rule`): the one hairline. Dark: `#34363B`.
- **Thumb / Thumb Ink** (`thumb`, `thumb-ink`): disc-type cells and frame placeholders. Dark: `#2C2E33`, `#B9BCC2`.
- **Drive Cell** (`drive-cell`): the dark left cell of the drive panel. It stays dark in both themes.
- **Log Ground / Log Text** (`log-ground`, `log-text`): the rip log. Like the log itself, the `log-*` tokens stay dark in both themes, so they have no dark-mode values (an exception to the Both-Themes Rule). Error lines are `log-error` (`#F08A70`); in step output they also get a `log-error-band` (`#3A1E17`) background, times are `log-dim` (`#8E929A`), and the scrollbar thumb and a targeted line's band are `log-thumb` (`#3A3C42`).
- **Notice / Notice Line** (`notice`, `notice-line`): a warm tint for notices that need attention. Dark: `#2A1B17`, `#6B3426`.

### Named Rules
**The One Stage, One Colour Rule.** Cobalt, tomato, mustard and teal each mean one pipeline stage. Never use them for decoration, links or generic emphasis. The primary button is `ink`, not a stage colour. Things that already happened (archived Titles and Tracks, "After the Rip") sit in `ink` bins, not stage-coloured ones.

**The Ink-3 Rule.** `ink-3` is never used for text that carries meaning. Use `ink-2`.

**The Ink-On-Sheet Rule.** When a stage colour is text or an icon on a sheet, use its `-ink` token. The raw stage colour is only for fills (tabs, stickers, bars, top edges).

**The Both-Themes Rule.** Every new token gets a light value, a `prefers-color-scheme: dark` value guarded by `:root:not([data-theme="light"])`, and a matching `:root[data-theme="dark"]` value.

## Typography

**Display Font:** Archivo (with system-ui, sans-serif)
**Label Font:** Archivo Narrow (with sans-serif), for divider tabs and the brand only
**Mono Font:** ui-monospace stack, for the log only

**Character:** a grotesque that reads like shop signage at heavy weights, paired with its condensed sibling for divider-tab lettering. The whole UI uses tabular numerals so percentages and sizes line up.

### Hierarchy
- **Display** (800, 44px, line-height 1, -0.02em): the progress percentage on the drive panel. The drive title is 38px/1.05 at the same weight, 26px when the drive is empty and on phones.
- **Headline** (800, 34px, line-height 1.1, -0.015em, balanced wrap): page h1. 26px under 720px.
- **Title** (700, 20px, line-height 1.2): section h2. Row titles are 600 at 16px, or 14px in compact rows.
- **Body** (400, 15px, line-height 1.45, tabular numerals): default text. Secondary text is 13px in `ink-2`.
- **Label: tab** (Archivo Narrow 700, 15px, 0.06em, uppercase): divider tabs. The brand is 19px at 0.02em, uppercase.
- **Label: sticker** (Archivo 700, 11px, 0.08em, uppercase): stickers and drive-cell captions.

### Named Rules
**The Narrow Is For Dividers Rule.** Archivo Narrow appears only on divider tabs and the brand. Headings and body stay in Archivo.

## Layout

The content area is capped at 1440px with 28px / 32px / 48px padding (top / sides / bottom). Single-task pages (`.solo`) narrow it to 844px.

The main working layout is a split: a left column of up to 780px holds the primary content (the drive at the largest scale, then Needs Review), and a right aside is separated by a 32px gap and a 1px rule on its left. The aside holds the small stacked bins. Stacks space their sections 28px apart.

Rows inside a bin use a three-column grid: a 56px disc-type cell, a flexible title, and a trailing action or sticker, with a 16px gap and 16px × 18px padding. Compact rows use a 40px cell and 11px × 16px padding. Rows are divided by the hairline rule.

The spacing rhythm is 4 / 8 / 12 / 16 / 18 / 24 / 28 / 32px.

**Responsive:**
- **≤1100px:** the split collapses to one column. The aside loses its left rule and sits 28px below.
- **Now with nothing happening (every width):** the layout never collapses. The drive panel and every bin (Needs Review, Ripping, Encoding, History, Didn't work) stay in place, each showing its empty state: the box holds one `ink-2` line saying the bin is empty (`docs/mockups/now-empty.html`).
- **≤720px:** the top bar wraps. The nav moves to a full-bleed, horizontally scrolling row with 48px targets, the scratch label hides and the meter shrinks to 48px. Page padding drops to 20px / 16px. The drive panel stacks, with its dark cell becoming a horizontal strip and the title dropping to 26px. Rows become two columns and their trailing action spans the full width (buttons stretch). Compact rows keep three columns. Buttons in action groups share the width equally. The selected-edition mark and the track list's Length column drop only under 480px. Long paths break after their separators (`| path` filter).

## Elevation & Depth

The system is flat. There are no drop shadows. Depth is the tab sitting on its sheet, the 3px stage-coloured top edge of the sheet, and the 1px hairline grid between rows and frames. The only box-shadow is `inset 0 0 0 2px ink` on a selected radio row, which is a selection mark rather than elevation.

### Named Rules
**The One Rule Weight Rule.** Every border and divider is 1px `rule`. The only exceptions are the 3px stage top edge on bin sheets, the 3px active-nav underline, and the 2px focus ring. A 1px border may change colour to mark state, never weight: `ink` for buttons, overrides, a pending restart, the Paused mark and hover; `review-ink` (border plus 1px outline, like focus) for an invalid input.

## Shapes

Corners are nearly square (3px) on controls, notices, badges, chips and frame captions. There is no 2px radius. Two shapes break this on purpose and carry the whole world:
- **Divider tab:** 6px top-left and 16px top-right, with a square bottom. This is the asymmetric die-cut.
- **Sticker:** 13px left and 4px right. It is pill-ended on the leading side, like a price-gun label, with a 6px round dot before the text.

The bin sheet itself is square. Frames are 16:9, laid on a 1px gap grid over a `rule` background, so the hairlines show through.

## Components

### Buttons
Plain, firm and printed.
- **Shape:** near-square (3px). Minimum height 44px, 18px horizontal padding, Archivo 600 at 14px.
- **Default:** `sheet` fill with a 1px `ink` border. Hover fills with `well`.
- **Primary:** `ink` fill with `sheet` text. Hover drops opacity to 0.9. Use one per row or group.
- **Quiet:** the default with a `rule` border.
- **Danger:** a `review-tomato` border with `review-ink` text.
- **Disabled:** 0.45 opacity with a not-allowed cursor. A disabled primary (Settings save bar) uses the well style instead: `well` fill, `rule` border, `ink-2` text, full opacity.
- **Focus:** a global 2px `focus` outline at a 2px offset.

### Inputs / Fields
- **Style:** `well` fill, a 1px `rule` border, 3px corners, 44px tall, 12px horizontal padding. Placeholder text is `ink-3`.
- **Focus:** the border and a 1px outline both change to `focus`.
- **Field:** a 600 / 14px label above the control and a 13px `ink-2` hint below it, 6px apart. Search inputs put an icon inset at 12px and pad the text by 40px.
- **Segmented control:** a `well` strip with 1px internal rules. The current segment is filled `ink` with `sheet` text.
- **Radio row:** a 22px control column. The selected row (`.on`) gets a `well` fill and a 2px inset `ink` ring. The accent colour is `ink`.

### Navigation
- **Top bar:** a 60px `sheet` bar with a bottom rule. It holds the uppercase Archivo Narrow brand, nav links (Now, Review, History) in Archivo 500 / `ink-2`, then the scratch meter and the menu button pushed to the right. The brand and scratch link are 44px tall targets.
- **Menu:** a 44px square button with the three-line icon (`aria-label="Menu"`). It opens a 280px `sheet` panel under it, bordered all round in 1px `rule` with no stage or `ink` top edge. Segmented groups have 44px segments; rows are 48px. On phones the button sits at the right end of the nav row.
  - **Mockups:** the panel (`#menu`, `hidden`) is always in the page: New Discs (Accepting / Paused; the menu owns this state), Theme (System / Light / Dark), then Settings, Logs and Log out. `menu.js` closes it on Escape (focus returns to the button) and on a click outside.
  - **Built:** a `<details>` menu (Escape and a click or focus outside close it) with Theme, then the pages in `web.MENU` (Settings, Logs; the current one in 700), then Log out when a password is set. Pause arrives with its ticket.
- **Paused mark:** while the drive is paused, an `ink`-outlined 26px "Paused" label (a mark, not a control; the menu changes it) with a pause icon sits before the scratch meter on every page. It is hidden on phones, where the menu shows the state.
- **Active link:** `ink` text with a 3px `ink` underline (`aria-current`). The scratch link gets the same active state on `/scratch`.
- **Review count:** a tomato badge (700, 12px, 3px corners). It is its own `sse-swap` span with `aria-live="polite"`, announcing "N waiting".
- **Scratch meter:** a 160px × 8px `well` track with a rule border and an `ink` fill that turns `review-tomato` when full. When space in use isn't all Rips, `/scratch` says "N GB is other files on this drive".
- **Scratch page:** `/scratch`, opened from the meter, is only about scratch: one `.solo` column with the drive panel (space in use, or "Ejected: not enough space" for a refused Disc) above an `ink` "Using scratch" bin listing each Job holding scratch with its size and state, live (`docs/mockups/scratch-full.html`). The Needs Review and Encoding bins belong on Now, not here.
- **Breadcrumb:** 14px `ink-2` text, underlined on hover; each link is a 24px target (44px on phones).

### Divider Tab + Bin (signature)
A bin is a stage. The tab is 34px tall, filled with the stage colour, and lettered in uppercase Archivo Narrow, with an optional count in Archivo 700 / 13px. It sits directly on a `sheet` box with a 1px rule border and a 3px top edge in the same stage colour. There are variants for Ripping, Review, Encoding (with `ink` lettering), Archived, and `ink`, used for "Didn't work", neutral groupings and anything that already happened ("After the Rip", an archived Disc's Titles or Tracks). A tab can be a link to that stage's screen. The tab is the bin's `h2` (`.tab-h` when it holds a link).

An archived Disc's Titles table ends in an "Archived as" column ("Kept as" for CD Tracks) naming what each became: Main Feature, Extra · category, S01E04 · name (600 weight), or Not kept / Didn't rip in `ink-2`.

### Sticker (signature)
There is exactly one sticker per Disc, showing its current Phase: Ripping, Review, Encoding, Archived or Failed, nothing else. It is 26px tall, 11px / 700 / 0.08em uppercase, and filled with the stage colour (Encoding uses `ink` text). Failed is outline-only in `failed-oxide`, with no fill. A sticker can be a link (for example, Failed links to the failure screen).
- A Disc queued for Encoding is ENCODING with "Next in line" in its meta; there is no Waiting sticker.
- A finished Rip shows the Phase it moved to (Ripping, Review or Archived), never "Ripped".
- History rows have no ARCHIVED sticker; the archived date sits in the trailing column.
- Non-Phase labels ("Same length", "Selected") are a **mark**: a 16px check icon in `ink` and 600 / 13px `ink-2` text (`.mark`; `.mark.sel` is `ink` text and shows only on the checked radio row).

### Disc-Type Cell
A whole-cell thumbnail: a 56px `thumb` square with a rule border and the disc type (CD, DVD, BD, UHD) set bottom-left in 700 / 11px. It is 40px in compact rows and 44px on phones.

### Drive Panel
The Disc in the drive, at the largest scale on the page. A 168px dark `drive-cell` on the left holds the disc icon (28px, 1.5 stroke) and the format caption. The body holds the 38px title, the meta line, the sticker with its step, and the progress row. The progress row has a 12px bar (`well` track, stage-colour fill, `role="progressbar"`) and a 44px percentage. An Encoding bar has an `ink-2` track border and a 1px `ink` end edge on the fill, so the mustard reads against the track. The empty state centres the body and uses a 26px title.

The drive card is not a live region. A visually hidden `role="status"` sentence beside it announces Phase changes only ("Ripping ARRIVAL.", "The drive is empty. Insert a Disc.").

### Notices
State as a mark, never a toast. A notice has a 24px icon column, a bold first line, and the message below.
- **Attention (default):** `notice` fill, `notice-line` border, and a `review-ink` alert icon. Use `role="alert"` or `role="status"`.
- **OK (`.notice.ok`):** `sheet` fill, `rule` border and an `archived-ink` check icon. Use it for reassurance ("Already archived").
- **Archiving ending:** after a Review decision the page goes to the next Disc in Review (`?done=<id>`) with a `notice ok` strip (`role="status"`) reading "Done: <name>", what happens next, and "The next Disc that needs you is below."

### Inline Confirm
A destructive or disruptive action asks in place, never in a modal: a `sheet` box with a 1px `ink` border under the trigger, a bold question, a 14px `ink-2` consequence, and Cancel plus the action (buttons share the width on phones). It is `role="alertdialog"`; focus moves into it, and Escape or Cancel returns focus to the trigger. Used by Discard in CD Review, Library Remove, Restart and the unsaved-changes guard.

### History Row
A compact row: cover or disc-type cell, the title link, a meta line (kind, resolution, "Disc N of M" for sets, Extras or Episode count, a source chip), then a separate `<details>` "Show Tracks / Episodes / Extras" whose `<summary>` holds no links. The archived date sits in the trailing column. The **source chip** (`.src`) is rule-bordered, 3px corners, 600 / 12px, reading "Details on TMDB" or "Details on MusicBrainz" (the built v1 rows read "TMDB" / "MusicBrainz").

### Comparison Tables
A differing cell (`td.diff`) is a `notice` tint at 600 weight, not a side stripe.

### Frames
Title thumbnails in a 3-up grid of 16:9 tiles with 1px hairline gaps. Tiles come in thumb, dark, mid and lite tones, with 600 / 11px captions. Mockup frames are synthetic placeholders.

### Per-Job Settings Panel
A Job's settings as overrides of the global ones (`docs/mockups/job-settings-*.html`).
- **Summary line:** on the rip card, a hairline-topped line at the foot of the drive body names only what differs from the defaults in plain words ("Quality 20 (default 22)", never "CQ") and ends with a Settings / Hide settings toggle (44px target).
- **Panel:** an `ink` bin, "This Job's settings", in two columns: Encode on the left, with Library and Identification stacked on the right for video Jobs. CD Jobs show Identification on the left, with Library and Rip on the right. One column under 720px, with labels above controls. A group lists only settings that exist in `ama.toml`, and a group with none is left out (video Rips have no Rip settings).
- **Group:** a 700 / 15px heading with its state at the right, then label and control pairs. An editable group ends with "Can change until <Phase> starts" or "until Archived".
- **Override:** the control gets an `ink` border and 600 weight, with "Default <value> · Reset" as a 13px `ink-2` hint under it; Reset keeps a 44px hit area. Beside a control on desktop, the label is 400 / 14px `ink-2`.
- **Saving:** each control saves on change, and an `archived-ink` check reading "Saved" appears by the group heading (`role="status"`, inserted on save so it is announced).
- **Locked:** a lock icon and "Locked at Ripping start", "Locked at Encoding start" or "Locked when Archived", with the stored values as a definition list in `ink-2` and no controls. An override stays named: "Changed for this Job · default <value>".
- **Rejected edit:** an attention notice at the top of the panel says the group locked first and the change wasn't saved.

### Settings Page
Editing `ama.toml` (v2, `docs/mockups/settings-*.html`). Content is capped at 1100px. The TOML stays the source of truth (ADR 0008); tabs only group its tables:

| Tab | Holds | TOML tables |
|---|---|---|
| General | Web UI (Address, Port), Storage, Scratch cleanup; Advanced "Database and log file" | `[web]`, `[scratch]`, `[paths]` |
| Ripping | Drive; Advanced "Reading CDs" and "Tools" | `[drive]`, `[cd]`, `[tools]` |
| Archive | sub-nav: Encode, Libraries, Identification | `[encode.*]`; `[plex]` and the Libraries; `[tmdb]` |
| Alerts | Discord, ntfy, Webhook (with "Send test") | `[discord]`, `[ntfy]`, `[webhook]` |
| Logs | Step output retention | the log settings |

- **Divider file:** the five tabs are divider tabs in a row, 32px below the h1. Each tab's hit area reaches 10px upward into that gap; on phones the tabs are 44px tall (48px when open). Closed tabs are `sheet` with a rule border and `ink-2` lettering; the open one is `ink`, 4px taller, and sits on a sheet with an `ink` top edge. Each tab is its own page. On phones the row scrolls sideways, fades at the right, and scrolls the open tab into view.
- **Sub-nav (Archive):** a row of 48px links under the tab, `ink-2` 500 / 15px, the current one `ink` 600 with a 3px `ink` underline.
- **Group:** a 700 / 16px heading with an optional 13px `ink-2` note at the right (for example "Takes effect at once").
- **Field row:** label and hint on the left, the control in a column of up to 380px on the right, rows divided by the hairline. One column under 720px.
- **Wording:** the plain explanation comes first and the technical term second (`.tech`, under the hint). TOML keys ("Key `[cd] offset`") appear only in Advanced rows and the Encode disclosure.
- **Advanced:** expert sections sit in a closed `<details>`: a 64px summary with the name, an "Advanced" tag (20px, rule-bordered, 600 / 11px), "You probably don't need to change this." in `ink-2`, the group's restart note at the right and a chevron that turns open. Encode's "Quality, sound and subtitles" uses the same disclosure with a "Now: …" summary.
- **Restart notes:** per group, in the group's note ("Used after a restart", "Checked when AMA starts · used after a restart", "Used from the next CD Rip"). A per-field restart tag (20px, rule-bordered, redo icon) appears only in a mixed group. Once such a key is saved it reads "Waiting for restart" with an `ink` border.
- **Restart banner:** an attention notice (`role="status"`) between the h1 and the tabs listing the saved keys waiting for a restart (key and tab). It says what happens to running Jobs: a Rip that's cut off fails and needs the Disc put back in; Encodes start again. After a Port or Address change it links to the new address. "Restart…" opens an inline confirm defaulting to "Restart when idle" (secondary: "Restart now"); while waiting the banner reads "AMA restarts when nothing is Ripping or Encoding" with what it is waiting for.
- **Field warning:** an inline `notice`-tinted warning under a control (`.fwarn`, `review-ink` alert icon), for example when Address is 127.0.0.1 ("Phones and other computers lose access").
- **Leave guard:** leaving a tab with unsaved changes shows a `well` strip at the top of the sheet (`role="alertdialog"`): "Leave General without saving?", what changed, then Stay, Discard and go, and Save and go.
- **Secret:** a saved secret is never rendered. It shows an `archived-ink` check and "Set" with quiet Replace and Remove buttons; an unset one is an empty password input reading "Not set".
- **Save bar:** each section ends with a footer: status on the left ("No unsaved changes", "Unsaved changes" in `ink` 600, or an `archived-ink` "Saved at 21:14" status), then "Undo changes" and the primary "Save <tab>", disabled (well style) when clean.
- **Rejected save:** an attention notice at the top of the sheet says the tab wasn't saved and `ama.toml` is unchanged, with an error summary listing a link to each bad field; each bad input gets a `review-ink` border and outline, and an alert-icon message under it naming the fix.
- **Choice list:** radio rows in a `well` box for the encoder, audio and subtitles. The radio is drawn, not native: an `ink-3` ring, filled `ink` with a `sheet` gap when chosen.
- **Speed:** one generic scale on every encoder (Faster, bigger / Balanced / Slower, smaller / Slowest, smallest), always in that order; the per-Job panel marks the global value "(default)". An encoder that fails its test encode is disabled with "Not available on this PC"; a configured one that stops working stays selected with a `review-ink` note, and an attention notice offers "Test encoders again".
- **Libraries:** the Plex connection is the top group, then the Libraries grouped by kind (Films, TV, Music), each group headed by its name with "Default: <Library>" at the right, the default listed first and an "Add <kind> Library" button at its foot. A row shows the name, then Folder and Plex library as small `ink-2` labels over their values, then a fixed-width actions column so columns align. The default row shows a lock and "Default, can't be removed" with Edit; others get Edit, Make default and Remove. Edit and Add open an inline `well` form (Name, Plex library, Folder, and the Naming Pattern for a kind that has one) under the row or at the group's foot. The Naming Pattern is a monospace field over its example: a `sheet` box with the name the example values get (for TV also a special and an Episode with no title), redrawn as the pattern is typed, or instead the reasons it can't be used (Field Error style); Plex warnings follow in `fwarn` boxes and don't stop a save. Under them, preset patterns as quiet buttons that fill the field, and a table of every field with its example and what it is; the Plex library list holds only Plex libraries of the group's type, and when Plex can't be reached it is disabled with a hint that saving still works. Remove opens an inline confirm under the row (see Inline Confirm) naming the default that unarchived Jobs fall back to. On phones a row stacks and its buttons share the width.

### Logs
Every run's steps and their output, laid out like a CI run log (`docs/mockups/logs*.html`, `now-output.html`). Reached from the top-bar menu.
- **Run list:** an h1, then filters: a search box (up to 380px, full width on phones) that filters runs by Disc, Job or kind, with a "No runs match" state and a match count; an All / Jobs / App segmented control (44px segments) and a "Problems only" toggle (rule-bordered, `failed-oxide` alert icon; filled `ink` when pressed), with the output-keeping note and a Change link at the right. Runs sit in `ink` bins, one per day (Today, Yesterday, then dates), newest first, with "Older runs" at the foot.
- **Run row:** the whole row links to the run and fills `well` on hover. A Job row is a normal row: disc-type cell, title, a meta line (current step or step count, start time, duration, error lines in `failed-oxide`), the step strip, and the Job's one sticker. An app-event row (startup, tool downloads, Scratch cleanup, and NAS Runs kept from before ADR 0011) gets a disc-type cell holding an icon and its kind (App, Tools, Scratch, NAS), and a Done (`archived-ink` check) or Failed (`failed-oxide` alert) mark instead of a sticker, since stickers belong to Jobs.
- **Step strip:** one 24 × 6px segment per step, 3px apart: done `ink-3`, running in its Phase colour (cobalt for the Rip, mustard for an Encode, `ink` otherwise), failed `failed-oxide`, waiting an empty `well` box, not run dashed. It is `aria-hidden`; the meta line says the same in words.
- **Run page:** a breadcrumb back to Logs, the h1 and a meta line, with the sticker (or the app mark) and a quiet "Job page" button at the right. The split layout holds an `ink` Steps bin on the left and, in the aside, "This run" as a definition list (Job, Disc, Phase, times, steps, how long output is kept) and "Settings used": the Job's locked groups with their lock line. A failed run puts an attention notice above the Steps bin.
- **Step:** a `<details>` row: a 20px state icon (`archived-ink` check, a turning loader in the Phase's `-ink` colour, `failed-oxide` alert, `ink-3` circle for waiting, `ink-3` dash for "Didn't run"; each `role="img"` with its state as the label), the step name in 600 / 16px with its subject in `ink-2` ("Encode · Main Feature, Title 1"), the tool and a short result in 13px `ink-2`, the duration at the right and a chevron that turns when open. A running step adds a 6px Phase-colour bar, percentage and time left. The header carries the tool and a short result; the exit code is in the open step's meta strip, and the Job and Phase are in the aside. Waiting and not-run steps are plain rows, not disclosures, since they have no output. A step whose output was pruned keeps its header and opens to "Output removed after N days" in place of the log, on a `well` band with an `ink-3` log icon and a "Keep output longer" link to Settings › Logs; its run row says the same, and the aside's Output line gives the date it went. On phones the duration drops under the tool line.
- **Step output:** a hairline-ruled meta strip (state and exit code, start and end times, line count, and buttons for "First error" and "Download log") over the dark log, up to 440px tall (360px on phones). A "Wrap lines" toggle (`aria-pressed`, on by default on phones) wraps long lines. Each line starts with its time in `log-dim`, which is the line's anchor (`#s1-L14`); the targeted line gets a `log-thumb` band, white time and a `log-dim` outline. Error lines are `log-error` on a `log-error-band` band that bleeds to the log's edges, and the failed step opens by default. Each step has an id, so other pages can link straight to it. Command-line arguments are never shown.
- **Live output:** the log is `role="log"`. A running step's meta strip starts with a Phase-colour dot (`ink` for app runs) and "Following live output" (`role="status"`). The log follows the tail while scrolled to the bottom. Scrolling up stops following, the status reads "Scrolled up, not following", and a "Jump to latest" button appears at the log's bottom right.
- **Inline output on Now:** a collapsed toggle on the rip card and on each running Encoding row. On the rip card it is a hairline-topped foot line (tool and step in `ink-2`, "Show output" / "Hide output", "Open in Logs" at the right), under the per-Job settings line when both show. On an Encoding row it sits under the row, indented to the title. Open, it shows the last ~20 lines in a compact log (12px, up to 200px on the card and 160px in the row; 150px for both on phones), scrolled to the newest line and updating live. "Open in Logs" goes to that step on its run page. A waiting Encoding row has no output, so no toggle.

### Public site
The website in `website/` (Astro, ADR 0014; mockups `docs/mockups/site/`) uses this system, but it is not the app and must never look like it.
- **Website vs app:** website sections are plain type on `ground`: headings, lists, a table and `ink` buttons. Bins, tabs, stickers, rows and radio rows appear only inside an **app window** (`.appwin`): a 6px-cornered frame with a 40px `well` bar reading "AMA in your browser · <page>" and an "Example" (or "Design mockup") tag, its contents `inert`, captioned below with "The app: …".
- **Landing:** the headline and lede, then Download for Windows and See how a Disc flows; under them, an app window showing the Now page. No animation. Stage colours outside app windows appear only as the 3px top rule over each stage in "How a Disc flows".
- **Docs:** pages are grouped into sections (Get started, How it works, Reference; `website/src/docs.ts`) shown as a divider file of `ink` tabs over a sheet with an `ink` top edge. The sheet holds the section's page list (240px), the reading column and "On this page" (220px, hidden under 1240px, where a `<details>` takes its place). Previous and next links end each page. On phones the tabs and the page list scroll sideways.
- **Text width:** body text runs to its column; no character-count caps on paragraphs or intros.
- **Examples:** films are Ocean's Eleven / Twelve / Thirteen, TV is Firefly, music is Queen's Greatest Hits.

### Log
A rip log on the always-dark `log-ground`, in 13px / 1.6 monospace, with whitespace preserved, a maximum height of 320px and scrolling. Error lines are `log-error`. Step output in Logs uses the same block, taller and with times (see Logs above).

### Icons
Stroke icons from a single SVG sprite (Lucide geometry, ISC; the eject icon is authored), 18px, stroke 2, round caps and joins, coloured with `currentColor`.

## Accessibility

- **Targets:** at least 44px on phones and 24px on desktop, including the brand, scratch link, breadcrumbs, Settings tabs and `.src` chips. Small links grow their hit area with padding or a `::after` inset rather than their visual size.
- **Skip link:** the first element on every page, "Skip to content", an `ink` fill with `sheet` text and 3px corners, off-screen until focused; it targets `#main` (`#content` in the built shell).
- **Headings:** every page has an h1; Now's is visually hidden (`.sr`). Bin tabs are `h2`s.
- **Progress:** bars are `role="progressbar"` with value, range and label.
- **Live regions:** only what changes meaning is announced. The drive card is silent; a hidden `role="status"` sentence carries its Phase changes. The nav Review count is its own `aria-live` swap. `theme.js` skips SSE swaps whose text hasn't changed, so progress ticks don't re-announce. Live logs are `role="log"`.
- **Confirms:** inline `role="alertdialog"` with focus management (see Inline Confirm).

## Do's and Don'ts

### Do:
- **Do** put every Disc in the bin for its current stage, with exactly one sticker naming a Phase.
- **Do** use stage colours only for their stage, and use the `-ink` tokens when they are text on a sheet.
- **Do** use `ink-2`, not `ink-3`, for any text that carries meaning.
- **Do** keep every control at least 44px tall, every target at least 44px on phones and 24px on desktop, and nav targets at 48px on phones.
- **Do** define every new token for light, system-dark and forced-dark themes.
- **Do** let size rank urgency: the drive is the largest thing, then Needs Review, then the small bins.
- **Do** self-host Archivo and Archivo Narrow (400–800, Narrow 600–700) in production. The mockups load them from Google Fonts only for convenience.

### Don't:
- **Don't** add drop shadows or raised cards. Depth comes from tabs, top edges and hairlines.
- **Don't** use toasts for state. Use a notice, a sticker or a change of bin.
- **Don't** build the default sidebar, equal card grid or status-badge table.
- **Don't** introduce a second rule weight beyond the documented exceptions.
- **Don't** put white text on Encoding mustard.
- **Don't** use a sticker for a non-Phase label ("Waiting", "Ripped", "Selected"). Use the meta line or a mark.
- **Don't** put links inside a `<summary>`.
