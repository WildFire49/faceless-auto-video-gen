package service

import (
	"context"
	"fmt"
	"strings"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/validate"
)

// FactsService is the Gate A use case: review, edit and approve the fact sheet.
//
// Every mutation returns the WHOLE recomputed view, because Gate A's approval
// rules depend on the sheet as a whole -- how many facts are ticked, how many
// eras they span. Returning a partial answer would let the dashboard show a
// stale verdict about whether the gate can be approved.
type FactsService struct {
	facts  domain.FactStore
	videos domain.VideoRepo
	log    domain.ReviewLog
	clock  domain.Clock
}

// NewFactsService wires the service.
//
// No thresholds here: each fact sheet carries the gate rules its own content
// format declared, so this service works unchanged for a format written after
// it (SPEC.md 14.2).
func NewFactsService(
	facts domain.FactStore,
	videos domain.VideoRepo,
	log domain.ReviewLog,
	clock domain.Clock,
) *FactsService {
	return &FactsService{facts: facts, videos: videos, log: log, clock: clock}
}

// FactsView is everything Gate A needs to render.
type FactsView struct {
	Exists    bool
	Sheet     *domain.FactSheet
	Readiness domain.GateAReadiness
}

// GetFacts returns the fact sheet for review.
func (s *FactsService) GetFacts(ctx context.Context, videoID string) (*FactsView, error) {
	if err := validate.VideoID(videoID); err != nil {
		return nil, err
	}

	sheet, exists, err := s.facts.Load(videoID)
	if err != nil {
		return nil, err
	}
	if !exists {
		return &FactsView{Exists: false}, nil
	}

	return &FactsView{
		Exists:    true,
		Sheet:     sheet,
		Readiness: domain.CheckGateA(sheet),
	}, nil
}

// SetApproval ticks or unticks one fact.
func (s *FactsService) SetApproval(
	ctx context.Context, videoID, factID string, approved bool,
) (*FactsView, error) {
	return s.mutate(ctx, videoID, func(sheet *domain.FactSheet) (string, error) {
		fact, found := sheet.Find(factID)
		if !found {
			return "", fmt.Errorf("%w: fact %q", domain.ErrNotFound, factID)
		}
		fact.Approved = approved

		verb := "unapproved"
		if approved {
			verb = "approved"
		}
		return fmt.Sprintf("%s fact %s (%s)", verb, factID, fact.Label), nil
	})
}

// ApproveAll ticks or unticks every fact.
func (s *FactsService) ApproveAll(
	ctx context.Context, videoID string, approved bool,
) (*FactsView, error) {
	return s.mutate(ctx, videoID, func(sheet *domain.FactSheet) (string, error) {
		for i := range sheet.Facts {
			sheet.Facts[i].Approved = approved
		}

		verb := "unapproved"
		if approved {
			verb = "approved"
		}
		return fmt.Sprintf("%s all %d facts", verb, len(sheet.Facts)), nil
	})
}

// UpdateFact edits a fact's wording.
//
// Only the narrator-facing fields can change. Evidence and SourceURL are
// untouched: they record where the claim came from, and a human rewriting
// them would erase the audit trail the verifier produced.
func (s *FactsService) UpdateFact(
	ctx context.Context,
	videoID, factID string,
	label string,
	sortKey int64,
	factContext, claim string,
) (*FactsView, error) {
	return s.mutate(ctx, videoID, func(sheet *domain.FactSheet) (string, error) {
		fact, found := sheet.Find(factID)
		if !found {
			return "", fmt.Errorf("%w: fact %q", domain.ErrNotFound, factID)
		}
		if strings.TrimSpace(claim) == "" {
			return "", fmt.Errorf("%w: a claim is required", domain.ErrValidation)
		}
		if strings.TrimSpace(label) == "" {
			return "", fmt.Errorf("%w: a label is required", domain.ErrValidation)
		}

		before := fmt.Sprintf("%s | %s", fact.Label, fact.Claim)

		fact.Label = label
		fact.SortKey = sortKey
		fact.Context = factContext
		fact.Claim = claim

		return fmt.Sprintf("edited fact %s: %q -> %q", factID, before,
			fmt.Sprintf("%s | %s", label, claim)), nil
	})
}

// DeleteFact removes a fact.
func (s *FactsService) DeleteFact(
	ctx context.Context, videoID, factID, reason string,
) (*FactsView, error) {
	return s.mutate(ctx, videoID, func(sheet *domain.FactSheet) (string, error) {
		index := -1
		for i := range sheet.Facts {
			if sheet.Facts[i].ID == factID {
				index = i
				break
			}
		}
		if index == -1 {
			return "", fmt.Errorf("%w: fact %q", domain.ErrNotFound, factID)
		}

		removed := sheet.Facts[index]
		sheet.Facts = append(sheet.Facts[:index], sheet.Facts[index+1:]...)

		note := fmt.Sprintf("deleted fact %s (%s: %s)", factID, removed.Label, removed.Claim)
		if reason != "" {
			note += " — " + reason
		}
		return note, nil
	})
}

// AddFact adds a fact the human sourced themselves.
func (s *FactsService) AddFact(ctx context.Context, videoID string, fact domain.Fact) (*FactsView, error) {
	return s.mutate(ctx, videoID, func(sheet *domain.FactSheet) (string, error) {
		if err := domain.ValidateHumanFact(fact); err != nil {
			return "", err
		}

		fact.ID = sheet.NextFactID()
		fact.AddedByHuman = true
		// A human-added fact is approved on arrival: typing it in IS the
		// approval. Making someone tick a box they just filled in would be
		// ceremony, not review.
		fact.Approved = true
		fact.Confidence = "high"
		fact.MatchScore = 1
		if fact.SourceTitle == "" {
			fact.SourceTitle = fact.SourceURL
		}

		// A human-added fact still needs a group, or it would not count
		// towards the variety requirement. Without knowing the format, the
		// honest answer is its own bucket.
		if fact.Group == "" {
			fact.Group = "added-by-hand"
		}

		sheet.Facts = append(sheet.Facts, fact)
		return fmt.Sprintf("added fact %s (%s: %s) sourced from %s",
			fact.ID, fact.Label, fact.Claim, fact.SourceURL), nil
	})
}

// mutate loads the sheet, applies a change, saves it, and logs what happened.
//
// Every Gate A edit goes through here, so none of them can forget to write a
// review-log entry -- the log is the project's evidence of human involvement
// (SPEC.md 7, 8.4), and an edit missing from it is a hole in that evidence.
func (s *FactsService) mutate(
	ctx context.Context,
	videoID string,
	apply func(*domain.FactSheet) (string, error),
) (*FactsView, error) {
	if err := validate.VideoID(videoID); err != nil {
		return nil, err
	}

	sheet, exists, err := s.facts.Load(videoID)
	if err != nil {
		return nil, err
	}
	if !exists {
		return nil, fmt.Errorf("%w: no fact sheet for %q — run the research step first",
			domain.ErrNotFound, videoID)
	}

	note, err := apply(sheet)
	if err != nil {
		return nil, err
	}

	if err := s.facts.Save(videoID, sheet); err != nil {
		return nil, err
	}

	// The video's status is unchanged by an edit -- it is still sitting at
	// Gate A -- so from/to are the same. What matters is that the change is
	// on the record.
	status := domain.StatusFactsReady
	if v, err := s.videos.Get(ctx, videoID); err == nil {
		status = v.Status
	}

	if err := s.log.Append(ctx, &domain.ReviewEntry{
		VideoID:    videoID,
		At:         s.clock.Now(),
		Gate:       domain.GateA,
		Action:     domain.ActionEdit,
		FromStatus: status,
		ToStatus:   status,
		Note:       note,
	}); err != nil {
		return nil, err
	}

	return &FactsView{
		Exists:    true,
		Sheet:     sheet,
		Readiness: domain.CheckGateA(sheet),
	}, nil
}
