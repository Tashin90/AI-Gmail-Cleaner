from selection import eligible_trash_ids, normalize_selected_ids


def test_normalize_uses_stable_valid_ids():
    selected = ['message-2', 'missing', 'message-1', 'message-2', 42]
    assert normalize_selected_ids(selected, ['message-1', 'message-2']) == [
        'message-2', 'message-1'
    ]


def test_protected_messages_are_never_eligible_for_trash():
    messages = [
        {'id': 'protected-id', 'category': 'Protected'},
        {'id': 'promotion-id', 'category': 'Promotion'},
        {'id': 'uncertain-id', 'category': 'Uncertain'},
    ]
    selected = ['protected-id', 'promotion-id', 'missing-id', 'uncertain-id']
    assert eligible_trash_ids(selected, messages) == ['promotion-id', 'uncertain-id']


if __name__ == '__main__':
    test_normalize_uses_stable_valid_ids()
    test_protected_messages_are_never_eligible_for_trash()
    print('2 selection safety tests passed')
