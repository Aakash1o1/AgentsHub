from ulid import ULID
# Create your views here.

def generate_ulid():
    return str(ULID())
