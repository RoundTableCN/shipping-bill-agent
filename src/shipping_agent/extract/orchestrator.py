"""Choose the extractor and fall back safely."""

from __future__ import annotations

from ..models.bundle import DocumentBundle
from ..models.candidate import RawChargeLine
from .llm import LLMConfig, LLMNotConfigured, build_chat_model
from .models import ExtractionResult
from .rules import RuleBasedExtractor


def extract_document(
    bundle: DocumentBundle,
    candidates: list[RawChargeLine],
    existing_bill: dict | None = None,
    *,
    use_llm: bool = False,
    llm_config: LLMConfig | None = None,
) -> ExtractionResult:
    """Run LLM extraction when enabled; always fall back to rules on failure."""
    if use_llm:
        try:
            config = llm_config or LLMConfig.from_env()
            if not config.enabled:
                raise LLMNotConfigured(
                    "LLM_MODEL / OPENAI_API_KEY not configured"
                )
            from .langchain_extractor import LangChainExtractor

            return LangChainExtractor(
                build_chat_model(config),
                method=config.structured_method,
            ).extract(bundle, candidates, existing_bill)
        except Exception as exc:  # noqa: BLE001 - never fail the batch
            result = RuleBasedExtractor().extract(bundle, candidates, existing_bill)
            result.source = "rules_fallback"
            result.warnings.append(
                f"LLM_FALLBACK: {type(exc).__name__}: {exc}"
            )
            result.warnings = list(dict.fromkeys(result.warnings))
            return result

    return RuleBasedExtractor().extract(bundle, candidates, existing_bill)
