/**
 * Design tokens. The single source of truth for every colour, radius, type
 * step and elevation in the dashboard (SPEC.md 8.1).
 *
 * No component may write a raw colour, radius or duration. If a value is not
 * here, it does not go in the UI -- that rule is what keeps the Apple feel
 * consistent instead of drifting file by file (SPEC.md 11, "MUI theme drifts").
 *
 * There is no Tailwind and no shadcn/ui in this project. shadcn is built on
 * Tailwind utility classes and cannot be used without it, so the Apple
 * language is expressed through MUI's theme instead (SPEC.md 3.3).
 */

/**
 * Apple's type scale is optical, not merely proportional: larger text gets
 * tighter tracking and shorter leading, so headings feel set rather than
 * scaled up. Values are unitless multipliers where the CSS property allows it.
 */
export const type = {
  display: { size: 34, weight: 700, tracking: '-0.022em', leading: 1.15 },
  title: { size: 22, weight: 600, tracking: '-0.012em', leading: 1.25 },
  heading: { size: 17, weight: 600, tracking: '-0.006em', leading: 1.35 },
  body: { size: 15, weight: 400, tracking: '0em', leading: 1.5 },
  caption: { size: 13, weight: 400, tracking: '0.006em', leading: 1.4 },
  mono: { size: 13, weight: 400, tracking: '0em', leading: 1.45 },
} as const;

/** Corner radii. Larger surfaces take larger radii, as on Apple platforms. */
export const radius = {
  sm: 8,
  md: 12,
  lg: 20,
  pill: 999,
} as const;

/** A 4pt spacing grid. MUI's spacing() is configured to match. */
export const space = {
  unit: 4,
} as const;

/**
 * Semantic colours.
 *
 * `gate` holds the Gate C highlight colours the spec fixes (facts blue, jokes
 * orange, refs green) so they stay identical between the script table, the
 * legend and any future export.
 */
export const palette = {
  light: {
    bg: 'rgb(247 247 250)',
    surface: 'rgba(255, 255, 255, 0.78)',
    surfaceSolid: 'rgb(255 255 255)',
    hairline: 'rgba(0, 0, 0, 0.08)',
    text: 'rgb(17 17 19)',
    textMuted: 'rgba(17, 17, 19, 0.56)',
    accent: 'rgb(10 132 255)',
  },
  dark: {
    bg: 'rgb(16 16 18)',
    surface: 'rgba(32, 32, 36, 0.72)',
    surfaceSolid: 'rgb(28 28 32)',
    hairline: 'rgba(255, 255, 255, 0.10)',
    text: 'rgb(245 245 247)',
    textMuted: 'rgba(245, 245, 247, 0.56)',
    accent: 'rgb(10 132 255)',
  },
  /** Health and gate status colours, shared by both themes. */
  status: {
    ok: 'rgb(48 209 88)',
    degraded: 'rgb(255 159 10)',
    down: 'rgb(255 69 58)',
    unknown: 'rgb(142 142 147)',
  },
  /** Gate C script highlights (SPEC.md 8.2). */
  gate: {
    fact: 'rgb(10 132 255)',
    joke: 'rgb(255 159 10)',
    ref: 'rgb(48 209 88)',
  },
} as const;

/**
 * Depth comes from layered translucency, not heavy drop shadows: a blurred,
 * saturated backdrop over content reads as a material rather than a card
 * floating in space.
 */
export const material = {
  blur: 'saturate(180%) blur(20px)',
  /** Used sparingly, and only for genuinely floating elements. */
  shadow: '0 1px 2px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.06)',
} as const;

export type ThemeMode = keyof Pick<typeof palette, 'light' | 'dark'>;
