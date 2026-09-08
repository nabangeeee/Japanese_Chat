from __future__ import annotations

import re
import unittest
from pathlib import Path


class SystemPromptNegativeFeedbackReproductionTests(unittest.TestCase):
    """Reproduce the root cause behind the 81.8% negative feedback rate.

    The quality reviewer penalizes ungrammatical Japanese, inappropriate
    difficulty level, and off-topic replies. The system prompt must
    explicitly instruct the model to avoid these failure modes so the
    defect is reproducible without a live model call.
    """

    @property
    def system_prompt_template(self) -> str:
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        match = re.search(
            r'SYSTEM_PROMPT_TEMPLATE\s*=\s*"""(.*?)"""',
            source,
            re.DOTALL,
        )
        self.assertTrue(match, "SYSTEM_PROMPT_TEMPLATE not found in main.py")
        return match.group(1)

    @property
    def difficulty_prompts(self) -> dict[str, str]:
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        prompts = {}
        for name in ("BEGINNER_PROMPT", "INTERMEDIATE_PROMPT", "ADVANCED_PROMPT"):
            match = re.search(rf'{name}\s*=\s*"([^"]+)"', source)
            self.assertTrue(match, f"{name} not found in main.py")
            prompts[name] = match.group(1)
        return prompts

    def test_system_prompt_requires_grammatical_correctness(self) -> None:
        """Quality reviewer penalizes ungrammatical Japanese; system prompt must require it."""
        template = self.system_prompt_template.lower()
        self.assertTrue(
            re.search(r"(문법|grammatical|correct|정확|올바른)", template),
            "System prompt must explicitly require grammatically correct Japanese. "
            "The quality reviewer penalizes ungrammatical output, but the system "
            "prompt only says 'naturally' without requiring correctness.",
        )

    def test_system_prompt_requires_difficulty_matching(self) -> None:
        """Quality reviewer penalizes inappropriate difficulty; system prompt must require matching."""
        template = self.system_prompt_template.lower()
        self.assertTrue(
            re.search(r"(레벨|level|난이도|difficulty|맞춤|match)", template),
            "System prompt must explicitly require matching the specified difficulty level. "
            "The quality reviewer penalizes inappropriate difficulty, but the system "
            "prompt doesn't explicitly instruct the model to match the level.",
        )

    def test_system_prompt_requires_topic_adherence(self) -> None:
        """Quality reviewer penalizes off-topic replies; system prompt must require topic adherence."""
        template = self.system_prompt_template.lower()
        self.assertTrue(
            re.search(r"(주제|topic|맥락|context|관련|relevant)", template),
            "System prompt must explicitly require staying on the specified topic. "
            "The quality reviewer penalizes off-topic replies, but the system "
            "prompt doesn't explicitly instruct the model to stay on topic.",
        )

    def test_difficulty_prompts_require_grammatical_correctness(self) -> None:
        """Each difficulty prompt should reinforce grammatical correctness."""
        for name, prompt in self.difficulty_prompts.items():
            lowered = prompt.lower()
            self.assertTrue(
                re.search(r"(문법|grammatical|correct|정확|올바른|polite|fluent)", lowered),
                f"{name} must reinforce grammatical correctness. "
                f"Current prompt: {prompt!r}",
            )

    def test_difficulty_prompts_distinct_by_level(self) -> None:
        """Difficulty prompts must be distinct so the model can differentiate levels."""
        prompts = self.difficulty_prompts
        beginner = prompts["BEGINNER_PROMPT"].lower()
        intermediate = prompts["INTERMEDIATE_PROMPT"].lower()
        advanced = prompts["ADVANCED_PROMPT"].lower()

        # Beginner should mention simplicity/politeness
        self.assertTrue(
            re.search(r"(simple|polite|簡単|初心|beginner|です・ます)", beginner),
            "Beginner prompt must signal simple/polite Japanese.",
        )
        # Advanced should mention fluency/native level
        self.assertTrue(
            re.search(r"(fluent|native|上級|advanced|自然)", advanced),
            "Advanced prompt must signal fluent/native-level Japanese.",
        )
        # They should not be identical
        self.assertNotEqual(
            beginner, intermediate,
            "Beginner and Intermediate prompts must be distinct.",
        )
        self.assertNotEqual(
            intermediate, advanced,
            "Intermediate and Advanced prompts must be distinct.",
        )


if __name__ == "__main__":
    unittest.main()
