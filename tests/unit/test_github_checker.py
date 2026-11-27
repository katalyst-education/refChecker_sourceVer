import base64
from unittest.mock import MagicMock, patch

import pytest
import requests

from refchecker.checkers.github_checker import GitHubChecker
from refchecker.core.refchecker import ArxivReferenceChecker


COMMIT = "a" * 40
API = "https://api.github.com/repos/example/project"


def test_github_owner_url_verifies_as_github_source():
    checker = GitHubChecker()
    reference = {
        'title': 'Qwen-vl 2.5 32b instruct',
        'authors': ['Alibaba DAMO Academy'],
        'venue': 'Qwen2.5-VL',
        'year': 2025,
        'url': 'https://github.com/QwenLM/',
    }

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        'login': 'QwenLM',
        'name': 'QwenLM',
        'company': 'Alibaba Cloud',
        'bio': 'Qwen large language model and multimodal model releases',
        'type': 'Organization',
        'created_at': '2023-01-01T00:00:00Z',
        'public_repos': 20,
    }

    with patch('refchecker.checkers.github_checker.requests.get', return_value=response) as mock_get:
        verified_data, errors, url = checker.verify_reference(reference)

    assert verified_data is not None
    assert verified_data['_matched_database'] == 'GitHub'
    assert verified_data['venue'] == 'GitHub Organization'
    assert errors == []
    assert url == 'https://github.com/QwenLM/'
    mock_get.assert_called_once()
    assert mock_get.call_args.args[0] == 'https://api.github.com/users/QwenLM'


def test_github_owner_url_404_is_unverified():
    checker = GitHubChecker()
    response = MagicMock()
    response.status_code = 404

    with patch('refchecker.checkers.github_checker.requests.get', return_value=response):
        verified_data, errors, url = checker.verify_reference({'url': 'https://github.com/not-a-real-owner/'})

    assert verified_data is None
    assert errors[0]['error_type'] == 'unverified'
    assert 'owner or organization not found' in errors[0]['error_details'].lower()
    assert url == 'https://github.com/not-a-real-owner/'


def test_github_blob_verifies_the_cited_file_not_repository_metadata():
    checker = GitHubChecker()
    url = f'https://github.com/meta-llama/llama3/blob/{COMMIT}/MODEL_CARD.md'
    reference = {
        'title': 'Llama 3 Model Card',
        'authors': ['AI@Meta'],
        'year': 2024,
        'url': url,
    }

    repo_response = MagicMock()
    repo_response.status_code = 200
    repo_response.json.return_value = {
        'name': 'llama3',
        'description': 'The official Meta Llama 3 GitHub site',
        'owner': {'login': 'meta-llama', 'name': 'Meta Llama'},
        'created_at': '2024-04-18T00:00:00Z',
        'archived': True,
    }
    file_response = MagicMock()
    file_response.status_code = 200
    file_response.json.return_value = {
        'type': 'file',
        'name': 'MODEL_CARD.md',
        'path': 'MODEL_CARD.md',
        'html_url': url,
        'encoding': 'base64',
        'content': base64.b64encode(
            b'## Model Details\nMeta developed and released the Meta Llama 3 family.'
        ).decode('ascii'),
    }

    with patch(
        'refchecker.checkers.github_checker.requests.get',
        side_effect=[repo_response, file_response],
    ) as mock_get:
        verified_data, errors, verified_url = checker.verify_reference(reference)

    assert verified_data is not None
    assert verified_data['_matched_database'] == 'GitHub File'
    assert verified_data['github_metadata']['archived_repository'] is True
    assert verified_data['github_metadata']['content_preview'].startswith('## Model Details')
    assert errors == []
    assert verified_url == url
    assert mock_get.call_args_list[1].args[0].endswith(
        '/repos/meta-llama/llama3/contents/MODEL_CARD.md'
    )
    assert mock_get.call_args_list[1].kwargs['params'] == {'ref': COMMIT}


def test_github_blob_404_is_unverified():
    checker = GitHubChecker()
    url = f'https://github.com/meta-llama/llama3/blob/{COMMIT}/MISSING.md'
    repo_response = MagicMock()
    repo_response.status_code = 200
    repo_response.json.return_value = {
        'name': 'llama3',
        'description': 'The official Meta Llama 3 GitHub site',
        'owner': {'login': 'meta-llama', 'name': 'Meta Llama'},
        'created_at': '2024-04-18T00:00:00Z',
        'archived': False,
    }
    file_response = MagicMock()
    file_response.status_code = 404

    with patch(
        'refchecker.checkers.github_checker.requests.get',
        side_effect=[repo_response, file_response],
    ):
        verified_data, errors, verified_url = checker.verify_reference({
            'title': 'Missing file',
            'authors': ['AI@Meta'],
            'year': 2024,
            'url': url,
        })

    assert verified_data is None
    assert errors[0]['error_type'] == 'unverified'
    assert verified_url == url


def test_github_blob_through_shared_dispatch_encodes_path_and_ref():
    url = 'https://www.github.com/example/project/blob/release%2Fdocs/docs/User%20Guide%20%231.md#L2'
    repo_response = MagicMock(status_code=200)
    repo_response.json.return_value = {'owner': {'login': 'example'}}
    file_response = MagicMock(status_code=200)
    file_response.json.return_value = {
        'type': 'file', 'name': 'User Guide #1.md', 'path': 'docs/User Guide #1.md',
    }

    with patch(
        'refchecker.checkers.github_checker.requests.get',
        side_effect=[repo_response, _ref('heads/release/docs'), _response(404),
                     _response(404), _response(404), file_response],
    ) as mock_get:
        errors, verified_url, verified_data = ArxivReferenceChecker.verify_github_reference(
            None, {'venue': f'Available at {url}', 'title': 'User Guide 1'},
        )

    assert errors is None
    assert verified_url == url
    assert verified_data['github_metadata']['path'] == 'docs/User Guide #1.md'
    assert mock_get.call_args_list[0].args[0] == 'https://api.github.com/repos/example/project'
    assert mock_get.call_args_list[1].args[0] == f'{API}/git/ref/heads/release/docs'
    assert mock_get.call_args.args[0] == f'{API}/contents/docs/User%20Guide%20%231.md'
    assert mock_get.call_args.kwargs['params'] == {'ref': COMMIT}


def test_github_blob_directory_is_unverified():
    url = f'https://github.com/example/project/blob/{COMMIT}/docs'
    repo_response = MagicMock(status_code=200)
    repo_response.json.return_value = {'owner': {'login': 'example'}}
    file_response = MagicMock(status_code=200)
    file_response.json.return_value = [{'type': 'file', 'name': 'guide.md'}]

    with patch(
        'refchecker.checkers.github_checker.requests.get',
        side_effect=[repo_response, file_response],
    ):
        verified_data, errors, verified_url = GitHubChecker().verify_reference({'url': url})

    assert verified_data is None
    assert errors == [{'error_type': 'unverified', 'error_details': 'Cited GitHub path is not a file'}]
    assert verified_url == url


def _response(status=200, payload=None):
    return MagicMock(status_code=status, **{'json.return_value': payload})


def _ref(name, sha=COMMIT, object_type='commit'):
    return _response(payload={'ref': f'refs/{name}', 'object': {'type': object_type, 'sha': sha}})


@pytest.mark.parametrize('spelling', ['notes;draft.md', 'notes%3Bdraft.md'])
def test_github_blob_preserves_semicolon_in_filename(spelling):
    url = f'https://github.com/example/project/blob/{COMMIT}/docs/{spelling}?plain=1#L2'
    with patch('refchecker.checkers.github_checker.requests.get', side_effect=[
        _response(payload={}), _response(payload={'type': 'file', 'path': 'docs/notes;draft.md'}),
    ]) as mock_get:
        data, errors, _ = GitHubChecker().verify_reference({'url': url})

    assert errors == []
    assert data['github_metadata']['path'] == 'docs/notes;draft.md'
    assert mock_get.call_args.args[0] == f'{API}/contents/docs/notes%3Bdraft.md'
    assert mock_get.call_count == 2


@pytest.mark.parametrize('payload', [
    {'type': 'file', 'submodule_git_url': 'https://github.com/example/vendor.git'},
    {'type': 'submodule'},
])
def test_github_blob_submodule_is_not_verified_as_a_file(payload):
    url = f'https://github.com/example/project/blob/{COMMIT}/vendor'
    with patch('refchecker.checkers.github_checker.requests.get', side_effect=[
        _response(payload={}), _response(payload={**payload, 'path': 'vendor'}),
    ]):
        data, errors, _ = GitHubChecker().verify_reference({'url': url})

    assert data is None
    assert errors[0]['error_type'] == 'unverified'
    assert 'submodule' in errors[0]['error_details'].lower()


@pytest.mark.parametrize(('ref', 'path'), [
    ('main', 'docs/Guide.md'), ('release/docs', 'Guide.md'),
])
def test_github_blob_ref_prefix_resolves_before_contents(ref, path):
    url = f'https://github.com/example/project/blob/{ref}/{path}'
    candidates = {
        f'{API}/git/ref/heads/main': _ref('heads/main'),
        f'{API}/git/ref/heads/release/docs': _ref('heads/release/docs'),
    }

    def get(endpoint, **kwargs):
        if endpoint == API:
            return _response(payload={})
        if endpoint.startswith(f'{API}/git/ref/'):
            return candidates.get(endpoint, _response(404))
        assert endpoint == f'{API}/contents/{path}'
        assert kwargs['params'] == {'ref': COMMIT}
        return _response(payload={'type': 'file', 'path': path})

    with patch('refchecker.checkers.github_checker.requests.get', side_effect=get) as mock_get:
        data, errors, _ = GitHubChecker().verify_reference({'url': url})

    assert errors == []
    assert data['github_metadata']['ref'] == ref
    assert data['github_metadata']['path'] == path
    for prefix in (ref.split('/')[0], f'{ref}/{path}'.rsplit('/', 1)[0]):
        for namespace in ('heads', 'tags'):
            assert f'{API}/git/ref/{namespace}/{prefix}' in [c.args[0] for c in mock_get.call_args_list[:-1]]


@pytest.mark.parametrize('second_candidate', [
    _ref('tags/main/docs'), _response(403), _response(200, []), requests.Timeout,
])
def test_github_blob_does_not_try_contents_on_ambiguous_or_unavailable_ref(second_candidate):
    url = 'https://github.com/example/project/blob/main/docs/Guide.md'
    responses = {
        API: _response(payload={}),
        f'{API}/git/ref/heads/main': _ref('heads/main'),
        f'{API}/git/ref/tags/main/docs': second_candidate,
    }

    def get(endpoint, **kwargs):
        if endpoint.startswith(f'{API}/contents/'):
            return _response(payload={'type': 'file', 'path': 'docs/Guide.md'})
        result = responses.get(endpoint, _response(404))
        if result is requests.Timeout:
            raise result
        return result

    with patch('refchecker.checkers.github_checker.requests.get', side_effect=get) as mock_get:
        data, errors, _ = GitHubChecker().verify_reference({'url': url})

    assert all('/contents/' not in c.args[0] for c in mock_get.call_args_list)
    assert data is None
    assert errors[0]['error_type'] == 'unverified'
    assert 'commit SHA permalink' in errors[0]['error_details']


def test_github_blob_ref_prefix_lookup_is_bounded():
    url = 'https://github.com/example/project/blob/main/' + 'docs/' * 20 + 'Guide.md'
    with patch('refchecker.checkers.github_checker.requests.get', return_value=_response(payload={})) as mock_get:
        data, errors, _ = GitHubChecker().verify_reference({'url': url})

    assert not any('/git/ref/' in c.args[0] or '/contents/' in c.args[0] for c in mock_get.call_args_list)
    assert data is None
    assert 'commit SHA permalink' in errors[0]['error_details']
    assert 'too many possible ref boundaries' in errors[0]['error_details']


def test_github_blob_does_not_choose_slash_ref_over_short_commit():
    responses = {
        API: _response(payload={}),
        f'{API}/git/ref/heads/2026/docs': _ref('heads/2026/docs'),
    }
    url = 'https://github.com/example/project/blob/2026/docs/Guide.md'
    with patch('refchecker.checkers.github_checker.requests.get', side_effect=lambda endpoint, **kw: responses.get(endpoint, _response(404))) as mock_get:
        data, errors, _ = GitHubChecker().verify_reference({'url': url})

    assert data is None
    assert 'commit SHA permalink' in errors[0]['error_details']
    assert all('/contents/' not in c.args[0] for c in mock_get.call_args_list)


def test_github_blob_annotated_tag_is_pinned_to_the_commit():
    url = 'https://github.com/example/project/blob/v1.2/Guide.md'
    tag_sha = 'b' * 40
    responses = {
        API: _response(payload={}),
        f'{API}/git/ref/tags/v1.2': _ref('tags/v1.2', tag_sha, 'tag'),
        f'{API}/git/tags/{tag_sha}': _response(payload={'sha': tag_sha, 'object': {'type': 'commit', 'sha': COMMIT}}),
        f'{API}/contents/Guide.md': _response(payload={'type': 'file', 'path': 'Guide.md'}),
    }
    with patch('refchecker.checkers.github_checker.requests.get', side_effect=lambda url, **kw: responses.get(url, _response(404))) as mock_get:
        data, errors, _ = GitHubChecker().verify_reference({'url': url})

    assert errors == []
    assert data['github_metadata']['ref'] == 'v1.2'
    assert mock_get.call_args.kwargs['params'] == {'ref': COMMIT}
