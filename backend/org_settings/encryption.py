"""
API Key Encryption Utilities

Provides secure encryption/decryption for API keys stored in the database.
Uses Fernet symmetric encryption with Django's SECRET_KEY as the base.
"""

import base64
import hashlib
from cryptography.fernet import Fernet
from django.conf import settings


def get_encryption_key():
    """
    Generate a consistent Fernet key from Django's SECRET_KEY.
    """
    # Use SHA256 to get a consistent 32-byte key from SECRET_KEY
    key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    # Fernet requires base64-encoded 32-byte key
    return base64.urlsafe_b64encode(key)


def encrypt_api_key(plain_key: str) -> str:
    """
    Encrypt an API key for secure storage.
    
    Args:
        plain_key: The plain text API key
        
    Returns:
        Encrypted key as base64 string
    """
    if not plain_key:
        return ""
    
    fernet = Fernet(get_encryption_key())
    encrypted = fernet.encrypt(plain_key.encode())
    return encrypted.decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """
    Decrypt an API key for use.
    
    Args:
        encrypted_key: The encrypted API key
        
    Returns:
        Plain text API key
    """
    if not encrypted_key:
        return ""
    
    try:
        fernet = Fernet(get_encryption_key())
        decrypted = fernet.decrypt(encrypted_key.encode())
        return decrypted.decode()
    except Exception:
        # If decryption fails, return None (key is corrupted/unusable)
        return None


def is_encrypted(key: str) -> bool:
    """
    Check if a key appears to be encrypted (Fernet format).
    """
    if not key:
        return False
    
    try:
        # Fernet tokens start with 'gAAAAA' after base64 encoding
        return key.startswith('gAAAAA')
    except Exception:
        return False
