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
  filed-teal: "#1F7A74"
  failed-oxide: "#8E2A1B"
  ripping-ink: "#2C4FA3"
  review-ink: "#B23A20"
  filed-ink: "#1B6B66"
  encoding-ink: "#7A5A00"
  thumb: "#D6D8DC"
  thumb-ink: "#3E4146"
  drive-cell: "#24262A"
  log-ground: "#17181A"
  log-text: "#D9DBDF"
  notice: "#FBEDE9"
  notice-line: "#E6B3A6"
  focus: "#2C4FA3"
  white: "#FFFFFF"
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
  tab-filed:
    backgroundColor: "{colors.filed-teal}"
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
  sticker-filed:
    backgroundColor: "{colors.filed-teal}"
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

The interface is an Operate surface used on a phone at the drive and on a desktop for Review. Density is moderate, with 44px minimum targets throughout. It refuses the default sidebar, equal cards and status-badge table.

**Key Characteristics:**
- Four stage colours, each owning one stage: Ripping cobalt, Needs Review tomato, Encoding mustard, Filed teal.
- Die-cut divider tabs with an asymmetric cut (6px lead corner, 16px trailing corner).
- One sticker per Disc, pill-left / square-right, with a dot.
- One rule weight (1px `rule`), except a 3px stage-coloured top edge on bin sheets.
- Three ink values (`ink`, `ink-2`, `ink-3`) and tabular numerals everywhere.
- Flat surfaces; state shown as a mark (sticker, notice, tab colour), never a toast.

## Colors

A cool neutral sheet-and-ink base with four saturated stage colours, plus a separate text-safe "-ink" tone for each stage colour used on sheets. Every token is redefined for dark mode.

### Primary (stage colours)
- **Ripping Cobalt** (`ripping-cobalt`): Ripping tab, sticker and progress bar fill. Also the light-mode focus ring.
- **Review Tomato** (`review-tomato`): Needs Review tab and sticker, the Review count badge in the top bar, and a full scratch meter. The colour that asks for the user.
- **Encoding Mustard** (`encoding-mustard`): Encoding tab, sticker and progress bar. It always carries `ink` text, never white. Also the text-selection colour.
- **Filed Teal** (`filed-teal`): Filed tab and sticker. Done.

### Secondary (text-safe stage tones)
- **Ripping / Review / Filed / Encoding Ink** (`ripping-ink`, `review-ink`, `filed-ink`, `encoding-ink`): used when a stage colour has to be text or an icon on a sheet, such as the danger button label, the notice alert icon or the "ok" check. They are darker in light mode and lighter in dark mode (`#8FA9EC`, `#F08A70`, `#5CC2B8`, `#F0C85A`).
- **Failed Oxide** (`failed-oxide`): outline-only Failed sticker. In dark mode it becomes `#E06A55`.

### Neutral
- **Bin Ground** (`ground`): page background. Dark: `#111214`.
- **Sheet** (`sheet`): top bar, bin boxes, default buttons. Dark: `#1B1C1F`.
- **Well** (`well`): inputs, meter and bar tracks, hover fill, selected radio row. Dark: `#232428`.
- **Ink / Ink 2 / Ink 3** (`ink`, `ink-2`, `ink-3`): primary text, secondary text, and placeholders or waiting states. Dark: `#ECEDEF`, `#A6A9B0`, `#8E929A`.
- **Rule** (`rule`): the one hairline. Dark: `#34363B`.
- **Thumb / Thumb Ink** (`thumb`, `thumb-ink`): disc-type cells and frame placeholders. Dark: `#2C2E33`, `#B9BCC2`.
- **Drive Cell** (`drive-cell`): the dark left cell of the drive panel. It stays dark in both themes.
- **Log Ground / Log Text** (`log-ground`, `log-text`): the rip log. It stays dark in both themes, and error lines are `#F08A70`.
- **Notice / Notice Line** (`notice`, `notice-line`): a warm tint for notices that need attention. Dark: `#2A1B17`, `#6B3426`.

### Named Rules
**The One Stage, One Colour Rule.** Cobalt, tomato, mustard and teal each mean one pipeline stage. Never use them for decoration, links or generic emphasis. The primary button is `ink`, not a stage colour.

**The Ink-On-Sheet Rule.** When a stage colour is text or an icon on a sheet, use its `-ink` token. The raw stage colour is only for fills (tabs, stickers, bars, top edges).

**The Both-Themes Rule.** Every new token gets a light value, a `prefers-color-scheme: dark` value guarded by `:root:not([data-theme="light"])`, and a matching `:root[data-theme="dark"]` value.

## Typography

**Display Font:** Archivo (with system-ui, sans-serif)
**Label Font:** Archivo Narrow (with sans-serif), for divider tabs and the brand only
**Mono Font:** ui-monospace stack, for the log only

**Character:** a grotesque that reads like shop signage at heavy weights, paired with its condensed sibling for divider-tab lettering. The whole UI uses tabular numerals so percentages and sizes line up.

### Hierarchy
- **Display** (800, 44px, line-height 1, -0.02em): the progress percentage on the drive panel. The drive title is 38px/1.05 at the same weight.
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
- **≤720px:** the top bar wraps. The nav moves to a full-bleed, horizontally scrolling row with 48px targets, the scratch label hides and the meter shrinks to 48px. Page padding drops to 20px / 16px. The drive panel stacks, with its dark cell becoming a horizontal strip and the title dropping to 28px. Rows become two columns and their trailing action spans the full width (buttons stretch). Compact rows keep three columns. Buttons in action groups share the width equally.

## Elevation & Depth

The system is flat. There are no drop shadows. Depth is the tab sitting on its sheet, the 3px stage-coloured top edge of the sheet, and the 1px hairline grid between rows and frames. The only box-shadow is `inset 0 0 0 2px ink` on a selected radio row, which is a selection mark rather than elevation.

### Named Rules
**The One Rule Weight Rule.** Every border and divider is 1px `rule`. The only exceptions are the 3px stage top edge on bin sheets, the 3px active-nav underline, and the 2px focus ring.

## Shapes

Corners are nearly square (3px) on controls, notices and badges. Two shapes break this on purpose and carry the whole world:
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
- **Disabled:** 0.45 opacity with a not-allowed cursor.
- **Focus:** a global 2px `focus` outline at a 2px offset.

### Inputs / Fields
- **Style:** `well` fill, a 1px `rule` border, 3px corners, 44px tall, 12px horizontal padding. Placeholder text is `ink-3`.
- **Focus:** the border and a 1px outline both change to `focus`.
- **Field:** a 600 / 14px label above the control and a 13px `ink-2` hint below it, 6px apart. Search inputs put an icon inset at 12px and pad the text by 40px.
- **Segmented control:** a `well` strip with 1px internal rules. The current segment is filled `ink` with `sheet` text.
- **Radio row:** a 22px control column. The selected row (`.on`) gets a `well` fill and a 2px inset `ink` ring. The accent colour is `ink`.

### Navigation
- **Top bar:** a 60px `sheet` bar with a bottom rule. It holds the uppercase Archivo Narrow brand, nav links in Archivo 500 / `ink-2`, and the scratch meter pushed to the right.
- **Active link:** `ink` text with a 3px `ink` underline (`aria-current`).
- **Review count:** a tomato badge (700, 12px, 3px corners).
- **Scratch meter:** a 160px × 8px `well` track with a rule border and an `ink` fill that turns `review-tomato` when full.
- **Breadcrumb:** 14px `ink-2` text, underlined on hover.

### Divider Tab + Bin (signature)
A bin is a stage. The tab is 34px tall, filled with the stage colour, and lettered in uppercase Archivo Narrow, with an optional count in Archivo 700 / 13px. It sits directly on a `sheet` box with a 1px rule border and a 3px top edge in the same stage colour. There are variants for Ripping, Review, Encoding (with `ink` lettering), Filed, and `ink`, used for "Didn't work" and neutral groupings. A tab can be a link to that stage's screen.

### Sticker (signature)
There is exactly one sticker per Disc, showing its current status. It is 26px tall, 11px / 700 / 0.08em uppercase, and filled with the stage colour (Encoding uses `ink` text). Failed is outline-only in `failed-oxide`, with no fill. A sticker can be a link (for example, Failed links to the failure screen).

### Disc-Type Cell
A whole-cell thumbnail: a 56px `thumb` square with a rule border and the disc type (CD, DVD, BD, UHD) set bottom-left in 700 / 11px. It is 40px in compact rows and 44px on phones.

### Drive Panel
The Disc in the drive, at the largest scale on the page. A 168px dark `drive-cell` on the left holds the disc icon (28px, 1.5 stroke) and the format caption. The body holds the 38px title, the meta line, the sticker with its step, and the progress row. The progress row has a 12px bar (`well` track, stage-colour fill) and a 44px percentage. The empty state centres the body and uses a 30px title.

### Notices
State as a mark, never a toast. A notice has a 24px icon column, a bold first line, and the message below.
- **Attention (default):** `notice` fill, `notice-line` border, and a `review-ink` alert icon. Use `role="alert"` or `role="status"`.
- **OK (`.notice.ok`):** `sheet` fill, `rule` border and a `filed-ink` check icon. Use it for reassurance ("Already filed").

### Frames
Title thumbnails in a 3-up grid of 16:9 tiles with 1px hairline gaps. Tiles come in thumb, dark, mid and lite tones, with 600 / 11px captions. Mockup frames are synthetic placeholders.

### Per-Job Settings Panel
A Job's settings as overrides of the global ones (`docs/mockups/job-settings-*.html`).
- **Summary line:** on the rip card, a hairline-topped line at the foot of the drive body names only what differs from the defaults ("CQ 20 (default 22)") and ends with a Settings / Hide settings toggle (44px target).
- **Panel:** an `ink` bin, "This Job's settings", in two columns: Encode on the left, then Library, Identification and Rip stacked on the right. One column under 720px, with labels above controls. CD Jobs show only Identification, Library and Rip.
- **Group:** a 700 / 15px heading with its state at the right, then label and control pairs. An editable group ends with "Can change until <Phase> starts" or "until Filed".
- **Override:** the control gets an `ink` border and 600 weight, with "Default <value> · Reset" as a 13px `ink-2` hint under it; Reset keeps a 44px hit area. Beside a control on desktop, the label is 400 / 14px `ink-2`.
- **Saving:** each control saves on change, and a `filed-ink` check reading "Saved" appears by the group heading (`role="status"`, inserted on save so it is announced).
- **Locked:** a lock icon and "Locked at Ripping start", "Locked at Encoding start" or "Locked when Filed", with the stored values as a definition list in `ink-2` and no controls. An override stays named: "Changed for this Job · default <value>".
- **Rejected edit:** an attention notice at the top of the panel says the group locked first and the change wasn't saved.

### Log
A rip log on the always-dark `log-ground`, in 13px / 1.6 monospace, with whitespace preserved, a maximum height of 320px and scrolling. Error lines are the warm `#F08A70`.

### Icons
Stroke icons from a single SVG sprite (Lucide geometry, ISC; the eject icon is authored), 18px, stroke 2, round caps and joins, coloured with `currentColor`.

## Do's and Don'ts

### Do:
- **Do** put every Disc in the bin for its current stage, with exactly one sticker.
- **Do** use stage colours only for their stage, and use the `-ink` tokens when they are text on a sheet.
- **Do** keep every control at least 44px tall, and nav targets at 48px on phones.
- **Do** define every new token for light, system-dark and forced-dark themes.
- **Do** let size rank urgency: the drive is the largest thing, then Needs Review, then the small bins.
- **Do** self-host Archivo and Archivo Narrow (400–800, Narrow 600–700) in production. The mockups load them from Google Fonts only for convenience.

### Don't:
- **Don't** add drop shadows or raised cards. Depth comes from tabs, top edges and hairlines.
- **Don't** use toasts for state. Use a notice, a sticker or a change of bin.
- **Don't** build the default sidebar, equal card grid or status-badge table.
- **Don't** introduce a second rule weight beyond the documented exceptions.
- **Don't** put white text on Encoding mustard.
