"""Selection helpers that keep Gmail mutation decisions ID-based and testable."""


def normalize_selected_ids(selected_ids, valid_ids):
    """Return unique, valid string IDs while preserving selection order."""
    valid = set(valid_ids)
    normalized = []
    seen = set()
    if not isinstance(selected_ids, (list, tuple, set)):
        return normalized
    for message_id in selected_ids:
        if isinstance(message_id, str) and message_id in valid and message_id not in seen:
            normalized.append(message_id)
            seen.add(message_id)
    return normalized


def eligible_trash_ids(selected_ids, classified_messages):
    """Return selected IDs that exist and are not classified as Protected."""
    by_id = {message['id']: message for message in classified_messages}
    normalized = normalize_selected_ids(selected_ids, by_id)
    return [
        message_id
        for message_id in normalized
        if by_id[message_id].get('category') != 'Protected'
    ]
