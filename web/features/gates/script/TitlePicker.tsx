/**
 * Pick the title (SPEC.md 5.4, "also pick the final title").
 *
 * The options come from the script writer; a title typed in full is allowed
 * too. Either way it is re-checked like any other edit -- a title is on
 * screen, so a number in it must be in an approved fact.
 */

'use client';

import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import FormControlLabel from '@mui/material/FormControlLabel';
import Paper from '@mui/material/Paper';
import Radio from '@mui/material/Radio';
import RadioGroup from '@mui/material/RadioGroup';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { useState } from 'react';

import type { ScriptMutations } from '@/lib/api/scripts';

export interface TitlePickerProps {
  options: string[];
  chosen: string;
  readOnly: boolean;
  mutations: ScriptMutations;
}

export function TitlePicker({ options, chosen, readOnly, mutations }: TitlePickerProps) {
  const [custom, setCustom] = useState('');
  const pending = mutations.chooseTitle.isPending;

  return (
    <Paper sx={{ p: 2.5 }}>
      <Stack spacing={1.5}>
        <Typography variant="h3" component="h2">
          Title
        </Typography>

        {readOnly ? (
          <Typography variant="body1">{chosen || 'No title was chosen.'}</Typography>
        ) : (
          <>
            <RadioGroup
              value={options.includes(chosen) ? chosen : ''}
              onChange={(e) => mutations.chooseTitle.mutate(e.target.value)}
            >
              {options.map((option) => (
                <FormControlLabel
                  key={option}
                  value={option}
                  control={<Radio disabled={pending} />}
                  label={option}
                />
              ))}
            </RadioGroup>

            {chosen && !options.includes(chosen) ? (
              <Typography variant="body2" color="text.secondary">
                Chosen: <strong>{chosen}</strong>
              </Typography>
            ) : null}

            <Stack direction="row" spacing={1} alignItems="flex-start">
              <TextField
                size="small"
                label="Or write your own"
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                fullWidth
              />
              <Button
                disabled={!custom.trim() || pending}
                onClick={() =>
                  mutations.chooseTitle.mutate(custom, { onSuccess: () => setCustom('') })
                }
              >
                Use it
              </Button>
            </Stack>

            {mutations.chooseTitle.isError ? (
              <Alert severity="error">{mutations.chooseTitle.error.message}</Alert>
            ) : null}
          </>
        )}
      </Stack>
    </Paper>
  );
}
