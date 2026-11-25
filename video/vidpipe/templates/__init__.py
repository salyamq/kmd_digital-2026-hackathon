"""Template registry. Add a template = add a class here; nothing else in the pipeline changes."""
from .cards import TitleCard, MisconceptionCard, QuestionCard, BeforeAfter, EquationCard, SummaryList, TextPanel
from .data_chart import DataChart
from .depth_track import DepthTrack
from .field_evolution import FieldEvolution
from .geology import CrossSection, PoreScale, InsetCallouts, ProcessSteps
from .media import Photo, AIClip
from .overlay import OverlayCard

REGISTRY = {c.name: c for c in [
    TitleCard, MisconceptionCard, QuestionCard, BeforeAfter, EquationCard, SummaryList, TextPanel,
    DataChart, DepthTrack, FieldEvolution, CrossSection, PoreScale, InsetCallouts, ProcessSteps, Photo, AIClip,
    OverlayCard,
]}

# Full-screen text-led templates: reported as class T ("text card"), capped at 25 % of screen time.
CARD_TEMPLATES = {"title_card", "misconception_card", "question_card", "before_after", "equation_card",
                  "summary_list", "text_panel", "process_steps"}
VISUAL_CLASSES = {"A", "B", "C"}


def catalog():
    """Machine-readable description of every template (fed to the LLM planner and the coverage report)."""
    return [c.describe() for c in REGISTRY.values()]
