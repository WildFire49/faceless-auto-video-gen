/**
 * The MUI theme, built entirely from tokens.ts.
 *
 * This file is the only place tokens are translated into MUI's vocabulary.
 * Components consume the theme; they never import tokens directly for a
 * scheme-dependent colour, so there is exactly one path from a design
 * decision to the screen.
 *
 * ONE theme carrying BOTH colour schemes, emitted as CSS variables and
 * switched by the `prefers-color-scheme` media query. The browser picks the
 * scheme before the first paint, with no JavaScript involved.
 *
 * The previous version chose the scheme in JavaScript (useMediaQuery). The
 * server cannot know the viewer's preference, so it always rendered light,
 * then the client flipped to dark -- a visible flash on every page load. Worse,
 * components reached for `palette.light.*` directly, so in dark mode they drew
 * light-mode colours: the approve bar on every gate was white text on a pale
 * grey panel, unreadable. With CSS variables, a component that names a
 * palette path ('divider', 'surface.translucent') gets the right colour in
 * either scheme without knowing which one is active.
 */

'use client';

import { createTheme, type Theme } from '@mui/material/styles';

import { palette, radius, space, type, type ThemeMode } from './tokens';

declare module '@mui/material/styles' {
  interface Palette {
    /** Translucent panel fill, for sticky bars and headers over content. */
    surface: { translucent: string };
  }
  interface PaletteOptions {
    surface?: { translucent: string };
  }
}

/** The system font stack, so the UI uses SF on Apple platforms and the
 *  platform's own UI face elsewhere rather than shipping a webfont. */
const fontFamily = [
  '-apple-system',
  'BlinkMacSystemFont',
  '"Segoe UI Variable Text"',
  '"Segoe UI"',
  'Roboto',
  '"Helvetica Neue"',
  'Arial',
  'sans-serif',
].join(',');

function schemePalette(mode: ThemeMode) {
  const c = palette[mode];
  return {
    palette: {
      background: { default: c.bg, paper: c.surfaceSolid },
      text: { primary: c.text, secondary: c.textMuted },
      primary: { main: c.accent },
      success: { main: palette.status.ok },
      warning: { main: palette.status.degraded },
      error: { main: palette.status.down },
      divider: c.hairline,
      surface: { translucent: c.surface },
    },
  };
}

export function buildTheme(): Theme {
  return createTheme({
    cssVariables: { colorSchemeSelector: 'media' },
    colorSchemes: {
      light: schemePalette('light'),
      dark: schemePalette('dark'),
    },

    spacing: space.unit,

    shape: { borderRadius: radius.md },

    typography: {
      fontFamily,
      h1: css(type.display),
      h2: css(type.title),
      h3: css(type.heading),
      body1: css(type.body),
      body2: css(type.caption),
      button: { ...css(type.body), textTransform: 'none', fontWeight: 600 },
    },

    components: {
      MuiCssBaseline: {
        styleOverrides: (theme) => ({
          body: {
            backgroundColor: theme.vars?.palette.background.default,
            // Grayscale antialiasing is what makes text on Apple platforms
            // look set rather than smeared.
            WebkitFontSmoothing: 'antialiased',
            MozOsxFontSmoothing: 'grayscale',
          },
        }),
      },

      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: {
          root: {
            borderRadius: radius.pill,
            paddingInline: 18,
            paddingBlock: 8,
          },
        },
      },

      MuiPaper: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: ({ theme }) => ({
            backgroundImage: 'none',
            borderRadius: radius.lg,
            border: `1px solid ${theme.vars?.palette.divider}`,
          }),
        },
      },

      MuiChip: {
        styleOverrides: {
          root: { borderRadius: radius.pill, fontWeight: 600 },
        },
      },

      MuiTooltip: {
        styleOverrides: {
          tooltip: { borderRadius: radius.sm, fontSize: type.caption.size },
        },
      },
    },
  });
}

/** Translate a type token into MUI typography properties. */
function css(t: (typeof type)[keyof typeof type]) {
  return {
    fontSize: t.size,
    fontWeight: t.weight,
    letterSpacing: t.tracking,
    lineHeight: t.leading,
  };
}
