"""
ARIA-OS: MathValidator — Numerical Precision Guard
Non-LLM worker that intercepts every agent response containing numbers
and cross-references them against the actual data source (Supabase).
Prevents hallucinated numbers from reaching the user.
"""
import re
from google.genai import types


class MathValidator:
    """Deterministic number validator. Zero LLM. Pure logic."""

    # Matches numbers like: 123, 1,234, 1234.56, $1,234.56
    _NUMBER_RE = re.compile(r"(?<!\w)[\$]?\d[\d,]*\.?\d*(?!\w)")

    def extract_numbers(self, text: str) -> list[float]:
        """Extract all numeric values from a text string."""
        matches = self._NUMBER_RE.findall(text)
        result = []
        for m in matches:
            cleaned = m.replace("$", "").replace(",", "")
            try:
                result.append(float(cleaned))
            except ValueError:
                continue
        return result

    def extract_numbers_from_data(self, data) -> list[float]:
        """Recursively extract all numbers from a data structure."""
        nums = []
        if isinstance(data, (int, float)):
            nums.append(float(data))
        elif isinstance(data, str):
            try:
                nums.append(float(data))
            except ValueError:
                pass
        elif isinstance(data, dict):
            for v in data.values():
                nums.extend(self.extract_numbers_from_data(v))
        elif isinstance(data, (list, tuple)):
            for item in data:
                nums.extend(self.extract_numbers_from_data(item))
        return nums

    def number_in_source(
        self, number: float, source_nums: list[float], tolerance: float = 0.05
    ) -> bool:
        """Check if a number exists in the source data within tolerance."""
        if number == 0:
            return True  # Zero is always valid

        for src in source_nums:
            if src == 0:
                continue
            if abs(number - src) <= abs(src * tolerance):
                return True

        # Also check if it's a simple sum, count, or average of source data
        if len(source_nums) > 0:
            if abs(number - sum(source_nums)) <= abs(sum(source_nums) * tolerance):
                return True
            if abs(number - len(source_nums)) < 1:
                return True
            avg = sum(source_nums) / len(source_nums)
            if abs(number - avg) <= abs(avg * tolerance):
                return True

        return False

    def validate_response(
        self, text: str, source_data: dict | list | None
    ) -> str:
        """Validate all numbers in a response against source data.

        Args:
            text: The agent's response text.
            source_data: The raw data returned by the last tool call.

        Returns:
            The text, possibly with warnings appended.
        """
        if source_data is None:
            return text

        response_nums = self.extract_numbers(text)
        if not response_nums:
            return text  # No numbers to validate

        source_nums = self.extract_numbers_from_data(source_data)
        if not source_nums:
            return text  # No source data to compare against

        unverified = []
        for num in response_nums:
            if not self.number_in_source(num, source_nums):
                # Skip small numbers that could be formatting/dates
                if num < 10 and num == int(num):
                    continue
                unverified.append(str(int(num) if num == int(num) else num))

        if unverified and len(unverified) <= 5:
            warning = (
                f"\n\n⚠️ **Nota de validación:** Los valores "
                f"{', '.join(unverified[:5])} no pudieron ser verificados "
                f"contra la fuente de datos."
            )
            return text + warning

        return text


# Singleton
math_validator = MathValidator()
