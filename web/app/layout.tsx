import type { Metadata, Viewport } from 'next';

import { Providers } from './providers';

export const metadata: Metadata = {
  title: 'Rewind Studio',
  description: 'Review dashboard for the Rewind faceless history shorts pipeline.',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  // The theme colour follows the system scheme, so the browser chrome matches
  // the page instead of fighting it.
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: 'rgb(247 247 250)' },
    { media: '(prefers-color-scheme: dark)', color: 'rgb(16 16 18)' },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
