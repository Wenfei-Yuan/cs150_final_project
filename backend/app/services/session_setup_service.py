"""
Session setup service — handles the 3-question questionnaire and LLM-based mode selection.

LLM call: mode_selection — determines reading mode from user's 3 answers.
"""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from app.llm.client import chat_completion_json
from app.llm.parser import parse_and_validate
from app.schemas.llm_mode import MODE_SELECTION_SCHEMA
from app.schemas.mode import (
    SETUP_QUESTIONS,
    STRATEGY_PROFILES,
    ModeChoice,
    ReadingMode,
)
from app.core.logger import get_logger

logger = get_logger(__name__)

PURPOSE_LABELS = [
    "Quickly understand what this paper is about",
    "Find specific information",
    "Deeply understand methods and experiments",
    "Prepare for class / presentation / writing",
]

TIME_LABELS = ["5-10 minutes", "10-30 minutes", "30-60 minutes", "60+ minutes"]

SUPPORT_LABELS = [
    "Help me get started quickly",
    "Help me stay focused",
    "Help me confirm I truly understand",
    "Less testing, let me move forward first",
]

MODE_DESCRIPTIONS = {
    "skim": {
        "name": "Skim / Overview Mode",
        "description": (
            "A quick overview of the paper. You'll see a full summary first, "
            "then read key sections (Abstract → Introduction → Figures → Results). "
            "You can freely jump between sections using the mind map. "
            "At each chunk you just self-assess: understood or have questions. "
            "No retelling required. At the end you write a brief takeaway."
        ),
    },
    "goal_directed": {
        "name": "Goal-Directed Search Mode",
        "description": (
            "You tell us what you're looking for, and we'll rank the most relevant "
            "sections for you. You only read what matters for your goal. "
            "You can freely jump via the mind map. "
            "At each chunk, a simple yes/no: was this helpful? Plus a quick T/F question. "
            "At the end, you say whether you found the target information and then try to answer your "
            "original question. You get feedback on strengths and limitations, with no score."
        ),
    },
    "deep_comprehension": {
        "name": "Deep Comprehension Mode",
        "description": (
            "You read every chunk in order. After each chunk, you retell what you read "
            "(you can skip by leaving it empty). Then a quiz question (T/F, MCQ, or fill-blank). "
            "If you get it wrong, you can retry, mark it for later, or skip. "
            "Marked questions come back at the end of each section. "
            "You can jump between sections via the mind map, but within a section you read in order. "
            "At the end you write a takeaway."
        ),
    },
}

_MODE_SELECTION_SYSTEM = (
    "You are an intelligent reading assistant for ADHD students. "
    "Based on the user's reading purpose, available time, and support preference, "
    "recommend the most suitable reading mode. "
    "Respond ONLY with valid JSON."
)

_MODE_SELECTION_USER = """\
The user answered three setup questions:

1. Reading purpose: {purpose}
2. Available time: {time}
3. Support needed: {support}

The three available reading modes are:

1. **skim** (Skim / Overview): Quick overview, read key sections only (abstract, intro, figures, results). Free jumping allowed. No retelling. Self-assessment checkpoints. Best for quick understanding or when time is very limited.

2. **goal_directed** (Goal-Directed Search): User specifies what they're looking for. System ranks and presents only relevant chunks. Free jumping. Helpfulness checks. Best when searching for specific information.

3. **deep_comprehension** (Deep Comprehension): Read ALL chunks sequentially. Forced retelling + quiz gates. Cannot skip within sections. Best for thorough learning, class prep, writing literature review.

Guidelines:
- If purpose is "Quickly understand" + short time → skim
- If purpose is "Find specific info" → goal_directed
- If purpose is "Deep understanding" or "Prepare for class" + enough time (30min+) → deep_comprehension
- If purpose is "Deep understanding" but only 5-10 min → skim (not enough time for deep)
- Support "get started quickly" or "less testing" biases toward skim
- Support "stay focused" biases toward deep_comprehension
- Support "confirm understanding" biases toward deep_comprehension

Return JSON:
{{
  "mode": "skim" | "goal_directed" | "deep_comprehension",
  "reasoning": "Brief explanation of why this mode was chosen",
  "mode_explanation": "A friendly 1-2 sentence explanation to the user about the chosen mode",
  "mode_flow_description": "A brief description of how this mode works step by step"
}}
"""


class SessionSetupService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def get_questionnaire(self) -> dict:
        """Return the 3 setup questions."""
        return {"questions": SETUP_QUESTIONS}

    def list_mode_choices(self) -> list[ModeChoice]:
        """Return the normalized choices for all reading modes."""
        return [
            ModeChoice(
                mode=ReadingMode(mode_key),
                name=mode_info["name"],
                description=mode_info["description"],
            )
            for mode_key, mode_info in MODE_DESCRIPTIONS.items()
        ]

    def get_mode_choice(self, mode: str | ReadingMode) -> ModeChoice:
        """Return the normalized choice object for one mode."""
        mode_enum = ReadingMode(mode)
        mode_info = MODE_DESCRIPTIONS[mode_enum.value]
        return ModeChoice(
            mode=mode_enum,
            name=mode_info["name"],
            description=mode_info["description"],
        )

    async def determine_mode(
        self, reading_purpose: int, available_time: int, support_needed: int
    ) -> dict:
        """
        LLM call: mode_selection
        Determine the best reading mode based on setup answers.
        Returns mode, reasoning, explanation, and alternatives.
        """
        purpose_text = PURPOSE_LABELS[reading_purpose]
        time_text = TIME_LABELS[available_time]
        support_text = SUPPORT_LABELS[support_needed]

        raw = await chat_completion_json(
            system_prompt=_MODE_SELECTION_SYSTEM,
            user_prompt=_MODE_SELECTION_USER.format(
                purpose=purpose_text,
                time=time_text,
                support=support_text,
            ),
        )

        data = parse_and_validate(raw, MODE_SELECTION_SCHEMA)
        recommended = ReadingMode(data["mode"])

        available_modes = [choice.model_dump() for choice in self.list_mode_choices()]
        alternatives = [
            choice for choice in available_modes if choice["mode"] != recommended.value
        ]

        logger.info("LLM recommended mode: %s (reason: %s)", recommended.value, data["reasoning"])

        return {
            "recommended_mode": recommended.value,
            "mode_explanation": data["mode_explanation"],
            "mode_flow_description": data["mode_flow_description"],
            "alternative_modes": alternatives,
            "available_modes": available_modes,
        }

    def get_mode_description(self, mode: str) -> dict:
        """Return the description for a mode."""
        return self.get_mode_choice(mode).model_dump()

    def get_strategy_profile(self, mode: str):
        """Return the StrategyProfile for a mode."""
        return STRATEGY_PROFILES.get(ReadingMode(mode))
