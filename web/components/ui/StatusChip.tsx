/**
 * StatusChip -- a themed primitive for health and gate status.
 *
 * LAYER 2 (primitive) of SPEC.md 14.1: dumb, reusable, no data fetching. It
 * takes a status and renders it; it does not know where the status came from.
 */

'use client';

import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Tooltip from '@mui/material/Tooltip';

import { HealthStatus } from '@/lib/gen/rewind/v1/health_pb';
import { palette, radius } from '@/theme/tokens';

export interface StatusChipProps {
  status: HealthStatus;
  label: string;
  /** Shown on hover. Use it for the failure reason, never for a secret. */
  detail?: string;
  /** Suppresses the pulse while a request is in flight. */
  loading?: boolean;
}

/** Status -> colour token. One mapping, used everywhere a status is shown. */
function colorFor(status: HealthStatus): string {
  switch (status) {
    case HealthStatus.OK:
      return palette.status.ok;
    case HealthStatus.DEGRADED:
      return palette.status.degraded;
    case HealthStatus.DOWN:
      return palette.status.down;
    default:
      return palette.status.unknown;
  }
}

export function StatusChip({ status, label, detail, loading = false }: StatusChipProps) {
  const color = colorFor(status);

  const chip = (
    <Chip
      variant="outlined"
      label={label}
      aria-live="polite"
      icon={
        <Box
          component="span"
          aria-hidden
          sx={{
            width: 8,
            height: 8,
            borderRadius: radius.pill,
            backgroundColor: color,
            // A soft halo rather than a hard dot; reads as a light, not a
            // sticker.
            boxShadow: `0 0 0 3px ${color}22`,
            opacity: loading ? 0.5 : 1,
            transition: 'opacity 120ms ease',
            ml: 1.5,
          }}
        />
      }
      sx={{
        borderColor: `${color}55`,
        color: 'text.primary',
        backgroundColor: `${color}12`,
        fontWeight: 600,
      }}
    />
  );

  return detail ? (
    <Tooltip title={detail} arrow placement="top">
      {/* Tooltip needs a focusable wrapper to work for keyboard users. */}
      <Box component="span" tabIndex={0} sx={{ display: 'inline-flex' }}>
        {chip}
      </Box>
    </Tooltip>
  ) : (
    chip
  );
}
