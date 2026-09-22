import type { NextConfig } from 'next';

const config: NextConfig = {
  reactStrictMode: true,
  // MUI's Emotion styles are compiled ahead of time; this keeps the
  // server-rendered markup and the client tree in agreement.
  modularizeImports: {
    '@mui/icons-material': {
      transform: '@mui/icons-material/{{member}}',
    },
  },
};

export default config;
