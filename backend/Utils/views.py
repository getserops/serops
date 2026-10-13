"""
Utils Views

API endpoints for utility services.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
import logging

from .data_redaction import DataRedactionService

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def scan_message(request):
    """
    Scan a message for sensitive data WITHOUT redacting.
    
    Returns findings so frontend can show warning popup for user consent.
    
    Request body:
        {
            "message": "string to scan"
        }
    
    Response:
        {
            "has_sensitive_data": bool,
            "findings": [
                {
                    "type": "password",
                    "severity": "critical",
                    "preview": "...***..."
                }
            ],
            "total_count": int,
            "critical_count": int,
            "high_count": int
        }
    """
    message = request.data.get('message', '')
    
    if not message:
        return Response({
            'has_sensitive_data': False,
            'findings': [],
            'total_count': 0,
            'critical_count': 0,
            'high_count': 0,
        })
    
    try:
        service = DataRedactionService()
        findings = service.scan(message)
        
        # Convert findings to JSON-serializable format with masked preview
        findings_data = []
        for f in findings:
            # Create a preview with the sensitive part masked
            start, end = f.position
            preview_start = max(0, start - 10)
            preview_end = min(len(message), end + 10)
            
            # Mask the sensitive part
            original_text = message[start:end]
            masked_preview = (
                message[preview_start:start] + 
                '***' + 
                message[end:preview_end]
            )
            
            findings_data.append({
                'type': f.pattern_type,
                'severity': f.sensitivity.value,
                'preview': masked_preview,
                'length': len(original_text)
            })
        
        # Get summary counts
        summary = service.get_summary(findings)
        
        return Response({
            'has_sensitive_data': len(findings) > 0,
            'findings': findings_data,
            'total_count': summary.get('total_count', 0),
            'critical_count': summary.get('critical_count', 0),
            'high_count': summary.get('high_count', 0),
        })
        
    except Exception as e:
        logger.error(f"Error scanning message for sensitive data: {e}")
        # On error, return safe response (no sensitive data)
        # Don't block user from sending
        return Response({
            'has_sensitive_data': False,
            'findings': [],
            'total_count': 0,
            'critical_count': 0,
            'high_count': 0,
            'error': 'Scan failed, proceeding without check'
        })
