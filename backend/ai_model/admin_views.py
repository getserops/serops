"""
Admin views for AI service monitoring and management.
"""

import logging
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def get_ai_circuit_status(request):
    """
    Get the status of all AI provider circuit breakers.
    
    Admin-only endpoint for monitoring AI service health.
    
    Returns:
        - Provider name
        - Circuit state (CLOSED, OPEN, HALF_OPEN)
        - Failure count
        - Recovery time remaining (if OPEN)
    """
    try:
        from .circuit_breaker import get_all_circuit_status
        status_data = get_all_circuit_status()
        
        return Response({
            'status': 'ok',
            'circuits': status_data
        })
    except ImportError:
        return Response({
            'status': 'error',
            'message': 'Circuit breaker module not available'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)
    except Exception as e:
        logger.error(f"Error getting circuit status: {e}")
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def get_ai_rate_status(request):
    """
    Get the current rate limit status for all AI providers.
    
    Admin-only endpoint for monitoring quota consumption.
    
    Returns:
        - Provider name
        - Requests remaining (minute/hour)
        - Wait time if rate limited
    """
    try:
        from .rate_limiter import get_all_rate_status
        status_data = get_all_rate_status()
        
        return Response({
            'status': 'ok',
            'rate_limits': status_data
        })
    except ImportError:
        return Response({
            'status': 'error',
            'message': 'Rate limiter module not available'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)
    except Exception as e:
        logger.error(f"Error getting rate status: {e}")
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def reset_ai_circuit(request, provider):
    """
    Manually reset a circuit breaker to CLOSED state.
    
    Use this for emergency recovery when a provider has recovered
    but the circuit hasn't automatically closed.
    
    Args:
        provider: Provider name (gemini, deepseek, claude, openai)
    """
    try:
        from .circuit_breaker import AICircuitBreaker
        
        valid_providers = ['gemini', 'deepseek', 'claude', 'openai']
        if provider.lower() not in valid_providers:
            return Response({
                'status': 'error',
                'message': f'Invalid provider. Must be one of: {valid_providers}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        circuit = AICircuitBreaker(provider)
        old_state = circuit.get_state().value
        circuit.force_close()
        
        logger.info(f"Admin {request.user.username} reset {provider} circuit from {old_state} to CLOSED")
        
        return Response({
            'status': 'ok',
            'message': f'Circuit for {provider} reset to CLOSED',
            'previous_state': old_state
        })
    except ImportError:
        return Response({
            'status': 'error',
            'message': 'Circuit breaker module not available'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)
    except Exception as e:
        logger.error(f"Error resetting circuit: {e}")
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def trip_ai_circuit(request, provider):
    """
    Manually trip (open) a circuit breaker.
    
    Use this to block requests to a provider during maintenance
    or known outage.
    
    Args:
        provider: Provider name (gemini, deepseek, claude, openai)
    
    Request body:
        duration: Optional duration in seconds (default: 300)
    """
    try:
        from .circuit_breaker import AICircuitBreaker
        
        valid_providers = ['gemini', 'deepseek', 'claude', 'openai']
        if provider.lower() not in valid_providers:
            return Response({
                'status': 'error',
                'message': f'Invalid provider. Must be one of: {valid_providers}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        duration = request.data.get('duration', 300)
        
        circuit = AICircuitBreaker(provider)
        circuit.force_open(duration=duration)
        
        logger.warning(f"Admin {request.user.username} manually tripped {provider} circuit for {duration}s")
        
        return Response({
            'status': 'ok',
            'message': f'Circuit for {provider} manually OPENED for {duration} seconds'
        })
    except ImportError:
        return Response({
            'status': 'error',
            'message': 'Circuit breaker module not available'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)
    except Exception as e:
        logger.error(f"Error tripping circuit: {e}")
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def get_ai_health(request):
    """
    Get overall AI service health status.
    
    Combines circuit breaker and rate limiter status into
    a single health check endpoint.
    """
    try:
        health = {
            'status': 'healthy',
            'providers': {}
        }
        
        # Get circuit status
        try:
            from .circuit_breaker import get_all_circuit_status
            circuits = get_all_circuit_status()
            for provider, circuit_info in circuits.items():
                health['providers'][provider] = {
                    'circuit': circuit_info['state'],
                    'available': circuit_info['state'] != 'OPEN'
                }
                if circuit_info['state'] == 'OPEN':
                    health['status'] = 'degraded'
        except ImportError:
            pass
        
        # Get rate limit status
        try:
            from .rate_limiter import get_all_rate_status
            rates = get_all_rate_status()
            for provider, rate_info in rates.items():
                if provider in health['providers']:
                    health['providers'][provider]['rate_remaining'] = rate_info['current']['remaining_minute']
                    if rate_info['wait_time_seconds'] > 0:
                        health['providers'][provider]['rate_limited'] = True
                        health['status'] = 'degraded'
        except ImportError:
            pass
        
        return Response(health)
    except Exception as e:
        logger.error(f"Error getting AI health: {e}")
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
