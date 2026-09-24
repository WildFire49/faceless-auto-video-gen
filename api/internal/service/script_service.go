package service

import (
	"context"
	"fmt"
	"strings"
	"unicode/utf8"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/validate"
)

// maxTitleRunes is YouTube's title limit. A longer title would be truncated
// at upload, silently changing what a human approved.
const maxTitleRunes = 100

// ScriptView is everything Gate C shows.
type ScriptView struct {
	Exists    bool
	Script    *domain.Script
	Readiness domain.GateCReadiness
}

// ScriptService is the Gate C use case: read the script, edit a beat, choose
// a title (SPEC.md 5.4, 8.2).
//
// Every edit is re-validated by the worker before it is saved. The rules live
// in one place (ai/rewind_ai/script/rules.py); Go asks, records the answer,
// and lets CheckGateC decide from it.
type ScriptService struct {
	scripts domain.ScriptStore
	facts   domain.FactStore
	refs    domain.ReferenceStore
	videos  domain.VideoRepo
	writer  domain.ScriptWriter
	log     domain.ReviewLog
	clock   domain.Clock
}

// NewScriptService wires the use case.
func NewScriptService(
	scripts domain.ScriptStore,
	facts domain.FactStore,
	refs domain.ReferenceStore,
	videos domain.VideoRepo,
	writer domain.ScriptWriter,
	log domain.ReviewLog,
	clock domain.Clock,
) *ScriptService {
	return &ScriptService{
		scripts: scripts, facts: facts, refs: refs, videos: videos,
		writer: writer, log: log, clock: clock,
	}
}

// GetScript loads the script for review.
func (s *ScriptService) GetScript(_ context.Context, videoID string) (*ScriptView, error) {
	if err := validate.VideoID(videoID); err != nil {
		return nil, err
	}
	script, exists, err := s.scripts.Load(videoID)
	if err != nil {
		return nil, err
	}
	if !exists {
		return &ScriptView{}, nil
	}
	return &ScriptView{Exists: true, Script: script, Readiness: domain.CheckGateC(script)}, nil
}

// UpdateBeat rewrites what one beat says or shows, and which comparisons it
// uses. refIDs is the beat's COMPLETE list after the edit. Taking one out is
// how a reviewer fixes a comparison sitting in a beat that does not cite its
// fact -- a first live run left exactly that, unfixable by words alone. What
// they choose is re-checked by the worker like any other edit.
func (s *ScriptService) UpdateBeat(
	ctx context.Context, videoID string, n int, voice, onScreen, yearStamp string, refIDs []string,
) (*ScriptView, error) {
	return s.mutate(ctx, videoID, func(script *domain.Script) (string, error) {
		beat, ok := script.Beat(n)
		if !ok {
			return "", fmt.Errorf("%w: the script has no beat %d", domain.ErrNotFound, n)
		}
		if strings.TrimSpace(voice) == "" {
			return "", fmt.Errorf("%w: beat %d needs something for the narrator to say",
				domain.ErrValidation, n)
		}
		before := beat.Voice
		beat.Voice = strings.TrimSpace(voice)
		beat.OnScreenText = strings.TrimSpace(onScreen)
		beat.YearStamp = strings.TrimSpace(yearStamp)
		beat.RefIDs = cleanIDs(refIDs)
		return fmt.Sprintf("edited beat %d: %q -> %q (comparisons %v)",
			n, before, beat.Voice, beat.RefIDs), nil
	})
}

// cleanIDs trims, drops blanks and duplicates, and never returns nil, so the
// stored list reads the same whether the reviewer cleared it or never had one.
func cleanIDs(ids []string) []string {
	out := []string{}
	seen := map[string]bool{}
	for _, id := range ids {
		id = strings.TrimSpace(id)
		if id != "" && !seen[id] {
			seen[id] = true
			out = append(out, id)
		}
	}
	return out
}

// ChooseTitle picks the title the video will be uploaded with.
func (s *ScriptService) ChooseTitle(ctx context.Context, videoID, title string) (*ScriptView, error) {
	return s.mutate(ctx, videoID, func(script *domain.Script) (string, error) {
		title = strings.TrimSpace(title)
		if title == "" {
			return "", fmt.Errorf("%w: a title is required", domain.ErrValidation)
		}
		if n := utf8.RuneCountInString(title); n > maxTitleRunes {
			return "", fmt.Errorf("%w: the title is %d characters; YouTube allows %d",
				domain.ErrValidation, n, maxTitleRunes)
		}
		script.ChosenTitle = title
		return fmt.Sprintf("chose the title %q", title), nil
	})
}

// mutate is the ONE path every Gate C edit takes: the gate must be open, the
// change is applied, the worker re-checks the whole script, and only then is
// it saved and logged.
//
// If the worker cannot check the edit, the edit is refused rather than saved
// on trust: saving it would keep the OLD verdict, and the gate could then
// open on a script nobody validated.
func (s *ScriptService) mutate(
	ctx context.Context,
	videoID string,
	apply func(*domain.Script) (string, error),
) (*ScriptView, error) {
	if err := validate.VideoID(videoID); err != nil {
		return nil, err
	}
	video, err := s.videos.Get(ctx, videoID)
	if err != nil {
		return nil, err
	}
	if err := domain.RequireOpenGate(video, domain.GateC); err != nil {
		return nil, err
	}

	script, exists, err := s.scripts.Load(videoID)
	if err != nil {
		return nil, err
	}
	if !exists {
		return nil, fmt.Errorf("%w: no script for %q -- run the script step first",
			domain.ErrNotFound, videoID)
	}

	note, err := apply(script)
	if err != nil {
		return nil, err
	}

	facts, refs, err := s.inputs(videoID)
	if err != nil {
		return nil, err
	}
	violations, err := s.writer.ValidateScript(ctx, script, facts, refs)
	if err != nil {
		return nil, fmt.Errorf("could not check the edit, so it was not saved: %w", err)
	}
	script.Violations = violations

	if err := s.scripts.Save(videoID, script); err != nil {
		return nil, err
	}
	if err := s.log.Append(ctx, &domain.ReviewEntry{
		VideoID:    videoID,
		At:         s.clock.Now(),
		Gate:       domain.GateC,
		Action:     domain.ActionEdit,
		FromStatus: video.Status,
		ToStatus:   video.Status,
		Note:       note,
	}); err != nil {
		return nil, err
	}

	return &ScriptView{Exists: true, Script: script, Readiness: domain.CheckGateC(script)}, nil
}

// inputs loads what the script may draw on: approved facts, selected refs.
func (s *ScriptService) inputs(videoID string) ([]domain.ScriptFact, []domain.ScriptReference, error) {
	return LoadScriptInputs(s.facts, s.refs, videoID)
}

// LoadScriptInputs reads both sheets and selects what a script may use. Shared
// by the script step and by every Gate C edit, so both check a script against
// the same facts.
func LoadScriptInputs(
	facts domain.FactStore, refs domain.ReferenceStore, videoID string,
) ([]domain.ScriptFact, []domain.ScriptReference, error) {
	factSheet, exists, err := facts.Load(videoID)
	if err != nil {
		return nil, nil, err
	}
	if !exists {
		return nil, nil, fmt.Errorf("%w: no fact sheet for %q", domain.ErrNotFound, videoID)
	}
	refSheet, _, err := refs.Load(videoID)
	if err != nil {
		return nil, nil, err
	}
	scriptFacts, scriptRefs := domain.ScriptInputs(factSheet, refSheet)
	return scriptFacts, scriptRefs, nil
}
