from src.client.api import ApiClient

def create_session(api_client: ApiClient):
    session_data = api_client.create_session()
    print("Session created:", session_data)

def submit_retell(api_client: ApiClient, session_id: str, retell_text: str):
    response = api_client.submit_retell(session_id, retell_text)
    print("Retell submitted:", response)

def advance_chunk(api_client: ApiClient, session_id: str):
    response = api_client.advance_chunk(session_id)
    print("Advanced to next chunk:", response)

def get_current_chunk(api_client: ApiClient, session_id: str):
    current_chunk = api_client.get_current_chunk(session_id)
    print("Current chunk:", current_chunk)

def get_progress(api_client: ApiClient, session_id: str):
    progress = api_client.get_progress(session_id)
    print("Reading progress:", progress)

def get_history(api_client: ApiClient, session_id: str):
    history = api_client.get_history(session_id)
    print("Interaction history:", history)