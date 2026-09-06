from __future__ import annotations

import re
import unittest
from pathlib import Path


class SystemPromptQualityGuardrailsTests(unittest.TestCase):
    """Reproduce the root cause behind the 81.8% negative feedback rate.

    The quality reviewer penalizes English leakage, off-topic replies, and
    verbose/irrelevant output, but the generation system prompt never
    instructed the model to avoid those failure modes. This test pins the
    guardrails the system prompt must express so the defect is reproducible
    without a live model call.
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

    def test_system_prompt_forbids_english_leakage(self) -> None:
        template = self.system_prompt_template.lower()
        self.assertTrue(
            re.search(r"(영어|english|のみ|일본어|日本語|japanese)", template),
            "System prompt must explicitly constrain language use to prevent "
            "English leakage, which is a primary driver of negative feedback.",
        )
        self.assertTrue(
            "영어" in template or "english" in template,
            "System prompt must explicitly forbid English mixing.",
        )

    def test_system_prompt_forbids_bracketed_annotations(self) -> None:
        template = self.system_prompt_template.lower()
        self.assertTrue(
            re.search(r"(괄호|읽|読み|ふりがな|후리가나|bracket)", template),
            "System prompt must instruct the model not to emit bracketed "
            "readings/annotations inside the reply.",
        )

    def test_system_prompt_requires_direct_relevance(self) -> None:
        template = self.system_prompt_template.lower()
        self.assertTrue(
            re.search(r"(직접|바로|관련|맥락|맞|관계|relevant|direct)", template),
            "System prompt must instruct the model to answer the user's "
            "message directly and stay on topic.",
        )

    def test_system_prompt_caps_length(self) -> None:
        template = self.system_prompt_template.lower()
        self.assertTrue(
            re.search(r"(1-2|1~2|두 문장|2문장|짧|간결|concise|brief|short)", template),
            "System prompt must constrain reply length to keep responses "
            "concise and reduce verbosity-related negative feedback.",
        )

    def test_system_prompt_forbids_system_leak(self) -> None:
        template = self.system_prompt_template.lower()
        self.assertTrue(
            re.search(r"(시스템|system|설명|해설|commentary|meta|지시|instruction)", template),
            "System prompt must forbid system text, meta-commentary, and "
            "instruction leakage that triggers low quality scores.",
        )


if __name__ == "__main__":
    unittest.main()
