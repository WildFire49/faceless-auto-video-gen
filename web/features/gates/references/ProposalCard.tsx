/**
 * ProposalCard — one suggested comparison at Gate B (SPEC.md 8.2).
 *
 * Cards rather than a table, because the unit of judgement here is a joke: you
 * read it, decide whether it lands, and move on. A row in a grid invites
 * scanning; a card invites reading, which is what this gate actually needs.
 */

'use client';

import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked';
import ScheduleIcon from '@mui/icons-material/Schedule';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';

import { ReferenceKind, type Proposal } from '@/lib/gen/rewind/v1/relevance_pb';
import { palette, radius } from '@/theme/tokens';

export interface ProposalCardProps {
  proposal: Proposal;
  /** The fact this comparison attaches to, for context. */
  factLabel?: string;
  factClaim?: string;
  stale: boolean;
  /** False when the selection limit is reached and this one is not selected. */
  selectable: boolean;
  onToggle: (selected: boolean) => void;
  onEdit: () => void;
  onDelete: () => void;
  busy?: boolean;
}

function kindChip(kind: ReferenceKind, freshUntil: string, stale: boolean) {
  if (kind === ReferenceKind.HOT) {
    return {
      label: stale ? `expired ${freshUntil}` : `hot · fresh until ${freshUntil}`,
      color: stale ? palette.status.down : palette.status.degraded,
      icon: <ScheduleIcon sx={{ fontSize: 14 }} />,
    };
  }
  if (kind === ReferenceKind.MANUAL) {
    return { label: 'yours', color: palette.light.accent, icon: undefined };
  }
  return { label: 'evergreen', color: palette.status.ok, icon: undefined };
}

export function ProposalCard({
  proposal,
  factLabel,
  factClaim,
  stale,
  selectable,
  onToggle,
  onEdit,
  onDelete,
  busy = false,
}: ProposalCardProps) {
  const selected = proposal.selected;
  const chip = kindChip(proposal.kind, proposal.freshUntil, stale);

  // Unselectable cards are dimmed rather than hidden: knowing what you passed
  // over is part of judging what you kept.
  const disabled = !selected && !selectable;

  return (
    <Paper
      sx={{
        p: 3,
        opacity: disabled ? 0.55 : 1,
        borderColor: selected ? `${palette.light.accent}66` : palette.light.hairline,
        backgroundColor: selected ? `${palette.light.accent}0A` : 'transparent',
        transition: 'opacity 160ms ease, background-color 160ms ease',
      }}
    >
      <Stack spacing={2}>
        <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap">
          <Typography variant="body1" sx={{ fontWeight: 700 }}>
            {proposal.reference}
          </Typography>

          <Chip
            size="small"
            icon={chip.icon}
            label={chip.label}
            sx={{
              backgroundColor: `${chip.color}18`,
              border: `1px solid ${chip.color}55`,
            }}
          />

          <Box sx={{ flex: 1 }} />

          <Tooltip title="Edit the wording">
            <span>
              <IconButton size="small" onClick={onEdit} disabled={busy}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Remove this comparison">
            <span>
              <IconButton size="small" onClick={onDelete} disabled={busy}>
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
        </Stack>

        {/* The line itself, set larger than everything else: it is the thing
            being judged. */}
        <Typography variant="h3" component="p" sx={{ lineHeight: 1.35 }}>
          “{proposal.comparison}”
        </Typography>

        {proposal.whyFunny ? (
          <Typography variant="body2" color="text.secondary">
            {proposal.whyFunny}
          </Typography>
        ) : null}

        {/* What the comparison attaches to. Shown because a joke that does not
            belong to its fact is the failure mode worth catching here. */}
        {factClaim ? (
          <Box sx={{ borderLeft: `2px solid ${palette.light.hairline}`, pl: 2, py: 0.5 }}>
            <Typography variant="body2" color="text.secondary">
              <Box component="span" sx={{ fontWeight: 600 }}>
                {factLabel}
              </Box>{' '}
              — {factClaim}
            </Typography>
          </Box>
        ) : null}

        <Stack direction="row" spacing={2} alignItems="center">
          <Button
            variant={selected ? 'contained' : 'outlined'}
            startIcon={selected ? <CheckCircleIcon /> : <RadioButtonUncheckedIcon />}
            onClick={() => onToggle(!selected)}
            disabled={busy || disabled}
            sx={{ borderRadius: radius.pill }}
          >
            {selected ? 'Using this' : 'Use this'}
          </Button>

          {proposal.accuracyNote ? (
            <Tooltip title="What is being compared — check it is not a claim about the brand">
              <Typography variant="body2" color="text.secondary" sx={{ cursor: 'help' }}>
                {proposal.accuracyNote}
              </Typography>
            </Tooltip>
          ) : null}
        </Stack>
      </Stack>
    </Paper>
  );
}
