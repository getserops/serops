"""
Credential Encryption Utilities

Provides secure encryption/decryption for sensitive data like API tokens.
See Utils/crypto.py for the key and the format.

Usage:
    from providers.encryption import encrypt_value, decrypt_value
    
    # Encrypt a token
    encrypted = encrypt_value("glpat-xxxxxxxxxxxx")
    
    # Decrypt when needed
    token = decrypt_value(encrypted)
"""

import logging
from typing import Dict, Any

from cryptography.fernet import InvalidToken

from Utils import crypto

logger = logging.getLogger(__name__)

SENSITIVE_FIELDS = {'access_token', 'api_key', 'api_token', 'password', 'secret', 'token'}


def encrypt_value(value: str) -> str:
    """Encrypt a string. Empty stays empty."""
    return crypto.encrypt(value) if value else ""


def decrypt_value(encrypted_value: str) -> str:
    """Decrypt a string. Raises crypto.DecryptionError (an InvalidToken) if it cannot be read."""
    return crypto.decrypt(encrypted_value) if encrypted_value else ""


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
    

    encrypted = {}
    for key, value in credentials.items():
        if key in SENSITIVE_FIELDS and isinstance(value, str) and value:
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
    
    
    decrypted = {}
    for key, value in credentials.items():
        if key == '_encrypted':
            continue  # Skip the marker
        if key in SENSITIVE_FIELDS and isinstance(value, str) and value:
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
