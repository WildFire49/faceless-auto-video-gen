/**
 * Client-side providers: MUI theme, Emotion cache and the query client.
 *
 * Separated from layout.tsx so the layout itself can stay a server component.
 */

'use client';

import CssBaseline from '@mui/material/CssBaseline';
import { ThemeProvider } from '@mui/material/styles';
import { AppRouterCacheProvider } from '@mui/material-nextjs/v15-appRouter';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

import { buildTheme } from '@/theme/theme';

// One theme for the lifetime of the app: it carries both colour schemes as CSS
// variables and the browser picks between them, so nothing here depends on
// the viewer's preference -- and the server renders exactly what the client
// will (see theme/theme.ts for the flash this replaced).
const theme = buildTheme();

export function Providers({ children }: { children: ReactNode }) {
  // Created once per mount, not per render: a new QueryClient each render
  // would throw away the cache on every state change.
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 2_000, refetchOnWindowFocus: true },
        },
      }),
  );

  return (
    <AppRouterCacheProvider options={{ key: 'mui' }}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </ThemeProvider>
    </AppRouterCacheProvider>
  );
}
