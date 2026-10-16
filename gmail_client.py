"""Read-only Gmail inbox retrieval with pagination and bounded retries."""
import json
import time

from googleapiclient.errors import HttpError


PAGE_SIZE = 100
MAX_RETRY_ATTEMPTS = 4
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
RETRYABLE_GMAIL_REASONS = {
    'backendError',
    'rateLimitExceeded',
    'userRateLimitExceeded',
}


def _gmail_error_reasons(error):
    try:
        content = error.content.decode('utf-8') if isinstance(error.content, bytes) else error.content
        payload = json.loads(content)
        return {
            item.get('reason')
            for item in payload.get('error', {}).get('errors', [])
            if item.get('reason')
        }
    except (AttributeError, TypeError, ValueError):
        return set()


def _is_retryable(error):
    status = int(getattr(error.resp, 'status', 0))
    return (
        status in RETRYABLE_HTTP_STATUSES
        or (status == 403 and bool(_gmail_error_reasons(error) & RETRYABLE_GMAIL_REASONS))
    )


def _retry_delay(error, failed_attempt):
    retry_after = None
    try:
        retry_after = error.resp.get('retry-after')
    except AttributeError:
        pass
    if retry_after is not None:
        try:
            return min(max(float(retry_after), 0.0), 30.0)
        except (TypeError, ValueError):
            pass
    return min(2 ** (failed_attempt - 1), 8)


def execute_with_retry(
    request,
    *,
    max_attempts=MAX_RETRY_ATTEMPTS,
    sleep_fn=time.sleep,
    retry_callback=None,
):
    """Execute a Gmail request with bounded retry for transient/rate-limit errors."""
    if max_attempts < 1:
        raise ValueError('max_attempts must be at least 1')
    for attempt in range(1, max_attempts + 1):
        try:
            return request.execute()
        except HttpError as error:
            if attempt == max_attempts or not _is_retryable(error):
                raise
            delay = _retry_delay(error, attempt)
            if retry_callback:
                retry_callback(attempt + 1, max_attempts, delay)
            sleep_fn(delay)
    raise RuntimeError('Gmail request retry loop ended unexpectedly')


def fetch_inbox(
    service,
    limit,
    *,
    progress_callback=None,
    retry_callback=None,
    sleep_fn=time.sleep,
):
    """Fetch up to ``limit`` inbox messages without modifying Gmail data."""
    if limit < 1:
        raise ValueError('limit must be at least 1')

    message_ids = []
    page_token = None
    seen_page_tokens = set()

    while len(message_ids) < limit:
        response = execute_with_retry(
            service.users().messages().list(
                userId='me',
                q='in:inbox -in:trash -in:spam',
                maxResults=min(PAGE_SIZE, limit - len(message_ids)),
                pageToken=page_token,
            ),
            sleep_fn=sleep_fn,
            retry_callback=retry_callback,
        )
        remaining = limit - len(message_ids)
        page_ids = [
            item['id']
            for item in response.get('messages', [])
            if item.get('id')
        ][:remaining]
        message_ids.extend(page_ids)
        if progress_callback:
            progress_callback('listing', len(message_ids), limit)

        next_page_token = response.get('nextPageToken')
        if not next_page_token or next_page_token in seen_page_tokens:
            break
        seen_page_tokens.add(next_page_token)
        page_token = next_page_token

    messages = []
    total = len(message_ids)
    if progress_callback:
        progress_callback('metadata', 0, total)

    for index, message_id in enumerate(message_ids, start=1):
        message = execute_with_retry(
            service.users().messages().get(
                userId='me',
                id=message_id,
                format='metadata',
                metadataHeaders=['From', 'Subject', 'Date'],
            ),
            sleep_fn=sleep_fn,
            retry_callback=retry_callback,
        )
        headers = {
            header['name'].lower(): header['value']
            for header in message.get('payload', {}).get('headers', [])
            if header.get('name') and 'value' in header
        }
        messages.append({
            'id': message_id,
            'from': headers.get('from', ''),
            'subject': headers.get('subject', '(no subject)'),
            'date': headers.get('date', ''),
            'snippet': message.get('snippet', ''),
            'labels': message.get('labelIds', []),
        })
        if progress_callback:
            progress_callback('metadata', index, total)

    return messages
