# calculator_agent/palindrome_tools.py

import re

from orchestrator.calculator_agent.tools import escalate  # shared escalate lives in calculator_agent


def _normalise(text: str) -> str:
    """Lowercase and strip all non-alphanumeric characters."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def is_palindrome(text: str) -> dict:
    """Checks if a word or sentence is a palindrome. Ignores case, spaces, and punctuation."""
    cleaned = _normalise(text)
    result = cleaned == cleaned[::-1]
    return {
        "operation": "is_palindrome",
        "text": text,
        "cleaned": cleaned,
        "result": result,
    }


def longest_palindrome_substring(text: str) -> dict:
    """Finds the longest palindromic substring within the given text using centre-expansion."""
    if not text:
        return {
            "operation": "longest_palindrome_substring",
            "text": text,
            "result": "",
            "length": 0,
        }

    start, end = 0, 0

    def _expand(left: int, right: int) -> tuple[int, int]:
        while left >= 0 and right < len(text) and text[left] == text[right]:
            left -= 1
            right += 1
        return left + 1, right - 1

    for i in range(len(text)):
        # odd-length palindromes
        l, r = _expand(i, i)
        if r - l > end - start:
            start, end = l, r

        # even-length palindromes
        l, r = _expand(i, i + 1)
        if r - l > end - start:
            start, end = l, r

    found = text[start : end + 1]
    return {
        "operation": "longest_palindrome_substring",
        "text": text,
        "result": found,
        "length": len(found),
    }


def make_palindrome(word: str) -> dict:
    """Appends the minimum number of characters to a word to make it a palindrome."""
    if not word:
        return {
            "operation": "make_palindrome",
            "word": word,
            "result": "",
            "suffix_appended": "",
            "characters_added": 0,
        }

    for i in range(len(word)):
        candidate = word + word[:i][::-1]
        if candidate == candidate[::-1]:
            suffix = word[:i][::-1]
            return {
                "operation": "make_palindrome",
                "word": word,
                "result": candidate,
                "suffix_appended": suffix,
                "characters_added": len(suffix),
            }

    # fallback — append full reverse minus first char
    suffix = word[:-1][::-1]
    result = word + suffix
    return {
        "operation": "make_palindrome",
        "word": word,
        "result": result,
        "suffix_appended": suffix,
        "characters_added": len(suffix),
    }


def palindrome_score(text: str) -> dict:
    """Scores how close text is to being a palindrome on a 0–100 scale."""
    cleaned = _normalise(text)

    if not cleaned:
        return {
            "operation": "palindrome_score",
            "text": text,
            "cleaned": cleaned,
            "result": None,
            "error": "Text is empty after normalisation",
        }

    total_pairs = len(cleaned) // 2
    if total_pairs == 0:
        # single character is a perfect palindrome
        return {
            "operation": "palindrome_score",
            "text": text,
            "cleaned": cleaned,
            "result": 100.0,
            "matching_pairs": 0,
            "total_pairs": 0,
        }

    matching_pairs = sum(
        1 for i in range(total_pairs) if cleaned[i] == cleaned[-(i + 1)]
    )

    score = round((matching_pairs / total_pairs) * 100, 2)
    return {
        "operation": "palindrome_score",
        "text": text,
        "cleaned": cleaned,
        "result": score,
        "matching_pairs": matching_pairs,
        "total_pairs": total_pairs,
    }
