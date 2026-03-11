"""
LLM provider abstraction for the contract analysis pipeline.

Usage:
    from llm.config import get_llm_provider
    from llm.base import LLMResponse, LLMAuditMetadata

    provider = get_llm_provider()   # None if LLM_ENABLED=false or no key
    if provider:
        response = provider.complete_structured(
            system_prompt=..., user_message=..., json_schema=..., prompt_version=...
        )
        if response:
            # LLM succeeded — use response.content, record response.metadata
"""
