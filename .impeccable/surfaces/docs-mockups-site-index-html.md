---
version: 1
slug: "docs-mockups-site-index-html"
primary_target: "docs/mockups/site/index.html"
related_targets: ["docs/mockups/site","website"]
---

# Public website (landing + docs)

Scope: the public AMA site, built later in Astro in `website/` (ADR 0014). Mockups in `docs/mockups/site/` are acceptance criteria for Forgejo #78. Two modes: Landing is Persuade; docs pages (Install, Setup walkthrough, How a Disc flows, Libraries & Naming Patterns, Settings reference, Third-party tools & licences, Contributing) are Read.

Audience: Plex self-hosters with a shelf of their own Discs, arriving from a link or forum. Primary action: Download for Windows (unsigned installer from GitHub Releases). Secondary: See how a Disc flows. Proof: live HTML bins in the app's language, plus mockup screenshots (labelled as examples). Docs wayfinding: pages grouped behind ink divider tabs (Get started / How it works / Reference), a page list beside the reading column, an on-page contents list on long pages; tabs scroll on phones.

Terminology: the last stage reads Archived on the site (Forgejo #82 renames Filed in the app). History keeps its name.

## Direction contract

THESIS: The landing page is one Disc row from the Now screen at poster scale: its sticker is the story, cycling Ripping, Needs review, Encoding, Archived. Refuses the split hero (copy beside a device screenshot) and the three-feature card row.

OWN-WORLD: Browser Bin unchanged (DESIGN.md): cool grey ground, near-white sheets, three ink values, four stage colours owning only their stages, die-cut divider tabs, price-gun stickers, 1px hairlines, no shadows. Archivo / Archivo Narrow.

STORY: In one viewport the visitor knows AMA turns a Disc in the drive into a correctly named Plex entry, that they only answer the odd question, and where to download it.

FIRST VIEWPORT: Top bar (brand, docs links, GitHub, Download). One full-width Disc row with a cobalt top edge and no tab row (a row of stage tabs read as navigation): 280px dark drive cell (disc icon, BD), the 80px headline "Put a Disc in, it turns up in Plex." and lede, the Ripping sticker with step strip and progress, and a right action column with Download for Windows (primary) and See how a Disc flows. Four small bins peek below.

FORM: The Disc at poster scale, position 6 on my ordered list; seed:4426fc3cc982006e. Static: the maintainer rejected the stage-cycling animation. Example titles are Ocean's Eleven/Twelve/Thirteen (films) and Firefly (TV).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
