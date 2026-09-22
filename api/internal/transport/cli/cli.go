// Package cli defines the `rewind` commands.
//
// LAYER 5 (transport) of SPEC.md 14.1. Like the Connect handlers, commands
// here only parse arguments, call one service method, and print the result.
//
// The CLI and the dashboard share the same service layer on purpose: a second
// implementation of the rules is how "gates can never be skipped" quietly
// stops being true in one of them.
package cli

import (
	"fmt"
	"io"
	"strings"
	"text/tabwriter"
	"time"

	"github.com/spf13/cobra"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service"
)

// Deps are the use cases the commands need, injected by the composition root.
type Deps struct {
	Videos *service.VideoService
	Gates  *service.GateService
	Facts  *service.FactsService
	Out    io.Writer
}

// NewRootCommand builds the `rewind` command tree.
func NewRootCommand(deps Deps) *cobra.Command {
	root := &cobra.Command{
		Use:   "rewind",
		Short: "REWIND studio: queue topics and move them through the review gates",
		Long: "REWIND turns an everyday object into a sourced history short.\n" +
			"The machine does the busywork; you approve every creative decision.",
		SilenceUsage: true,
		// Errors are printed by main with a consistent prefix, so cobra should
		// not print them a second time.
		SilenceErrors: true,
	}

	root.AddCommand(
		newAddCommand(deps),
		newQueueCommand(deps),
		newShowCommand(deps),
		newRunCommand(deps),
		newRetryCommand(deps),
		newApproveCommand(deps),
		newRejectCommand(deps),
		newLogCommand(deps),
		newFactsCommand(deps),
	)
	return root
}

// --------------------------------------------------------------------- add

func newAddCommand(deps Deps) *cobra.Command {
	var (
		priority int
		notes    string
	)

	cmd := &cobra.Command{
		Use:   `add "<topic>"`,
		Short: "Queue a new topic",
		Example: `  rewind add "sandals" --priority 2 --notes "compare to Birkenstocks, Crocs"` +
			"\n  rewind add \"computer mouse\"",
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			v, err := deps.Videos.AddVideo(cmd.Context(), args[0], domain.Priority(priority), notes)
			if err != nil {
				return err
			}
			fmt.Fprintf(deps.Out, "Queued %s (id: %s, priority %d)\n", v.Topic, v.ID, v.Priority)
			fmt.Fprintf(deps.Out, "Next: rewind run %s\n", v.ID)
			return nil
		},
	}

	cmd.Flags().IntVar(&priority, "priority", 0, "1 (highest) to 5 (lowest); default 3")
	cmd.Flags().StringVar(&notes, "notes", "", "notes for yourself, and hints for the research step")
	return cmd
}

// ------------------------------------------------------------------- queue

func newQueueCommand(deps Deps) *cobra.Command {
	var needsReview bool

	cmd := &cobra.Command{
		Use:     "queue",
		Short:   "List topics and their status",
		Example: "  rewind queue\n  rewind queue --needs-review",
		Args:    cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			videos, err := deps.Videos.ListVideos(cmd.Context(), domain.VideoFilter{
				AwaitingReview: needsReview,
			})
			if err != nil {
				return err
			}

			if len(videos) == 0 {
				if needsReview {
					fmt.Fprintln(deps.Out, "Nothing is waiting for your review.")
				} else {
					fmt.Fprintln(deps.Out, `The queue is empty. Add one with: rewind add "iron"`)
				}
				return nil
			}

			w := tabwriter.NewWriter(deps.Out, 0, 0, 2, ' ', 0)
			fmt.Fprintln(w, "ID\tTOPIC\tPRI\tSTATUS\tWAITING ON\tUPDATED")
			for _, v := range videos {
				waiting := "—"
				if g, ok := domain.GateFor(v.Status); ok {
					waiting = g.Label()
				} else if v.Status == domain.StatusError {
					waiting = "you (failed)"
				}
				fmt.Fprintf(w, "%s\t%s\t%d\t%s\t%s\t%s\n",
					v.ID, truncate(v.Topic, 28), v.Priority, v.Status, waiting, humanAge(v.UpdatedAt))
			}
			return w.Flush()
		},
	}

	cmd.Flags().BoolVar(&needsReview, "needs-review", false, "only videos waiting for you")
	return cmd
}

// -------------------------------------------------------------------- show

func newShowCommand(deps Deps) *cobra.Command {
	return &cobra.Command{
		Use:   "show <video_id>",
		Short: "Show one video in detail",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			v, err := deps.Videos.GetVideo(cmd.Context(), args[0])
			if err != nil {
				return err
			}

			w := tabwriter.NewWriter(deps.Out, 0, 0, 2, ' ', 0)
			fmt.Fprintf(w, "ID\t%s\n", v.ID)
			fmt.Fprintf(w, "Topic\t%s\n", v.Topic)
			fmt.Fprintf(w, "Status\t%s\n", v.Status)
			fmt.Fprintf(w, "Priority\t%d\n", v.Priority)
			if v.Notes != "" {
				fmt.Fprintf(w, "Notes\t%s\n", v.Notes)
			}
			if g, ok := domain.GateFor(v.Status); ok {
				fmt.Fprintf(w, "Waiting on\t%s\n", g.Label())
			}
			if v.RejectedTo != "" {
				fmt.Fprintf(w, "Sent back to\t%s (%s)\n", v.RejectedTo, v.RejectNote)
			}
			if v.Error != "" {
				fmt.Fprintf(w, "Error\t%s\n", v.Error)
				fmt.Fprintf(w, "Resume from\t%s\n", v.RetryFrom)
			}
			fmt.Fprintf(w, "Created\t%s\n", v.CreatedAt.Local().Format(time.RFC1123))
			fmt.Fprintf(w, "Updated\t%s\n", v.UpdatedAt.Local().Format(time.RFC1123))
			return w.Flush()
		},
	}
}

// --------------------------------------------------------------------- run

func newRunCommand(deps Deps) *cobra.Command {
	var all bool

	cmd := &cobra.Command{
		Use:   "run [video_id]",
		Short: "Advance a video as far as it can go before the next gate",
		Long: "Advance a video until it needs you.\n\n" +
			"In M1 the pipeline steps do not exist yet, so this reports what WOULD\n" +
			"happen rather than pretending to work. Steps arrive in M2.",
		Args: cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if all == (len(args) == 1) {
				return fmt.Errorf("give either a video id or --all, not both or neither")
			}

			var ids []string
			if all {
				videos, err := deps.Videos.ListVideos(cmd.Context(), domain.VideoFilter{})
				if err != nil {
					return err
				}
				for _, v := range videos {
					ids = append(ids, v.ID)
				}
			} else {
				ids = args
			}

			for _, id := range ids {
				step, err := deps.Videos.PlanNext(cmd.Context(), id)
				if err != nil {
					return err
				}
				fmt.Fprintf(deps.Out, "%-20s %-22s %s\n", step.Video.ID, step.Video.Status, step.Reason)
			}
			return nil
		},
	}

	cmd.Flags().BoolVar(&all, "all", false, "advance every video")
	return cmd
}

// ------------------------------------------------------------------- retry

func newRetryCommand(deps Deps) *cobra.Command {
	return &cobra.Command{
		Use:   "retry <video_id>",
		Short: "Resume a failed video from the step that failed",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			v, err := deps.Videos.RetryVideo(cmd.Context(), args[0])
			if err != nil {
				return err
			}
			fmt.Fprintf(deps.Out, "%s resumed at %s\n", v.ID, v.Status)
			return nil
		},
	}
}

// ----------------------------------------------------------------- approve

func newApproveCommand(deps Deps) *cobra.Command {
	var note string

	cmd := &cobra.Command{
		Use:   "approve <video_id> <gate>",
		Short: "Approve a review gate (A-F)",
		Long: "Approve the gate a video is waiting at.\n\n" +
			"The gate must be named explicitly and must match the video's current\n" +
			"state. That is deliberate: it stops a stale terminal or browser tab\n" +
			"from approving something you are not actually looking at.",
		Example: `  rewind approve iron A --note "checked every source"`,
		Args:    cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			gate, err := parseGate(args[1])
			if err != nil {
				return err
			}
			v, err := deps.Gates.Approve(cmd.Context(), args[0], gate, note)
			if err != nil {
				return err
			}
			fmt.Fprintf(deps.Out, "Approved %s for %s — now %s\n", gate, v.ID, v.Status)
			return nil
		},
	}

	cmd.Flags().StringVar(&note, "note", "", "recorded in the review log")
	return cmd
}

// ------------------------------------------------------------------ reject

func newRejectCommand(deps Deps) *cobra.Command {
	var (
		backTo string
		note   string
	)

	cmd := &cobra.Command{
		Use:     "reject <video_id> <gate>",
		Short:   "Send a video back to an earlier stage",
		Example: `  rewind reject iron C --back-to researching --note "the 1882 date is wrong"`,
		Args:    cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			gate, err := parseGate(args[1])
			if err != nil {
				return err
			}
			if backTo == "" {
				return fmt.Errorf("--back-to is required; where should this video go?")
			}
			if note == "" {
				return fmt.Errorf("--note is required; a rejection without a reason helps nobody later")
			}

			v, err := deps.Gates.Reject(cmd.Context(), args[0], gate, domain.Status(backTo), note)
			if err != nil {
				return err
			}
			fmt.Fprintf(deps.Out, "Sent %s back to %s\n", v.ID, v.Status)
			return nil
		},
	}

	cmd.Flags().StringVar(&backTo, "back-to", "", "status to send the video back to, e.g. researching")
	cmd.Flags().StringVar(&note, "note", "", "why (required)")
	return cmd
}

// --------------------------------------------------------------------- log

func newLogCommand(deps Deps) *cobra.Command {
	return &cobra.Command{
		Use:   "log <video_id>",
		Short: "Show the human decision history for a video",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			entries, err := deps.Videos.ListReviewLog(cmd.Context(), args[0])
			if err != nil {
				return err
			}
			if len(entries) == 0 {
				fmt.Fprintln(deps.Out, "No decisions recorded yet.")
				return nil
			}

			w := tabwriter.NewWriter(deps.Out, 0, 0, 2, ' ', 0)
			fmt.Fprintln(w, "WHEN\tGATE\tACTION\tFROM\tTO\tNOTE")
			for _, e := range entries {
				gate := string(e.Gate)
				if gate == "" {
					gate = "—"
				}
				fmt.Fprintf(w, "%s\t%s\t%s\t%s\t%s\t%s\n",
					e.At.Local().Format("2006-01-02 15:04"),
					gate, e.Action, e.FromStatus, e.ToStatus, truncate(e.Note, 40))
			}
			return w.Flush()
		},
	}
}

// ----------------------------------------------------------------- helpers

// parseGate accepts "A", "a", or "gate-a" so the command is forgiving about
// case without accepting anything ambiguous.
func parseGate(s string) (domain.Gate, error) {
	normalised := strings.ToUpper(strings.TrimPrefix(strings.ToLower(strings.TrimSpace(s)), "gate-"))

	for _, g := range domain.AllGates() {
		if string(g) == normalised {
			return g, nil
		}
	}
	return domain.GateNone, fmt.Errorf("%q is not a gate; expected one of A B C D E F", s)
}

func truncate(s string, max int) string {
	if len(s) <= max {
		return s
	}
	if max <= 1 {
		return s[:max]
	}
	return s[:max-1] + "…"
}

// humanAge renders a timestamp the way a person scanning a queue wants it.
func humanAge(t time.Time) string {
	d := time.Since(t)
	switch {
	case d < time.Minute:
		return "just now"
	case d < time.Hour:
		return fmt.Sprintf("%dm ago", int(d.Minutes()))
	case d < 24*time.Hour:
		return fmt.Sprintf("%dh ago", int(d.Hours()))
	default:
		return fmt.Sprintf("%dd ago", int(d.Hours()/24))
	}
}
