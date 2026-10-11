"""
Credential Encryption Utilities

Provides secure encryption/decryption for sensitive data like API tokens.
Uses Fernet symmetric encryption with key derived from Django SECRET_KEY.

Usage:
    from providers.encryption import encrypt_value, decrypt_value
    
    # Encrypt a token
    encrypted = encrypt_value("glpat-xxxxxxxxxxxx")
    
    # Decrypt when needed
    token = decrypt_value(encrypted)
"""

import base64
import hashlib
import logging
from functools import lru_cache
from typing import Optional, Dict, Any, Union

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

logger = logging.getLogger(__name__)


def _get_encryption_key() -> bytes:
    """
    Derive a Fernet-compatible key from Django's SECRET_KEY.
    
    Uses SHA-256 hash of SECRET_KEY, then base64 encodes to get 32-byte key.
    This ensures key is always consistent for the same SECRET_KEY.
    """
    # Get secret key from settings
    secret_key = settings.SECRET_KEY
    if not secret_key:
        raise ValueError("Django SECRET_KEY is not set - cannot encrypt credentials")
    
    # Hash to get consistent 32 bytes
    key_hash = hashlib.sha256(secret_key.encode()).digest()
    
    # Fernet requires base64-encoded 32-byte key
    return base64.urlsafe_b64encode(key_hash)


@lru_cache(maxsize=1)
def get_fernet() -> Fernet:
    """Get cached Fernet instance for encryption/decryption."""
    return Fernet(_get_encryption_key())


def encrypt_value(value: str) -> str:
    """
    Encrypt a string value.
    
    Args:
        value: Plain text string to encrypt
        
    Returns:
        Base64-encoded encrypted string
        
    Example:
        >>> encrypted = encrypt_value("my-api-token")
        >>> print(encrypted)  # "gAAAAABh..."
    """
    if not value:
        return ""
    
    fernet = get_fernet()
    encrypted_bytes = fernet.encrypt(value.encode('utf-8'))
    return encrypted_bytes.decode('utf-8')


def decrypt_value(encrypted_value: str) -> str:
    """
    Decrypt an encrypted string value.
    
    Args:
        encrypted_value: Base64-encoded encrypted string
        
    Returns:
        Decrypted plain text string
        
    Raises:
        InvalidToken: If decryption fails (wrong key or corrupted data)
        
    Example:
        >>> token = decrypt_value(encrypted)
        >>> print(token)  # "my-api-token"
    """
    if not encrypted_value:
        return ""
    
    try:
        fernet = get_fernet()
        decrypted_bytes = fernet.decrypt(encrypted_value.encode('utf-8'))
        return decrypted_bytes.decode('utf-8')
    except InvalidToken:
        logger.error("Failed to decrypt value - invalid token or corrupted data")
        raise


def encrypt_credentials(credentials: Dict[str, Any]) -> Dict[str, Any]:
    """
    Encrypt sensitive fields in a credentials dictionary.
    
    Encrypts: access_token, api_key, password, secret
    Leaves other fields as-is (e.g., username, url)
    
    Args:
        credentials: Dictionary with credential fields
        
    Returns:
        Dictionary with sensitive fields encrypted
        
    Example:
        >>> creds = {"access_token": "glpat-xxx", "username": "admin"}
        >>> encrypted = encrypt_credentials(creds)
        >>> print(encrypted)
        {"access_token": "gAAAAABh...", "username": "admin", "_encrypted": True}
    """
    if not credentials:
        return {}
    
    # Fields that should be encrypted
    sensitive_fields = {'access_token', 'api_key', 'api_token', 'password', 'secret', 'token'}

    encrypted = {}
    for key, value in credentials.items():
        if key in sensitive_fields and isinstance(value, str) and value:
            encrypted[key] = encrypt_value(value)
        else:
            encrypted[key] = value

    # Mark as encrypted to avoid double-encryption
    encrypted['_encrypted'] = True

    return encrypted


def decrypt_credentials(credentials: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decrypt sensitive fields in a credentials dictionary.
    
    Args:
        credentials: Dictionary with encrypted credential fields
        
    Returns:
        Dictionary with sensitive fields decrypted
        
    Example:
        >>> decrypted = decrypt_credentials(encrypted_creds)
        >>> print(decrypted["access_token"])  # "glpat-xxx"
    """
    if not credentials:
        return {}
    
    # Check if already decrypted or never encrypted
    if not credentials.get('_encrypted', False):
        return credentials
    
    # Fields that should be decrypted
    sensitive_fields = {'access_token', 'api_key', 'api_token', 'password', 'secret', 'token'}
    
    decrypted = {}
    for key, value in credentials.items():
        if key == '_encrypted':
            continue  # Skip the marker
        if key in sensitive_fields and isinstance(value, str) and value:
            try:
                decrypted[key] = decrypt_value(value)
            except InvalidToken:
                logger.warning(f"Could not decrypt field '{key}' - returning as-is")
                decrypted[key] = value
        else:
            decrypted[key] = value
    
    return decrypted


def is_encrypted(credentials: Dict[str, Any]) -> bool:
    """Check if credentials dictionary is already encrypted."""
    return credentials.get('_encrypted', False) if credentials else False
