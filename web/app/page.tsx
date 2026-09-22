/**
 * Home.
 *
 * In M0 this page exists to prove one thing: the whole spine works.
 * The chip below is fetched Next.js -> Go (Connect/JSON) -> Python (gRPC) and
 * back. When it is green, all three services and the generated contract are
 * talking to each other (SPEC.md 9, M0).
 *
 * M1 replaces the placeholder below with the video queue.
 */

'use client';

import Box from '@mui/material/Box';
import Container from '@mui/material/Container';
import Divider from '@mui/material/Divider';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import * as motion from 'motion/react-client';

import { StatusChip } from '@/components/ui/StatusChip';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { useSystemHealth } from '@/lib/api/queries';
import { type ComponentHealth } from '@/lib/gen/rewind/v1/api_pb';
import { HealthStatus } from '@/lib/gen/rewind/v1/health_pb';
import { slideIn } from '@/theme/motion';
import { material, palette } from '@/theme/tokens';

/** Wire enum -> human label. The UI never shows a raw enum name. */
function statusLabel(status: HealthStatus): string {
  switch (status) {
    case HealthStatus.OK:
      return 'healthy';
    case HealthStatus.DEGRADED:
      return 'degraded';
    case HealthStatus.DOWN:
      return 'unreachable';
    default:
      return 'unknown';
  }
}

export default function HomePage() {
  const reduced = useReducedMotion();
  const { data, isLoading, error } = useSystemHealth();

  // A stopped Go API is an expected state while developing, so it renders as
  // DOWN rather than as a crash (SPEC.md 8.3).
  const api: Partial<ComponentHealth> = data?.api ?? {
    status: error ? HealthStatus.DOWN : HealthStatus.UNSPECIFIED,
    detail: error?.message ?? '',
  };
  const ai: Partial<ComponentHealth> = data?.ai ?? {
    status: HealthStatus.UNSPECIFIED,
    detail: error ? 'unknown while the API is unreachable' : '',
  };

  return (
    <Box component="main" sx={{ minHeight: '100dvh', bgcolor: 'background.default' }}>
      {/* Sticky translucent header: depth from a blurred material over the
          content plus a hairline, never a drop shadow (SPEC.md 8.1). */}
      <Box
        component="header"
        sx={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          backdropFilter: material.blur,
          WebkitBackdropFilter: material.blur,
          borderBottom: `1px solid ${palette.light.hairline}`,
          bgcolor: 'transparent',
        }}
      >
        <Container maxWidth="md">
          <Stack
            direction="row"
            alignItems="center"
            justifyContent="space-between"
            sx={{ py: 3, gap: 2 }}
          >
            <Typography variant="h3" component="h1">
              Rewind Studio
            </Typography>
            <StatusChip
              status={ai.status ?? HealthStatus.UNSPECIFIED}
              label={`AI service ${statusLabel(ai.status ?? HealthStatus.UNSPECIFIED)}`}
              detail={ai.detail || undefined}
              loading={isLoading}
            />
          </Stack>
        </Container>
      </Box>

      <Container maxWidth="md" sx={{ py: 6 }}>
        <motion.div {...slideIn(reduced)}>
          <Stack spacing={4}>
            <Stack spacing={1}>
              <Typography variant="h1">Milestone 0</Typography>
              <Typography variant="body1" color="text.secondary" sx={{ maxWidth: '58ch' }}>
                The spine is wired. This page calls the Go API over Connect, which calls the
                Python worker over gRPC, using stubs generated from a single set of{' '}
                <code>.proto</code> files. Nothing here does any AI work yet — that starts at M2.
              </Typography>
            </Stack>

            <Paper component="section" sx={{ p: 0 }}>
              <Stack divider={<Divider />}>
                <ServiceRow
                  name="Go API"
                  role="Owns state, gates and orchestration"
                  health={api}
                />
                <ServiceRow
                  name="Python AI worker"
                  role="Owns model and media work; no state"
                  health={ai}
                />
              </Stack>
            </Paper>

            <Typography variant="body2" color="text.secondary">
              Next: <strong>M1</strong> — SQLite, the video state machine, gates A–F and the queue
              table that replaces this placeholder.
            </Typography>
          </Stack>
        </motion.div>
      </Container>
    </Box>
  );
}

function ServiceRow({
  name,
  role,
  health,
}: {
  name: string;
  role: string;
  health: Partial<ComponentHealth>;
}) {
  const status = health.status ?? HealthStatus.UNSPECIFIED;

  return (
    <Stack
      direction={{ xs: 'column', sm: 'row' }}
      alignItems={{ xs: 'flex-start', sm: 'center' }}
      justifyContent="space-between"
      sx={{ p: 3, gap: 2 }}
    >
      <Stack spacing={0.5}>
        <Typography variant="h3" component="h2">
          {name}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {role}
        </Typography>
        {health.version ? (
          <Typography variant="body2" color="text.secondary">
            version {health.version}
            {health.latencyMs ? ` · ${health.latencyMs}ms` : ''}
          </Typography>
        ) : null}
      </Stack>

      <StatusChip status={status} label={statusLabel(status)} detail={health.detail || undefined} />
    </Stack>
  );
}
