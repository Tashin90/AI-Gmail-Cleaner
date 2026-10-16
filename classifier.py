"""Conservative explainable heuristic classifier; no external AI services."""
import re
from email.utils import parseaddr

# This is a transparent rules baseline, NOT a trained ML model.
PROMO_DOMAINS = ('foodpanda.', 'daraz.', 'grameenphone.', 'mygp.', 'robi.', 'banglalink.')
PROMO_TERMS = ('discount', 'offer', 'sale', 'voucher', 'coupon', 'promo', 'promotion',
               'flash deal', 'limited time', 'cashback offer', 'free delivery',
               'special deal', 'ছাড়', 'অফার', 'ডিসকাউন্ট')
PROTECT_TERMS = ('otp', 'one-time password', 'verification code', 'verify your',
                 'security alert', 'reset password', 'password reset', 'payment received',
                 'payment confirmation', 'invoice', 'receipt', 'transaction', 'statement',
                 'order confirmation', 'your order', 'delivery update', 'shipped',
                 'exam', 'assignment', 'university', 'admission', 'interview',
                 'appointment', 'ticket', 'booking confirmation', '2fa', 'login code',
                 'বিল', 'পেমেন্ট', 'পরীক্ষা', 'ভেরিফিকেশন')


def classify_email(mail, whitelist):
    sender = parseaddr(mail.get('from', ''))[1].lower()
    domain = sender.rsplit('@', 1)[-1] if '@' in sender else ''
    subject = mail.get('subject', '').lower()
    snippet = mail.get('snippet', '').lower()
    text = f'{subject} {snippet}'
    labels = set(mail.get('labels', []))

    # User overrides have the highest priority.
    for entry in whitelist:
        entry = entry.lower().strip().lstrip('@')
        if not entry:
            continue
        if ('@' in entry and sender == entry) or (('@' not in entry) and (domain == entry or domain.endswith('.' + entry))):
            return {'category': 'Protected', 'suggested': False, 'reason': 'User whitelist'}
    if 'STARRED' in labels or 'IMPORTANT' in labels:
        return {'category': 'Protected', 'suggested': False, 'reason': 'Starred / marked important'}
    if any(term in text for term in PROTECT_TERMS):
        return {'category': 'Protected', 'suggested': False, 'reason': 'Potential transaction, account, job or study email'}

    if 'CATEGORY_PROMOTIONS' in labels and (any(term in text for term in PROMO_TERMS) or any(k in domain for k in PROMO_DOMAINS)):
        return {'category': 'Promotion', 'suggested': True, 'reason': 'Gmail promotion category + promotional cue'}
    if any(k in domain for k in PROMO_DOMAINS) and any(term in text for term in PROMO_TERMS):
        return {'category': 'Promotion', 'suggested': True, 'reason': 'Known promotional sender + offer language'}
    return {'category': 'Uncertain', 'suggested': False, 'reason': 'Not enough evidence; leave in inbox'}
