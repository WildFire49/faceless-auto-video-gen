/**
 * FactRow — one fact at Gate A.
 *
 * The design job here is making the SOURCE as prominent as the claim. The
 * whole project rests on every fact being traceable (SPEC.md 5.2), so the
 * evidence sentence and its link are first-class content, not a tooltip you
 * have to go looking for.
 */

'use client';

import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';

import type { Fact } from '@/lib/gen/rewind/v1/research_pb';
import { palette, radius } from '@/theme/tokens';

export interface FactRowProps {
  fact: Fact;
  onToggle: (approved: boolean) => void;
  onEdit: () => void;
  onDelete: () => void;
  busy?: boolean;
}

/** Confidence comes from how closely the evidence matched its source. */
function confidenceColor(confidence: string): string {
  switch (confidence) {
    case 'high':
      return palette.status.ok;
    case 'medium':
      return palette.status.degraded;
    default:
      return palette.status.unknown;
  }
}

export function FactRow({ fact, onToggle, onEdit, onDelete, busy = false }: FactRowProps) {
  const approved = fact.approved;

  return (
    <Stack
      direction="row"
      spacing={2}
      sx={{
        p: 2.5,
        alignItems: 'flex-start',
        // Approved facts get a quiet tint rather than a loud one: at eight-plus
        // rows, a saturated background would be exhausting to read.
        backgroundColor: approved ? `${palette.status.ok}0A` : 'transparent',
        transition: 'background-color 160ms ease',
      }}
    >
      <Tooltip title={approved ? 'Approved — click to untick' : 'Click to approve this fact'}>
        <span>
          <IconButton
            onClick={() => onToggle(!approved)}
            disabled={busy}
            aria-label={approved ? `Unapprove fact ${fact.id}` : `Approve fact ${fact.id}`}
            sx={{ color: approved ? palette.status.ok : 'text.secondary', mt: -0.5 }}
          >
            {approved ? <CheckCircleIcon /> : <RadioButtonUncheckedIcon />}
          </IconButton>
        </span>
      </Tooltip>

      <Stack spacing={1} sx={{ flex: 1, minWidth: 0 }}>
        <Stack direction="row" spacing={1.5} alignItems="baseline" flexWrap="wrap">
          <Typography
            variant="body1"
            sx={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}
          >
            {fact.yearLabel}
          </Typography>
          {fact.place ? (
            <Typography variant="body2" color="text.secondary">
              {fact.place}
            </Typography>
          ) : null}

          <Box sx={{ flex: 1 }} />

          {fact.conflict ? (
            <Tooltip title="Sources disagree about this date — worth checking before approving">
              <Chip
                size="small"
                icon={<WarningAmberIcon />}
                label="conflict"
                sx={{
                  backgroundColor: `${palette.status.degraded}18`,
                  border: `1px solid ${palette.status.degraded}55`,
                }}
              />
            </Tooltip>
          ) : null}

          <Tooltip
            title={`Evidence matched its source at ${(fact.matchScore * 100).toFixed(1)}%`}
          >
            <Chip
              size="small"
              label={fact.confidence}
              sx={{
                backgroundColor: `${confidenceColor(fact.confidence)}18`,
                border: `1px solid ${confidenceColor(fact.confidence)}55`,
              }}
            />
          </Tooltip>
        </Stack>

        <Typography variant="body1">{fact.claim}</Typography>

        {/* The evidence: the exact sentence from the source. Set apart with a
            rule and a slightly recessive colour so it reads as a quotation
            rather than as the narrator's words. */}
        <Box
          sx={{
            borderLeft: `2px solid ${palette.light.hairline}`,
            pl: 2,
            py: 0.5,
          }}
        >
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ fontStyle: 'italic', lineHeight: 1.55 }}
          >
            “{fact.evidence}”
          </Typography>
        </Box>

        <Stack direction="row" spacing={1} alignItems="center">
          <Link
            href={fact.sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            variant="body2"
            sx={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 0.5,
              borderRadius: `${radius.sm}px`,
            }}
          >
            {fact.sourceTitle || fact.sourceUrl}
            <OpenInNewIcon sx={{ fontSize: 14 }} />
          </Link>
        </Stack>
      </Stack>

      <Stack direction="row" spacing={0.5} sx={{ mt: -0.5 }}>
        <Tooltip title="Edit the year, place or claim">
          <span>
            <IconButton onClick={onEdit} disabled={busy} aria-label={`Edit fact ${fact.id}`}>
              <EditOutlinedIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title="Remove this fact">
          <span>
            <IconButton onClick={onDelete} disabled={busy} aria-label={`Delete fact ${fact.id}`}>
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
      </Stack>
    </Stack>
  );
}
