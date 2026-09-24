package factstore

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/validate"
)

// ScriptStore reads and writes projects/<video_id>/script.json.
//
// Same division of labour as the other sheets: the worker writes it once when
// the script step finishes, and Go owns it from then on, because every later
// change is a human decision at Gate C. The JSON keys match the worker's
// codec (ai/rewind_ai/script/codec.py) exactly; a key renamed on one side
// only would silently drop that field.
type ScriptStore struct {
	projectsDir string
}

// NewScriptStore wires the store to the projects directory.
func NewScriptStore(projectsDir string) *ScriptStore { return &ScriptStore{projectsDir: projectsDir} }

// Field order matches domain.Beat exactly, so the two convert directly and a
// field added to one without the other is a compile error, not lost data.
type beatJSON struct {
	N             int      `json:"n"`
	Role          string   `json:"role"`
	YearStamp     string   `json:"year_stamp"`
	Voice         string   `json:"voice"`
	OnScreenText  string   `json:"on_screen_text"`
	VisualPrompts []string `json:"visual_prompts"`
	SFX           string   `json:"sfx"`
	Motion        string   `json:"motion"`
	EmphasisWords []string `json:"emphasis_words"`
	FactIDs       []string `json:"fact_ids"`
	RefIDs        []string `json:"ref_ids"`
	IsPunch       bool     `json:"is_punch"`
}

type violationJSON struct {
	Rule    string `json:"rule"`
	Beat    int    `json:"beat"`
	Message string `json:"message"`
}

type scriptJSON struct {
	Beats        []beatJSON      `json:"beats"`
	TitleOptions []string        `json:"title_options"`
	ChosenTitle  string          `json:"chosen_title"`
	Description  string          `json:"description"`
	Hashtags     []string        `json:"hashtags"`
	Sources      []string        `json:"sources"`
	Attempts     int             `json:"attempts"`
	Violations   []violationJSON `json:"violations"`
}

// Load reads a video's script.
func (s *ScriptStore) Load(videoID string) (*domain.Script, bool, error) {
	path, err := s.scriptPath(videoID)
	if err != nil {
		return nil, false, err
	}

	data, err := os.ReadFile(path) //nolint:gosec // path is validated above
	if os.IsNotExist(err) {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, fmt.Errorf("reading %s: %w", path, err)
	}

	var raw scriptJSON
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, false, fmt.Errorf("parsing %s: %w", path, err)
	}

	script := &domain.Script{
		TitleOptions: raw.TitleOptions,
		ChosenTitle:  raw.ChosenTitle,
		Description:  raw.Description,
		Hashtags:     raw.Hashtags,
		Sources:      raw.Sources,
		Path:         path,
		Attempts:     raw.Attempts,
	}
	for _, b := range raw.Beats {
		script.Beats = append(script.Beats, domain.Beat(b))
	}
	for _, v := range raw.Violations {
		script.Violations = append(script.Violations, domain.Violation(v))
	}
	return script, true, nil
}

// Save writes a script back, atomically.
func (s *ScriptStore) Save(videoID string, script *domain.Script) error {
	path, err := s.scriptPath(videoID)
	if err != nil {
		return err
	}

	raw := scriptJSON{
		TitleOptions: nonNil(script.TitleOptions),
		ChosenTitle:  script.ChosenTitle,
		Description:  script.Description,
		Hashtags:     nonNil(script.Hashtags),
		Sources:      nonNil(script.Sources),
		Attempts:     script.Attempts,
		Beats:        []beatJSON{},
		Violations:   []violationJSON{},
	}
	for _, b := range script.Beats {
		raw.Beats = append(raw.Beats, beatJSON(b))
	}
	for _, v := range script.Violations {
		raw.Violations = append(raw.Violations, violationJSON(v))
	}

	encoded, err := json.MarshalIndent(raw, "", "  ")
	if err != nil {
		return fmt.Errorf("encoding script for %q: %w", videoID, err)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("creating project folder for %q: %w", videoID, err)
	}
	return writeAtomic(path, append(encoded, '\n'))
}

// scriptPath validates the id and builds the file path -- the same
// defence-in-depth check as the other stores (SPEC.md 13.5).
func (s *ScriptStore) scriptPath(videoID string) (string, error) {
	if err := validate.VideoID(videoID); err != nil {
		return "", err
	}
	return filepath.Join(s.projectsDir, videoID, "script.json"), nil
}

// nonNil keeps an empty list as [] rather than null in the JSON, so the
// worker's codec reads the same shape it wrote.
func nonNil(values []string) []string {
	if values == nil {
		return []string{}
	}
	return values
}

var _ domain.ScriptStore = (*ScriptStore)(nil)
