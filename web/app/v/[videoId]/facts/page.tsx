/**
 * Gate A route: /v/<videoId>/facts
 *
 * Wraps the gate in the shared shell so every gate page from here on has the
 * same chrome: topic, gate progress, and a way back to the queue.
 */

'use client';

import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Container from '@mui/material/Container';
import IconButton from '@mui/material/IconButton';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { useQuery } from '@tanstack/react-query';
import * as motion from 'motion/react-client';
import Link from 'next/link';
import { use } from 'react';

import { FactsGate } from '@/features/gates/facts/FactsGate';
import { GateProgress } from '@/features/videos/GateProgress';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { videoClient } from '@/lib/api/client';
import { videoKeys } from '@/lib/api/videos';
import { slideIn } from '@/theme/motion';
import { material, palette } from '@/theme/tokens';

export default function FactsPage({ params }: { params: Promise<{ videoId: string }> }) {
  const { videoId } = use(params);
  const reduced = useReducedMotion();

  const video = useQuery({
    queryKey: videoKeys.detail(videoId),
    queryFn: async () => (await videoClient.getVideo({ videoId })).video,
  });

  return (
    <Box component="main" sx={{ minHeight: '100dvh', bgcolor: 'background.default' }}>
      <Box
        component="header"
        sx={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          backdropFilter: material.blur,
          WebkitBackdropFilter: material.blur,
          borderBottom: `1px solid ${palette.light.hairline}`,
        }}
      >
        <Container maxWidth="md">
          <Stack direction="row" alignItems="center" sx={{ py: 2.5, gap: 2 }}>
            <IconButton component={Link} href="/" aria-label="Back to the queue">
              <ArrowBackIcon />
            </IconButton>

            <Stack sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="h3" component="h1" noWrap>
                {video.data?.topic ?? videoId}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Gate A — Facts
              </Typography>
            </Stack>

            {video.data ? <GateProgress video={video.data} /> : null}
          </Stack>
        </Container>
      </Box>

      <Container maxWidth="md" sx={{ py: 4 }}>
        {video.isLoading ? <LinearProgress /> : null}
        {video.isError ? <Alert severity="error">{video.error.message}</Alert> : null}
        {video.data ? (
          <motion.div {...slideIn(reduced)}>
            <FactsGate video={video.data} />
          </motion.div>
        ) : null}
      </Container>
    </Box>
  );
}
