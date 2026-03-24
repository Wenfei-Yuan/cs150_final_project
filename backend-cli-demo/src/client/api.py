class ApiClient:
    def __init__(self, base_url):
        self.base_url = base_url

    def upload_document(self, file_path):
        import requests

        with open(file_path, 'rb') as file:
            response = requests.post(f"{self.base_url}/documents/upload", files={'file': file})
        return response.json()

    def create_session(self):
        import requests

        response = requests.post(f"{self.base_url}/sessions")
        return response.json()

    def check_health(self):
        import requests

        response = requests.get(f"{self.base_url}/health")
        return response.json()