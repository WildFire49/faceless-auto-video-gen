/**
 * GateClosedBar — what a gate page shows when the video is not waiting at it.
 *
 * An approved gate used to look exactly like an open one: the same "Use this"
 * toggles, the same edit and delete buttons, and an Approve button that was
 * merely greyed out. Worse, the API honoured the edits. The API now refuses
 * them (domain.RequireOpenGate); this bar is the page saying so plainly
 * instead of offering controls that would fail.
 *
 * Shared by every gate, so "approved" reads the same on each.
 */

'use client';

import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { GATE_ORDER, attentionColor, gateLabel, gatesPassed, statusLabel } from '@/lib/api/videos';
import type { Gate, Video } from '@/lib/gen/rewind/v1/video_pb';

export interface GateClosedBarProps {
  video: Video;
  gate: Gate;
  /** What was decided, e.g. "3 comparisons went to the script." */
  summary: string;
}

export function GateClosedBar({ video, gate, summary }: GateClosedBarProps) {
  const approved = gatesPassed(video) > GATE_ORDER.indexOf(gate);

  const title = approved
    ? `Gate ${gateLabel(gate)} approved`
    : `Gate ${gateLabel(gate)} is not open`;
  const detail = approved
    ? `${summary} To change it, send the video back from a later gate.`
    : `The video is ${statusLabel(video.status).toLowerCase()}; this gate opens when it arrives here.`;

  return (
    <Paper sx={{ p: 2.5 }}>
      <Stack direction="row" spacing={1.5} alignItems="flex-start">
        <Box
          sx={{
            pt: 0.25,
            color: approved ? attentionColor('done') : 'text.secondary',
          }}
        >
          {approved ? <CheckCircleIcon /> : <InfoOutlinedIcon />}
        </Box>
        <Box>
          <Typography variant="body1" sx={{ fontWeight: 600 }}>
            {title}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {detail}
          </Typography>
        </Box>
      </Stack>
    </Paper>
  );
}
