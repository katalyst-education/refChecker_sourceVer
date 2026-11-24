"""Empty vLLM final answers are safe and remain eligible for extraction fallback."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from refchecker.llm.providers import vLLMProvider


@pytest.mark.parametrize('content', [None, ''])
def test_empty_final_content_is_safe_and_logs_finish_reason(content, caplog):
    provider = vLLMProvider({'model': 'ds41', 'skip_initialization': True, 'auto_start_server': False})
    response = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content, reasoning='internal reasoning'),
            finish_reason='length',
        )],
        usage=None,
    )
    provider.client = Mock()
    provider.client.chat.completions.create.return_value = response

    with caplog.at_level(logging.WARNING):
        assert provider._call_llm('Extract a citation') == ''

    assert 'finish_reason=length' in caplog.text
    assert 'max_tokens=4000' in caplog.text
    assert 'API call failed' not in caplog.text
    assert 'internal reasoning' not in caplog.text


def test_empty_vllm_response_is_not_cached_or_replaced_with_reasoning(tmp_path):
    provider = vLLMProvider({'model': 'ds41', 'skip_initialization': True, 'auto_start_server': False})
    provider.cache_dir = str(tmp_path)
    provider.is_available = lambda: True
    provider.client = Mock()
    provider.client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(
                content=None, reasoning_content='Wrong Author#Invented article#Journal#2020#',
            ),
            finish_reason='length',
        )],
        usage=None,
    )

    for _ in range(2):
        assert provider.extract_references('[1] A. Author, "A solar cell article," Journal, 2020.') == []

    assert provider.client.chat.completions.create.call_count == 2


def test_vllm_final_answer_is_preserved():
    provider = vLLMProvider({'model': 'ds41', 'skip_initialization': True, 'auto_start_server': False})
    provider.client = Mock()
    provider.client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content='A. Author#A solar cell article#Journal#2020#'),
            finish_reason='stop',
        )],
        usage=None,
    )

    assert provider._call_llm('Extract a citation') == 'A. Author#A solar cell article#Journal#2020#'
