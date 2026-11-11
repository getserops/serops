"""Encryption of API keys stored in the database. See Utils/crypto.py."""
from Utils import crypto


def encrypt_api_key(plain_key: str) -> str:
    return crypto.encrypt(plain_key) if plain_key else ""


def decrypt_api_key(encrypted_key: str) -> str:
    """The plain key. Raises crypto.DecryptionError if it cannot be read."""
    return crypto.decrypt(encrypted_key) if encrypted_key else ""


def is_encrypted(key: str) -> bool:
    return crypto.is_ciphertext(key)
