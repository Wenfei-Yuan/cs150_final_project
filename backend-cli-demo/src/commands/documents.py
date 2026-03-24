from src.client.api import ApiClient

def upload_document(file_path):
    client = ApiClient()
    response = client.upload_document(file_path)
    if response.status_code == 200:
        print("Document uploaded successfully.")
        print("Document ID:", response.json().get("id"))
    else:
        print("Failed to upload document:", response.text)

def get_document_status(document_id):
    client = ApiClient()
    response = client.get_document_status(document_id)
    if response.status_code == 200:
        status = response.json()
        print("Document Status:", status)
    else:
        print("Failed to retrieve document status:", response.text)