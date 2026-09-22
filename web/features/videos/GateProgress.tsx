/**
 * GateProgress — six dots showing how far a video has travelled through the
 * review gates, and which one it is waiting at.
 *
 * Spatial consistency (SPEC.md 8.1): gates always read left to right, so the
 * same video always occupies the same position on this track no matter which
 * screen it appears on.
 */

'use client';

import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';

import { Gate, type Video } from '@/lib/gen/rewind/v1/video_pb';
import { GATE_ORDER, attentionColor, gateLabel } from '@/lib/api/videos';
import { palette, radius } from '@/theme/tokens';

/** How many gates a video has already passed, derived from its status. */
function gatesPassed(video: Video): number {
  // The wire enum is ordered along the pipeline, so a status number above a
  // gate's approval status means that gate is behind us. Deriving it from the
  // ordering keeps this in step with the state machine automatically.
  const passedThresholds = [4, 7, 10, 13, 16, 19]; // *_APPROVED statuses
  return passedThresholds.filter((threshold) => video.status >= threshold).length;
}

export function GateProgress({ video }: { video: Video }) {
  const passed = gatesPassed(video);

  return (
    <Stack direction="row" spacing={0.75} alignItems="center" aria-label="Review gate progress">
      {GATE_ORDER.map((gate, index) => {
        const isDone = index < passed;
        const isWaiting = video.awaitingGate === gate;

        let color: string = palette.light.hairline;
        if (isDone) color = palette.status.ok;
        if (isWaiting) color = attentionColor('waiting-on-you');

        const state = isWaiting ? 'waiting for you' : isDone ? 'approved' : 'not reached';

        return (
          <Tooltip key={gate} title={`${gateLabel(gate)} — ${state}`} arrow>
            <Box
              component="span"
              aria-label={`${gateLabel(gate)}: ${state}`}
              sx={{
                width: isWaiting ? 10 : 8,
                height: isWaiting ? 10 : 8,
                borderRadius: radius.pill,
                backgroundColor: color,
                // The waiting gate gets a halo so the eye lands on it first.
                boxShadow: isWaiting ? `0 0 0 3px ${color}33` : 'none',
                transition: 'width 120ms ease, height 120ms ease',
              }}
            />
          </Tooltip>
        );
      })}
    </Stack>
  );
}

export { Gate };
