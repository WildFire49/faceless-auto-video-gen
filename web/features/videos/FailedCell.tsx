/**
 * FailedCell — what a failed row says, and the one thing you can do about it.
 *
 * The row used to show a grey "Failed" pill with the actual reason hidden in a
 * tooltip, and no way to act on it short of the CLI. The reason is the whole
 * point: "ollama returned HTTP 500" and "0 of 172 facts verified" need
 * completely different responses, and you should not have to hover to learn
 * which one you have.
 */

'use client';

import ReplayIcon from '@mui/icons-material/Replay';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';

import { attentionColor, useRetryVideo } from '@/lib/api/videos';
import type { Video } from '@/lib/gen/rewind/v1/video_pb';

/**
 * The part of an error a person reads. Errors arrive wrapped by every layer
 * they crossed -- "research: DEPENDENCY_UNAVAILABLE: ollama returned HTTP 500"
 * -- and in a narrow cell only the wrapping would show. Drop the leading step
 * name and SHOUTING_CODE prefixes; the full text stays in the tooltip.
 */
function headline(error: string): string {
  let text = error.split('\n')[0]?.trim() ?? '';
  const prefix = /^([a-z_]+|[A-Z][A-Z_]+):\s+/;
  while (prefix.test(text)) text = text.replace(prefix, '');
  return text || 'The step failed';
}

export function FailedCell({ video }: { video: Video }) {
  const retry = useRetryVideo();

  return (
    <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0, width: '100%' }}>
      <Tooltip title={video.error || 'The step failed'} arrow>
        <Typography
          variant="body2"
          noWrap
          sx={{ flex: 1, minWidth: 0, color: attentionColor('failed') }}
        >
          {headline(video.error)}
        </Typography>
      </Tooltip>
      <Button
        size="small"
        variant="outlined"
        startIcon={<ReplayIcon fontSize="small" />}
        disabled={retry.isPending}
        onClick={(event) => {
          // The row itself is clickable; retrying must not also navigate.
          event.stopPropagation();
          retry.mutate(video.id);
        }}
        sx={{ flexShrink: 0, py: 0.25 }}
      >
        {retry.isPending ? 'Retrying…' : 'Retry'}
      </Button>
    </Stack>
  );
}
