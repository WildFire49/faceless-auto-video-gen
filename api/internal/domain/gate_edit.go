package domain

import "fmt"

// RequireOpenGate returns nil only while v is waiting at gate g -- the one
// moment a human is reviewing that gate's sheet.
//
// Before it, the pipeline step is still writing the sheet. After it, the
// approval is on the record and everything downstream was built from what
// was approved; changing the sheet then would leave the approval describing
// something that no longer exists. To change an approved sheet, a later gate
// sends the video back, which puts it at this gate again.
//
// Read from the same `gates` table ApproveGate uses, so "which status waits
// at which gate" has exactly one definition.
func RequireOpenGate(v *Video, g Gate) error {
	for _, t := range gates {
		if t.Gate != g {
			continue
		}
		if v.Status == t.From {
			return nil
		}
		return fmt.Errorf("%w: %s can only be edited while the video waits at it; "+
			"%q is %s", ErrGateClosed, g, v.ID, v.Status)
	}
	return fmt.Errorf("%w: unknown gate %q", ErrValidation, string(g))
}
