---
name: Archival Dossier
colors:
  surface: '#111317'
  surface-dim: '#111317'
  surface-bright: '#37393d'
  surface-container-lowest: '#0c0e11'
  surface-container-low: '#1a1c1f'
  surface-container: '#1e2023'
  surface-container-high: '#282a2d'
  surface-container-highest: '#333538'
  on-surface: '#e2e2e6'
  on-surface-variant: '#d3c4b3'
  inverse-surface: '#e2e2e6'
  inverse-on-surface: '#2f3034'
  outline: '#9c8f7f'
  outline-variant: '#4f4538'
  surface-tint: '#f2be71'
  primary: '#f2be71'
  on-primary: '#442b00'
  primary-container: '#d4a359'
  on-primary-container: '#583a00'
  inverse-primary: '#7e5713'
  secondary: '#44e2cd'
  on-secondary: '#003731'
  secondary-container: '#03c6b2'
  on-secondary-container: '#004d44'
  tertiary: '#ffb3b7'
  on-tertiary: '#67001b'
  tertiary-container: '#ff8892'
  on-tertiary-container: '#840025'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#ffddb1'
  primary-fixed-dim: '#f2be71'
  on-primary-fixed: '#291800'
  on-primary-fixed-variant: '#614000'
  secondary-fixed: '#62fae3'
  secondary-fixed-dim: '#3cddc7'
  on-secondary-fixed: '#00201c'
  on-secondary-fixed-variant: '#005047'
  tertiary-fixed: '#ffdadb'
  tertiary-fixed-dim: '#ffb2b7'
  on-tertiary-fixed: '#40000d'
  on-tertiary-fixed-variant: '#92002a'
  background: '#111317'
  on-background: '#e2e2e6'
  surface-variant: '#333538'
typography:
  headline-xl:
    fontFamily: Newsreader
    fontSize: 2.75rem
    fontWeight: '400'
    lineHeight: '1.15'
    letterSpacing: -0.02em
  headline-xl-mobile:
    fontFamily: Newsreader
    fontSize: 2rem
    fontWeight: '400'
    lineHeight: '1.2'
    letterSpacing: -0.015em
  headline-lg:
    fontFamily: Newsreader
    fontSize: 2rem
    fontWeight: '400'
    lineHeight: '1.25'
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Newsreader
    fontSize: 1.5rem
    fontWeight: '500'
    lineHeight: '1.3'
    letterSpacing: 0em
  headline-sm:
    fontFamily: Newsreader
    fontSize: 1.25rem
    fontWeight: '500'
    lineHeight: '1.35'
    letterSpacing: 0em
  body-lg:
    fontFamily: IBM Plex Sans
    fontSize: 1.125rem
    fontWeight: '400'
    lineHeight: '1.5'
    letterSpacing: -0.01em
  body-md:
    fontFamily: IBM Plex Sans
    fontSize: 0.9375rem
    fontWeight: '400'
    lineHeight: '1.5'
    letterSpacing: 0em
  body-sm:
    fontFamily: IBM Plex Sans
    fontSize: 0.8125rem
    fontWeight: '400'
    lineHeight: '1.45'
    letterSpacing: 0.01em
  label-lg:
    fontFamily: JetBrains Mono
    fontSize: 0.875rem
    fontWeight: '500'
    lineHeight: '1.3'
    letterSpacing: 0.02em
  label-md:
    fontFamily: JetBrains Mono
    fontSize: 0.75rem
    fontWeight: '500'
    lineHeight: '1.25'
    letterSpacing: 0.04em
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 0.6875rem
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: 0.06em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-desktop: 1.5rem
  margin: 1rem
  margin-desktop: 2.5rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style

This design system expresses a forensic, investigative aesthetic structured around an archival case dossier. It rejects hyper-polished corporate minimalism in favor of an authoritative, high-contrast, editorial intelligence interface. Designed for senior engineers, forensic analysts, and technical investigators performing root-cause analysis, the environment feels clinical, deliberate, and archival—like opening an illuminated terminal ledger in an intelligence vault.

The design movement blends **Dark Editorial** and **Technical Skeuomorphism**: crisp hairline registration marks, index tabs, archival stamp accents, calibrated confidence meters, and rigorous typographic hierarchies. High-density data tables and file timelines sit alongside literary serif titles and monospaced cryptographic citations. Surfaces remain pitch-dark and ink-like, punctuated by brass provenance stamps, crisp emerald telemetry, and strict structural hairline dividers.

## Colors

The palette operates under an absolute dark-canvas protocol where contrast conveys evidentiary certainty. Backgrounds use `--ink` (`#0d0f12`) as the base substrate, overlaid with `--panel` (`#14171d`) containers and `--panel-raised` (`#1c2027`) interactive states.

Structural division relies on micro-hairlines: `--hairline` (`#2a303c`) establishes container boundaries and architectural grids, while `--hairline-soft` (`#1f242e`) delineates interior records and table ledgers. Text contrast hierarchy follows strict readability: `--text-primary` (`#f0f3f6`) provides high-contrast parchment white, `--text-secondary` (`#9aa5b5`) serves structural summaries and field labels, and `--text-tertiary` (`#657182`) is reserved for timestamps, dossier file paths, and indexing codes.

Functional status relies on forensic signaling:
- **Brass** (`#d4a359`): Provenance, root-cause attribution, Git revision lineage, archival seal markings.
- **Teal** (`#2dd4bf`) & **Teal-Dim** (`#115e59`): High confidence, verified signals, healthy system traces.
- **Amber** (`#f59e0b`): Fluctuating telemetry, moderate confidence, warning markers.
- **Crimson** (`#f43f5e`): Direct regression, low confidence, fatal assertions, regression originators.

## Typography

The typographic stack balances literary journalism with technical telemetry.

1. **Newsreader (Editorial Serif):** Applied to primary case titles, dossier headers, and post-mortem section introductions. Italicized cuts indicate subjective analyst annotations, evidentiary hypotheses, or investigative status tags.
2. **IBM Plex Sans (Technical Humanist Sans):** Delivers clean optical rhythm for narrative incident logs, explanatory summaries, and user interface controls. Ensures sustained readability at small point sizes without clinical coldness.
3. **JetBrains Mono (Forensic Citations):** Explicitly handles hexadecimal memory addresses, SHA-1 commit hashes, code-diff citations, confidence ratings, and ISO-8601 timestamps. Always displayed in uppercase for system metadata tags.

## Layout & Spacing

The layout is built on a 12-column analytical ledger grid designed for dense information parsing:
- **Desktop (1200px+):** 12 columns with 24px (`1.5rem`) gutters and 40px (`2.5rem`) canvas margins. Sidebars operate as fixed dossier navigation indexing rails (280px to 320px).
- **Tablet (768px - 1199px):** 8 columns with 16px (`1rem`) gutters and 24px margins. Metadata sidebars convert into collapsible header dossiers.
- **Mobile (< 768px):** 4 columns with 16px (`1rem`) gutters and 16px margins. Information stacks vertically along the timeline spine.

Horizontal datum lines mimic archival ledger stock: row structures use exact multiples of 8px base increments. Containers should employ hairline dividers rather than open whitespace to anchor dense data sets into rigid analytical envelopes.

## Elevation & Depth

Visual hierarchy does not use diffuse blurs or floating shadows. Instead, depth is produced through **tonal stratification and structural hairlines**:

1. **Substrate (`--ink` #0d0f12):** The unlit desk surface. Houses base structural lines and inactive layout zones.
2. **Panel Tier (`--panel` #14171d):** The primary dossier folder surface. Defined with a 1px solid border of `--hairline` (`#2a303c`). Never casts ambient blur.
3. **Elevated Record Tier (`--panel-raised` #1c2027):** For selected cards, active file inspections, and hover overlays. Framed with a 1px solid `--hairline` and an internal inset specular edge: `inset 0 1px 0 0 rgba(255, 255, 255, 0.05)`.
4. **Modal Dossier & Popovers:** Anchored with an absolute 1px perimeter of `--hairline` backed by a high-density directional drop: `0 12px 32px -4px rgba(0, 0, 0, 0.8)`.
5. **Timeline Spine & Crosshairs:** Linear coordinates and timeline traces sit precisely centered on 1px grid rules using `--hairline-soft` (`#1f242e`), providing physical depth akin to engraved archival scales.

## Shapes

Shapes reflect precision laboratory apparatus and archival document folders. The primary border-radius is strictly clipped to **Soft (`roundedness: 1`)**:

- Cards, inputs, and interactive containers use `0.25rem` (4px) radii.
- Chips, confidence badges, and commit stamps utilize `0.125rem` (2px) or sharp `0px` radii for a chiseled forensic finish.
- Modal panels and full dossier sheets step up to `0.5rem` (8px) maximum.
- Never use full-circle pills or soft rounded bubbles; all corner cuts must communicate intentional structural geometry.

## Components

### Buttons
- **Primary (Attribution/Execution):** `--brass` background with `--ink` text, set in `JetBrains Mono` medium uppercase. Border: 1px solid transparent. Hover: Subtle brightness lift to `#deb46f`.
- **Secondary (Inspect/Trace):** `--panel` background with `--text-primary`, bordered with 1px solid `--hairline`. Hover: `--panel-raised` and border shifts to `--text-secondary`.
- **Tertiary/Ghost:** Transparent ground, `--text-secondary` copy, underline decoration on hover.

### Confidence Meters (`.meter`)
- Horizontal rail (4px height) set on `--hairline-soft`.
- Filled segment represents forensic confidence:
  - `.high`: Solid `--teal` with subtle glow (`drop-shadow(0 0 4px rgba(45, 212, 191, 0.4))`).
  - `.medium`: Solid `--amber`.
  - `.low`: Solid `--crimson`.

### Tags & Chips (`.chip`, `.tag`)
- Compact height (22px), 2px radius, monospace font (`label-sm`).
- Outer border: 1px solid `--hairline`.
- Left-side signal glyph: 6px solid dot denoting status (`--teal` verified, `--brass` historical, `--crimson` anomaly).

### Stratum Cards (`.stratum-card`)
- Rich dark surface (`--panel`) bordered with 1px `--hairline`.
- Upper ledger header: Newsreader display title flanked by a JetBrains Mono docket stamp (`[CASE: #0921-A]`) rendered in `--brass`.
- Interior split: Hairline ruled separator (`--hairline-soft`) bisecting narrative findings and raw cryptographic stack traces.
- Vertical timeline spine on the left edge: 2px wide vertical guide using `--hairline` with status dot nodes positioned over key code milestones.

### Input Fields & Search
- Recessed background (`--ink`), 1px border (`--hairline`), text formatted in `IBM Plex Sans`. Placeholder set in `--text-tertiary`.
- Active/Focus: Border transitions to `--brass` with an interior 1px crisp outline, removing default browser focus rings entirely.

### Checkboxes & Selectors
- Sharp square inputs (16px × 16px) with `--panel-raised` fill and 1px `--hairline` frame.
- Selected state: Filled with `--brass`, carrying a high-contrast `#0d0f12` center checkmark.