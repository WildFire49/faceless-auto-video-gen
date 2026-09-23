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
import { useRouter } from 'next/navigation';

import { FailedCell } from './FailedCell';
import { GateProgress } from './GateProgress';
import { Gate, VideoStatus, type Video } from '@/lib/gen/rewind/v1/video_pb';
import {
  attentionColor,
  attentionOf,
  gateLabel,
  humanAge,
  reviewRouteOf,
  statusLabel,
} from '@/lib/api/videos';
import { radius, type as typeTokens } from '@/theme/tokens';
import { opacity, schemeColour, tint } from '@/theme/colour';

function WaitingCell({ video }: { video: Video }) {
  const attention = attentionOf(video);

  if (attention === 'failed') return <FailedCell video={video} />;

  if (video.awaitingGate !== Gate.UNSPECIFIED) {
    return (
      <Chip
        size="small"
        label={gateLabel(video.awaitingGate)}
        sx={{
          backgroundColor: tint(attentionColor('waiting-on-you'), opacity.fill),
          color: 'text.primary',
          border: `1px solid ${tint(attentionColor('waiting-on-you'), opacity.outline)}`,
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
    flex: 1.3,
    minWidth: 220,
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
      <Stack justifyContent="center" sx={{ height: '100%' }}>
        <Typography variant="body2" color="text.secondary">
          {humanAge(row.updatedAt)}
        </Typography>
      </Stack>
    ),
  },
];

export function VideoTable({ videos, loading }: { videos: Video[]; loading: boolean }) {
  const router = useRouter();

  return (
    <DataGrid
      rows={videos}
      columns={columns}
      loading={loading}
      getRowId={(row) => row.id}
      rowHeight={64}
      disableRowSelectionOnClick
      disableColumnMenu
      onRowClick={(params) => {
        // The gate waiting for you, or else the last gate you approved, so a
        // past decision can be looked at again. Nothing for rows with no
        // built page yet, rather than a 404.
        const route = reviewRouteOf(params.row as Video);
        if (route) router.push(route);
      }}
      hideFooter={videos.length <= 25}
      initialState={{
        pagination: { paginationModel: { pageSize: 25 } },
        // Most recently touched first: the video you just worked on, or the
        // one that just finished a step, is the one you are looking for.
        // RFC 3339 timestamps in one zone sort correctly as strings.
        sorting: { sortModel: [{ field: 'updatedAt', sort: 'desc' }] },
      }}
      sx={{
        border: 'none',
        // Hairlines rather than heavy rules: the table should read as a list,
        // not a spreadsheet.
        '& .MuiDataGrid-columnHeaders': {
          borderBottom: `1px solid ${schemeColour.hairline}`,
        },
        '& .MuiDataGrid-columnHeaderTitle': {
          fontSize: typeTokens.caption.size,
          fontWeight: 600,
          letterSpacing: '0.04em',
          textTransform: 'uppercase',
          color: 'text.secondary',
        },
        '& .MuiDataGrid-cell': {
          borderBottom: `1px solid ${schemeColour.hairline}`,
          outline: 'none !important',
        },
        '& .MuiDataGrid-row:hover': {
          backgroundColor: tint(schemeColour.accent, opacity.wash),
        },
        '& .MuiDataGrid-row': { cursor: 'pointer' },
      }}
    />
  );
}
