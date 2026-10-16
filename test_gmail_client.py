import json

from googleapiclient.errors import HttpError
from httplib2 import Response

from gmail_client import execute_with_retry, fetch_inbox


class FakeRequest:
    def __init__(self, execute_fn):
        self.execute_fn = execute_fn

    def execute(self):
        return self.execute_fn()


class FakeMessagesResource:
    def __init__(self, total_messages):
        self.ids = [f'message-{index}' for index in range(1, total_messages + 1)]
        self.list_calls = []
        self.get_calls = []

    def list(self, *, userId, q, maxResults, pageToken):
        self.list_calls.append({
            'userId': userId,
            'q': q,
            'maxResults': maxResults,
            'pageToken': pageToken,
        })

        def execute():
            start = int(pageToken) if pageToken else 0
            end = min(start + maxResults, len(self.ids))
            response = {
                'messages': [{'id': message_id} for message_id in self.ids[start:end]],
            }
            if end < len(self.ids):
                response['nextPageToken'] = str(end)
            return response

        return FakeRequest(execute)

    def get(self, *, userId, id, format, metadataHeaders):
        self.get_calls.append({
            'userId': userId,
            'id': id,
            'format': format,
            'metadataHeaders': metadataHeaders,
        })
        return FakeRequest(lambda: {
            'id': id,
            'snippet': 'Synthetic test snippet',
            'labelIds': ['INBOX'],
            'payload': {'headers': [
                {'name': 'From', 'value': 'Synthetic Sender'},
                {'name': 'Subject', 'value': f'Subject for {id}'},
                {'name': 'Date', 'value': 'Thu, 01 Jan 2026 00:00:00 +0000'},
            ]},
        })


class FakeService:
    def __init__(self, total_messages):
        self.resource = FakeMessagesResource(total_messages)

    def users(self):
        return self

    def messages(self):
        return self.resource


def test_fetches_500_messages_across_five_pages():
    service = FakeService(650)
    progress = []
    messages = fetch_inbox(
        service,
        500,
        progress_callback=lambda phase, current, total: progress.append(
            (phase, current, total)
        ),
        sleep_fn=lambda _: None,
    )

    assert len(messages) == 500
    assert len(service.resource.list_calls) == 5
    assert all(call['maxResults'] == 100 for call in service.resource.list_calls)
    assert len(service.resource.get_calls) == 500
    assert progress[-1] == ('metadata', 500, 500)


def test_reports_actual_total_when_inbox_has_fewer_messages():
    service = FakeService(135)
    progress = []
    messages = fetch_inbox(
        service,
        500,
        progress_callback=lambda phase, current, total: progress.append(
            (phase, current, total)
        ),
        sleep_fn=lambda _: None,
    )

    assert len(messages) == 135
    assert len(service.resource.list_calls) == 2
    assert progress[-1] == ('metadata', 135, 135)


def test_rate_limit_is_retried_without_changing_data():
    calls = 0
    delays = []
    retries = []

    def execute():
        nonlocal calls
        calls += 1
        if calls == 1:
            response = Response({'status': '429', 'retry-after': '0'})
            content = json.dumps({
                'error': {'errors': [{'reason': 'rateLimitExceeded'}]}
            }).encode('utf-8')
            raise HttpError(response, content)
        return {'ok': True}

    result = execute_with_retry(
        FakeRequest(execute),
        sleep_fn=delays.append,
        retry_callback=lambda attempt, maximum, delay: retries.append(
            (attempt, maximum, delay)
        ),
    )

    assert result == {'ok': True}
    assert calls == 2
    assert delays == [0.0]
    assert retries == [(2, 4, 0.0)]


def test_persistent_rate_limit_stops_after_bounded_attempts():
    calls = 0
    delays = []

    def execute():
        nonlocal calls
        calls += 1
        response = Response({'status': '429'})
        raise HttpError(response, b'{"error":{"errors":[{"reason":"rateLimitExceeded"}]}}')

    try:
        execute_with_retry(
            FakeRequest(execute),
            max_attempts=3,
            sleep_fn=delays.append,
        )
    except HttpError:
        pass
    else:
        raise AssertionError('Persistent rate limits must be reported after bounded retries')

    assert calls == 3
    assert delays == [1, 2]


if __name__ == '__main__':
    test_fetches_500_messages_across_five_pages()
    test_reports_actual_total_when_inbox_has_fewer_messages()
    test_rate_limit_is_retried_without_changing_data()
    test_persistent_rate_limit_stops_after_bounded_attempts()
    print('4 Gmail pagination and retry tests passed')
