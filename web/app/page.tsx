/**
 * Home — the video queue (SPEC.md 8).
 *
 * The queue table, a "needs my review" filter, and adding a topic. A row
 * opens the gate waiting for you, or the last one you approved.
 */

'use client';

import AddIcon from '@mui/icons-material/Add';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Container from '@mui/material/Container';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import Typography from '@mui/material/Typography';
import * as motion from 'motion/react-client';
import { useState } from 'react';

import { AddVideoDialog } from '@/features/videos/AddVideoDialog';
import { VideoTable } from '@/features/videos/VideoTable';
import { StatusChip } from '@/components/ui/StatusChip';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { useSystemHealth } from '@/lib/api/queries';
import { useVideos } from '@/lib/api/videos';
import { HealthStatus } from '@/lib/gen/rewind/v1/health_pb';
import { slideIn } from '@/theme/motion';
import { material } from '@/theme/tokens';
import { schemeColour } from '@/theme/colour';

function healthLabel(status: HealthStatus): string {
  switch (status) {
    case HealthStatus.OK:
      return 'healthy';
    case HealthStatus.DEGRADED:
      return 'degraded';
    case HealthStatus.DOWN:
      return 'unreachable';
    default:
      return 'unknown';
  }
}

export default function HomePage() {
  const reduced = useReducedMotion();
  const [needsReviewOnly, setNeedsReviewOnly] = useState(false);
  const [addOpen, setAddOpen] = useState(false);

  const health = useSystemHealth();
  const videos = useVideos(needsReviewOnly);

  const aiStatus = health.data?.ai?.status ?? HealthStatus.UNSPECIFIED;
  const apiUnreachable = health.isError;

  return (
    <Box component="main" sx={{ minHeight: '100dvh', bgcolor: 'background.default' }}>
      {/* Sticky translucent header: depth from a blurred material over the
          content plus a hairline, never a drop shadow (SPEC.md 8.1). */}
      <Box
        component="header"
        sx={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          backgroundColor: 'surface.translucent',
          backdropFilter: material.blur,
          WebkitBackdropFilter: material.blur,
          borderBottom: `1px solid ${schemeColour.hairline}`,
        }}
      >
        <Container maxWidth="lg">
          <Stack
            direction="row"
            alignItems="center"
            justifyContent="space-between"
            sx={{ py: 3, gap: 2, flexWrap: 'wrap' }}
          >
            <Typography variant="h3" component="h1">
              Rewind Studio
            </Typography>

            <Stack direction="row" spacing={2} alignItems="center">
              <StatusChip
                status={apiUnreachable ? HealthStatus.DOWN : aiStatus}
                label={apiUnreachable ? 'API unreachable' : `AI service ${healthLabel(aiStatus)}`}
                detail={
                  apiUnreachable ? health.error?.message : health.data?.ai?.detail || undefined
                }
                loading={health.isLoading}
              />
              <Button variant="contained" startIcon={<AddIcon />} onClick={() => setAddOpen(true)}>
                Queue a topic
              </Button>
            </Stack>
          </Stack>
        </Container>
      </Box>

      <Container maxWidth="lg" sx={{ py: 5 }}>
        <motion.div {...slideIn(reduced)}>
          <Stack spacing={3}>
            <Tabs
              value={needsReviewOnly ? 1 : 0}
              onChange={(_, v) => setNeedsReviewOnly(v === 1)}
              sx={{ minHeight: 0, '& .MuiTab-root': { minHeight: 0, py: 1.5 } }}
            >
              <Tab label="All videos" />
              <Tab label="Needs my review" />
            </Tabs>

            <Paper sx={{ overflow: 'hidden' }}>
              {videos.isError ? (
                <EmptyState
                  title="Cannot reach the API"
                  body={`${videos.error.message}. Start it with \`task dev\`.`}
                />
              ) : videos.data && videos.data.length === 0 ? (
                <EmptyState
                  title={needsReviewOnly ? 'Nothing needs you right now' : 'The queue is empty'}
                  body={
                    needsReviewOnly
                      ? 'Videos appear here the moment they reach a review gate.'
                      : 'Queue an everyday object — iron, computer mouse, sandals — and the pipeline traces its history.'
                  }
                />
              ) : (
                <Box sx={{ height: 'min(70vh, 640px)' }}>
                  <VideoTable videos={videos.data ?? []} loading={videos.isLoading} />
                </Box>
              )}
            </Paper>

          </Stack>
        </motion.div>
      </Container>

      <AddVideoDialog open={addOpen} onClose={() => setAddOpen(false)} />
    </Box>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <Stack spacing={1} alignItems="center" sx={{ py: 10, px: 4, textAlign: 'center' }}>
      <Typography variant="h3" component="p">
        {title}
      </Typography>
      <Typography variant="body1" color="text.secondary" sx={{ maxWidth: '46ch' }}>
        {body}
      </Typography>
    </Stack>
  );
}
