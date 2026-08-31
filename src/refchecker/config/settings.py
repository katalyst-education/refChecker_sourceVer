"""
Configuration settings for RefChecker
"""

import os
from typing import Dict, Any, Optional


# ── API key resolution ────────────────────────────────────────────────
# Canonical env-var fallback chains.  Every component that needs an API
# key should call ``resolve_api_key`` instead of duplicating the logic.

_PROVIDER_ENV_VARS: Dict[str, list] = {
    'openai':    ['OPENAI_API_KEY', 'REFCHECKER_OPENAI_API_KEY', 'OPENAI_CHAT_KEY'],
    'anthropic': ['ANTHROPIC_API_KEY', 'REFCHECKER_ANTHROPIC_API_KEY'],
    'google':    ['GOOGLE_API_KEY', 'REFCHECKER_GOOGLE_API_KEY'],
    'azure':     ['AZURE_OPENAI_API_KEY', 'REFCHECKER_AZURE_API_KEY'],
}

_ENDPOINT_ENV_VARS: Dict[str, list] = {
    'openai':   ['OPENAI_CHAT_ENDPOINT'],
    'azure':    ['AZURE_OPENAI_ENDPOINT', 'REFCHECKER_AZURE_ENDPOINT'],
    'lmstudio': ['REFCHECKER_LMSTUDIO_SERVER_URL', 'LM_STUDIO_BASE_URL'],
}


def resolve_api_key(provider: str, override: Optional[str] = None) -> Optional[str]:
    """Return the first available API key for *provider*.

    Checks *override* first, then walks the canonical env-var list.
    """
    if override:
        return override
    for var in _PROVIDER_ENV_VARS.get(provider, []):
        val = os.getenv(var)
        if val:
            return val
    return None


def resolve_endpoint(provider: str, override: Optional[str] = None) -> Optional[str]:
    """Return the first available endpoint for *provider*."""
    if override:
        return override
    for var in _ENDPOINT_ENV_VARS.get(provider, []):
        val = os.getenv(var)
        if val:
            return val
    return None


# ── Default models per provider ───────────────────────────────────────
# Single source of truth for all model names used across the codebase.

DEFAULT_EXTRACTION_MODELS: Dict[str, str] = {
    'openai':    'gpt-4.1',
    'anthropic': 'claude-sonnet-4-6',
    'google':    'gemini-3.1-flash-lite-preview',
    'azure':     'gpt-4.1',
    'vllm':      'meta-llama/Llama-3.1-8B-Instruct',
    'lmstudio':  '',
}

DEFAULT_HALLUCINATION_MODELS: Dict[str, str] = {
    'openai':    'gpt-4.1',
    'anthropic': 'claude-sonnet-4-6',
    'google':    'gemini-3.1-flash-lite-preview',
    'azure':     'gpt-4.1',
    'vllm':      'gpt-4.1',
}

DEFAULT_WEB_SEARCH_MODELS: Dict[str, str] = {
    'openai':    'gpt-4.1',
    'anthropic': 'claude-sonnet-4-6',
    'google':    'gemini-3.1-flash-lite-preview',
}

# Providers that can perform hallucination checking (i.e. have web-search
# capability so the LLM can verify references against the live web).
# vLLM is excluded because local models cannot perform web searches.
HALLUCINATION_CAPABLE_PROVIDERS = frozenset({'openai', 'anthropic', 'google', 'azure'})


# Default configuration
DEFAULT_CONFIG = {
    # API Settings
    "semantic_scholar": {
        "base_url": "https://api.semanticscholar.org/graph/v1",
        "rate_limit_delay": 1.0,
        "max_retries": 3,
        "timeout": 30,
    },

    "springer_nature": {
        "base_url": "https://api.springernature.com/meta/v2/json",
        "rate_limit_delay": 1.0,
        # Conservative free-plan guardrails (provider allowance: 100/min,
        # 500/day).  The lower defaults leave room for key validation and
        # other applications that may share the same key.
        "minute_request_limit": 90,
        "daily_request_limit": 450,
        "max_retries": 3,
        "timeout": 30,
    },
    
    "arxiv": {
        "base_url": "https://export.arxiv.org/api/query",
        "rate_limit_delay": 3.0,
        "max_retries": 5,
        "timeout": 30,
    },
    
    "arxiv_citation": {
        "base_url": "https://arxiv.org/bibtex",
        "rate_limit_delay": 3.0,  # Share rate limiting with other ArXiv endpoints
        "timeout": 30,
        "use_as_authoritative": True,  # Use ArXiv BibTeX as authoritative source
        "enabled": True,  # Enable ArXiv citation checker in hybrid checker
    },
    
    # Processing Settings
    "processing": {
        "max_papers": 50,
        "days_back": 365,
        "batch_size": 100,
    },
    
    # Output Settings
    "output": {
        "debug_dir": "debug",
        "logs_dir": "logs", 
        "output_dir": "output",
        "validation_output_dir": "validation_output",
    },
    
    # Database Settings
    "database": {
        "default_path": "semantic_scholar_db/semantic_scholar.db",
        "download_batch_size": 100,
    },
    
    # Text Processing Settings
    "text_processing": {
        "similarity_threshold": 0.8,
        "max_title_similarity": 0.8,
        "max_author_similarity": 0.7,
        "year_tolerance": 1,
    },
    
    # LLM Settings
    "llm": {
        "enabled": False,
        "provider": "openai",
        "fallback_enabled": True,
        "parallel_chunks": True,  # Enable parallel chunk processing
        "max_chunk_workers": 4,   # Maximum number of parallel workers for chunk processing
        "openai": {
            "model": DEFAULT_EXTRACTION_MODELS['openai'],
            "max_tokens": 4000,
            "temperature": 0.1,
            "timeout": 30,
        },
        "anthropic": {
            "model": DEFAULT_EXTRACTION_MODELS['anthropic'],
            "max_tokens": 4000,
            "temperature": 0.1,
            "timeout": 30,
        },
        "google": {
            "model": DEFAULT_EXTRACTION_MODELS['google'],
            "max_tokens": 4000,
            "temperature": 0.1,
            "timeout": 30,
        },
        "azure": {
            "model": DEFAULT_EXTRACTION_MODELS['azure'],
            "max_tokens": 4000,
            "temperature": 0.1,
            "timeout": 30,
        },
        "vllm": {
            "model": DEFAULT_EXTRACTION_MODELS['vllm'],
            "max_tokens": 4000,
            "temperature": 0.1,
            "timeout": 30,
            "server_url": "http://localhost:8000",
            "download_path": "./models",
            "auto_download": True,
        },
        "lmstudio": {
            "model": DEFAULT_EXTRACTION_MODELS['lmstudio'],
            "max_tokens": 4000,
            "temperature": 0.1,
            "timeout_seconds": 300,
            "server_url": "http://localhost:1234",
            "context_length": None,
            # Reference extraction is a formatting task. Disable reasoning by
            # default so thinking models do not consume the completion budget
            # before producing message.content.
            "reasoning_effort": "none",
        }
    }
}

def get_config() -> Dict[str, Any]:
    """Get configuration with environment variable overrides"""
    config = DEFAULT_CONFIG.copy()
    
    # Override with environment variables if present
    if os.getenv("SEMANTIC_SCHOLAR_API_KEY"):
        config["semantic_scholar"]["api_key"] = os.getenv("SEMANTIC_SCHOLAR_API_KEY")

    springer_key = os.getenv("SPRINGER_NATURE_API_KEY") or os.getenv("SPRINGER_API_KEY")
    if springer_key:
        config["springer_nature"]["api_key"] = springer_key
    
    if os.getenv("REFCHECKER_DEBUG"):
        config["debug"] = os.getenv("REFCHECKER_DEBUG").lower() == "true"
    
    if os.getenv("REFCHECKER_OUTPUT_DIR"):
        config["output"]["output_dir"] = os.getenv("REFCHECKER_OUTPUT_DIR")
    
    # LLM configuration from environment variables
    if os.getenv("REFCHECKER_USE_LLM"):
        config["llm"]["enabled"] = os.getenv("REFCHECKER_USE_LLM").lower() == "true"
    
    if os.getenv("REFCHECKER_LLM_PROVIDER"):
        config["llm"]["provider"] = os.getenv("REFCHECKER_LLM_PROVIDER")
    
    if os.getenv("REFCHECKER_LLM_FALLBACK_ON_ERROR"):
        config["llm"]["fallback_enabled"] = os.getenv("REFCHECKER_LLM_FALLBACK_ON_ERROR").lower() == "true"
    
    # Provider-specific API keys and endpoints via shared resolver
    for provider in ('openai', 'anthropic', 'google', 'azure'):
        key = resolve_api_key(provider)
        if key:
            config["llm"][provider]["api_key"] = key
        endpoint = resolve_endpoint(provider)
        if endpoint:
            config["llm"][provider]["endpoint"] = endpoint
    
    # vLLM configuration
    if os.getenv("REFCHECKER_VLLM_SERVER_URL"):
        config["llm"]["vllm"]["server_url"] = os.getenv("REFCHECKER_VLLM_SERVER_URL")
    
    if os.getenv("REFCHECKER_VLLM_DOWNLOAD_PATH"):
        config["llm"]["vllm"]["download_path"] = os.getenv("REFCHECKER_VLLM_DOWNLOAD_PATH")
    
    if os.getenv("REFCHECKER_VLLM_AUTO_DOWNLOAD"):
        config["llm"]["vllm"]["auto_download"] = os.getenv("REFCHECKER_VLLM_AUTO_DOWNLOAD").lower() == "true"

    lmstudio_endpoint = resolve_endpoint("lmstudio")
    if lmstudio_endpoint:
        config["llm"]["lmstudio"]["server_url"] = lmstudio_endpoint

    if os.getenv("REFCHECKER_LMSTUDIO_REASONING_EFFORT"):
        config["llm"]["lmstudio"]["reasoning_effort"] = os.getenv("REFCHECKER_LMSTUDIO_REASONING_EFFORT")

    if os.getenv("REFCHECKER_LMSTUDIO_MAX_TOKENS"):
        config["llm"]["lmstudio"]["max_tokens"] = int(os.getenv("REFCHECKER_LMSTUDIO_MAX_TOKENS"))

    if os.getenv("REFCHECKER_LMSTUDIO_CONTEXT_LENGTH"):
        config["llm"]["lmstudio"]["context_length"] = int(os.getenv("REFCHECKER_LMSTUDIO_CONTEXT_LENGTH"))

    if os.getenv("REFCHECKER_LMSTUDIO_TIMEOUT"):
        config["llm"]["lmstudio"]["timeout_seconds"] = int(os.getenv("REFCHECKER_LMSTUDIO_TIMEOUT"))
    
    # Parallel processing configuration
    if os.getenv("REFCHECKER_LLM_PARALLEL_CHUNKS"):
        config["llm"]["parallel_chunks"] = os.getenv("REFCHECKER_LLM_PARALLEL_CHUNKS").lower() == "true"
    
    if os.getenv("REFCHECKER_LLM_MAX_CHUNK_WORKERS"):
        config["llm"]["max_chunk_workers"] = int(os.getenv("REFCHECKER_LLM_MAX_CHUNK_WORKERS"))
    
    # Model configuration
    if os.getenv("REFCHECKER_LLM_MODEL"):
        provider = config["llm"]["provider"]
        if provider in config["llm"]:
            config["llm"][provider]["model"] = os.getenv("REFCHECKER_LLM_MODEL")
    
    if os.getenv("REFCHECKER_LLM_MAX_TOKENS"):
        provider = config["llm"]["provider"]
        if provider in config["llm"]:
            config["llm"][provider]["max_tokens"] = int(os.getenv("REFCHECKER_LLM_MAX_TOKENS"))
    
    if os.getenv("REFCHECKER_LLM_TEMPERATURE"):
        provider = config["llm"]["provider"]
        if provider in config["llm"]:
            config["llm"][provider]["temperature"] = float(os.getenv("REFCHECKER_LLM_TEMPERATURE"))
    
    return config
