from elasticsearch import Elasticsearch
from django.conf import settings
import re


def get_elasticsearch_client():
    # BE-P1-07 (audit 2026-09-05): ``verify_certs`` was previously
    # hardcoded False, making every ES call MITM-vulnerable in
    # production. Default to True; operators with self-signed certs
    # or intra-VPC HTTP endpoints can opt out via ELASTICSEARCH_VERIFY_CERTS=False
    # in their .env — an explicit informed choice rather than a silent
    # bypass.
    es_config = settings.ELASTICSEARCH
    connection_params = {
        "hosts": [es_config["HOST"]],
        "request_timeout": 60,
        "retry_on_timeout": True,
        "max_retries": 3,
        "verify_certs": es_config.get("VERIFY_CERTS", True),
    }
    if es_config['USERNAME'] and es_config['PASSWORD']:
          connection_params["basic_auth"] = (
            es_config["USERNAME"],
            es_config["PASSWORD"],
        )
    return Elasticsearch(**connection_params)

def sanitize_project_name(project_name):
    """Sanitize project name for Elasticsearch index naming"""
    # Convert to lowercase and replace spaces and special chars with hyphens
    sanitized = project_name.lower()
    sanitized = re.sub(r'[^a-z0-9]+', '-', sanitized)
    # Remove leading/trailing hyphens and collapse multiple hyphens
    sanitized = re.sub(r'^-+|-+$', '', sanitized)
    sanitized = re.sub(r'-+', '-', sanitized)
    return sanitized

def get_project_index_name():
    """Get the sanitized index name for the current project"""
    project_name = getattr(settings, 'PROJECT_NAME', 'default-project')
    sanitized_name = sanitize_project_name(project_name)
    return f"application-logs-{sanitized_name}"

def search_logs(index, query):
    """
    Search logs in one or multiple Elasticsearch indices
    
    Args:
        index: A string for a single index, a comma-separated string for multiple indices,
              or a list of index names
        query: The Elasticsearch query to execute
        
    Returns:
        The Elasticsearch response
    """
    client = get_elasticsearch_client()
    
    # Handle different index input formats
    if isinstance(index, list):
        # If it's a list, join with commas
        index = ','.join(index)
    
    # If it's already a comma-separated string or single index, use as is
    response = client.search(index=index, body=query)
    return response

def search_application_logs(query, log_type=None):
    """
    Search application logs specifically
    
    Args:
        query: The Elasticsearch query to execute
        log_type: Optional filter for log type (django, user_actions)
        
    Returns:
        The Elasticsearch response
    """
    index_pattern = get_project_index_name()
    
    if log_type:
        # Add log_type filter to the query
        if 'query' not in query:
            query['query'] = {'bool': {'must': []}}
        elif 'bool' not in query['query']:
            original_query = query['query']
            query['query'] = {'bool': {'must': [original_query]}}
        
        query['query']['bool']['must'].append({
            'term': {'log_type': log_type}
        })
    
    return search_logs(index_pattern, query)

def index_logs(index, document):
    client = get_elasticsearch_client()
    response = client.index(index=index, body=document)
    return response

def index_application_log(document, log_type='general'):
    """
    Index an application log with automatic index naming
    
    Args:
        document: The log document to index
        log_type: The type of log (django, user_actions, etc.)
        
    Returns:
        The Elasticsearch response
    """
    index_name = get_project_index_name()
    
    # Add metadata to the document
    document['log_type'] = log_type
    document['application'] = sanitize_project_name(getattr(settings, 'PROJECT_NAME', 'default-project'))
    document['project_name'] = getattr(settings, 'PROJECT_NAME', 'Default Project')
    
    return index_logs(index_name, document)

