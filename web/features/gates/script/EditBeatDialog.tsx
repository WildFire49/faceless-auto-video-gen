/**
 * Edit what one beat says (SPEC.md 8.2, "edit inline -> re-validate").
 *
 * Saving sends the edit to the API, which has the worker re-check the WHOLE
 * script before storing it. The dialog shows the result the moment it
 * returns, so a fix that breaks a different rule is visible straight away.
 *
 * What it does not offer: changing which facts a beat cites. Numbers are
 * checked against the cited facts, so re-pointing citations to make a number
 * pass would defeat the check. To use a different fact, send the script back.
 *
 * What it does offer: taking a comparison OUT of a beat. A first live run
 * left one in a beat that did not cite its fact, and no edit of the words
 * alone could clear it -- the gate could never have opened.
 */

'use client';

import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { useEffect, useState, type FormEvent } from 'react';

import type { ScriptMutations } from '@/lib/api/scripts';
import type { Proposal } from '@/lib/gen/rewind/v1/relevance_pb';
import type { Beat } from '@/lib/gen/rewind/v1/script_pb';

const WORD = /[\w'’]+/g;

export interface EditBeatDialogProps {
  /** null closes the dialog. */
  beat: Beat | null;
  /** The comparisons selected at Gate B, to name the ones this beat uses. */
  proposals: Proposal[];
  onClose: () => void;
  mutations: ScriptMutations;
}

export function EditBeatDialog({ beat, proposals, onClose, mutations }: EditBeatDialogProps) {
  const [voice, setVoice] = useState('');
  const [onScreen, setOnScreen] = useState('');
  const [yearStamp, setYearStamp] = useState('');
  const [refIds, setRefIds] = useState<string[]>([]);

  useEffect(() => {
    if (!beat) return;
    setVoice(beat.voice);
    setOnScreen(beat.onScreenText);
    setYearStamp(beat.yearStamp);
    setRefIds([...beat.refIds]);
    mutations.updateBeat.reset();
    // mutations is recreated each render; keying on the beat is the intent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [beat]);

  if (!beat) return null;

  const close = () => {
    if (!mutations.updateBeat.isPending) onClose();
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    mutations.updateBeat.mutate(
      { n: beat.n, voice, onScreenText: onScreen, yearStamp, refIds },
      { onSuccess: onClose },
    );
  };

  const words = (voice.match(WORD) ?? []).length;

  return (
    <Dialog
      open
      onClose={close}
      fullWidth
      maxWidth="sm"
      slotProps={{ paper: { component: 'form', onSubmit: submit } }}
    >
      <DialogTitle>Edit beat {beat.n}</DialogTitle>
      <DialogContent>
        <Stack spacing={3} sx={{ pt: 1 }}>
          <TextField
            autoFocus
            required
            label="Narration"
            helperText={`${words} words. Numbers as digits, and only ones in the facts this beat cites (${
              beat.factIds.join(', ') || 'none'
            }).`}
            value={voice}
            onChange={(e) => setVoice(e.target.value)}
            fullWidth
            multiline
            minRows={2}
          />
          <TextField
            label="On-screen text"
            value={onScreen}
            onChange={(e) => setOnScreen(e.target.value)}
            fullWidth
          />
          <TextField
            label="Year stamp"
            value={yearStamp}
            onChange={(e) => setYearStamp(e.target.value)}
            fullWidth
          />
          {refIds.length > 0 ? (
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Typography variant="body2" color="text.secondary">
                Comparisons:
              </Typography>
              {refIds.map((id) => (
                <Chip
                  key={id}
                  size="small"
                  label={proposals.find((p) => p.id === id)?.reference ?? id}
                  onDelete={() => setRefIds(refIds.filter((r) => r !== id))}
                />
              ))}
            </Stack>
          ) : null}
          <Typography variant="body2" color="text.secondary">
            Saving re-checks the whole script against the approved facts.
          </Typography>
          {mutations.updateBeat.isError ? (
            <Alert severity="error">{mutations.updateBeat.error.message}</Alert>
          ) : null}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 3 }}>
        <Button onClick={close} disabled={mutations.updateBeat.isPending}>
          Cancel
        </Button>
        <Button type="submit" variant="contained" disabled={!voice.trim() || mutations.updateBeat.isPending}>
          {mutations.updateBeat.isPending ? 'Checking…' : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
