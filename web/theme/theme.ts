/**
 * The MUI theme, built entirely from tokens.ts.
 *
 * This file is the only place tokens are translated into MUI's vocabulary.
 * Components consume the theme; they never import tokens directly for colour
 * or radius, so there is exactly one path from a design decision to the screen.
 */

'use client';

import { createTheme, type Theme } from '@mui/material/styles';

import { material, palette, radius, space, type, type ThemeMode } from './tokens';

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

export function buildTheme(mode: ThemeMode): Theme {
  const c = palette[mode];

  return createTheme({
    palette: {
      mode,
      background: { default: c.bg, paper: c.surfaceSolid },
      text: { primary: c.text, secondary: c.textMuted },
      primary: { main: c.accent },
      success: { main: palette.status.ok },
      warning: { main: palette.status.degraded },
      error: { main: palette.status.down },
      divider: c.hairline,
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
        styleOverrides: {
          body: {
            backgroundColor: c.bg,
            // Grayscale antialiasing is what makes text on Apple platforms
            // look set rather than smeared.
            WebkitFontSmoothing: 'antialiased',
            MozOsxFontSmoothing: 'grayscale',
          },
        },
      },

      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: {
          root: { borderRadius: radius.pill, paddingInline: 18, paddingBlock: 8 },
        },
      },

      MuiPaper: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: {
            backgroundImage: 'none',
            borderRadius: radius.lg,
            border: `1px solid ${c.hairline}`,
          },
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

/** Surface styling for translucent panels; used via the `sx` prop. */
export const surfaceSx = (mode: ThemeMode) => ({
  backgroundColor: palette[mode].surface,
  backdropFilter: material.blur,
  WebkitBackdropFilter: material.blur,
  border: `1px solid ${palette[mode].hairline}`,
  borderRadius: `${radius.lg}px`,
});
