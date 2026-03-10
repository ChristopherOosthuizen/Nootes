"""LLM-based categorization using OpenAI gpt-5-nano."""

from __future__ import annotations

import logging

from openai import OpenAI
from pydantic import BaseModel, Field

from nootes.categories import CategoriesManager
from nootes.config import NootesConfig
from nootes.readers import ExtractedContent

logger = logging.getLogger("nootes.categorizer")


class CategorizationResult(BaseModel):
    """Structured output from the LLM categorization."""

    category: str = Field(description="The top-level category name")
    category_description: str = Field(
        description="A brief description of the category (1 sentence)"
    )
    subcategory: str = Field(description="The subcategory name")
    subcategory_description: str = Field(
        description="A brief description of the subcategory (1 sentence)"
    )
    is_new_category: bool = Field(
        description="True if this category did not exist before"
    )
    confidence: float = Field(
        description="Confidence score from 0.0 to 1.0", ge=0.0, le=1.0
    )


CATEGORIZE_SYSTEM_PROMPT = """\
You are a notes organizer. Given a note's content, assign it to a category \
and subcategory. Use an EXISTING category/subcategory if one fits well. \
Only create a new category if nothing existing is appropriate.

Category and subcategory names should be:
- Short (1-3 words)
- Title case
- Descriptive but general enough to hold multiple notes

Existing categories:
{existing_categories}
"""

CATEGORIZE_USER_PROMPT = """\
Categorize this note:

Filename: {filename}

Content:
{content}
"""

CHUNK_SIZE = 50_000  # chars per chunk for map-reduce


class Categorizer:
    """Handles LLM-based categorization of notes."""

    def __init__(self, config: NootesConfig, categories_mgr: CategoriesManager) -> None:
        self._client = OpenAI(api_key=config.openai_api_key)
        self._model = config.openai_model
        self._categories_mgr = categories_mgr

    def categorize(
        self, filename: str, content: ExtractedContent
    ) -> CategorizationResult:
        """Categorize a single note, returning structured result.

        Handles text, images, and large content via map-reduce.
        """
        if content.needs_map_reduce and not content.is_visual:
            return self._categorize_map_reduce(filename, content.text)

        if content.is_visual and content.images:
            return self._categorize_with_vision(filename, content)

        return self._categorize_text(filename, content.text)

    def _categorize_text(
        self, filename: str, text: str
    ) -> CategorizationResult:
        """Categorize using text content only."""
        existing = self._categories_mgr.summary_for_prompt()

        response = self._client.beta.chat.completions.parse(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": CATEGORIZE_SYSTEM_PROMPT.format(
                        existing_categories=existing
                    ),
                },
                {
                    "role": "user",
                    "content": CATEGORIZE_USER_PROMPT.format(
                        filename=filename, content=text[:100_000]
                    ),
                },
            ],
            response_format=CategorizationResult,
            temperature=0.2,
        )
        result = response.choices[0].message.parsed
        if result is None:
            raise RuntimeError("LLM returned no parseable categorization result.")
        return result

    def _categorize_with_vision(
        self, filename: str, content: ExtractedContent
    ) -> CategorizationResult:
        """Categorize using vision API for images/PDF pages."""
        existing = self._categories_mgr.summary_for_prompt()

        # Build message with images (limit to first 5 pages/images to control cost)
        user_parts: list[dict] = [
            {
                "type": "text",
                "text": f"Categorize this note.\n\nFilename: {filename}\n\n"
                + (f"Extracted text:\n{content.text[:10_000]}\n\n" if content.text else "")
                + "Visual content follows:",
            }
        ]

        for img_b64 in content.images[:5]:
            user_parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_b64}",
                        "detail": "low",
                    },
                }
            )

        response = self._client.beta.chat.completions.parse(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": CATEGORIZE_SYSTEM_PROMPT.format(
                        existing_categories=existing
                    ),
                },
                {"role": "user", "content": user_parts},
            ],
            response_format=CategorizationResult,
            temperature=0.2,
        )
        result = response.choices[0].message.parsed
        if result is None:
            raise RuntimeError("LLM returned no parseable categorization result.")
        return result

    def _categorize_map_reduce(
        self, filename: str, text: str
    ) -> CategorizationResult:
        """Map-reduce categorization for large documents (>100K chars).

        1. Split text into chunks
        2. Summarize each chunk
        3. Combine summaries and categorize
        """
        logger.info(
            "Content too large (%d chars), using map-reduce for: %s",
            len(text),
            filename,
        )

        # Map phase: summarize each chunk
        chunks = [text[i : i + CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE)]
        summaries: list[str] = []

        for i, chunk in enumerate(chunks):
            logger.info("  Summarizing chunk %d/%d...", i + 1, len(chunks))
            summary = self._summarize_chunk(filename, chunk, i + 1, len(chunks))
            summaries.append(summary)

        # Reduce phase: categorize from combined summaries
        combined = "\n\n".join(
            f"[Part {i + 1}] {s}" for i, s in enumerate(summaries)
        )
        return self._categorize_text(filename, combined)

    def _summarize_chunk(
        self, filename: str, chunk: str, part: int, total: int
    ) -> str:
        """Summarize a single chunk of a large document."""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Summarize the following text excerpt in 2-3 sentences. "
                        "Focus on the main topic and key concepts."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Filename: {filename} (Part {part}/{total})\n\n"
                        f"Content:\n{chunk}"
                    ),
                },
            ],
            temperature=0.1,
            max_tokens=200,
        )
        return response.choices[0].message.content or ""

    def summarize_for_clustering(self, filename: str, content: ExtractedContent) -> str:
        """Extract a brief summary for use in full-categorize clustering."""
        if content.is_visual and content.images:
            return self._summarize_visual(filename, content)

        text = content.text
        if len(text) > CHUNK_SIZE:
            # For very large docs, just summarize the first chunk
            text = text[:CHUNK_SIZE]

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Summarize the following note in 1-2 sentences. "
                        "Focus on the main topic and key concepts."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Filename: {filename}\n\nContent:\n{text}",
                },
            ],
            temperature=0.1,
            max_tokens=150,
        )
        return response.choices[0].message.content or ""

    def _summarize_visual(self, filename: str, content: ExtractedContent) -> str:
        """Summarize visual content (images/PDF) using vision API."""
        user_parts: list[dict] = [
            {
                "type": "text",
                "text": (
                    f"Summarize this in 1-2 sentences.\n\nFilename: {filename}"
                ),
            }
        ]

        for img_b64 in content.images[:3]:
            user_parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_b64}",
                        "detail": "low",
                    },
                }
            )

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Summarize the visual content in 1-2 sentences. "
                        "Focus on the main topic."
                    ),
                },
                {"role": "user", "content": user_parts},
            ],
            temperature=0.1,
            max_tokens=150,
        )
        return response.choices[0].message.content or ""
