from classifier import classify_email

def test_offer():
    m={'from':'Sale <offers@foodpanda.com>', 'subject':'50% discount offer', 'snippet':'promo', 'labels':['CATEGORY_PROMOTIONS']}
    assert classify_email(m, [])['category'] == 'Promotion'

def test_protected_receipt():
    m={'from':'orders@foodpanda.com','subject':'Your order confirmation receipt','snippet':'','labels':['CATEGORY_PROMOTIONS']}
    assert classify_email(m, [])['category'] == 'Protected'

def test_whitelist():
    m={'from':'news@aiub.edu', 'subject':'sale discount', 'snippet':'', 'labels':['CATEGORY_PROMOTIONS']}
    assert classify_email(m, ['aiub.edu'])['category'] == 'Protected'

def test_uncertain():
    m={'from':'friend@example.com','subject':'Hello','snippet':'','labels':[]}
    assert classify_email(m, [])['category'] == 'Uncertain'

if __name__ == '__main__':
    for test in (test_offer, test_protected_receipt, test_whitelist, test_uncertain):
        test()
    print('4 classification tests passed')
