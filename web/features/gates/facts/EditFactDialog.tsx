/**
 * Edit and add dialogs for Gate A.
 *
 * Note what the edit dialog does NOT offer: the evidence and the source URL.
 * Those record where the claim came from, and letting them be rewritten would
 * erase the audit trail the verifier produced (SPEC.md 5.2). Correcting a
 * claim means editing the claim, or deleting it and adding your own.
 */

'use client';

import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { useEffect, useState } from 'react';

import type { useFactMutations } from '@/lib/api/facts';
import type { Fact } from '@/lib/gen/rewind/v1/research_pb';
import { palette } from '@/theme/tokens';

type Mutations = ReturnType<typeof useFactMutations>;

export function EditFactDialog({
  videoId,
  fact,
  onClose,
  mutations,
}: {
  videoId: string;
  fact: Fact | null;
  onClose: () => void;
  mutations: Mutations;
}) {
  const [yearLabel, setYearLabel] = useState('');
  const [sortYear, setSortYear] = useState(0);
  const [place, setPlace] = useState('');
  const [claim, setClaim] = useState('');

  // Reload the form whenever a different fact is opened.
  useEffect(() => {
    if (!fact) return;
    setYearLabel(fact.yearLabel);
    setSortYear(fact.sortYear);
    setPlace(fact.place);
    setClaim(fact.claim);
  }, [fact]);

  if (!fact) return null;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    mutations.updateFact.mutate(
      { factId: fact.id, yearLabel, sortYear, place, claim },
      { onSuccess: onClose },
    );
  };

  return (
    <Dialog
      open
      onClose={onClose}
      fullWidth
      maxWidth="sm"
      slotProps={{ paper: { component: 'form', onSubmit: submit } }}
    >
      <DialogTitle>Edit fact {fact.id}</DialogTitle>
      <DialogContent>
        <Stack spacing={3} sx={{ pt: 1 }}>
          <Stack direction="row" spacing={2}>
            <TextField
              required
              label="Year label"
              helperText="How a narrator says it"
              value={yearLabel}
              onChange={(e) => setYearLabel(e.target.value)}
              fullWidth
            />
            <TextField
              required
              type="number"
              label="Sort year"
              helperText="Negative for BC"
              value={sortYear}
              onChange={(e) => setSortYear(Number(e.target.value))}
              fullWidth
            />
          </Stack>

          <TextField
            label="Place"
            value={place}
            onChange={(e) => setPlace(e.target.value)}
            fullWidth
          />

          <TextField
            required
            label="Claim"
            value={claim}
            onChange={(e) => setClaim(e.target.value)}
            fullWidth
            multiline
            minRows={2}
          />

          <Box
            sx={{
              borderLeft: `2px solid ${palette.light.hairline}`,
              pl: 2,
              py: 0.5,
            }}
          >
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              Evidence (not editable — this is what the source actually says)
            </Typography>
            <Typography variant="body2" sx={{ fontStyle: 'italic' }}>
              “{fact.evidence}”
            </Typography>
          </Box>

          {mutations.updateFact.isError ? (
            <Alert severity="error">{mutations.updateFact.error.message}</Alert>
          ) : null}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 3 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          type="submit"
          variant="contained"
          disabled={!claim.trim() || !yearLabel.trim() || mutations.updateFact.isPending}
        >
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}
