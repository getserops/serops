from Middlewares.rbac import Requires
import os
from django.shortcuts import render, get_object_or_404
import requests
import json
from django.http import JsonResponse
import logging

from Data.models import AIAnalyzedBatch
from .ai_service import (generate_text_unified,
                         generate_with_fallback, get_api_key_for_org)
from .serializers import (BatchAnalysisRequestSerializer, BatchLogsSerializer, LogEntrySerializer, 
                        ChatRequestSerializer)
from .prompts import get_batch_analysis_prompt, get_chat_prompt, get_intent_classification_prompt, get_data_injection_prompt
from datetime import datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from .models import ChatSession, ChatMessage
from rest_framework.response import Response
from rest_framework import status
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework import serializers
from .tasks import analyze_batch

POD_API_URL = os.getenv('RUNPOD_API_URL')
MAX_SERVICES = 20
MAX_LOG_LENGTH = 1000

logger = logging.getLogger(__name__)

def safe_int_convert(value, default=0):
    """Safely convert value to integer"""
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        logger.warning(f"Could not convert {value} to integer, returning default value {default}")
        return default

def format_log_for_analysis(log_entry):
    """Format a log entry for analysis."""
    return f"[{log_entry['timestamp']}] {log_entry['level']}: {log_entry['message']} | Metadata: {json.dumps(log_entry['metadata'])}"

def process_ai_request(prompt, ai_model, organisation=None):
    """Process request with selected AI model."""
    
    logger.info(f'Using AI model: {ai_model} for org: {organisation.name if organisation else "None"}')
    
    # helper to get key if org present
    api_key = None
    base_url = None
    extra_config = {}
    if organisation:
        api_key, base_url, extra_config = get_api_key_for_org(organisation, ai_model.lower())

    # Unified dynamic call - works for 'gemini', 'deepseek', or any DB-registered provider
    response, error, _, _ = generate_text_unified(
        prompt,
        provider=ai_model.lower(),
        api_key=api_key,
        base_url=base_url,
        extra_config=extra_config,
    )
    
    if error:
        logger.error(f'{ai_model} error: {error}')
        return None
        
    return response




@swagger_auto_schema(
    method='post',
    operation_summary="Generate chat response",
    operation_description="Generate a response for chat messages with context",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=['type', 'prompt'],
        properties={
            'type': openapi.Schema(type=openapi.TYPE_STRING, default='chat'),
            'ai_model': openapi.Schema(type=openapi.TYPE_STRING, default='gemini'),
            'chat_id': openapi.Schema(type=openapi.TYPE_STRING, description='Optional existing chat ID'),
            'prompt': openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'message': openapi.Schema(type=openapi.TYPE_STRING)
                }
            )
        }
    ),
    responses={
        200: openapi.Response(
            description="Chat response generated successfully",
            examples={
                "application/json": {
                    "response": "AI generated response",
                    "chat_id": "uuid-string",
                    "timestamp": "2024-05-09T12:00:00Z",
                    "user": "username",
                    "context_used": True,
                    "message_count": 1
                }
            }
        ),
        400: openapi.Response(description="Bad request"),
        404: openapi.Response(description="Chat session not found"),
        500: openapi.Response(description="Failed to process chat request")
    }
)

@api_view(['POST'])
@permission_classes([IsAuthenticated, Requires(POST='chat.use')])
def generate_text(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            request_type = data.get('type', 'batch_analysis')
            ai_model = data.get('ai_model', 'gemini')
            # Log metadata only. The prior log line included request.body,
            # which contains the raw prompt — that can carry user PII and
            # occasionally embedded credentials the redaction service
            # missed. Never worth having in structured logs.
            logger.info(
                "generate_text request user=%s type=%s ai_model=%s prompt_len=%s",
                request.user.username, request_type, ai_model,
                len((data.get('prompt') or {}).get('message', '') or ''),
            )
            
            # Legacy Frontend Support: Remap 'pods' to 'gemini'
            if ai_model == 'pods':
                ai_model = 'gemini'

            if request_type == 'chat':
                chat_serializer = ChatRequestSerializer(data=data)
                if not chat_serializer.is_valid():
                    logger.error(f'Chat validation errors: {chat_serializer.errors}')
                    return JsonResponse({'error': chat_serializer.errors}, status=400)
                
                chat_data = chat_serializer.validated_data
                prompt_data = chat_data['prompt']
                # Metadata only — never log the prompt itself. Chat prompts
                # can carry user PII and occasionally embedded credentials
                # the redaction service missed. This was the regression
                # spot for BE-P1-02 (audit 2026-09-05): the earlier
                # generate_text log at ~L122 was hardened, but this chat
                # branch was missed and still emitted the full prompt.
                logger.info(
                    "chat request user=%s chat_id=%s ai_model=%s prompt_msg_len=%s",
                    request.user.username,
                    chat_data.get('chat_id'),
                    ai_model,
                    len((prompt_data or {}).get('message', '') or ''),
                )

                chat_id = chat_data.get('chat_id')
                batch_id = chat_data.get('batch_id')
                
                if chat_id:
                    try:
                        chat_session = ChatSession.objects.get(
                            chat_id=chat_id, 
                            user=request.user,
                            is_active=True
                        )
                        # If session exists but has no batch_id, and we were passed one, update it
                        if not chat_session.batch_id and batch_id:
                            chat_session.batch_id = batch_id
                            chat_session.save(update_fields=['batch_id'])
                        
                        # Use session's batch_id as source of truth if available
                        if chat_session.batch_id:
                            batch_id = chat_session.batch_id
                            
                    except ChatSession.DoesNotExist:
                        logger.warning(f"Chat session not found: chat_id={chat_id}, user={request.user.username}")
                        return JsonResponse({'error': 'Chat session not found'}, status=404)
                else:
                    chat_session = ChatSession.objects.create(
                        user=request.user,
                        title=prompt_data['message'][:50],
                        batch_id=batch_id
                    )
                
                messages = chat_session.messages.order_by('-timestamp')[:10][::-1]
                context = []
                
                # --- AGENTIC WORKFLOW START ---
                
                # Step 1: Intent Classification (The Brain)
                # Only run if we have a batch_id context to query against
                injected_data = {}
                data_sources_needed = []
                
                if batch_id:
                    # HEURISTIC OPTIMIZATION: Skip LLM Intent Classification for obvious keywords
                    # This saves API quota and prevents "Context Missing" errors if the Intent LLM fails
                    prompt_lower = prompt_data['message'].lower()
                    
                    keywords_map = {
                        'LOGS': ['log', 'error', 'exception', 'trace', 'fail', 'issue', 'bug', 'crash', 'warn'],
                        'METRICS': ['metric', 'cpu', 'memory', 'ram', 'usage', 'load', 'performance', 'stats'],
                        'CODE_CHANGES': ['code', 'commit', 'change', 'diff', 'pr', 'merge', 'git'],
                        'CICD': ['pipeline', 'build', 'deploy', 'job', 'ci/cd', 'ci', 'cd']
                    }
                    
                    detected_sources = set()
                    for source, keywords in keywords_map.items():
                        if any(k in prompt_lower for k in keywords):
                            detected_sources.add(source)
                    
                    # Special Case: "What happened?" or "Analyze this" -> Needs everything
                    if any(x in prompt_lower for x in ['analyze', 'what happened', 'root cause', 'explain']):
                        detected_sources.update(['LOGS', 'METRICS', 'CODE_CHANGES'])
                        
                    if detected_sources:
                        data_sources_needed = list(detected_sources)
                        logger.info(f"Heuristic Intent Detection: {data_sources_needed} (Skipped LLM)")
                        
                    else:
                        # Fallback to LLM Intent Classification only if heuristics failed
                        try:
                            intent_prompt = get_intent_classification_prompt(prompt_data['message'])
                            # Use a fast model for intent classification if possible, or same model
                            intent_response = process_ai_request(intent_prompt, ai_model, request.user.organisation)
                            
                            logger.info(f"Agentic Intent Analysis: {intent_response}")
                            
                            # Parse JSON response (robust parsing)
                            try:
                                # Clean up potential markdown headers
                                clean_response = intent_response.replace('```json', '').replace('```', '').strip()
                                data_sources_needed = json.loads(clean_response)
                                if not isinstance(data_sources_needed, list):
                                    data_sources_needed = []
                            except (json.JSONDecodeError, AttributeError):
                                logger.warning(f"Failed to parse intent JSON: {intent_response}")
                                data_sources_needed = []
                                
                        except Exception as e:
                            logger.error(f"Error in intent classification: {e}")
                            data_sources_needed = []

                # Step 2: Dynamic Data Fetching (The Tool)
                if data_sources_needed and batch_id:
                    try:
                        # Fetch batch base object
                        # We defer 'data' initially, but fetch it if LOGS or METRICS are needed
                        defer_fields = ['data']
                        if 'LOGS' in data_sources_needed or 'METRICS' in data_sources_needed:
                            defer_fields = [] # Don't defer if we need data
                            
                        # Multi-tenancy: a batch is only addressable from its
                        # owning organisation. Filtering here prevents IDOR
                        # where a chat session in org A tries to pull
                        # context from a batch belonging to org B.
                        batch_qs = AIAnalyzedBatch.objects.filter(
                            batch_id=batch_id,
                            organisation=request.user.organisation,
                        )
                        if defer_fields:
                            batch = batch_qs.defer(*defer_fields).get()
                        else:
                            batch = batch_qs.get()

                        # A. LOGS
                        if 'LOGS' in data_sources_needed:
                            logger.info("Agent fetching LOGS...")
                            log_snippet = ""
                            count = 0
                            max_logs = 50
                            
                            # Method 1: Direct logs array (primary format)
                            direct_logs = batch.data.get('logs', [])
                            if direct_logs:
                                for log_entry in direct_logs[:max_logs]:
                                    source = log_entry.get('_source', {})
                                    msg = source.get('message', '')
                                    ts = source.get('timestamp', source.get('@timestamp', ''))
                                    service = source.get('service_name', 'unknown')
                                    occ = source.get('occurrence_count', 1)
                                    dedup = source.get('deduplicated', False)
                                    
                                    if msg:
                                        log_line = f"[{service}] {ts} {msg}"
                                        if dedup and occ > 1:
                                            log_line += f" [REPEATED {occ}x]"
                                        log_snippet += log_line + "\n"
                                        count += 1
                            
                            # Method 2: Services nested format (fallback)
                            if count == 0:
                                services_data = batch.data.get('services', {})
                                for service_name, s_data in services_data.items():
                                    logs_by_level = s_data.get('logs', {})
                                    for level, entries in logs_by_level.items():
                                        for entry in entries:
                                            if count < max_logs:
                                                log_snippet += f"[{service_name.upper()}] {format_log_for_analysis(entry)}\n"
                                                count += 1
                                            else: break
                                        if count >= max_logs: break
                                    if count >= max_logs: break
                            
                            if log_snippet:
                                injected_data['logs'] = log_snippet

                        # B. METRICS
                        if 'METRICS' in data_sources_needed:
                            logger.info("Agent fetching METRICS...")
                            # Try to get metrics from batch data first
                            metrics_data = batch.data.get('metrics', {})
                            if metrics_data:
                                injected_data['metrics'] = json.dumps(metrics_data, indent=2)
                            else:
                                injected_data['metrics'] = "No distinct metrics found in batch data."

                        # C. CODE CHANGES
                        if 'CODE_CHANGES' in data_sources_needed:
                            logger.info("Agent fetching CODE_CHANGES...")
                            # Import here to avoid circular dependencies if any
                            from providers.models import CodeChange
                            # Find code changes linked to this project/batch timeframe
                            # This is a heuristic lookup based on project or time
                            if batch.project:
                                changes = CodeChange.objects.filter(
                                    gitlab_project__organisation__projects=batch.project
                                ).order_by('-timestamp')[:5]
                                
                                result = ""
                                for c in changes:
                                    result += f"- [{c.commit_sha[:8]}] {c.commit_message} (Files: {c.files_changed})\n"
                                
                                if result:
                                    injected_data['code_changes'] = result
                                else:
                                    injected_data['code_changes'] = "No recent code changes found linked to this project."
                            else:
                                injected_data['code_changes'] = "Project context missing, cannot look up code changes."

                        # D. CICD OUTPUT
                        if 'CICD_OUTPUT' in data_sources_needed:
                            logger.info("Agent fetching CICD_OUTPUT...")
                            from providers.models import Pipeline, Job
                            # Heuristic: find pipelines for this project around batch timestamp
                            # Placeholder for actual complex logic
                            injected_data['cicd'] = "No CI/CD pipeline data explicitly linked to this analysis batch."

                    except AIAnalyzedBatch.DoesNotExist:
                        logger.warning(f"Batch {batch_id} not found for data injection")
                    except Exception as e:
                        logger.error(f"Error in data injection step: {e}")

                # Step 2.5: Past-Incident Memory (diagnostic hints from resolved issues)
                # Keep narrow — only inject when the user is clearly investigating.
                past_memories_text = ''
                MEMORY_TRIGGER_KEYWORDS = (
                    'root cause', 'why', 'what happened', 'fix', 'resolve',
                    'analyze', 'explain', 'similar', 'before', 'recur',
                )
                if batch_id and any(k in prompt_data['message'].lower() for k in MEMORY_TRIGGER_KEYWORDS):
                    try:
                        from Data.memory import find_past_memories, format_memories_for_prompt
                        batch_for_memory = AIAnalyzedBatch.objects.filter(
                            batch_id=batch_id,
                            organisation=request.user.organisation,
                        ).first()
                        if batch_for_memory and batch_for_memory.project:
                            organisation = batch_for_memory.organisation or batch_for_memory.project.organisation
                            if organisation:
                                memories = find_past_memories(
                                    project=batch_for_memory.project,
                                    environment=batch_for_memory.environment or '',
                                    organisation=organisation,
                                )
                                past_memories_text = format_memories_for_prompt(memories)
                                if past_memories_text:
                                    logger.info(f"Injecting {len(memories)} past memories into chat for batch {batch_id}")
                    except Exception as e:
                        logger.warning(f"Skipping past-memory injection for chat (batch {batch_id}): {e}")

                # Step 3: Context Injection (The Assembler)
                if injected_data:
                    final_prompt_header = get_data_injection_prompt(
                        prompt_data['message'],
                        injected_data,
                        "" # History handled below
                    )
                    # We inject the data prompt components differently than the standard prompt
                    # Hack: Replace the standard prompt builder's system prompt with our enhanced one
                    prompt = final_prompt_header
                    # Add history
                    for msg in messages:
                        prompt += f"\nUser: {msg.message}\nAssistant: {msg.response}"
                    if past_memories_text:
                        prompt += f"\n\n{past_memories_text}\n"
                    prompt += f"\nUser: {prompt_data['message']}\nAssistant:"

                    logger.info(f"Generated AGENTIC prompt for AI.")
                else:
                    # Fallback to standard prompt if no complex data needed
                    for msg in messages:
                        context.append(f"User: {msg.message}")
                        context.append(f"Assistant: {msg.response}")
                    prompt = get_chat_prompt(
                        prompt_data['message'],
                        context,
                        past_memories=past_memories_text or None,
                    )
                    logger.info(f"Generated STANDARD prompt for AI.")
                
                # --- AGENTIC WORKFLOW END ---

                result = process_ai_request(prompt, ai_model, request.user.organisation)
                logger.info(f"AI response: {result}")

                if result:
                    chat_message = ChatMessage.objects.create(
                        chat_session=chat_session,
                        message=prompt_data['message'],
                        response=result,
                        metadata={
                            'ai_model': ai_model,
                            'context_length': len(context),
                            'agentic_sources': data_sources_needed # Track what sources were used
                        }
                    )
                    chat_session.last_message_at = chat_message.timestamp
                    chat_session.save()
                    return JsonResponse({
                        "response": result,
                        "chat_id": str(chat_session.chat_id),
                        "timestamp": chat_message.timestamp.isoformat(),
                        "user": request.user.username,
                        "context_used": True,
                        "message_count": chat_session.messages.count()
                    })
                logger.error("Failed to process chat request: AI returned no result")
                return JsonResponse({"error": "Failed to process chat request"}, status=500)

            else:
                batch_serializer = BatchLogsSerializer(data=data.get('batch_logs'))
                if not batch_serializer.is_valid():
                    logger.error(f'Invalid batch logs format: {batch_serializer.errors}')
                    return JsonResponse({'error': 'Invalid batch logs format', 
                                    'details': batch_serializer.errors}, status=400)

                batch_data = batch_serializer.validated_data
                logger.info(f"Processing batch analysis: batch_id={batch_data.get('batch_id')}, ai_model={ai_model}")

                # The LogAnalysis cache lookup that used to sit here was
                # removed: nothing in the codebase writes a LogAnalysis row, so
                # the query could only ever miss. It cost a DB round-trip on
                # every batch-analysis request and its "from_cache" response
                # was unreachable. Caching of analyses lives on AIAnalyzedBatch,
                # which superseded this model.
                services_count = len(batch_data['services'])
                if services_count > MAX_SERVICES:
                    logger.warning(f"Too many services: {services_count} (max {MAX_SERVICES})")
                    return JsonResponse({
                        'error': f'Too many services. Maximum allowed is {MAX_SERVICES}'
                    }, status=400)
                
                all_logs = []
                total_logs = 0
                for service_name, service_data in batch_data['services'].items():
                    for level, entries in service_data['logs'].items():
                        total_logs += len(entries)
                        if total_logs > MAX_LOG_LENGTH:
                            logger.warning(f"Too many logs: {total_logs} (max {MAX_LOG_LENGTH})")
                            return JsonResponse({
                                'error': f'Too many logs. Maximum allowed is {MAX_LOG_LENGTH}'
                            }, status=400)
                        for entry in entries:
                            formatted_log = format_log_for_analysis(entry)
                            all_logs.append(f"Service {service_name}: {formatted_log}")

                if not all_logs:
                    logger.warning("No logs found in the batch")
                    return JsonResponse({'error': 'No logs found in the batch'}, status=400)

                from .prompt_context import DataSourceContext
                analysis_prompt = get_batch_analysis_prompt(
                    DataSourceContext(batch_data=batch_data, logs=all_logs)
                )
                logger.info(f"Generated analysis prompt for AI: {analysis_prompt}")

                result = process_ai_request(analysis_prompt, ai_model, request.user.organisation)
                logger.info(f"AI analysis result: {result}")

                if result:
                    return JsonResponse({
                        "analysis_result": result,
                        "logs_analyzed": len(all_logs),
                        "services_analyzed": services_count,
                        "batch_id": batch_data['batch_id'],
                        "environment": batch_data['environment'],
                        "timestamp": batch_data['timestamp']
                    })
                logger.error("Failed to analyze logs: AI returned no result")
                return JsonResponse({"error": "Failed to analyze logs"}, status=500)

        except json.JSONDecodeError as e:
            logger.error(f'Failed to parse JSON: {str(e)}')
            return JsonResponse({"error": "Invalid JSON payload"}, status=400)
        
        except Exception as e:
            logger.exception(f'Unexpected error occurred: {str(e)}')
            return JsonResponse({"error": "Internal server error", "details": str(e)}, status=500)
    
    return JsonResponse({"error": "Invalid request method"}, status=400)




@swagger_auto_schema(
    method='post',
    operation_summary="Trigger batch log analysis",
    operation_description="Analyzes the specified batch of logs",
    request_body=BatchAnalysisRequestSerializer,
    responses={
        200: openapi.Response(
            description="Analysis completed successfully",
            examples={
                "application/json": {
                    "status": "success",
                    "message": "Analysis completed for batch abc123",
                    "analysis_result": "Analysis details here"
                }
            }
        ),
        400: openapi.Response(
            description="Bad request",
            examples={
                "application/json": {
                    "error": "batch_id is required"
                }
            }
        ),
        500: openapi.Response(
            description="Internal server error",
            examples={
                "application/json": {
                    "error": "Internal server error",
                    "details": "Error message details"
                }
            }
        )
    },
    tags=['Log Analysis']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated, Requires(POST='batch.analyze')])
def trigger_batch_analysis(request):
    """
    Trigger analysis for a specific batch ID
    """
    try:
        data = json.loads(request.body)
        batch_id = data.get('batch_id')
        
        if not batch_id:
            return JsonResponse({
                'error': 'batch_id is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Org-scoped fetch — the batch must belong to the caller's org.
        # Prior to this fix any authenticated user could trigger analysis
        # on any batch by ID, including another org's batches. Now the
        # queryset filter enforces the boundary before the Celery task
        # is dispatched.
        user_org = getattr(request.user, 'organisation', None)
        if not user_org:
            return JsonResponse(
                {'error': f'Batch {batch_id} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )
        qs = AIAnalyzedBatch.objects.all()
        qs = qs.filter(organisation=user_org)
        batch = qs.filter(batch_id=batch_id).first()
        if batch is None:
            # Same 404 whether the batch doesn't exist or belongs to
            # another org — no cross-org enumeration oracle.
            return JsonResponse(
                {'error': f'Batch {batch_id} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Dispatch analysis. Severity pre-filter now lives inside
        # analyze_batch (non-destructive — batch.data is preserved),
        # so no separate preprocessing task is needed. The old
        # preprocess_logs step was removed with this commit.
        task = analyze_batch.delay(batch_id)
        logger.info(f"Log analysis task {task.id} initiated for batch {batch_id}")

        return JsonResponse({
            'status': 'success',
            'message': f'Log analysis initiated for batch {batch_id}',
            'task_id': task.id,
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'error': 'Invalid JSON payload'
        }, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f'Error analyzing batch: {str(e)}')
        return JsonResponse({
            'error': 'Internal server error',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@swagger_auto_schema(
    method='get',
    operation_summary="Get chat history",
    operation_description="Get the complete message history for a specific chat session",
    manual_parameters=[
        openapi.Parameter(
            'chat_id',
            openapi.IN_PATH,
            description="UUID of the chat session",
            type=openapi.TYPE_STRING,
            format="uuid"
        )
    ],
    responses={
        200: openapi.Response(
            description="Chat history retrieved successfully",
            examples={
                "application/json": {
                    "chat_id": "uuid-string",
                    "title": "Chat session title",
                    "created_at": "2024-05-09T12:00:00Z",
                    "messages": [
                        {
                            "message": "User message",
                            "response": "AI response",
                            "timestamp": "2024-05-09T12:00:00Z",
                            "metadata": {
                                "ai_model": "pods",
                                "context_length": 5
                            }
                        }
                    ]
                }
            }
        ),
        404: openapi.Response(description="Chat session not found"),
        401: openapi.Response(description="Unauthorized")
    }
)
@api_view(['GET'])
@permission_classes([IsAuthenticated, Requires(GET='self.manage')])
def get_chat_history(request, chat_id):
    """
    Retrieve the complete message history for a specific chat session
    """
    try:
        chat_session = ChatSession.objects.get(
            chat_id=chat_id,
            user=request.user,
            is_active=True
        )

        messages = chat_session.messages.all().order_by('timestamp')
        
        return JsonResponse({
            'chat_id': str(chat_session.chat_id),
            'title': chat_session.title,
            'created_at': chat_session.created_at.isoformat(),
            'messages': [{
                'message': msg.message,
                'response': msg.response,
                'timestamp': msg.timestamp.isoformat(),
                'metadata': msg.metadata
            } for msg in messages]
        })

    except ChatSession.DoesNotExist:
        return JsonResponse({
            'error': 'Chat session not found'
        }, status=404)
    
    except Exception as e:
        logger.error(f'Error fetching chat history: {str(e)}')
        return JsonResponse({
            'error': 'Internal server error',
            'details': str(e)
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated, Requires(GET='self.manage')])
def list_chat_sessions(request):
    # Filter out soft-deleted sessions (delete_chat_session sets
    # is_active=False). Without this filter, "deleted" chats still
    # appear in the sidebar, confusing users. Found during E45.
    sessions = ChatSession.objects.filter(user=request.user, is_active=True)
    return Response({
        'sessions': [{
            'chat_id': str(session.chat_id),
            'title': session.title,
            'created_at': session.created_at
        } for session in sessions]
    })




@api_view(['DELETE'])
@permission_classes([IsAuthenticated, Requires(DELETE='self.manage')])
def delete_chat_session(request, chat_id):
    """Soft delete a chat session"""
    session = get_object_or_404(ChatSession, chat_id=chat_id, user=request.user)
    session.is_active = False
    session.save()
    return JsonResponse({'status': 'success', 'message': 'Chat session archived'})

@api_view(['PATCH'])
@permission_classes([IsAuthenticated, Requires(PATCH='self.manage')])
def update_chat_session(request, chat_id):
    """Update chat session title"""
    session = get_object_or_404(ChatSession, chat_id=chat_id, user=request.user)
    try:
        data = json.loads(request.body)
        if 'title' in data:
            session.title = data['title']
            session.save()
        return JsonResponse({
            'chat_id': str(session.chat_id),
            'title': session.title,
            'updated_at': session.last_message_at.isoformat()
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON payload'}, status=400)
    


@swagger_auto_schema(
    method='get',
    operation_summary="Get chat sessions",
    operation_description="Get all active chat sessions for the authenticated user",
    responses={
        200: openapi.Response(
            description="List of chat sessions",
            examples={
                "application/json": {
                    "sessions": [
                        {
                            "chat_id": "uuid-string",
                            "title": "Chat session title",
                            "created_at": "2024-05-09T12:00:00Z",
                            "last_message_at": "2024-05-09T12:00:00Z",
                            "message_count": 10
                        }
                    ]
                }
            }
        ),
        401: openapi.Response(description="Unauthorized")
    }
)
@api_view(['GET'])
@permission_classes([IsAuthenticated, Requires(GET='self.manage')])
def get_chat_sessions(request):
    """
    Get all active chat sessions for the authenticated user
    """
    try:
        sessions = ChatSession.objects.filter(
            user=request.user,
            is_active=True
        ).order_by('-last_message_at')

        return JsonResponse({
            'sessions': [{
                'chat_id': str(session.chat_id),
                'title': session.title,
                'created_at': session.created_at.isoformat(),
                'last_message_at': session.last_message_at.isoformat() if session.last_message_at else None,
                'message_count': session.messages.count()
            } for session in sessions]
        })

    except Exception as e:
        logger.error(f'Error fetching chat sessions: {str(e)}')
        return JsonResponse({
            'error': 'Internal server error',
            'details': str(e)
        }, status=500)