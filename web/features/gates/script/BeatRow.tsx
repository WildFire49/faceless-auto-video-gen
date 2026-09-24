/**
 * BeatRow — one beat of the script at Gate C (SPEC.md 8.2).
 *
 * The narration is coloured by what each sentence IS (see highlight.ts), and
 * hovering a fact sentence shows the approved fact and its source. A rule the
 * beat breaks is shown on the beat itself, in words, so the reviewer fixes it
 * where it is rather than hunting for it.
 */

'use client';

import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';

import { highlightBeat, type Segment, type SegmentKind } from './highlight';
import type { Fact } from '@/lib/gen/rewind/v1/research_pb';
import type { Proposal } from '@/lib/gen/rewind/v1/relevance_pb';
import type { Beat, Violation } from '@/lib/gen/rewind/v1/script_pb';
import { opacity, tint } from '@/theme/colour';
import { palette, radius } from '@/theme/tokens';

/** The one place a segment kind becomes a colour. */
export const KIND_COLOUR: Record<Exclude<SegmentKind, 'plain'>, string> = {
  fact: palette.gate.fact,
  joke: palette.gate.joke,
  ref: palette.gate.ref,
};

export interface BeatRowProps {
  beat: Beat;
  /** Approved facts this beat cites. */
  facts: Fact[];
  /** Selected comparisons this beat uses. */
  refs: Proposal[];
  violations: Violation[];
  readOnly: boolean;
  onEdit: () => void;
}

function SegmentText({ segment }: { segment: Segment }) {
  if (segment.kind === 'plain') return <>{segment.text} </>;

  const colour = KIND_COLOUR[segment.kind];
  const span = (
    <Box
      component="span"
      sx={{
        backgroundColor: tint(colour, opacity.fill),
        borderBottom: `2px solid ${tint(colour, opacity.selected)}`,
        borderRadius: `${radius.sm / 2}px`,
        px: 0.25,
        cursor: segment.kind === 'fact' ? 'help' : 'default',
      }}
    >
      {segment.text}
    </Box>
  );

  if (segment.kind !== 'fact') return <>{span} </>;

  return (
    <>
      <Tooltip
        arrow
        title={
          <Stack spacing={1} sx={{ p: 0.5 }}>
            {segment.facts.map((fact) => (
              <Box key={fact.id}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {fact.id} · {fact.label}
                </Typography>
                <Typography variant="body2">{fact.claim}</Typography>
                {fact.sourceUrl ? (
                  <Link href={fact.sourceUrl} target="_blank" rel="noopener noreferrer" color="inherit">
                    {fact.sourceTitle || fact.sourceUrl}
                  </Link>
                ) : null}
              </Box>
            ))}
          </Stack>
        }
      >
        {span}
      </Tooltip>{' '}
    </>
  );
}

export function BeatRow({ beat, facts, refs, violations, readOnly, onEdit }: BeatRowProps) {
  const segments = highlightBeat(beat.voice, facts, refs);
  const broken = violations.length > 0;

  return (
    <Stack
      direction="row"
      spacing={2}
      sx={{
        p: 2.5,
        alignItems: 'flex-start',
        backgroundColor: broken ? tint(palette.status.down, opacity.wash) : 'transparent',
      }}
    >
      <Stack spacing={0.75} alignItems="center" sx={{ width: 64, flexShrink: 0 }}>
        <Typography variant="h3" component="span" sx={{ fontVariantNumeric: 'tabular-nums' }}>
          {beat.n}
        </Typography>
        <Chip size="small" label={beat.role} variant="outlined" />
      </Stack>

      <Stack spacing={1} sx={{ flex: 1, minWidth: 0 }}>
        {beat.yearStamp ? (
          <Typography variant="body2" sx={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
            {beat.yearStamp}
          </Typography>
        ) : null}

        <Typography variant="body1" sx={{ lineHeight: 1.7 }}>
          {segments.map((segment, i) => (
            <SegmentText key={i} segment={segment} />
          ))}
        </Typography>

        {beat.onScreenText ? (
          <Typography variant="body2" color="text.secondary">
            On screen: <strong>{beat.onScreenText}</strong>
          </Typography>
        ) : null}

        {broken ? (
          <Stack spacing={0.5}>
            {violations.map((v) => (
              <Stack key={v.rule + v.message} direction="row" spacing={0.75} alignItems="flex-start">
                <ErrorOutlineIcon sx={{ fontSize: 16, mt: 0.25, color: palette.status.down }} />
                <Typography variant="body2" sx={{ color: palette.status.down }}>
                  {v.message}
                </Typography>
              </Stack>
            ))}
          </Stack>
        ) : null}

        <Typography variant="body2" color="text.secondary">
          {beat.factIds.length > 0 ? `Cites ${beat.factIds.join(', ')}` : 'Cites no fact'}
          {beat.sfx ? ` · sound: ${beat.sfx}` : ''}
        </Typography>
      </Stack>

      {readOnly ? null : (
        <Tooltip title="Edit what this beat says">
          <IconButton onClick={onEdit} aria-label={`Edit beat ${beat.n}`} sx={{ mt: -0.5 }}>
            <EditOutlinedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      )}
    </Stack>
  );
}
