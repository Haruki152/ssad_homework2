STATES = ('draft', 'reviewing', 'approved', 'implemented', 'verified', 'deprecated')

_FORWARD = {
    'draft': 'reviewing',
    'reviewing': 'approved',
    'approved': 'implemented',
    'implemented': 'verified',
}


def can_transition(src: str, dst: str) -> bool:
    if src not in STATES or dst not in STATES:
        return False
    if src == dst:
        return True
    if dst == 'deprecated':
        return True
    return _FORWARD.get(src) == dst
