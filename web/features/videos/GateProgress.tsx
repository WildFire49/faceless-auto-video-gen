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
import Typography from '@mui/material/Typography';

import { VideoStatus, type Video } from '@/lib/gen/rewind/v1/video_pb';
import { GATE_ORDER, attentionColor, gateLabel, gatesPassed } from '@/lib/api/videos';
import { opacity, tint } from '@/theme/colour';
import { radius } from '@/theme/tokens';

type DotState = 'approved' | 'waiting' | 'failed' | 'ahead';

const STATE_TEXT: Record<DotState, string> = {
  approved: 'approved',
  waiting: 'waiting for you',
  failed: 'the step before it failed',
  ahead: 'not reached',
};

function dotState(video: Video, index: number, passed: number): DotState {
  if (index < passed) return 'approved';
  if (index !== passed) return 'ahead';
  if (video.status === VideoStatus.ERROR) return 'failed';
  if (video.awaitingGate === GATE_ORDER[index]) return 'waiting';
  return 'ahead';
}

function dotColour(state: DotState): string {
  switch (state) {
    case 'approved':
      return attentionColor('done');
    case 'waiting':
      return attentionColor('waiting-on-you');
    case 'failed':
      return attentionColor('failed');
    default:
      // A palette path, so it is visible in both schemes.
      return 'action.disabled';
  }
}

/** A one-line reading of the track, for places with room to say it. */
function caption(video: Video, passed: number): string {
  const nextGate = GATE_ORDER[Math.min(passed, GATE_ORDER.length - 1)];
  const next = nextGate === undefined ? '' : gateLabel(nextGate);
  if (video.status === VideoStatus.ERROR) return `Failed before ${next}`;
  if (passed === GATE_ORDER.length) return 'All six gates approved';
  if (video.awaitingGate === GATE_ORDER[passed]) return `Waiting on you at ${next}`;
  return `${passed} of ${GATE_ORDER.length} approved`;
}

export function GateProgress({ video, labelled = false }: { video: Video; labelled?: boolean }) {
  const passed = gatesPassed(video);

  return (
    <Stack direction="row" spacing={1.5} alignItems="center">
      <Stack direction="row" spacing={0.75} alignItems="center" aria-label="Review gate progress">
        {GATE_ORDER.map((gate, index) => {
          const state = dotState(video, index, passed);
          const colour = dotColour(state);
          const emphasised = state === 'waiting' || state === 'failed';

          return (
            <Tooltip key={gate} title={`${gateLabel(gate)} — ${STATE_TEXT[state]}`} arrow>
              <Box
                component="span"
                aria-label={`${gateLabel(gate)}: ${STATE_TEXT[state]}`}
                sx={{
                  width: emphasised ? 10 : 8,
                  height: emphasised ? 10 : 8,
                  borderRadius: radius.pill,
                  backgroundColor: colour,
                  // The gate that needs you gets a halo so the eye lands on it.
                  boxShadow: emphasised ? `0 0 0 3px ${tint(colour, opacity.halo)}` : 'none',
                  transition: 'width 120ms ease, height 120ms ease',
                }}
              />
            </Tooltip>
          );
        })}
      </Stack>
      {labelled ? (
        <Typography variant="body2" color="text.secondary" noWrap>
          {caption(video, passed)}
        </Typography>
      ) : null}
    </Stack>
  );
}
