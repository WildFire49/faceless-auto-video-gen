package service

import (
	"context"
	"fmt"
	"strings"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/validate"
)

// ReferencesService is the Gate B use case: review, select and edit the
// proposed modern comparisons.
//
// Shaped exactly like FactsService, and for the same reason: every mutation
// returns the whole recomputed view, because Gate B's verdict depends on the
// sheet as a whole -- how many are ticked, whether any has expired.
type ReferencesService struct {
	refs   domain.ReferenceStore
	facts  domain.FactStore
	videos domain.VideoRepo
	log    domain.ReviewLog
	clock  domain.Clock
}

// NewReferencesService wires the service.
func NewReferencesService(
	refs domain.ReferenceStore,
	facts domain.FactStore,
	videos domain.VideoRepo,
	log domain.ReviewLog,
	clock domain.Clock,
) *ReferencesService {
	return &ReferencesService{refs: refs, facts: facts, videos: videos, log: log, clock: clock}
}

// ReferencesView is everything Gate B needs to render.
type ReferencesView struct {
	Exists    bool
	Sheet     *domain.ReferenceSheet
	Readiness domain.GateBReadiness
}

// GetReferences returns the sheet for review.
func (s *ReferencesService) GetReferences(ctx context.Context, videoID string) (*ReferencesView, error) {
	if err := validate.VideoID(videoID); err != nil {
		return nil, err
	}

	sheet, exists, err := s.refs.Load(videoID)
	if err != nil {
		return nil, err
	}
	if !exists {
		return &ReferencesView{Exists: false}, nil
	}

	return &ReferencesView{
		Exists:    true,
		Sheet:     sheet,
		Readiness: domain.CheckGateB(sheet, s.clock.Now()),
	}, nil
}

// Select ticks or unticks a comparison, enforcing the max-3 limit.
func (s *ReferencesService) Select(
	ctx context.Context, videoID, proposalID string, selected bool,
) (*ReferencesView, error) {
	return s.mutate(ctx, videoID, func(sheet *domain.ReferenceSheet) (string, error) {
		if err := domain.SelectProposal(sheet, proposalID, selected); err != nil {
			return "", err
		}

		proposal, _ := sheet.Find(proposalID)
		verb := "deselected"
		if selected {
			verb = "selected"
		}
		return fmt.Sprintf("%s %s (%s)", verb, proposalID, proposal.Reference), nil
	})
}

// UpdateProposal rewrites a comparison's wording, or re-points it at another
// approved fact.
func (s *ReferencesService) UpdateProposal(
	ctx context.Context, videoID, proposalID, comparison, whyFunny, linkedFactID string,
) (*ReferencesView, error) {
	approved, err := s.approvedFactIDs(videoID)
	if err != nil {
		return nil, err
	}

	return s.mutate(ctx, videoID, func(sheet *domain.ReferenceSheet) (string, error) {
		proposal, found := sheet.Find(proposalID)
		if !found {
			return "", fmt.Errorf("%w: proposal %q", domain.ErrNotFound, proposalID)
		}
		if strings.TrimSpace(comparison) == "" {
			return "", fmt.Errorf("%w: a comparison is required", domain.ErrValidation)
		}

		// Re-pointing is allowed, but only at a fact the human approved.
		factID := proposal.LinkedFactID
		if trimmed := strings.TrimSpace(linkedFactID); trimmed != "" {
			if _, ok := approved[trimmed]; !ok {
				return "", fmt.Errorf("%w: %q is not an approved fact",
					domain.ErrValidation, trimmed)
			}
			factID = trimmed
		}

		before := proposal.Comparison
		proposal.Comparison = comparison
		proposal.WhyFunny = whyFunny
		proposal.LinkedFactID = factID

		return fmt.Sprintf("edited %s: %q -> %q", proposalID, before, comparison), nil
	})
}

// DeleteProposal removes a comparison.
func (s *ReferencesService) DeleteProposal(
	ctx context.Context, videoID, proposalID, reason string,
) (*ReferencesView, error) {
	return s.mutate(ctx, videoID, func(sheet *domain.ReferenceSheet) (string, error) {
		index := -1
		for i := range sheet.Proposals {
			if sheet.Proposals[i].ID == proposalID {
				index = i
				break
			}
		}
		if index == -1 {
			return "", fmt.Errorf("%w: proposal %q", domain.ErrNotFound, proposalID)
		}

		removed := sheet.Proposals[index]
		sheet.Proposals = append(sheet.Proposals[:index], sheet.Proposals[index+1:]...)

		note := fmt.Sprintf("deleted %s (%s: %s)", proposalID, removed.Reference, removed.Comparison)
		if reason != "" {
			note += " — " + reason
		}
		return note, nil
	})
}

// AddProposal adds a comparison the human wrote themselves.
func (s *ReferencesService) AddProposal(
	ctx context.Context, videoID, reference, comparison, whyFunny, linkedFactID string,
) (*ReferencesView, error) {
	approved, err := s.approvedFactIDs(videoID)
	if err != nil {
		return nil, err
	}

	return s.mutate(ctx, videoID, func(sheet *domain.ReferenceSheet) (string, error) {
		proposal := domain.Proposal{
			Reference:    strings.TrimSpace(reference),
			Kind:         domain.KindManual,
			LinkedFactID: strings.TrimSpace(linkedFactID),
			Comparison:   strings.TrimSpace(comparison),
			WhyFunny:     strings.TrimSpace(whyFunny),
			AccuracyNote: "written by hand at Gate B",
		}

		if err := domain.ValidateHumanProposal(proposal, approved); err != nil {
			return "", err
		}

		proposal.ID = sheet.NextProposalID()
		// Not auto-selected: writing a line and choosing to spend one of only
		// three slots on it are different decisions.
		sheet.Proposals = append(sheet.Proposals, proposal)

		return fmt.Sprintf("added %s (%s) attached to %s",
			proposal.ID, proposal.Reference, proposal.LinkedFactID), nil
	})
}

// approvedFactIDs reads which facts the human approved at Gate A.
//
// Needed because a comparison must attach to one of them, and Gate B has no
// business trusting an id the caller supplied.
func (s *ReferencesService) approvedFactIDs(videoID string) (map[string]struct{}, error) {
	sheet, exists, err := s.facts.Load(videoID)
	if err != nil {
		return nil, err
	}
	if !exists {
		return nil, fmt.Errorf("%w: no fact sheet for %q", domain.ErrNotFound, videoID)
	}

	ids := make(map[string]struct{}, len(sheet.Facts))
	for _, f := range sheet.Facts {
		if f.Approved {
			ids[f.ID] = struct{}{}
		}
	}
	return ids, nil
}

// mutate loads the sheet, applies a change, saves it, and logs what happened.
//
// Every Gate B edit goes through here, so none can forget the review-log
// entry -- the log is the project's evidence of human involvement.
func (s *ReferencesService) mutate(
	ctx context.Context,
	videoID string,
	apply func(*domain.ReferenceSheet) (string, error),
) (*ReferencesView, error) {
	if err := validate.VideoID(videoID); err != nil {
		return nil, err
	}

	sheet, exists, err := s.refs.Load(videoID)
	if err != nil {
		return nil, err
	}
	if !exists {
		return nil, fmt.Errorf("%w: no comparisons for %q — run the relevance step first",
			domain.ErrNotFound, videoID)
	}

	note, err := apply(sheet)
	if err != nil {
		return nil, err
	}

	if err := s.refs.Save(videoID, sheet); err != nil {
		return nil, err
	}

	status := domain.StatusRefsReady
	if v, err := s.videos.Get(ctx, videoID); err == nil {
		status = v.Status
	}

	if err := s.log.Append(ctx, &domain.ReviewEntry{
		VideoID:    videoID,
		At:         s.clock.Now(),
		Gate:       domain.GateB,
		Action:     domain.ActionEdit,
		FromStatus: status,
		ToStatus:   status,
		Note:       note,
	}); err != nil {
		return nil, err
	}

	return &ReferencesView{
		Exists:    true,
		Sheet:     sheet,
		Readiness: domain.CheckGateB(sheet, s.clock.Now()),
	}, nil
}

// ApprovedFactsFor returns the approved facts in the shape the relevance step
// sends to the worker.
//
// Deliberately only id, label, claim and group: the worker has no business
// with evidence or sources, and handing them over would invite it to reason
// about their truth rather than just be funny about the claim.
func ApprovedFactsFor(sheet *domain.FactSheet) []domain.ApprovedFact {
	if sheet == nil {
		return nil
	}

	out := make([]domain.ApprovedFact, 0, len(sheet.Facts))
	for _, f := range sheet.Facts {
		if !f.Approved {
			continue
		}
		out = append(out, domain.ApprovedFact{
			ID:    f.ID,
			Label: f.Label,
			Claim: f.Claim,
			Group: f.Group,
		})
	}
	return out
}
