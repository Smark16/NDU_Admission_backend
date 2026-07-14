import random
import string

def generate_number():
    numbers = random.randint(1000, 9999)
    letters = ''.join(random.choices(string.ascii_uppercase, k=3))
    return f"STF-{numbers}-{letters}"
