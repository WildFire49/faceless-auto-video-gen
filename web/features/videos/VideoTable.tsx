/**
 * VideoTable — the queue (SPEC.md 8, "Home").
 *
 * Restraint (SPEC.md 8.1): the only colour in this table marks what needs a
 * human. Everything else is typography and spacing, so the eye goes straight
 * to the row that wants attention.
 */

'use client';

import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';

import { GateProgress } from './GateProgress';
import { Gate, VideoStatus, type Video } from '@/lib/gen/rewind/v1/video_pb';
import {
  attentionColor,
  attentionOf,
  gateLabel,
  humanAge,
  statusLabel,
} from '@/lib/api/videos';
import { palette, radius, type as typeTokens } from '@/theme/tokens';

function WaitingCell({ video }: { video: Video }) {
  const attention = attentionOf(video);

  if (attention === 'failed') {
    return (
      <Tooltip title={video.error || 'The step failed'} arrow>
        <Chip
          size="small"
          label="Failed"
          sx={{
            backgroundColor: `${palette.status.down}18`,
            color: 'text.primary',
            border: `1px solid ${palette.status.down}55`,
          }}
        />
      </Tooltip>
    );
  }

  if (video.awaitingGate !== Gate.UNSPECIFIED) {
    return (
      <Chip
        size="small"
        label={gateLabel(video.awaitingGate)}
        sx={{
          backgroundColor: `${attentionColor('waiting-on-you')}18`,
          color: 'text.primary',
          border: `1px solid ${attentionColor('waiting-on-you')}55`,
        }}
      />
    );
  }

  if (video.status === VideoStatus.UPLOADED_PRIVATE) {
    return (
      <Tooltip title="Review it on YouTube and publish by hand" arrow>
        <Chip size="small" variant="outlined" label="You, on YouTube" />
      </Tooltip>
    );
  }

  return (
    <Typography variant="body2" color="text.secondary">
      —
    </Typography>
  );
}

const columns: GridColDef<Video>[] = [
  {
    field: 'topic',
    headerName: 'Topic',
    flex: 1.4,
    minWidth: 180,
    renderCell: ({ row }) => (
      <Stack justifyContent="center" sx={{ height: '100%' }}>
        <Typography variant="body1" sx={{ fontWeight: 600, lineHeight: 1.3 }}>
          {row.topic}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.3 }}>
          {row.id}
        </Typography>
      </Stack>
    ),
  },
  {
    field: 'status',
    headerName: 'Status',
    flex: 1,
    minWidth: 150,
    renderCell: ({ row }) => (
      <Stack direction="row" spacing={1} alignItems="center" sx={{ height: '100%' }}>
        <Box
          component="span"
          aria-hidden
          sx={{
            width: 8,
            height: 8,
            borderRadius: radius.pill,
            flexShrink: 0,
            backgroundColor: attentionColor(attentionOf(row)),
          }}
        />
        <Typography variant="body2">{statusLabel(row.status)}</Typography>
      </Stack>
    ),
  },
  {
    field: 'awaitingGate',
    headerName: 'Waiting on',
    flex: 0.9,
    minWidth: 150,
    sortable: false,
    renderCell: ({ row }) => (
      <Stack justifyContent="center" sx={{ height: '100%' }}>
        <WaitingCell video={row} />
      </Stack>
    ),
  },
  {
    field: 'gates',
    headerName: 'Gates',
    flex: 0.8,
    minWidth: 120,
    sortable: false,
    renderCell: ({ row }) => (
      <Stack justifyContent="center" sx={{ height: '100%' }}>
        <GateProgress video={row} />
      </Stack>
    ),
  },
  {
    field: 'priority',
    headerName: 'Pri',
    width: 70,
    align: 'center',
    headerAlign: 'center',
  },
  {
    field: 'updatedAt',
    headerName: 'Updated',
    width: 110,
    renderCell: ({ row }) => (
      <Typography variant="body2" color="text.secondary">
        {humanAge(row.updatedAt)}
      </Typography>
    ),
  },
];

export function VideoTable({ videos, loading }: { videos: Video[]; loading: boolean }) {
  return (
    <DataGrid
      rows={videos}
      columns={columns}
      loading={loading}
      getRowId={(row) => row.id}
      rowHeight={64}
      disableRowSelectionOnClick
      disableColumnMenu
      hideFooter={videos.length <= 25}
      initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
      sx={{
        border: 'none',
        // Hairlines rather than heavy rules: the table should read as a list,
        // not a spreadsheet.
        '& .MuiDataGrid-columnHeaders': {
          borderBottom: `1px solid ${palette.light.hairline}`,
        },
        '& .MuiDataGrid-columnHeaderTitle': {
          fontSize: typeTokens.caption.size,
          fontWeight: 600,
          letterSpacing: '0.04em',
          textTransform: 'uppercase',
          color: 'text.secondary',
        },
        '& .MuiDataGrid-cell': {
          borderBottom: `1px solid ${palette.light.hairline}`,
          outline: 'none !important',
        },
        '& .MuiDataGrid-row:hover': {
          backgroundColor: `${palette.light.accent}0A`,
        },
      }}
    />
  );
}
