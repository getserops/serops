"""
Adapter Registry.
Responsible for dynamically loading and caching adapter classes.
"""

import importlib
import logging
from typing import Type
from .base import BaseProviderAdapter

logger = logging.getLogger(__name__)

class AdapterRegistry:
    _cache = {}
    
    @classmethod
    def get_adapter(cls, class_path: str) -> BaseProviderAdapter:
        """
        Dynamically load an adapter class from a dotted path string.
        Example: 'ai_model.adapters.openai_generic.GenericOpenAIAdapter'
        """
        if class_path in cls._cache:
            return cls._cache[class_path]()
            
        try:
            # Security Check: Only allow loading from ai_model.adapters
            if not class_path.startswith('ai_model.adapters.'):
                raise ValueError(f"Security Violation: Cannot load adapter from outside ai_model.adapters ({class_path})")
                
            module_path, class_name = class_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            adapter_class = getattr(module, class_name)
            
            # Type Check
            if not issubclass(adapter_class, BaseProviderAdapter):
                raise TypeError(f"{class_path} is not a valid BaseProviderAdapter")
                
            # Instantiate and cache (adapters should be stateless)
            instance = adapter_class()
            cls._cache[class_path] = adapter_class
            return instance
            
        except ImportError as e:
            logger.error(f"Failed to import adapter {class_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error loading adapter {class_path}: {e}")
            raise
