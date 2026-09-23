/**
 * The chrome every gate page shares: topic, which gate you are at, progress,
 * and a way back to the queue (SPEC.md 8.1).
 *
 * Extracted at Gate B rather than left duplicated, because gates C–F are
 * coming and the shell is exactly the part that must not drift between them —
 * a reviewer should never have to re-learn where "back" is.
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
import type { ReactNode } from 'react';

import { GateProgress } from '@/features/videos/GateProgress';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { videoClient } from '@/lib/api/client';
import { videoKeys } from '@/lib/api/videos';
import type { Video } from '@/lib/gen/rewind/v1/video_pb';
import { slideIn } from '@/theme/motion';
import { material, palette } from '@/theme/tokens';

export interface GateShellProps {
  videoId: string;
  /** e.g. "Gate B — References". */
  gateLabel: string;
  /** Rendered once the video has loaded, so gates never handle the null case. */
  children: (video: Video) => ReactNode;
}

export function GateShell({ videoId, gateLabel, children }: GateShellProps) {
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
                {gateLabel}
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
          <motion.div {...slideIn(reduced)}>{children(video.data)}</motion.div>
        ) : null}
      </Container>
    </Box>
  );
}
