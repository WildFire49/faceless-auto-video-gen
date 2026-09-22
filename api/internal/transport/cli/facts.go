package cli

import (
	"fmt"
	"io"
	"text/tabwriter"

	"github.com/spf13/cobra"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service"
)

// newFactsCommand shows and approves the researched fact sheet (Gate A).
//
// The dashboard is the better place to do this -- it makes source links
// clickable and shows the evidence beside each claim -- but a terminal view is
// worth having for checking a run without opening a browser.
func newFactsCommand(deps Deps) *cobra.Command {
	var approveAll bool

	cmd := &cobra.Command{
		Use:     "facts <video_id>",
		Short:   "Review the researched fact sheet (Gate A)",
		Example: "  rewind facts iron\n  rewind facts iron --approve-all",
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			videoID := args[0]

			if approveAll {
				view, err := deps.Facts.ApproveAll(cmd.Context(), videoID, true)
				if err != nil {
					return err
				}
				fmt.Fprintf(deps.Out, "Approved all %d facts.\n", len(view.Sheet.Facts))
				printReadiness(deps.Out, view)
				return nil
			}

			view, err := deps.Facts.GetFacts(cmd.Context(), videoID)
			if err != nil {
				return err
			}
			if !view.Exists {
				fmt.Fprintf(deps.Out, "No fact sheet yet. Run: rewind run %s\n", videoID)
				return nil
			}

			fmt.Fprintf(deps.Out, "%s — %d facts from %d source(s) [format: %s]\n",
				view.Sheet.Topic, len(view.Sheet.Facts), len(view.Sheet.Sources),
				view.Sheet.Format)
			if view.Sheet.CandidatesExtracted > 0 {
				fmt.Fprintf(deps.Out,
					"The model proposed %d; %d were rejected as unverifiable or unusable.\n",
					view.Sheet.CandidatesExtracted, view.Sheet.CandidatesRejected)
			}
			fmt.Fprintln(deps.Out)

			w := tabwriter.NewWriter(deps.Out, 0, 0, 2, ' ', 0)
			fmt.Fprintln(w, "ID\tOK\tLABEL\tCLAIM\tCONFIDENCE\tSOURCE")
			for _, f := range view.Sheet.Facts {
				tick := " "
				if f.Approved {
					tick = "x"
				}
				confidence := f.Confidence
				if f.Conflict {
					confidence += " (conflict)"
				}
				fmt.Fprintf(w, "%s\t[%s]\t%s\t%s\t%s\t%s\n",
					f.ID, tick,
					truncate(f.Label, 24),
					truncate(f.Claim, 52),
					confidence,
					truncate(f.SourceTitle, 24),
				)
			}
			if err := w.Flush(); err != nil {
				return fmt.Errorf("writing fact table: %w", err)
			}

			fmt.Fprintln(deps.Out)
			printReadiness(deps.Out, view)
			return nil
		},
	}

	cmd.Flags().BoolVar(&approveAll, "approve-all", false, "tick every fact")
	return cmd
}

// printReadiness reports whether Gate A can be approved, and what is missing.
func printReadiness(out io.Writer, view *service.FactsView) {
	if view.Readiness.CanApprove {
		fmt.Fprintf(out, "Gate A is ready: %d facts approved across %d %ss.\n",
			view.Readiness.Approved, view.Readiness.Groups, view.Readiness.GroupNoun)
		fmt.Fprintln(out, "Approve it with: rewind approve <video_id> A")
		return
	}
	fmt.Fprintf(out, "Gate A is not ready: %s\n", view.Readiness.Blocker)
}
