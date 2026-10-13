"""
Data Redaction Service

Scans and redacts sensitive data from text before sending to AI models.
Supports detection of:
- Credentials (passwords, API keys, tokens)
- Personal Identifiable Information (PII)
- Infrastructure data (connection strings, IPs)

Usage:
    from Utils.data_redaction import DataRedactionService
    
    service = DataRedactionService()
    
    # Scan only (returns findings without modifying text)
    findings = service.scan(text)
    
    # Scan and redact (returns redacted text + findings)
    redacted_text, findings = service.redact(text)
"""

import re
import logging
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class SensitivityLevel(Enum):
    """Sensitivity levels for detected patterns."""
    CRITICAL = "critical"  # Passwords, tokens, keys - immediate risk
    HIGH = "high"          # PII (emails, phones) - privacy risk
    MEDIUM = "medium"      # Infrastructure data - potential risk
    LOW = "low"            # Potentially sensitive


@dataclass
class RedactedItem:
    """Represents a single sensitive data finding."""
    pattern_type: str
    original_length: int
    position: Tuple[int, int]
    sensitivity: SensitivityLevel
    context: str  # Surrounding text for context (with sensitive part masked)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            'pattern_type': self.pattern_type,
            'original_length': self.original_length,
            'position': list(self.position),
            'sensitivity': self.sensitivity.value,
            'context': self.context
        }


class DataRedactionService:
    """
    Service for scanning and redacting sensitive data from text.
    
    Supports multiple pattern categories:
    - Credentials: passwords, API keys, tokens, private keys
    - PII: emails, phone numbers, SSN, credit cards
    - Infrastructure: connection strings, database URLs, IPs
    """
    
    # Pattern definitions: (regex, sensitivity_level)
    PATTERNS = {
        # ==========================================
        # CREDENTIALS (CRITICAL)
        # ==========================================
        'password': (
            r'(?i)(password|passwd|pwd|secret|credential|pass)["\']?\s*[:=\s]\s*["\']?([^\s"\'<>]{4,})',
            SensitivityLevel.CRITICAL
        ),
        'api_key': (
            r'(?i)(api[_-]?key|apikey|api_secret|access[_-]?key|secret[_-]?key)["\']?\s*[:=\s]\s*["\']?([a-zA-Z0-9_\-]{16,})',
            SensitivityLevel.CRITICAL
        ),
        'aws_access_key': (
            r'(AKIA[0-9A-Z]{16})',
            SensitivityLevel.CRITICAL
        ),
        'aws_secret_key': (
            r'(?i)(aws[_-]?secret[_-]?access[_-]?key)["\']?\s*[:=\s]\s*["\']?([a-zA-Z0-9/+=]{40})',
            SensitivityLevel.CRITICAL
        ),
        'jwt_token': (
            r'eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+',
            SensitivityLevel.CRITICAL
        ),
        'bearer_token': (
            r'(?i)bearer\s+([a-zA-Z0-9_\-.]{20,})',
            SensitivityLevel.CRITICAL
        ),
        'private_key': (
            r'-----BEGIN\s+(RSA\s+|EC\s+|DSA\s+|OPENSSH\s+)?PRIVATE\s+KEY-----',
            SensitivityLevel.CRITICAL
        ),
        'ssh_key': (
            r'ssh-(rsa|ed25519|ecdsa)\s+[A-Za-z0-9+/=]{40,}',
            SensitivityLevel.CRITICAL
        ),
        'gitlab_token': (
            r'glpat-[a-zA-Z0-9_\-]{20,}',
            SensitivityLevel.CRITICAL
        ),
        'github_token': (
            r'(ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36,}',
            SensitivityLevel.CRITICAL
        ),
        'slack_token': (
            r'xox[baprs]-[0-9]{10,}-[a-zA-Z0-9]{10,}',
            SensitivityLevel.CRITICAL
        ),
        'generic_secret': (
            r'(?i)(secret|token|auth)[_-]?(key|token)?["\']?\s*[:=\s]\s*["\']?([a-zA-Z0-9_\-]{8,})',
            SensitivityLevel.CRITICAL
        ),
        
        # ==========================================
        # PERSONAL IDENTIFIABLE INFORMATION (HIGH)
        # ==========================================
        'email': (
            r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
            SensitivityLevel.HIGH
        ),
        'phone_us': (
            r'(\+?1?[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
            SensitivityLevel.HIGH
        ),
        'phone_international': (
            r'\+[1-9]\d{1,14}',
            SensitivityLevel.HIGH
        ),
        'ssn': (
            r'\b\d{3}[-]?\d{2}[-]?\d{4}\b',
            SensitivityLevel.HIGH
        ),
        'credit_card': (
            r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b',
            SensitivityLevel.HIGH
        ),
        'credit_card_formatted': (
            r'\b(?:\d{4}[-\s]?){3}\d{4}\b',
            SensitivityLevel.HIGH
        ),
        
        # ==========================================
        # INFRASTRUCTURE (MEDIUM)
        # ==========================================
        'connection_string': (
            r'(?i)(mongodb|postgresql|postgres|mysql|redis|amqp|mssql)://[^\s<>"\']+',
            SensitivityLevel.MEDIUM
        ),
        'database_url': (
            r'(?i)(database[_-]?url|db[_-]?url)["\']?\s*[:=\s]\s*["\']?([^\s"\'<>]+)',
            SensitivityLevel.MEDIUM
        ),
        's3_bucket': (
            r's3://[a-zA-Z0-9.\-_]+(/[^\s<>"\']*)?',
            SensitivityLevel.MEDIUM
        ),
        'private_ip': (
            r'\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b',
            SensitivityLevel.MEDIUM
        ),
        'env_variable': (
            r'(?i)export\s+([A-Z_][A-Z0-9_]*)\s*=\s*["\']?([^\s"\']+)',
            SensitivityLevel.MEDIUM
        ),
    }
    
    # Masks for each pattern type
    MASKS = {
        'password': '*****',
        'api_key': '[API_KEY]',
        'aws_access_key': 'AKIA***',
        'aws_secret_key': '[AWS_SECRET]',
        'jwt_token': '[JWT_TOKEN]',
        'bearer_token': 'Bearer [REDACTED]',
        'private_key': '[PRIVATE_KEY]',
        'ssh_key': '[SSH_KEY]',
        'gitlab_token': 'glpat-[REDACTED]',
        'github_token': 'gh*_[REDACTED]',
        'slack_token': 'xox*-[REDACTED]',
        'generic_secret': '[SECRET]',
        'email': '[EMAIL]',
        'phone_us': '[PHONE]',
        'phone_international': '[PHONE]',
        'ssn': '[SSN]',
        'credit_card': '[CREDIT_CARD]',
        'credit_card_formatted': '****-****-****-XXXX',
        'connection_string': '[CONNECTION_STRING]',
        'database_url': '[DATABASE_URL]',
        's3_bucket': 's3://[BUCKET]',
        'private_ip': '[PRIVATE_IP]',
        'env_variable': 'export [VAR]=*****',
    }
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the redaction service.
        
        Args:
            config: Optional configuration dict with:
                - patterns: List of pattern names to enable (default: all)
                - custom_patterns: Dict of custom patterns to add
        """
        self.config = config or {}

        # Per-instance copies. Custom patterns used to be written into the
        # class-level PATTERNS/MASKS dicts, so one caller's pattern leaked into
        # every DataRedactionService in the process — and they were added
        # after `enabled_patterns` had been computed, so the caller who asked
        # for them never had them scanned.
        custom = self.config.get('custom_patterns', {})
        self.patterns = {**self.PATTERNS, **custom}
        self.masks = {**self.MASKS, **{name: '[REDACTED]' for name in custom
                                       if name not in self.MASKS}}
        self.enabled_patterns = list(
            self.config.get('patterns', list(self.PATTERNS.keys()))
        ) + [name for name in custom]
    
    def scan(self, text: str) -> List[RedactedItem]:
        """
        Scan text for sensitive data patterns.
        
        Args:
            text: The text to scan
            
        Returns:
            List of RedactedItem findings
        """
        if not text:
            return []
            
        findings = []
        
        for pattern_name, (regex, sensitivity) in self.patterns.items():
            if pattern_name not in self.enabled_patterns:
                continue
            
            try:
                for match in re.finditer(regex, text):
                    # Get context with sensitive part masked
                    start, end = match.start(), match.end()
                    context_start = max(0, start - 15)
                    context_end = min(len(text), end + 15)
                    
                    # Mask the sensitive part in context
                    context = (
                        text[context_start:start] + 
                        '***' + 
                        text[end:context_end]
                    )
                    
                    finding = RedactedItem(
                        pattern_type=pattern_name,
                        original_length=len(match.group()),
                        position=(start, end),
                        sensitivity=sensitivity,
                        context=context
                    )
                    findings.append(finding)
                    
            except re.error as e:
                logger.warning(f"Regex error for pattern {pattern_name}: {e}")
                continue
        
        # Remove duplicates (overlapping matches)
        findings = self._deduplicate_findings(findings)
        
        return findings
    
    def redact(self, text: str) -> Tuple[str, List[RedactedItem]]:
        """
        Scan and redact sensitive data from text.
        
        Args:
            text: The text to redact
            
        Returns:
            Tuple of (redacted_text, list of findings)
        """
        if not text:
            return text, []
            
        findings = self.scan(text)
        redacted_text = text
        
        # Process in reverse order to maintain positions
        for finding in sorted(findings, key=lambda x: x.position[0], reverse=True):
            start, end = finding.position
            mask = self._get_mask(finding)
            redacted_text = redacted_text[:start] + mask + redacted_text[end:]
        
        return redacted_text, findings
    
    def _get_mask(self, finding: RedactedItem) -> str:
        """Get the appropriate mask for a finding."""
        return self.masks.get(finding.pattern_type, '[REDACTED]')
    
    # Catch-alls that match a key name plus whatever follows it. When one of
    # these overlaps a specific pattern (jwt_token, gitlab_token, ...), the
    # specific one names the finding.
    GENERIC_PATTERNS = frozenset({'generic_secret'})

    def _deduplicate_findings(self, findings: List[RedactedItem]) -> List[RedactedItem]:
        """Merge overlapping findings into one covering their union.

        Overlapping matches used to be resolved by keeping one and discarding
        the other, so only the kept span was masked. ``token=<JWT>`` showed
        why that leaks: the generic ``token=`` pattern stops at the JWT's
        first dot, won the tie, and the payload and signature went to the AI
        provider in clear text. Redaction must only ever grow, so the merged
        finding spans every overlapping match; the label goes to the most
        specific pattern — highest sensitivity, then a named pattern over a
        catch-all, then the longest match.
        """
        if not findings:
            return findings

        def specificity(f: RedactedItem):
            return (
                self._sensitivity_rank(f.sensitivity),
                f.pattern_type not in self.GENERIC_PATTERNS,
                f.position[1] - f.position[0],
            )

        groups: List[List[RedactedItem]] = []
        for finding in sorted(findings, key=lambda f: f.position[0]):
            if groups and finding.position[0] < max(f.position[1] for f in groups[-1]):
                groups[-1].append(finding)
            else:
                groups.append([finding])

        merged = []
        for group in groups:
            best = max(group, key=specificity)
            start = min(f.position[0] for f in group)
            end = max(f.position[1] for f in group)
            merged.append(RedactedItem(
                pattern_type=best.pattern_type,
                original_length=end - start,
                position=(start, end),
                sensitivity=best.sensitivity,
                context=best.context,
            ))
        return merged

    def _sensitivity_rank(self, level: SensitivityLevel) -> int:
        """Get numeric rank for sensitivity level."""
        ranks = {
            SensitivityLevel.CRITICAL: 4,
            SensitivityLevel.HIGH: 3,
            SensitivityLevel.MEDIUM: 2,
            SensitivityLevel.LOW: 1,
        }
        return ranks.get(level, 0)
    
    def get_summary(self, findings: List[RedactedItem]) -> Dict[str, Any]:
        """
        Get a summary of findings for reporting.
        
        Args:
            findings: List of RedactedItem findings
            
        Returns:
            Summary dictionary with counts by type and severity
        """
        if not findings:
            return {
                'total_count': 0,
                'by_severity': {},
                'by_type': {}
            }
        
        by_severity = {}
        by_type = {}
        
        for finding in findings:
            # Count by severity
            sev = finding.sensitivity.value
            by_severity[sev] = by_severity.get(sev, 0) + 1
            
            # Count by type
            ptype = finding.pattern_type
            by_type[ptype] = by_type.get(ptype, 0) + 1
        
        return {
            'total_count': len(findings),
            'by_severity': by_severity,
            'by_type': by_type,
            'critical_count': by_severity.get('critical', 0),
            'high_count': by_severity.get('high', 0),
            'medium_count': by_severity.get('medium', 0),
        }


def redact_batch_logs(logs: List[Dict], config: Optional[Dict] = None) -> Tuple[List[Dict], Dict]:
    """
    Convenience function to redact a batch of logs.
    
    Args:
        logs: List of log dictionaries with '_source.message' field
        config: Optional configuration for DataRedactionService
        
    Returns:
        Tuple of (redacted_logs, summary)
    """
    service = DataRedactionService(config)
    all_findings = []
    redacted_logs = []
    
    for log in logs:
        log_copy = log.copy()
        source = log_copy.get('_source', {})
        message = source.get('message', '')
        
        if message:
            redacted_message, findings = service.redact(message)
            source['message'] = redacted_message
            source['_redaction_applied'] = len(findings) > 0
            source['_redaction_count'] = len(findings)
            log_copy['_source'] = source
            all_findings.extend(findings)
        
        redacted_logs.append(log_copy)
    
    summary = service.get_summary(all_findings)
    return redacted_logs, summary


def redact_code_changes(changes: List[Dict], config: Optional[Dict] = None) -> Tuple[List[Dict], Dict]:
    """
    Convenience function to redact code change diffs.
    
    Args:
        changes: List of code change dictionaries with 'diff' or 'message' fields
        config: Optional configuration for DataRedactionService
        
    Returns:
        Tuple of (redacted_changes, summary)
    """
    service = DataRedactionService(config)
    all_findings = []
    redacted_changes = []
    
    for change in changes:
        change_copy = change.copy()
        
        # Redact diff content
        if 'diff' in change_copy and change_copy['diff']:
            redacted_diff, findings = service.redact(change_copy['diff'])
            change_copy['diff'] = redacted_diff
            all_findings.extend(findings)
        
        # Redact commit message
        if 'message' in change_copy and change_copy['message']:
            redacted_message, findings = service.redact(change_copy['message'])
            change_copy['message'] = redacted_message
            all_findings.extend(findings)
        
        change_copy['_redaction_applied'] = len(all_findings) > 0
        redacted_changes.append(change_copy)
    
    summary = service.get_summary(all_findings)
    return redacted_changes, summary
