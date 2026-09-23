/**
 * Colour expressions that are correct in BOTH colour schemes.
 *
 * Components used to add transparency by appending a hex pair to a colour:
 * `${palette.status.ok}18`. Our tokens are `rgb(48 209 88)`, so that produced
 * `rgb(48 209 88)18` -- not valid CSS. Browsers drop an invalid declaration
 * without a word, so for three milestones every tinted chip, the approved-row
 * highlight, the red "Failed" badge and the waiting-gate halo simply never
 * rendered. Nothing failed; they were just absent.
 *
 * `tint` uses color-mix, which accepts any CSS colour -- an rgb() token or a
 * theme CSS variable alike -- so the same call works for a fixed status
 * colour and for a scheme-dependent accent.
 */

/** `color` at `opacity` (0..1) over transparent. */
export function tint(color: string, opacity: number): string {
  const percent = Math.round(Math.min(1, Math.max(0, opacity)) * 100);
  return `color-mix(in srgb, ${color} ${percent}%, transparent)`;
}

/**
 * Scheme-dependent colours as CSS variables, for the few places that need a
 * colour as a STRING (inside a border shorthand, a box-shadow, or `tint`)
 * rather than as an sx palette path. Kept here so nothing else spells out
 * MUI's variable names.
 */
export const schemeColour = {
  accent: 'var(--mui-palette-primary-main)',
  hairline: 'var(--mui-palette-divider)',
} as const;

/** Opacities, named so the same tint means the same thing everywhere. */
export const opacity = {
  /** A barely-there wash behind a selected or approved row. */
  wash: 0.06,
  /** Chip and badge fills. */
  fill: 0.14,
  /** Chip and badge outlines. */
  outline: 0.34,
  /** The halo around the gate waiting for you. */
  halo: 0.25,
  /** The border of a selected card. */
  selected: 0.45,
} as const;
