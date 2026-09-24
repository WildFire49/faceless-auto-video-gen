/**
 * StepRunning — what a gate page shows while its pipeline step is working.
 *
 * Gates A and B each carry their own copy of this panel; new gates use this
 * one. (Folding the older copies in is a refactor for a pass that is allowed
 * to touch those pages.)
 */

'use client';

import LinearProgress from '@mui/material/LinearProgress';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import type { Job } from '@/lib/gen/rewind/v1/video_pb';

export function StepRunning({ title, job }: { title: string; job: Job | undefined }) {
  const percent = (job?.percent ?? 0) * 100;
  return (
    <Paper sx={{ p: 5 }}>
      <Stack spacing={3}>
        <Typography variant="h3" component="h2">
          {title}
        </Typography>
        <Typography variant="body1" color="text.secondary">
          {job?.stage || 'starting'}…
        </Typography>
        <LinearProgress
          variant={percent > 0 ? 'determinate' : 'indeterminate'}
          value={percent}
          sx={{ height: 6, borderRadius: 3 }}
        />
      </Stack>
    </Paper>
  );
}
